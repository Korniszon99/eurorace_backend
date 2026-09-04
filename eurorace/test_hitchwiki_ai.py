"""Offline Hitchwiki AI enrichment tests (no live network / no ML runtime required)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings

from eurorace.hitchwiki_ai_offline import (
    AdvisoryLockBusy,
    HitchwikiAIError,
    heatmap_lookup,
    lonlat_to_mercator,
    pixel_from_lonlat,
    sync_hitchwiki_ai,
    upsert_ai_predictions,
    world_grid_axes,
)
from eurorace.models import HitchwikiSpot, HitchwikiSpotAI


class HitchwikiAIOfflineTests(TestCase):
    def setUp(self):
        self.spot = HitchwikiSpot.objects.create(
            external_id="hitchmap:1",
            title="Warsaw ramp",
            location=Point(21.0122, 52.2297, srid=4326),
            rating=4.5,
            is_active=True,
        )
        self.spot2 = HitchwikiSpot.objects.create(
            external_id="hitchmap:2",
            title="Berlin ramp",
            location=Point(13.4050, 52.5200, srid=4326),
            rating=4.0,
            is_active=True,
        )

    def test_world_grid_matches_official_heatmap_shape(self):
        x_axis, y_axis, width, height = world_grid_axes()
        self.assertEqual(width, 3600)
        self.assertEqual(height, 1360)
        self.assertEqual(len(x_axis), 3600)
        self.assertEqual(len(y_axis), 1360)

    def test_pixel_from_lonlat_known_point(self):
        x_axis, y_axis, _, _ = world_grid_axes()
        yi, xi = pixel_from_lonlat(21.0122, 52.2297, x_axis, y_axis)
        self.assertIsNotNone(yi)
        self.assertIsNotNone(xi)
        self.assertGreaterEqual(yi, 0)
        self.assertGreaterEqual(xi, 0)

    def test_pixel_outside_bounds(self):
        x_axis, y_axis, _, _ = world_grid_axes()
        yi, xi = pixel_from_lonlat(0.0, -80.0, x_axis, y_axis)
        self.assertTrue(yi is None or xi is None)

    def test_mercator_roundtrip_rough(self):
        x, y = lonlat_to_mercator(21.0, 52.0)
        self.assertGreater(x, 0)
        self.assertGreater(y, 0)

    def test_heatmap_lookup_on_list_raster(self):
        # Tiny synthetic raster with same indexing rules; avoids numpy dependency.
        x_axis = [0.0, 1.0, 2.0]
        y_axis = [2.0, 1.0, 0.0]
        waiting = [
            [10.0, 11.0, 0.0],
            [12.0, 13.0, 0.0],
            [0.0, 0.0, 0.0],
        ]
        unc = [
            [1.1, 1.2, 0.0],
            [1.3, 1.4, 0.0],
            [0.0, 0.0, 0.0],
        ]
        with mock.patch(
            "eurorace.hitchwiki_ai_offline.pixel_from_lonlat",
            return_value=(1, 0),
        ):
            hit = heatmap_lookup(0, 0, waiting, unc, x_axis, y_axis)
        self.assertEqual(hit, (12.0, 1.3))

    @override_settings(HITCHWIKI_AI_MODE="model")
    def test_model_enrichment_mocked(self):
        def fake_run(batch_size, temp_dir):
            from eurorace.hitchwiki_ai_offline import AISyncStats

            rows = [
                {
                    "spot_id": self.spot.id,
                    "predicted_wait_minutes": 15.0,
                    "uncertainty": 0.95,
                    "prediction_source": "model",
                    "model_version": "test-model",
                },
                {
                    "spot_id": self.spot2.id,
                    "predicted_wait_minutes": 16.0,
                    "uncertainty": 0.96,
                    "prediction_source": "model",
                    "model_version": "test-model",
                },
            ]
            upsert_ai_predictions(rows)
            return AISyncStats(
                mode="model",
                prediction_source="model",
                model_version="test-model",
                processed=2,
                upserted=2,
            )

        with mock.patch(
            "eurorace.hitchwiki_ai_offline.run_model_enrichment",
            side_effect=fake_run,
        ):
            stats = sync_hitchwiki_ai(mode="model", batch_size=10)

        self.assertEqual(stats.prediction_source, "model")
        self.assertEqual(stats.upserted, 2)
        ai = HitchwikiSpotAI.objects.get(spot=self.spot)
        self.assertEqual(ai.predicted_wait_minutes, 15.0)
        self.assertAlmostEqual(ai.uncertainty, 0.95)
        self.assertEqual(ai.confidence, "high")
        self.spot.refresh_from_db()
        self.assertEqual(self.spot.average_waiting_time_minutes, 15.0)

    @override_settings(HITCHWIKI_AI_MODE="heatmap")
    def test_heatmap_enrichment_mocked(self):
        def fake_run(batch_size, temp_dir):
            from eurorace.hitchwiki_ai_offline import AISyncStats

            rows = [
                {
                    "spot_id": self.spot.id,
                    "predicted_wait_minutes": 22.5,
                    "uncertainty": 1.1,
                    "prediction_source": "heatmap",
                    "model_version": "heatmap:test",
                },
                {
                    "spot_id": self.spot2.id,
                    "predicted_wait_minutes": 22.5,
                    "uncertainty": 1.1,
                    "prediction_source": "heatmap",
                    "model_version": "heatmap:test",
                },
            ]
            upsert_ai_predictions(rows)
            return AISyncStats(
                mode="heatmap",
                prediction_source="heatmap",
                model_version="heatmap:test",
                processed=2,
                upserted=2,
            )

        with mock.patch(
            "eurorace.hitchwiki_ai_offline.run_heatmap_enrichment",
            side_effect=fake_run,
        ):
            stats = sync_hitchwiki_ai(mode="heatmap", batch_size=10)

        self.assertEqual(stats.prediction_source, "heatmap")
        ai = HitchwikiSpotAI.objects.get(spot=self.spot)
        self.assertEqual(ai.predicted_wait_minutes, 22.5)
        self.assertEqual(ai.confidence, "high")

    @override_settings(HITCHWIKI_AI_MODE="auto")
    def test_auto_falls_back_to_heatmap_when_model_unavailable(self):
        from eurorace.hitchwiki_ai_offline import AISyncStats

        def boom(batch_size, temp_dir):
            raise HitchwikiAIError("no sklearn")

        def heatmap_ok(batch_size, temp_dir):
            upsert_ai_predictions(
                [
                    {
                        "spot_id": self.spot.id,
                        "predicted_wait_minutes": 18.0,
                        "uncertainty": 1.2,
                        "prediction_source": "heatmap",
                        "model_version": "heatmap:fb",
                    }
                ]
            )
            stats = AISyncStats(
                mode="heatmap",
                prediction_source="heatmap",
                model_version="heatmap:fb",
                processed=1,
                upserted=1,
            )
            stats.details["fallback_reason"] = "no sklearn"
            return stats

        with (
            mock.patch(
                "eurorace.hitchwiki_ai_offline.run_model_enrichment",
                side_effect=boom,
            ),
            mock.patch(
                "eurorace.hitchwiki_ai_offline.run_heatmap_enrichment",
                side_effect=heatmap_ok,
            ),
        ):
            stats = sync_hitchwiki_ai(mode="auto", batch_size=10)

        self.assertEqual(stats.prediction_source, "heatmap")
        self.assertEqual(HitchwikiSpotAI.objects.count(), 1)

    def test_upsert_atomicity_on_failure(self):
        HitchwikiSpotAI.objects.create(
            spot=self.spot,
            predicted_wait_minutes=10.0,
            uncertainty=1.0,
            prediction_source="heatmap",
            model_version="old",
        )
        rows = [
            {
                "spot_id": self.spot.id,
                "predicted_wait_minutes": 99.0,
                "uncertainty": 0.5,
                "prediction_source": "model",
                "model_version": "new",
            }
        ]
        with mock.patch(
            "eurorace.hitchwiki_ai_offline.HitchwikiSpotAI.objects.bulk_update",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                upsert_ai_predictions(rows)

        ai = HitchwikiSpotAI.objects.get(spot=self.spot)
        self.assertEqual(ai.predicted_wait_minutes, 10.0)
        self.assertEqual(ai.model_version, "old")

    def test_advisory_lock_busy(self):
        with mock.patch("eurorace.hitchwiki_ai_offline.advisory_lock") as lock_mock:
            lock_mock.side_effect = AdvisoryLockBusy("busy")
            with self.assertRaises(AdvisoryLockBusy):
                sync_hitchwiki_ai(mode="heatmap")

    def test_inactive_spots_not_written_by_upsert_helper(self):
        # Enrichment iterators skip inactive spots; upsert itself is explicit.
        HitchwikiSpot.objects.filter(pk=self.spot2.pk).update(is_active=False)
        upsert_ai_predictions(
            [
                {
                    "spot_id": self.spot.id,
                    "predicted_wait_minutes": 11.0,
                    "uncertainty": 0.9,
                    "prediction_source": "model",
                    "model_version": "v",
                }
            ]
        )
        self.assertTrue(HitchwikiSpotAI.objects.filter(spot=self.spot).exists())
        self.assertFalse(HitchwikiSpotAI.objects.filter(spot=self.spot2).exists())

    def test_download_failure_keeps_previous_ai(self):
        HitchwikiSpotAI.objects.create(
            spot=self.spot,
            predicted_wait_minutes=10.0,
            uncertainty=1.0,
            prediction_source="heatmap",
            model_version="keep",
        )

        with mock.patch(
            "eurorace.hitchwiki_ai_offline.run_heatmap_enrichment",
            side_effect=HitchwikiAIError("download failed"),
        ):
            with self.assertRaises(HitchwikiAIError):
                sync_hitchwiki_ai(mode="heatmap")

        ai = HitchwikiSpotAI.objects.get(spot=self.spot)
        self.assertEqual(ai.model_version, "keep")
        self.assertEqual(ai.predicted_wait_minutes, 10.0)
