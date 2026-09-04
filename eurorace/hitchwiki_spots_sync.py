"""
Offline import of Hitchmap spots into local HitchwikiSpot rows.

Request path must not call this module's network helpers.
"""
from __future__ import annotations

import logging
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.request import urlopen

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from eurorace.models import HitchwikiSpot

logger = logging.getLogger(__name__)

EXTERNAL_ID_PREFIX = "hitchmap:"
REQUIRED_POINT_COLUMNS = ("id", "lat", "lon")
BATCH_SIZE = 1000


def _point(lon: float, lat: float):
    from django.contrib.gis.geos import Point

    return Point(lon, lat, srid=4326)


@dataclass
class HitchmapSyncStats:
    downloaded_bytes: int = 0
    rows_read: int = 0
    valid: int = 0
    skipped_invalid: int = 0
    skipped_filtered: int = 0
    created: int = 0
    updated: int = 0
    deactivated: int = 0
    source_schema: dict = field(default_factory=dict)
    duration_seconds: float = 0.0


class HitchmapDumpError(Exception):
    """Raised when the Hitchmap dump cannot be used safely."""


def build_external_id(point_id: int | str) -> str:
    return f"{EXTERNAL_ID_PREFIX}{point_id}"


def _parse_source_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        dt = parse_datetime(text.replace(" ", "T", 1)) if text else None
        if dt is None:
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text[:26], fmt)
                    break
                except ValueError:
                    continue
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, dt_timezone.utc)
    return dt


def validate_coordinates(lat, lon) -> tuple[float, float] | None:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        return None
    if lat_f == 0.0 and lon_f == 0.0:
        return None
    return lat_f, lon_f


def inspect_points_schema(connection: sqlite3.Connection) -> dict:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "points" not in tables:
        raise HitchmapDumpError("Hitchmap dump is missing required table 'points'")

    columns = {
        row[1]: row[2]
        for row in connection.execute('PRAGMA table_info("points")')
    }
    missing = [name for name in REQUIRED_POINT_COLUMNS if name not in columns]
    if missing:
        raise HitchmapDumpError(
            f"Hitchmap points table missing required columns: {', '.join(missing)}"
        )
    return {"tables": sorted(tables), "points_columns": columns}


def download_hitchmap_dump(url: str, destination: Path, timeout: int = 120) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    bytes_written = 0
    try:
        with urlopen(url, timeout=timeout) as response, open(destination, "wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                bytes_written += len(chunk)
    except (URLError, TimeoutError, OSError) as exc:
        raise HitchmapDumpError(f"Failed to download Hitchmap dump: {exc}") from exc
    if bytes_written < 1000:
        raise HitchmapDumpError("Downloaded Hitchmap dump is empty or too small")
    return bytes_written


def _row_is_active(row: sqlite3.Row, columns: set[str]) -> bool:
    if "banned" in columns:
        banned = row["banned"]
        if banned not in (None, 0, False):
            return False
    if "reviewed" in columns:
        reviewed = row["reviewed"]
        # Keep rows with reviewed=1; also keep NULL reviewed for older dumps.
        if reviewed not in (None, 1, True):
            return False
    return True


def _title_for_point(point_id, comment, country) -> str:
    if comment:
        text = " ".join(str(comment).split())
        if text:
            return text[:120]
    if country:
        return f"Hitchmap spot ({country}) #{point_id}"
    return f"Hitchmap spot #{point_id}"


def iter_hitchmap_spot_records(connection: sqlite3.Connection) -> Iterable[dict]:
    schema = inspect_points_schema(connection)
    columns = set(schema["points_columns"])
    connection.row_factory = sqlite3.Row
    query = 'SELECT * FROM "points"'
    for row in connection.execute(query):
        if not _row_is_active(row, columns):
            yield {"_skip": "filtered"}
            continue

        coords = validate_coordinates(row["lat"], row["lon"])
        if coords is None:
            yield {"_skip": "invalid"}
            continue

        lat, lon = coords
        point_id = row["id"]
        comment = row["comment"] if "comment" in columns else ""
        country = row["country"] if "country" in columns else ""
        rating = row["rating"] if "rating" in columns else None
        wait = row["wait"] if "wait" in columns else None
        source_dt = _parse_source_datetime(row["datetime"]) if "datetime" in columns else None

        metadata = {
            "source": "hitchmap",
            "hitchmap_point_id": point_id,
        }
        if country:
            metadata["country"] = country
        if "from_hitchwiki" in columns and row["from_hitchwiki"] is not None:
            metadata["from_hitchwiki"] = bool(row["from_hitchwiki"])
        if "signal" in columns and row["signal"]:
            metadata["signal"] = row["signal"]

        try:
            rating_f = float(rating) if rating is not None else None
        except (TypeError, ValueError):
            rating_f = None
        try:
            wait_f = float(wait) if wait is not None else None
        except (TypeError, ValueError):
            wait_f = None

        yield {
            "external_id": build_external_id(point_id),
            "title": _title_for_point(point_id, comment, country),
            "description": (str(comment).strip() if comment else ""),
            "location": _point(lon, lat),
            "rating": rating_f,
            "rating_count": 1,
            "average_waiting_time_minutes": wait_f,
            "source_url": f"https://hitchmap.com/#{lat:.5f},{lon:.5f},15",
            "metadata": metadata,
            "source_updated_at": source_dt,
            "is_active": True,
        }


def load_records_from_sqlite(path: Path) -> tuple[list[dict], HitchmapSyncStats]:
    stats = HitchmapSyncStats()
    records: list[dict] = []
    with sqlite3.connect(path) as connection:
        stats.source_schema = inspect_points_schema(connection)
        for item in iter_hitchmap_spot_records(connection):
            stats.rows_read += 1
            skip = item.get("_skip")
            if skip == "filtered":
                stats.skipped_filtered += 1
                continue
            if skip == "invalid":
                stats.skipped_invalid += 1
                continue
            records.append(item)
            stats.valid += 1
    if stats.valid == 0:
        raise HitchmapDumpError("No valid Hitchmap points found in dump")
    return records, stats


def apply_hitchmap_records(records: list[dict], *, now=None) -> HitchmapSyncStats:
    """
    Upsert spots transactionally. On failure the transaction rolls back and
    previous DB state remains intact.
    """
    now = now or timezone.now()
    stats = HitchmapSyncStats(valid=len(records))
    incoming_ids = [record["external_id"] for record in records]

    update_fields = [
        "title",
        "description",
        "location",
        "rating",
        "rating_count",
        "average_waiting_time_minutes",
        "source_url",
        "metadata",
        "source_updated_at",
        "imported_at",
        "is_active",
        "updated_at",
    ]

    with transaction.atomic():
        existing: dict[str, HitchwikiSpot] = {}
        for offset in range(0, len(incoming_ids), BATCH_SIZE):
            batch_ids = incoming_ids[offset : offset + BATCH_SIZE]
            for spot in HitchwikiSpot.objects.filter(external_id__in=batch_ids).only(
                "id", "external_id"
            ):
                existing[spot.external_id] = spot

        to_create: list[HitchwikiSpot] = []
        to_update: list[HitchwikiSpot] = []

        for record in records:
            payload = {**record, "imported_at": now}
            external_id = payload["external_id"]
            if external_id in existing:
                spot = existing[external_id]
                for field_name in update_fields:
                    if field_name == "updated_at":
                        setattr(spot, field_name, now)
                    else:
                        setattr(spot, field_name, payload[field_name])
                to_update.append(spot)
            else:
                to_create.append(HitchwikiSpot(**payload))

        if to_create:
            HitchwikiSpot.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
            stats.created = len(to_create)
        if to_update:
            HitchwikiSpot.objects.bulk_update(
                to_update, fields=update_fields, batch_size=BATCH_SIZE
            )
            stats.updated = len(to_update)

        incoming_set = set(incoming_ids)
        existing_hitchmap_ids = set(
            HitchwikiSpot.objects.filter(
                external_id__startswith=EXTERNAL_ID_PREFIX,
                is_active=True,
            ).values_list("external_id", flat=True)
        )
        to_deactivate = list(existing_hitchmap_ids - incoming_set)
        deactivated = 0
        for offset in range(0, len(to_deactivate), BATCH_SIZE):
            batch = to_deactivate[offset : offset + BATCH_SIZE]
            deactivated += HitchwikiSpot.objects.filter(external_id__in=batch).update(
                is_active=False
            )
        stats.deactivated = deactivated

    return stats


def sync_hitchmap_spots_from_file(path: Path | str) -> HitchmapSyncStats:
    started = timezone.now()
    records, read_stats = load_records_from_sqlite(Path(path))
    write_stats = apply_hitchmap_records(records)
    write_stats.rows_read = read_stats.rows_read
    write_stats.skipped_invalid = read_stats.skipped_invalid
    write_stats.skipped_filtered = read_stats.skipped_filtered
    write_stats.valid = read_stats.valid
    write_stats.source_schema = read_stats.source_schema
    write_stats.duration_seconds = (timezone.now() - started).total_seconds()
    return write_stats


def sync_hitchmap_spots_from_url(url: str | None = None) -> HitchmapSyncStats:
    url = url or getattr(
        settings, "HITCHWIKI_SPOTS_DUMP_URL", "https://hitchmap.com/dump.sqlite"
    )
    started = timezone.now()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="hitchmap_dump_", suffix=".sqlite", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        downloaded = download_hitchmap_dump(url, tmp_path)
        stats = sync_hitchmap_spots_from_file(tmp_path)
        stats.downloaded_bytes = downloaded
        stats.duration_seconds = (timezone.now() - started).total_seconds()
        logger.info(
            "Hitchmap sync finished: created=%s updated=%s deactivated=%s "
            "valid=%s skipped_invalid=%s skipped_filtered=%s bytes=%s duration=%.1fs",
            stats.created,
            stats.updated,
            stats.deactivated,
            stats.valid,
            stats.skipped_invalid,
            stats.skipped_filtered,
            stats.downloaded_bytes,
            stats.duration_seconds,
        )
        return stats
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove temporary Hitchmap dump %s", tmp_path)
