"""Tests for local PostGIS Hitchwiki recommendations and manual API."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from eurorace.hitchwiki_recommendations import (
    BADGE_BEST_OVERALL,
    BADGE_CLOSEST,
    BADGE_COMMUNITY_FAVORITE,
    BADGE_FASTEST_AI,
    get_ranked_hitchwiki_spots,
)
from eurorace.models import (
    DetectedStop,
    HitchwikiRecommendation,
    HitchwikiSpot,
    HitchwikiSpotAI,
    Race,
    Team,
)
from eurorace.services import recommend_hitchwiki_spots


class HitchwikiRankingTests(TestCase):
    def setUp(self):
        self.origin = Point(21.0122, 52.2297, srid=4326)
        self.near = HitchwikiSpot.objects.create(
            external_id="hitchmap:near",
            title="Near",
            location=Point(21.0150, 52.2300, srid=4326),
            rating=3.0,
            is_active=True,
        )
        self.far_better = HitchwikiSpot.objects.create(
            external_id="hitchmap:far",
            title="Far favorite",
            location=Point(21.0400, 52.2400, srid=4326),
            rating=5.0,
            is_active=True,
        )
        self.fast = HitchwikiSpot.objects.create(
            external_id="hitchmap:fast",
            title="Fast AI",
            location=Point(21.0200, 52.2320, srid=4326),
            rating=4.0,
            is_active=True,
        )
        HitchwikiSpotAI.objects.create(
            spot=self.near,
            predicted_wait_minutes=30.0,
            uncertainty=1.2,
            prediction_source="heatmap",
            model_version="heatmap:test",
        )
        HitchwikiSpotAI.objects.create(
            spot=self.far_better,
            predicted_wait_minutes=20.0,
            uncertainty=1.1,
            prediction_source="heatmap",
            model_version="heatmap:test",
        )
        HitchwikiSpotAI.objects.create(
            spot=self.fast,
            predicted_wait_minutes=8.0,
            uncertainty=0.95,
            prediction_source="model",
            model_version="model:test",
        )

    def test_ranking_returns_limited_unique_spots_with_badges(self):
        result = get_ranked_hitchwiki_spots(self.origin, radius_km=5, limit=5)
        self.assertGreaterEqual(len(result.recommendations), 3)
        ids = [item.spot.id for item in result.recommendations]
        self.assertEqual(len(ids), len(set(ids)))
        badges = {badge for item in result.recommendations for badge in item.badges}
        self.assertIn(BADGE_BEST_OVERALL, badges)
        self.assertIn(BADGE_CLOSEST, badges)
        self.assertIn(BADGE_FASTEST_AI, badges)
        self.assertIn(BADGE_COMMUNITY_FAVORITE, badges)
        self.assertIn(result.prediction_source, {"model", "heatmap", "mixed"})

    def test_ranking_works_without_ai(self):
        HitchwikiSpotAI.objects.all().delete()
        result = get_ranked_hitchwiki_spots(self.origin, radius_km=5, limit=3)
        self.assertEqual(result.prediction_source, "none")
        self.assertFalse(result.ai_available)
        self.assertGreaterEqual(len(result.recommendations), 1)

    def test_ranking_works_without_rating(self):
        HitchwikiSpot.objects.update(rating=None)
        result = get_ranked_hitchwiki_spots(self.origin, radius_km=5, limit=3)
        self.assertGreaterEqual(len(result.recommendations), 1)

    def test_radius_expansion(self):
        HitchwikiSpot.objects.all().delete()
        # Only one spot ~12 km away → should expand beyond 5 km.
        HitchwikiSpot.objects.create(
            external_id="hitchmap:faraway",
            title="Faraway",
            location=Point(21.20, 52.2297, srid=4326),
            rating=4.0,
            is_active=True,
        )
        result = get_ranked_hitchwiki_spots(self.origin, radius_km=5, limit=3)
        self.assertEqual(result.requested_radius_km, 5)
        self.assertGreater(result.effective_radius_km, 5)
        self.assertEqual(len(result.recommendations), 1)

    def test_inactive_spots_excluded(self):
        HitchwikiSpot.objects.update(is_active=False)
        result = get_ranked_hitchwiki_spots(self.origin, radius_km=25, limit=5)
        self.assertEqual(result.recommendations, [])

    @override_settings(HITCHWIKI_RECOMMENDATIONS_ENABLED=False)
    def test_feature_flag_disables_recommendations(self):
        result = get_ranked_hitchwiki_spots(self.origin, radius_km=5, limit=5)
        self.assertEqual(result.recommendations, [])


class HitchwikiPipelineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="team1", password="pass")
        self.race = Race.objects.create(name="Race")
        self.team = Team.objects.create(
            race=self.race,
            account_user=self.user,
            display_name="Team 1",
            bib_number="1",
        )
        self.stop = DetectedStop.objects.create(
            team=self.team,
            started_at=timezone.now() - timedelta(minutes=40),
            ended_at=timezone.now(),
            location=Point(21.0122, 52.2297, srid=4326),
            radius_meters=100,
            duration_seconds=2400,
        )
        HitchwikiSpot.objects.create(
            external_id="hitchmap:pipeline",
            title="Pipeline spot",
            location=Point(21.02, 52.23, srid=4326),
            rating=4.5,
            is_active=True,
        )

    def test_recommend_hitchwiki_spots_uses_local_db_only(self):
        self.assertFalse(hasattr(__import__("eurorace.services", fromlist=["services"]), "fetch_hitchwiki_spots"))
        recommendations = recommend_hitchwiki_spots(self.stop)
        self.assertEqual(len(recommendations), 1)
        self.assertTrue(
            HitchwikiRecommendation.objects.filter(stop=self.stop).exists()
        )
        self.stop.refresh_from_db()
        self.assertIsNotNone(self.stop.recommendation_generated_at)


class HitchwikiManualAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="apiuser", password="pass")
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        HitchwikiSpot.objects.create(
            external_id="hitchmap:api",
            title="API spot",
            location=Point(21.015, 52.230, srid=4326),
            rating=4.2,
            is_active=True,
        )

    def test_requires_auth(self):
        anon = APIClient()
        response = anon.get("/api/hitchwiki/recommendations/", {"lat": 52.23, "lon": 21.01})
        self.assertEqual(response.status_code, 401)

    def test_validation_errors(self):
        response = self.client.get("/api/hitchwiki/recommendations/")
        self.assertEqual(response.status_code, 400)
        response = self.client.get(
            "/api/hitchwiki/recommendations/",
            {"lat": 52.23, "lon": 21.01, "limit": 9},
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.get(
            "/api/hitchwiki/recommendations/",
            {"lat": 52.23, "lon": 21.01, "radius_km": 50},
        )
        self.assertEqual(response.status_code, 400)

    def test_manual_recommendations_read_only(self):
        before_stops = DetectedStop.objects.count()
        response = self.client.get(
            "/api/hitchwiki/recommendations/",
            {"lat": 52.2297, "lon": 21.0122, "radius_km": 5, "limit": 3},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("recommendations", payload)
        self.assertIn("effective_radius_km", payload)
        self.assertLessEqual(len(payload["recommendations"]), 3)
        self.assertEqual(DetectedStop.objects.count(), before_stops)

    def test_empty_response_far_away(self):
        response = self.client.get(
            "/api/hitchwiki/recommendations/",
            {"lat": 0.1, "lon": 0.1, "radius_km": 1, "limit": 5},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recommendations"], [])
