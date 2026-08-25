import json
import math
from datetime import timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.utils import timezone

from eurorace.models import (
    DetectedStop,
    HitchwikiRecommendation,
    HitchwikiSpot,
    LocationReport,
    Race,
    Team,
    TeamStatistics,
)
from eurorace.task_models import UserTask

EARTH_RADIUS_METERS = 6_371_000
STOP_RADIUS_METERS = 15_000
STOP_MIN_DURATION = timedelta(minutes=30)
RECOMMENDATION_RADIUS_METERS = 25_000
DEFAULT_RECOMMENDATION_LIMIT = 5


def haversine_distance_meters(first, second):
    lon1, lat1 = math.radians(first.x), math.radians(first.y)
    lon2, lat2 = math.radians(second.x), math.radians(second.y)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(value))


def get_active_race():
    return Race.objects.filter(is_active=True).order_by("-starts_at", "-created_at").first()


def get_user_team(user):
    if not user or not user.is_authenticated:
        return None
    return Team.objects.filter(account_user=user, is_active=True).select_related("race").first()


def get_team_users(team):
    if not team:
        return User.objects.none()
    return User.objects.filter(pk=team.account_user_id)


def get_team_location_reports(team):
    user_ids = get_team_users(team).values_list("id", flat=True)
    return LocationReport.objects.filter(user_id__in=user_ids).order_by("timestamp")


def calculate_route_statistics(locations):
    points = list(locations)
    if not points:
        return {
            "started_at": None,
            "finished_at": None,
            "duration_seconds": 0,
            "distance_meters": 0,
            "elevation_gain_meters": 0,
        }

    distance_meters = 0
    elevation_gain_meters = 0
    previous = None
    for report in points:
        if previous:
            distance_meters += haversine_distance_meters(previous.location, report.location)
            if previous.altitude_m is not None and report.altitude_m is not None:
                elevation_gain_meters += max(report.altitude_m - previous.altitude_m, 0)
        previous = report

    started_at = points[0].timestamp
    finished_at = points[-1].timestamp
    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": int((finished_at - started_at).total_seconds()),
        "distance_meters": distance_meters,
        "elevation_gain_meters": elevation_gain_meters,
    }


def update_team_statistics(team):
    if not team:
        return None

    route_stats = calculate_route_statistics(get_team_location_reports(team))
    completed_tasks_count = UserTask.objects.filter(user=team.account_user, status="completed").count()
    hitch_count = DetectedStop.objects.filter(team=team).count()

    statistics, _ = TeamStatistics.objects.update_or_create(
        team=team,
        defaults={
            **route_stats,
            "hitch_count": hitch_count,
            "completed_tasks_count": completed_tasks_count,
            "last_calculated_at": timezone.now(),
        },
    )
    return statistics


def _centroid_for_reports(reports):
    lon = sum(report.location.x for report in reports) / len(reports)
    lat = sum(report.location.y for report in reports) / len(reports)
    return Point(lon, lat, srid=4326)


def detect_stationary_stop(team, now=None):
    if not team:
        return None

    now = now or timezone.now()
    window_start = now - STOP_MIN_DURATION
    reports = list(get_team_location_reports(team).filter(timestamp__gte=window_start))
    if len(reports) < 2:
        return None

    started_at = reports[0].timestamp
    ended_at = reports[-1].timestamp
    if ended_at - started_at < STOP_MIN_DURATION:
        return None

    centroid = _centroid_for_reports(reports)
    radius_meters = max(haversine_distance_meters(centroid, report.location) for report in reports)
    if radius_meters > STOP_RADIUS_METERS:
        return None

    recent_stop = (
        DetectedStop.objects.filter(team=team, ended_at__gte=window_start)
        .order_by("-ended_at")
        .first()
    )
    duration_seconds = int((ended_at - started_at).total_seconds())
    if recent_stop:
        recent_stop.started_at = min(recent_stop.started_at, started_at)
        recent_stop.ended_at = ended_at
        recent_stop.location = centroid
        recent_stop.radius_meters = radius_meters
        recent_stop.duration_seconds = duration_seconds
        recent_stop.save(
            update_fields=("started_at", "ended_at", "location", "radius_meters", "duration_seconds")
        )
        stop = recent_stop
    else:
        stop = DetectedStop.objects.create(
            team=team,
            started_at=started_at,
            ended_at=ended_at,
            location=centroid,
            radius_meters=radius_meters,
            duration_seconds=duration_seconds,
        )

    recommend_hitchwiki_spots(stop)
    update_team_statistics(team)
    return stop


def _normalize_hitchwiki_items(payload):
    if isinstance(payload, dict):
        for key in ("spots", "features", "results", "data"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
        return []
    if isinstance(payload, list):
        return payload
    return []


def _extract_coordinate(item, *names):
    for name in names:
        value = item.get(name)
        if value is not None:
            return value
    geometry = item.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) >= 2:
        if "lon" in names or "lng" in names or "longitude" in names:
            return coordinates[0]
        return coordinates[1]
    return None


def _upsert_hitchwiki_spot(item):
    properties = item.get("properties") or item
    lat = _extract_coordinate(item, "lat", "latitude", "y")
    lon = _extract_coordinate(item, "lon", "lng", "longitude", "x")
    if lat is None or lon is None:
        lat = _extract_coordinate(properties, "lat", "latitude", "y")
        lon = _extract_coordinate(properties, "lon", "lng", "longitude", "x")
    if lat is None or lon is None:
        return None

    external_id = str(properties.get("id") or properties.get("external_id") or item.get("id") or "")
    defaults = {
        "title": properties.get("title") or properties.get("name") or "Hitchwiki spot",
        "description": properties.get("description") or properties.get("comment") or "",
        "location": Point(float(lon), float(lat), srid=4326),
        "rating": properties.get("rating"),
        "average_waiting_time_minutes": properties.get("average_wait") or properties.get("waiting_time"),
        "source_url": properties.get("url") or properties.get("source_url") or "",
        "metadata": properties,
    }
    if external_id:
        spot, _ = HitchwikiSpot.objects.update_or_create(external_id=external_id, defaults=defaults)
        return spot
    return HitchwikiSpot.objects.create(**defaults)


def fetch_hitchwiki_spots(latitude, longitude, radius_km=25):
    base_url = getattr(settings, "HITCHWIKI_SPOTS_URL", "")
    if not base_url:
        return []

    query = urlencode({"lat": latitude, "lon": longitude, "radius_km": radius_km})
    separator = "&" if "?" in base_url else "?"
    with urlopen(f"{base_url}{separator}{query}", timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))

    spots = []
    for item in _normalize_hitchwiki_items(payload):
        spot = _upsert_hitchwiki_spot(item)
        if spot:
            spots.append(spot)
    return spots


def _spot_score(spot, distance_meters):
    rating = spot.rating if spot.rating is not None else 0
    wait_penalty = spot.average_waiting_time_minutes or 0
    return (rating * 20) - (distance_meters / 1000) - (wait_penalty * 0.2)


def recommend_hitchwiki_spots(stop, limit=DEFAULT_RECOMMENDATION_LIMIT):
    latitude = stop.location.y
    longitude = stop.location.x

    try:
        fetch_hitchwiki_spots(latitude, longitude, radius_km=RECOMMENDATION_RADIUS_METERS / 1000)
    except Exception:
        # Hitchwiki currently has no stable public nearby API. Cached spots still make recommendations usable.
        pass

    candidates = []
    for spot in HitchwikiSpot.objects.all():
        distance_meters = haversine_distance_meters(stop.location, spot.location)
        if distance_meters <= RECOMMENDATION_RADIUS_METERS:
            candidates.append((spot, distance_meters, _spot_score(spot, distance_meters)))

    candidates.sort(key=lambda item: (-item[2], item[1]))
    recommendations = []
    for spot, distance_meters, score in candidates[:limit]:
        recommendation, _ = HitchwikiRecommendation.objects.update_or_create(
            stop=stop,
            spot=spot,
            defaults={"distance_meters": distance_meters, "score": score},
        )
        recommendations.append(recommendation)

    if recommendations:
        stop.recommendation_generated_at = timezone.now()
        stop.save(update_fields=("recommendation_generated_at",))
    return recommendations


def process_location_report(report):
    team = get_user_team(report.user)
    if not team:
        return None
    update_team_statistics(team)
    return detect_stationary_stop(team)
