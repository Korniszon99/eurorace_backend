import math
from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.utils import timezone

from eurorace.hitchwiki_recommendations import get_ranked_hitchwiki_spots
from eurorace.models import (
    DetectedStop,
    HitchwikiRecommendation,
    LocationReport,
    Race,
    Team,
    TeamStatistics,
)
from eurorace.task_models import UserTask

EARTH_RADIUS_METERS = 6_371_000
# Same place ≈ within this radius of the latest GPS reading.
STOP_RADIUS_METERS = 15_000
# Wall-clock span between first and last reading in that place (not app uptime).
STOP_MIN_DURATION = timedelta(minutes=30)
# How far back we look for a stay cluster (gaps in tracking are OK).
STOP_LOOKBACK = timedelta(hours=12)
# Ignore stale last fixes — team is not actively waiting for a ride.
STOP_MAX_STALENESS = timedelta(hours=2)
# Don't regenerate Hitchwiki tips on every ping once we have fresh ones.
RECOMMENDATION_REFRESH = timedelta(minutes=10)
DEFAULT_RECOMMENDATION_LIMIT = 5
STOP_MIN_REPORTS = 2


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


def _cluster_reports_around_latest(reports):
    """
    Walk backwards from the newest GPS fix and keep points still in the same ~15 km area.
    Duration comes from reading timestamps, so intermittent tracking still counts as a stay.
    """
    if len(reports) < STOP_MIN_REPORTS:
        return []

    latest = reports[-1]
    cluster = [latest]
    for report in reversed(reports[:-1]):
        if haversine_distance_meters(latest.location, report.location) <= STOP_RADIUS_METERS:
            cluster.append(report)
        else:
            # Left the area earlier — only the current stay matters.
            break
    cluster.reverse()
    return cluster


def detect_stationary_stop(team, now=None):
    """
    Detect that a team likely needs a hitchhiking hotspot.

    Criteria (place + GPS time, not continuous app session):
    - latest reading is fresh enough
    - consecutive history around that place stays within STOP_RADIUS_METERS
    - span between first and last reading timestamps >= STOP_MIN_DURATION
    """
    if not team:
        return None

    now = now or timezone.now()
    lookback_start = now - STOP_LOOKBACK
    reports = list(
        get_team_location_reports(team).filter(timestamp__gte=lookback_start).order_by("timestamp")
    )
    cluster = _cluster_reports_around_latest(reports)
    if len(cluster) < STOP_MIN_REPORTS:
        return None

    started_at = cluster[0].timestamp
    ended_at = cluster[-1].timestamp
    if now - ended_at > STOP_MAX_STALENESS:
        return None
    if ended_at - started_at < STOP_MIN_DURATION:
        return None

    centroid = _centroid_for_reports(cluster)
    radius_meters = max(haversine_distance_meters(centroid, report.location) for report in cluster)
    duration_seconds = int((ended_at - started_at).total_seconds())

    recent_stop = (
        DetectedStop.objects.filter(team=team, ended_at__gte=lookback_start)
        .order_by("-ended_at")
        .first()
    )
    if recent_stop and haversine_distance_meters(recent_stop.location, centroid) <= STOP_RADIUS_METERS:
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

    needs_refresh = (
        stop.recommendation_generated_at is None
        or now - stop.recommendation_generated_at >= RECOMMENDATION_REFRESH
        or not stop.recommendations.exists()
    )
    if needs_refresh:
        recommend_hitchwiki_spots(stop)
    update_team_statistics(team)
    return stop


def recommend_hitchwiki_spots(stop, limit=DEFAULT_RECOMMENDATION_LIMIT):
    """
    Persist ranked local Hitchwiki spots for a DetectedStop.

    Uses PostGIS + HitchwikiSpot(+AI) only — no external HitchWiki HTTP API.
    """
    result = get_ranked_hitchwiki_spots(stop.location, radius_km=5, limit=limit)
    recommendations = []
    keep_spot_ids = []
    for ranked in result.recommendations:
        keep_spot_ids.append(ranked.spot.id)
        recommendation, _ = HitchwikiRecommendation.objects.update_or_create(
            stop=stop,
            spot=ranked.spot,
            defaults={
                "distance_meters": ranked.distance_m,
                "score": ranked.score,
            },
        )
        recommendations.append(recommendation)

    if keep_spot_ids:
        HitchwikiRecommendation.objects.filter(stop=stop).exclude(spot_id__in=keep_spot_ids).delete()
        stop.recommendation_generated_at = timezone.now()
        stop.save(update_fields=("recommendation_generated_at",))
    elif not result.recommendations:
        # Clear stale recommendations when nothing is nearby.
        HitchwikiRecommendation.objects.filter(stop=stop).delete()

    return recommendations


def process_location_report(report):
    team = get_user_team(report.user)
    if not team:
        return None
    update_team_statistics(team)
    return detect_stationary_stop(team)
