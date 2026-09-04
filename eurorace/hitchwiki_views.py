from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from eurorace.hitchwiki_recommendations import (
    MAX_RADIUS_KM,
    MIN_RADIUS_KM,
    get_ranked_hitchwiki_spots_for_lonlat,
)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def hitchwiki_recommendations(request):
    """
    Manual read-only hitch hotspot recommendations for the current map location.

    Does not write LocationReport / DetectedStop and does not run ML.
    """
    try:
        lat = float(request.query_params.get("lat"))
        lon = float(request.query_params.get("lon"))
    except (TypeError, ValueError):
        return Response(
            {"detail": "Parametry lat i lon są wymagane i muszą być liczbami."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return Response(
            {"detail": "Nieprawidłowe współrzędne lat/lon."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    radius_raw = request.query_params.get("radius_km")
    limit_raw = request.query_params.get("limit")
    radius_km = None
    limit = None
    if radius_raw is not None:
        try:
            radius_km = float(radius_raw)
        except (TypeError, ValueError):
            return Response(
                {"detail": "radius_km musi być liczbą."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not (MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM):
            return Response(
                {"detail": f"radius_km musi być w zakresie {MIN_RADIUS_KM}..{MAX_RADIUS_KM}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            return Response(
                {"detail": "limit musi być liczbą całkowitą."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not (1 <= limit <= 5):
            return Response(
                {"detail": "limit musi być w zakresie 1..5."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    result = get_ranked_hitchwiki_spots_for_lonlat(
        latitude=lat,
        longitude=lon,
        radius_km=radius_km,
        limit=limit,
    )
    return Response(result.to_api_dict())
