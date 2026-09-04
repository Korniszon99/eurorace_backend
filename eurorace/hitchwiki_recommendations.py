"""
Local Hitchwiki hotspot recommendations (PostGIS + DB only).

No external HTTP, no ML runtime, no heatmap loading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.contrib.gis.geos import Point
from django.db.models import FloatField
from django.db.models.expressions import RawSQL

from eurorace.models import HitchwikiSpot

DEFAULT_RADIUS_KM = 5
RADIUS_EXPANSION_KM = (5, 10, 15, 25)
MIN_CANDIDATES = 3
DEFAULT_LIMIT = 5
MAX_LIMIT = 5
MIN_RADIUS_KM = 1
MAX_RADIUS_KM = 25

RANK_WEIGHTS = {
    "distance": 0.30,
    "rating": 0.25,
    "predicted_wait": 0.30,
    "confidence": 0.15,
}

BADGE_BEST_OVERALL = "BEST_OVERALL"
BADGE_CLOSEST = "CLOSEST"
BADGE_FASTEST_AI = "FASTEST_AI"
BADGE_COMMUNITY_FAVORITE = "COMMUNITY_FAVORITE"


@dataclass
class RankedSpot:
    spot: HitchwikiSpot
    distance_m: float
    score: float
    badges: list[str] = field(default_factory=list)
    explanation: str = ""
    ai_wait_minutes: float | None = None
    ai_uncertainty: float | None = None
    ai_confidence: str | None = None
    prediction_source: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "spot_id": self.spot.id,
            "latitude": self.spot.location.y,
            "longitude": self.spot.location.x,
            "distance_m": round(self.distance_m, 1),
            "rating": self.spot.rating,
            "ai_wait_minutes": self.ai_wait_minutes,
            "ai_uncertainty": self.ai_uncertainty,
            "ai_confidence": self.ai_confidence,
            "prediction_source": self.prediction_source,
            "score": round(self.score, 4),
            "badges": list(self.badges),
            "explanation": self.explanation,
            "title": self.spot.title,
            "description": self.spot.description,
            "source_url": self.spot.source_url,
        }


@dataclass
class RecommendationResult:
    origin: Point
    requested_radius_km: float
    effective_radius_km: float
    recommendations: list[RankedSpot]
    ai_available: bool
    ai_data_version: str | None
    prediction_source: str  # model | heatmap | mixed | none

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "origin": {
                "latitude": self.origin.y,
                "longitude": self.origin.x,
            },
            "requested_radius_km": self.requested_radius_km,
            "effective_radius_km": self.effective_radius_km,
            "ai_available": self.ai_available,
            "ai_data_version": self.ai_data_version,
            "prediction_source": self.prediction_source,
            "recommendations": [item.to_api_dict() for item in self.recommendations],
        }


def _clamp_radius(radius_km: float | None) -> float:
    if radius_km is None:
        return float(DEFAULT_RADIUS_KM)
    return float(max(MIN_RADIUS_KM, min(MAX_RADIUS_KM, radius_km)))


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return int(max(1, min(MAX_LIMIT, limit)))


def _weights() -> dict[str, float]:
    configured = getattr(settings, "HITCHWIKI_RANK_WEIGHTS", None)
    return dict(configured or RANK_WEIGHTS)


def _distance_annotation(lon: float, lat: float):
    return RawSQL(
        "ST_DistanceSphere(location, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
        (lon, lat),
        output_field=FloatField(),
    )


def _query_candidates(origin: Point, radius_km: float):
    lon, lat = origin.x, origin.y
    radius_m = radius_km * 1000.0
    return (
        HitchwikiSpot.objects.filter(is_active=True)
        .annotate(distance_m=_distance_annotation(lon, lat))
        .filter(distance_m__lte=radius_m)
        .select_related("ai")
        .order_by("distance_m")
    )


def _expand_candidates(origin: Point, requested_radius_km: float):
    radii = []
    for value in RADIUS_EXPANSION_KM:
        if value >= requested_radius_km and value not in radii:
            radii.append(float(value))
    if requested_radius_km not in radii:
        radii.insert(0, float(requested_radius_km))
    radii = sorted(set(radii))

    effective = requested_radius_km
    candidates = []
    for radius in radii:
        effective = radius
        candidates = list(_query_candidates(origin, radius)[:80])
        if len(candidates) >= MIN_CANDIDATES:
            break
    return candidates, effective


def _norm_higher(values: list[float | None]) -> list[float | None]:
    present = [v for v in values if v is not None]
    if not present:
        return [None] * len(values)
    lo, hi = min(present), max(present)
    if hi == lo:
        return [1.0 if v is not None else None for v in values]
    return [None if v is None else (v - lo) / (hi - lo) for v in values]


def _norm_lower(values: list[float | None]) -> list[float | None]:
    # lower is better → invert after normalize
    higher = _norm_higher(values)
    return [None if v is None else 1.0 - v for v in higher]


def _ai_fields(spot: HitchwikiSpot) -> tuple[float | None, float | None, str | None, str | None]:
    ai = getattr(spot, "ai", None)
    if ai is None:
        # Fallback to mirrored wait on spot if present (legacy serializers).
        wait = spot.average_waiting_time_minutes
        return wait, None, None, None
    return (
        ai.predicted_wait_minutes,
        ai.uncertainty,
        ai.confidence,
        ai.prediction_source,
    )


def _score_candidates(spots: list[HitchwikiSpot]) -> list[tuple[HitchwikiSpot, float, dict]]:
    weights = _weights()
    distances = [float(getattr(spot, "distance_m")) for spot in spots]
    ratings = [spot.rating for spot in spots]
    waits = []
    uncertainties = []
    for spot in spots:
        wait, unc, _, _ = _ai_fields(spot)
        waits.append(wait)
        uncertainties.append(unc)

    dist_scores = _norm_lower(distances)
    rating_scores = _norm_higher(ratings)
    wait_scores = _norm_lower(waits)
    conf_scores = _norm_lower(uncertainties)

    scored = []
    for idx, spot in enumerate(spots):
        components = {
            "distance": dist_scores[idx],
            "rating": rating_scores[idx],
            "predicted_wait": wait_scores[idx],
            "confidence": conf_scores[idx],
        }
        available = {k: v for k, v in components.items() if v is not None}
        if not available:
            score = 0.0
        else:
            weight_sum = sum(weights[k] for k in available)
            score = sum(available[k] * (weights[k] / weight_sum) for k in available)
        scored.append((spot, float(score), components))
    scored.sort(key=lambda item: (-item[1], float(getattr(item[0], "distance_m", 0))))
    return scored


def _assign_badges(ranked: list[RankedSpot]) -> None:
    if not ranked:
        return
    ranked[0].badges.append(BADGE_BEST_OVERALL)

    closest = min(ranked, key=lambda item: item.distance_m)
    if BADGE_CLOSEST not in closest.badges:
        closest.badges.append(BADGE_CLOSEST)

    with_rating = [item for item in ranked if item.spot.rating is not None]
    if with_rating:
        favorite = max(with_rating, key=lambda item: item.spot.rating)
        if BADGE_COMMUNITY_FAVORITE not in favorite.badges:
            favorite.badges.append(BADGE_COMMUNITY_FAVORITE)

    with_ai_wait = [item for item in ranked if item.ai_wait_minutes is not None]
    if with_ai_wait:
        fastest = min(with_ai_wait, key=lambda item: item.ai_wait_minutes)
        if BADGE_FASTEST_AI not in fastest.badges:
            fastest.badges.append(BADGE_FASTEST_AI)


def _explanation(item: RankedSpot) -> str:
    parts = []
    if BADGE_BEST_OVERALL in item.badges:
        parts.append("Dobry balans między odległością, oceną społeczności i przewidywanym czasem oczekiwania")
    if BADGE_CLOSEST in item.badges:
        parts.append("Najbliższy spot względem Twojej lokalizacji")
    if BADGE_FASTEST_AI in item.badges:
        parts.append("Najkrótszy przewidywany czas oczekiwania")
    if BADGE_COMMUNITY_FAVORITE in item.badges:
        parts.append("Najwyższa ocena społeczności w zestawieniu")
    if not parts:
        if item.ai_wait_minutes is not None and item.spot.rating is not None:
            parts.append("Uwzględniono odległość, rating i AI wait")
        elif item.spot.rating is not None:
            parts.append("Ocena na podstawie odległości i ratingu społeczności")
        else:
            parts.append("Ocena głównie na podstawie odległości")
    return ". ".join(parts) + "."


def _prediction_source_summary(ranked: list[RankedSpot]) -> str:
    sources = {item.prediction_source for item in ranked if item.prediction_source}
    if not sources:
        return "none"
    if sources == {"model"}:
        return "model"
    if sources == {"heatmap"}:
        return "heatmap"
    if len(sources) > 1:
        return "mixed"
    return next(iter(sources))


def _ai_meta(ranked: list[RankedSpot]) -> tuple[bool, str | None]:
    versions = []
    for item in ranked:
        ai = getattr(item.spot, "ai", None)
        if ai and ai.model_version:
            versions.append(ai.model_version)
    ai_available = any(item.ai_wait_minutes is not None and item.prediction_source for item in ranked)
    version = versions[0] if versions else None
    if versions and any(v != version for v in versions):
        version = "mixed"
    return ai_available, version


def get_ranked_hitchwiki_spots(
    origin: Point,
    radius_km: float | None = None,
    limit: int | None = None,
) -> RecommendationResult:
    if not getattr(settings, "HITCHWIKI_RECOMMENDATIONS_ENABLED", True):
        requested = _clamp_radius(radius_km)
        return RecommendationResult(
            origin=origin,
            requested_radius_km=requested,
            effective_radius_km=requested,
            recommendations=[],
            ai_available=False,
            ai_data_version=None,
            prediction_source="none",
        )

    requested = _clamp_radius(radius_km)
    limit_n = _clamp_limit(limit)
    if origin.srid is None:
        origin.srid = 4326

    candidates, effective = _expand_candidates(origin, requested)
    scored = _score_candidates(candidates)
    ranked: list[RankedSpot] = []
    for spot, score, _components in scored[:limit_n]:
        wait, unc, confidence, source = _ai_fields(spot)
        # Only treat as AI when HitchwikiSpotAI row exists.
        ai = getattr(spot, "ai", None)
        ranked.append(
            RankedSpot(
                spot=spot,
                distance_m=float(getattr(spot, "distance_m")),
                score=score,
                ai_wait_minutes=wait if ai is not None else None,
                ai_uncertainty=unc if ai is not None else None,
                ai_confidence=confidence if ai is not None else None,
                prediction_source=source if ai is not None else None,
            )
        )

    _assign_badges(ranked)
    for item in ranked:
        item.explanation = _explanation(item)

    ai_available, ai_version = _ai_meta(ranked)
    return RecommendationResult(
        origin=origin,
        requested_radius_km=requested,
        effective_radius_km=effective,
        recommendations=ranked,
        ai_available=ai_available,
        ai_data_version=ai_version,
        prediction_source=_prediction_source_summary(ranked),
    )


def get_ranked_hitchwiki_spots_for_lonlat(
    latitude: float,
    longitude: float,
    radius_km: float | None = None,
    limit: int | None = None,
) -> RecommendationResult:
    origin = Point(float(longitude), float(latitude), srid=4326)
    return get_ranked_hitchwiki_spots(origin, radius_km=radius_km, limit=limit)
