"""
Offline Hitchwiki AI enrichment.

IMPORTANT:
- Import this module only from management commands / offline jobs.
- Never import from views, serializers, consumers, or request-path services.
- Heavy ML deps (numpy/sklearn/pyarrow/joblib) are loaded lazily inside functions.
"""
from __future__ import annotations

import logging
import math
import os
import pickle
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.request import urlopen

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from eurorace.models import HitchwikiSpot, HitchwikiSpotAI

logger = logging.getLogger(__name__)

# Official heatchmap world raster parameters (verified in ETAP 2).
WORLD_BOUNDS = (-180.0, -56.0, 180.0, 80.0)  # lon_min, lat_min, lon_max, lat_max
HEATMAP_RESOLUTION = 10  # pixels per degree
EARTH_RADIUS_M = 6378137.0
MAX_WEB_MERCATOR_LAT = 85.05112878

STUB_FILES = (
    "transformed_target_regressor_with_uncertainty.py",
    "numeric_transformers.py",
)


@dataclass
class AISyncStats:
    mode: str = ""
    prediction_source: str = ""
    model_version: str = ""
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    upserted: int = 0
    duration_seconds: float = 0.0
    peak_rss_mb: float | None = None
    details: dict = field(default_factory=dict)


class HitchwikiAIError(Exception):
    """Raised when offline AI enrichment cannot complete safely."""


class AdvisoryLockBusy(HitchwikiAIError):
    """Another AI sync holds the lock."""


def _rss_mb() -> float | None:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux: KB, macOS: bytes
        if sys.platform == "darwin":
            return usage / (1024 * 1024)
        return usage / 1024
    except Exception:
        try:
            import psutil

            return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        except Exception:
            return None


def lonlat_to_mercator(lon: float, lat: float) -> tuple[float, float]:
    lat = max(min(lat, MAX_WEB_MERCATOR_LAT), -MAX_WEB_MERCATOR_LAT)
    x = math.radians(lon) * EARTH_RADIUS_M
    y = math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0)) * EARTH_RADIUS_M
    return x, y


def world_grid_axes(resolution: int = HEATMAP_RESOLUTION):
    """Build mercator axes matching heatchmap GPMap(world, resolution=10)."""
    lon0, lat0, lon1, lat1 = WORLD_BOUNDS
    x_min = lonlat_to_mercator(lon0, 0.0)[0]
    x_max = lonlat_to_mercator(lon1, 0.0)[0]
    y_min = lonlat_to_mercator(0.0, lat0)[1]
    y_max = lonlat_to_mercator(0.0, lat1)[1]
    pixel_width = int(lon1 - lon0) * resolution
    pixel_height = int(lat1 - lat0) * resolution
    # numpy is optional until heatmap/model path runs; axes can be plain lists for tests
    try:
        import numpy as np

        x_axis = np.linspace(x_min, x_max, pixel_width)
        y_axis = np.linspace(y_max, y_min, pixel_height)
    except ImportError:
        if pixel_width <= 1:
            x_axis = [x_min]
        else:
            step_x = (x_max - x_min) / (pixel_width - 1)
            x_axis = [x_min + i * step_x for i in range(pixel_width)]
        if pixel_height <= 1:
            y_axis = [y_max]
        else:
            step_y = (y_min - y_max) / (pixel_height - 1)
            y_axis = [y_max + i * step_y for i in range(pixel_height)]
    return x_axis, y_axis, pixel_width, pixel_height


def pixel_from_lonlat(lon: float, lat: float, x_axis, y_axis) -> tuple[int | None, int | None]:
    """Map WGS84 point to heatmap pixel using mercator grid inequalities (heatchmap-compatible)."""
    mx, my = lonlat_to_mercator(lon, lat)
    lat_index = None
    for i in range(len(y_axis) - 1):
        if y_axis[i] >= my >= y_axis[i + 1]:
            lat_index = i
            break
    lon_index = None
    for i in range(len(x_axis) - 1):
        if x_axis[i] <= mx <= x_axis[i + 1]:
            lon_index = i
            break
    return lat_index, lon_index


def download_to_path(url: str, destination: Path, timeout: int = 180) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with urlopen(url, timeout=timeout) as response, open(destination, "wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
    except (URLError, TimeoutError, OSError) as exc:
        raise HitchwikiAIError(f"Download failed for {url}: {exc}") from exc
    if written < 100:
        raise HitchwikiAIError(f"Downloaded artifact too small: {destination}")
    return written


@contextmanager
def advisory_lock(lock_key: int | None = None):
    """PostgreSQL session-level advisory lock; prevents concurrent AI syncs."""
    key = lock_key if lock_key is not None else int(
        getattr(settings, "HITCHWIKI_AI_LOCK_KEY", 742891)
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
        acquired = bool(cursor.fetchone()[0])
        if not acquired:
            raise AdvisoryLockBusy("Hitchwiki AI sync already running")
        try:
            yield
        finally:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [key])


def _ensure_model_stubs(stub_dir: Path) -> None:
    """
    Download tiny official unpickle helper modules into stub_dir and put on sys.path.

    These files are AGPL and are kept only in a temporary directory for the sync process.
    They are never imported by the web runtime.
    """
    commit = getattr(settings, "HITCHWIKI_AI_STUB_COMMIT", "master")
    base = (
        f"https://raw.githubusercontent.com/Hitchwiki/heatchmap/{commit}/"
        "heatchmap/utils"
    )
    stub_dir.mkdir(parents=True, exist_ok=True)
    for name in STUB_FILES:
        target = stub_dir / name
        download_to_path(f"{base}/{name}", target)
    # Fix relative import used by the official wrapper when loaded as top-level module.
    ttr = stub_dir / "transformed_target_regressor_with_uncertainty.py"
    text = ttr.read_text(encoding="utf-8")
    text = text.replace(
        "from .numeric_transformers import Transformer",
        "from numeric_transformers import Transformer",
    )
    ttr.write_text(text, encoding="utf-8")
    stub_path = str(stub_dir.resolve())
    if stub_path not in sys.path:
        sys.path.insert(0, stub_path)


def load_pretrained_model(model_path: Path, stub_dir: Path):
    """Lazy-load sklearn-compatible Hitchwiki GP model."""
    try:
        import sklearn  # noqa: F401
        import joblib  # noqa: F401
        import numpy  # noqa: F401
        import scipy  # noqa: F401
    except ImportError as exc:
        raise HitchwikiAIError(
            "Model mode requires optional deps: numpy, scipy, scikit-learn, joblib"
        ) from exc

    _ensure_model_stubs(stub_dir)
    with open(model_path, "rb") as handle:
        model = pickle.load(handle)
    if not hasattr(model, "predict"):
        raise HitchwikiAIError("Loaded artifact has no predict()")
    return model


def load_heatmap_arrays(parquet_path: Path):
    """Load waiting_times / uncertainties from official heatmap parquet."""
    try:
        import numpy as np
        import pandas as pd
    except ImportError as exc:
        raise HitchwikiAIError(
            "Heatmap mode requires optional deps: numpy, pandas, pyarrow"
        ) from exc

    df = pd.read_parquet(parquet_path)
    if "waiting_times" not in df.columns:
        raise HitchwikiAIError(f"Heatmap missing waiting_times; columns={list(df.columns)}")

    if len(df) == 1 and df["waiting_times"].dtype == object:
        waiting = np.asarray(df["waiting_times"].iloc[0])
        unc = (
            np.asarray(df["uncertainties"].iloc[0])
            if "uncertainties" in df.columns
            else None
        )
    else:
        # Dataset rows = raster rows
        waiting = np.stack(df["waiting_times"].to_numpy())
        unc = (
            np.stack(df["uncertainties"].to_numpy())
            if "uncertainties" in df.columns
            else None
        )

    x_axis, y_axis, width, height = world_grid_axes()
    if list(waiting.shape) not in ([height, width], [width, height]):
        raise HitchwikiAIError(
            f"Unexpected heatmap shape {waiting.shape}; expected {(height, width)}"
        )
    return waiting, unc, x_axis, y_axis


def heatmap_lookup(lon: float, lat: float, waiting, unc, x_axis, y_axis):
    yi, xi = pixel_from_lonlat(lon, lat, x_axis, y_axis)
    if yi is None or xi is None:
        return None
    shape0 = len(waiting)
    shape1 = len(waiting[0]) if shape0 else 0

    def cell(arr, row, col):
        if arr is None:
            return None
        try:
            return arr[row, col]
        except Exception:
            return arr[row][col]

    try:
        if shape0 == len(y_axis) and shape1 == len(x_axis):
            wait = cell(waiting, yi, xi)
            uncertainty = cell(unc, yi, xi)
        else:
            wait = cell(waiting, xi, yi)
            uncertainty = cell(unc, xi, yi)
    except Exception:
        return None

    try:
        wait_f = float(wait)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(wait_f):
        return None
    unc_f = None
    if uncertainty is not None:
        try:
            unc_f = float(uncertainty)
            if not math.isfinite(unc_f):
                unc_f = None
        except (TypeError, ValueError):
            unc_f = None
    return wait_f, unc_f


def iter_active_spots(batch_size: int) -> Iterable[list[HitchwikiSpot]]:
    qs = (
        HitchwikiSpot.objects.filter(is_active=True)
        .order_by("id")
        .only("id", "location", "average_waiting_time_minutes")
    )
    batch: list[HitchwikiSpot] = []
    for spot in qs.iterator(chunk_size=batch_size):
        batch.append(spot)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _features_mercator(spots: list[HitchwikiSpot]):
    import numpy as np

    rows = []
    for spot in spots:
        x, y = lonlat_to_mercator(spot.location.x, spot.location.y)
        rows.append([x, y])
    return np.asarray(rows, dtype=float)


def predict_with_model(model, spots: list[HitchwikiSpot]) -> list[tuple[float, float | None]]:
    if not spots:
        return []
    try:
        import numpy as np
    except ImportError as exc:
        raise HitchwikiAIError("numpy is required for model predictions") from exc

    features = _features_mercator(spots)
    out = model.predict(features, return_std=True)
    if isinstance(out, tuple) and len(out) == 2:
        means, stds = out
        means = np.asarray(means).ravel()
        stds = np.asarray(stds).ravel()
        return [
            (float(means[i]), float(stds[i]) if np.isfinite(stds[i]) else None)
            for i in range(len(spots))
        ]
    means = np.asarray(out).ravel()
    return [(float(means[i]), None) for i in range(len(spots))]


def predict_with_heatmap(spots, waiting, unc, x_axis, y_axis):
    results = []
    skipped = 0
    for spot in spots:
        hit = heatmap_lookup(spot.location.x, spot.location.y, waiting, unc, x_axis, y_axis)
        if hit is None:
            skipped += 1
            results.append(None)
        else:
            results.append(hit)
    return results, skipped


def upsert_ai_predictions(
    rows: list[dict],
    *,
    update_spot_wait: bool = True,
) -> int:
    """
    Atomically replace AI rows for the provided spots and optionally mirror wait
    onto HitchwikiSpot.average_waiting_time_minutes for legacy serializers.
    """
    if not rows:
        return 0

    now = timezone.now()
    with transaction.atomic():
        spot_ids = [row["spot_id"] for row in rows]
        existing = {
            obj.spot_id: obj
            for obj in HitchwikiSpotAI.objects.filter(spot_id__in=spot_ids)
        }
        to_create: list[HitchwikiSpotAI] = []
        to_update: list[HitchwikiSpotAI] = []
        for row in rows:
            payload = {
                "predicted_wait_minutes": row["predicted_wait_minutes"],
                "uncertainty": row.get("uncertainty"),
                "prediction_source": row["prediction_source"],
                "model_version": row.get("model_version", ""),
                "prediction_generated_at": row.get("prediction_generated_at") or now,
            }
            if row["spot_id"] in existing:
                obj = existing[row["spot_id"]]
                for key, value in payload.items():
                    setattr(obj, key, value)
                to_update.append(obj)
            else:
                to_create.append(HitchwikiSpotAI(spot_id=row["spot_id"], **payload))

        if to_create:
            HitchwikiSpotAI.objects.bulk_create(to_create, batch_size=1000)
        if to_update:
            HitchwikiSpotAI.objects.bulk_update(
                to_update,
                fields=[
                    "predicted_wait_minutes",
                    "uncertainty",
                    "prediction_source",
                    "model_version",
                    "prediction_generated_at",
                    "updated_at",
                ],
                batch_size=1000,
            )

        if update_spot_wait:
            spot_updates = []
            spots = {
                s.id: s
                for s in HitchwikiSpot.objects.filter(id__in=spot_ids).only(
                    "id", "average_waiting_time_minutes"
                )
            }
            for row in rows:
                spot = spots.get(row["spot_id"])
                if not spot:
                    continue
                spot.average_waiting_time_minutes = row["predicted_wait_minutes"]
                spot_updates.append(spot)
            if spot_updates:
                HitchwikiSpot.objects.bulk_update(
                    spot_updates,
                    fields=["average_waiting_time_minutes", "updated_at"],
                    batch_size=1000,
                )
    return len(rows)


def _resolve_mode(requested: str | None) -> str:
    mode = (requested or getattr(settings, "HITCHWIKI_AI_MODE", "auto") or "auto").lower()
    if mode not in {"auto", "model", "heatmap"}:
        raise HitchwikiAIError(f"Invalid HITCHWIKI_AI_MODE={mode}")
    return mode


def run_model_enrichment(batch_size: int, temp_dir: Path) -> AISyncStats:
    stats = AISyncStats(mode="model", prediction_source=HitchwikiSpotAI.SOURCE_MODEL)
    model_url = getattr(settings, "HITCHWIKI_AI_MODEL_URL")
    revision = getattr(settings, "HITCHWIKI_AI_MODEL_REVISION", "main")
    filename = getattr(settings, "HITCHWIKI_AI_MODEL_FILENAME")
    version = f"{getattr(settings, 'HITCHWIKI_AI_MODEL_REPO', 'Hitchwiki/heatchmap-models')}@{revision}:{filename}"
    stats.model_version = version

    model_path = temp_dir / "model.pkl"
    stub_dir = temp_dir / "stubs"
    logger.info("Downloading Hitchwiki model artifact...")
    download_to_path(model_url, model_path)
    model = load_pretrained_model(model_path, stub_dir)
    peak = _rss_mb()

    all_rows: list[dict] = []
    now = timezone.now()
    try:
        for batch in iter_active_spots(batch_size):
            try:
                preds = predict_with_model(model, batch)
            except Exception as exc:
                logger.exception("Model batch failed")
                stats.failed += len(batch)
                raise HitchwikiAIError(f"Model prediction failed: {exc}") from exc

            for spot, (wait, unc) in zip(batch, preds):
                if wait is None or not math.isfinite(wait):
                    stats.skipped += 1
                    continue
                all_rows.append(
                    {
                        "spot_id": spot.id,
                        "predicted_wait_minutes": float(wait),
                        "uncertainty": unc,
                        "prediction_source": HitchwikiSpotAI.SOURCE_MODEL,
                        "model_version": version,
                        "prediction_generated_at": now,
                    }
                )
                stats.processed += 1
            peak = _max_rss(peak, _rss_mb())
    finally:
        del model

    # Single transactional write after all predictions succeed.
    stats.upserted = upsert_ai_predictions(all_rows)
    stats.peak_rss_mb = _max_rss(peak, _rss_mb())
    return stats


def run_heatmap_enrichment(batch_size: int, temp_dir: Path) -> AISyncStats:
    stats = AISyncStats(mode="heatmap", prediction_source=HitchwikiSpotAI.SOURCE_HEATMAP)
    heatmap_url = getattr(settings, "HITCHWIKI_AI_HEATMAP_URL")
    version = getattr(settings, "HITCHWIKI_AI_HEATMAP_VERSION", "heatmap")
    stats.model_version = f"heatmap:{version}"

    parquet_path = temp_dir / "heatmap.parquet"
    logger.info("Downloading Hitchwiki heatmap parquet...")
    download_to_path(heatmap_url, parquet_path)
    waiting, unc, x_axis, y_axis = load_heatmap_arrays(parquet_path)
    peak = _rss_mb()
    stats.details["heatmap_shape"] = list(waiting.shape)

    all_rows: list[dict] = []
    now = timezone.now()
    try:
        for batch in iter_active_spots(batch_size):
            preds, skipped = predict_with_heatmap(batch, waiting, unc, x_axis, y_axis)
            stats.skipped += skipped
            for spot, pred in zip(batch, preds):
                if pred is None:
                    continue
                wait, uncertainty = pred
                all_rows.append(
                    {
                        "spot_id": spot.id,
                        "predicted_wait_minutes": wait,
                        "uncertainty": uncertainty,
                        "prediction_source": HitchwikiSpotAI.SOURCE_HEATMAP,
                        "model_version": stats.model_version,
                        "prediction_generated_at": now,
                    }
                )
                stats.processed += 1
            peak = _max_rss(peak, _rss_mb())
    finally:
        del waiting, unc

    stats.upserted = upsert_ai_predictions(all_rows)
    stats.peak_rss_mb = _max_rss(peak, _rss_mb())
    return stats


def _max_rss(previous: float | None, current: float | None) -> float | None:
    values = [v for v in (previous, current) if v is not None]
    return max(values) if values else None


def sync_hitchwiki_ai(*, mode: str | None = None, batch_size: int | None = None) -> AISyncStats:
    """
    Offline AI enrichment entrypoint.

    Strategy:
    - model: pretrained GP only
    - heatmap: parquet lookup only
    - auto: try model, fall back to heatmap on dependency/runtime failure
    """
    started = timezone.now()
    resolved = _resolve_mode(mode)
    batch = batch_size or int(getattr(settings, "HITCHWIKI_AI_BATCH_SIZE", 1000))
    stats = AISyncStats(mode=resolved)

    with advisory_lock():
        with tempfile.TemporaryDirectory(prefix="hitchwiki_ai_") as tmp:
            temp_dir = Path(tmp)
            try:
                if resolved in {"model", "auto"}:
                    try:
                        stats = run_model_enrichment(batch, temp_dir)
                    except HitchwikiAIError as exc:
                        if resolved == "model":
                            raise
                        logger.warning("Model mode unavailable (%s); falling back to heatmap", exc)
                        stats = run_heatmap_enrichment(batch, temp_dir)
                        stats.details["fallback_reason"] = str(exc)
                else:
                    stats = run_heatmap_enrichment(batch, temp_dir)
            finally:
                # Ensure temporary artifacts are gone with TemporaryDirectory.
                pass

    stats.duration_seconds = (timezone.now() - started).total_seconds()
    logger.info(
        "Hitchwiki AI sync done mode=%s source=%s version=%s processed=%s upserted=%s "
        "skipped=%s failed=%s duration=%.1fs peak_rss_mb=%s",
        stats.mode,
        stats.prediction_source,
        stats.model_version,
        stats.processed,
        stats.upserted,
        stats.skipped,
        stats.failed,
        stats.duration_seconds,
        stats.peak_rss_mb,
    )
    return stats


def compare_model_vs_heatmap_sample(
    points: list[tuple[float, float]],
    model,
    waiting,
    unc,
    x_axis,
    y_axis,
) -> dict:
    """Integrity helper used by tests / optional validation."""
    import numpy as np

    class _FakeSpot:
        def __init__(self, lon, lat):
            self.location = type("P", (), {"x": lon, "y": lat})()

    spots = [_FakeSpot(lon, lat) for lon, lat in points]
    model_preds = predict_with_model(model, spots)
    diffs = []
    rows = []
    for (lon, lat), (m_wait, m_unc) in zip(points, model_preds):
        hit = heatmap_lookup(lon, lat, waiting, unc, x_axis, y_axis)
        h_wait = hit[0] if hit else None
        h_unc = hit[1] if hit else None
        abs_diff = abs(m_wait - h_wait) if h_wait is not None else None
        if abs_diff is not None:
            diffs.append(abs_diff)
        rows.append(
            {
                "lon": lon,
                "lat": lat,
                "model_wait": m_wait,
                "heatmap_wait": h_wait,
                "model_unc": m_unc,
                "heatmap_unc": h_unc,
                "abs_diff": abs_diff,
            }
        )
    arr = np.asarray(diffs, dtype=float) if diffs else np.asarray([], dtype=float)
    return {
        "n": len(points),
        "n_comparable": int(arr.size),
        "mae": float(arr.mean()) if arr.size else None,
        "median_abs_diff": float(np.median(arr)) if arr.size else None,
        "max_abs_diff": float(arr.max()) if arr.size else None,
        "rows": rows,
    }
