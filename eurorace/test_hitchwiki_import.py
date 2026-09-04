"""Tests for Hitchmap dump → HitchwikiSpot import (no live network)."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase

from eurorace.hitchwiki_spots_sync import (
    HitchmapDumpError,
    apply_hitchmap_records,
    build_external_id,
    download_hitchmap_dump,
    load_records_from_sqlite,
    sync_hitchmap_spots_from_file,
    sync_hitchmap_spots_from_url,
)
from eurorace.models import HitchwikiSpot


def _write_dump(path: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE points (
            id INTEGER PRIMARY KEY,
            lat REAL,
            lon REAL,
            rating REAL,
            country TEXT,
            wait REAL,
            comment TEXT,
            datetime TEXT,
            reviewed INTEGER,
            banned INTEGER
        )
        """
    )
    con.executemany(
        """
        INSERT INTO points
        (id, lat, lon, rating, country, wait, comment, datetime, reviewed, banned)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.commit()
    con.close()


class HitchmapImportTests(TestCase):
    def test_import_dump_creates_spots(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "dump.sqlite"
            _write_dump(
                dump,
                [
                    (1, 52.23, 21.01, 4.5, "PL", 12.0, "Good ramp", "2024-01-01 10:00:00", 1, 0),
                    (2, 52.24, 21.02, 3.0, "PL", None, "Ok", "2024-01-02 10:00:00", 1, 0),
                ],
            )
            stats = sync_hitchmap_spots_from_file(dump)

        self.assertEqual(stats.created, 2)
        self.assertEqual(stats.updated, 0)
        self.assertEqual(HitchwikiSpot.objects.count(), 2)
        spot = HitchwikiSpot.objects.get(external_id=build_external_id(1))
        self.assertEqual(spot.rating, 4.5)
        self.assertEqual(spot.rating_count, 1)
        self.assertEqual(spot.average_waiting_time_minutes, 12.0)
        self.assertTrue(spot.is_active)
        self.assertAlmostEqual(spot.location.y, 52.23, places=5)
        self.assertAlmostEqual(spot.location.x, 21.01, places=5)

    def test_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "dump.sqlite"
            rows = [
                (10, 50.0, 19.0, 5.0, "PL", 8.0, "A", "2024-01-01 00:00:00", 1, 0),
            ]
            _write_dump(dump, rows)
            first = sync_hitchmap_spots_from_file(dump)
            # Update rating in dump and re-import
            con = sqlite3.connect(dump)
            con.execute("UPDATE points SET rating=4.0, comment='B' WHERE id=10")
            con.commit()
            con.close()
            second = sync_hitchmap_spots_from_file(dump)

        self.assertEqual(first.created, 1)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.updated, 1)
        self.assertEqual(HitchwikiSpot.objects.count(), 1)
        spot = HitchwikiSpot.objects.get(external_id=build_external_id(10))
        self.assertEqual(spot.rating, 4.0)
        self.assertEqual(spot.title, "B")

    def test_invalid_coordinates_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "dump.sqlite"
            _write_dump(
                dump,
                [
                    (1, 91.0, 21.0, 4.0, "PL", None, "bad lat", "2024-01-01 00:00:00", 1, 0),
                    (2, 52.0, 21.0, 4.0, "PL", None, "ok", "2024-01-01 00:00:00", 1, 0),
                    (3, None, 21.0, 4.0, "PL", None, "null", "2024-01-01 00:00:00", 1, 0),
                ],
            )
            stats = sync_hitchmap_spots_from_file(dump)

        self.assertEqual(stats.skipped_invalid, 2)
        self.assertEqual(stats.valid, 1)
        self.assertEqual(HitchwikiSpot.objects.count(), 1)

    def test_filtered_unreviewed_and_banned_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "dump.sqlite"
            _write_dump(
                dump,
                [
                    (1, 52.0, 21.0, 4.0, "PL", None, "ok", "2024-01-01 00:00:00", 1, 0),
                    (2, 52.1, 21.1, 4.0, "PL", None, "unreviewed", "2024-01-01 00:00:00", 0, 0),
                    (3, 52.2, 21.2, 4.0, "PL", None, "banned", "2024-01-01 00:00:00", 1, 1),
                ],
            )
            stats = sync_hitchmap_spots_from_file(dump)

        self.assertEqual(stats.skipped_filtered, 2)
        self.assertEqual(stats.valid, 1)
        self.assertEqual(HitchwikiSpot.objects.count(), 1)

    def test_download_failure_preserves_old_data(self):
        HitchwikiSpot.objects.create(
            external_id=build_external_id(99),
            title="Existing",
            location=Point(21.0, 52.0, srid=4326),
            rating=5.0,
            is_active=True,
        )
        with mock.patch(
            "eurorace.hitchwiki_spots_sync.download_hitchmap_dump",
            side_effect=HitchmapDumpError("network down"),
        ):
            with self.assertRaises(HitchmapDumpError):
                sync_hitchmap_spots_from_url("https://example.test/dump.sqlite")

        self.assertEqual(HitchwikiSpot.objects.count(), 1)
        self.assertEqual(HitchwikiSpot.objects.get().title, "Existing")

    def test_apply_failure_is_atomic(self):
        HitchwikiSpot.objects.create(
            external_id=build_external_id(1),
            title="Keep me",
            location=Point(21.0, 52.0, srid=4326),
            rating=5.0,
            is_active=True,
        )
        records = [
            {
                "external_id": build_external_id(2),
                "title": "New",
                "description": "",
                "location": Point(21.1, 52.1, srid=4326),
                "rating": 4.0,
                "rating_count": 1,
                "average_waiting_time_minutes": None,
                "source_url": "https://hitchmap.com/#52.1,21.1,15",
                "metadata": {"source": "hitchmap"},
                "source_updated_at": None,
                "is_active": True,
            }
        ]
        with mock.patch(
            "eurorace.hitchwiki_spots_sync.HitchwikiSpot.objects.bulk_create",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                apply_hitchmap_records(records)

        self.assertEqual(HitchwikiSpot.objects.count(), 1)
        self.assertEqual(HitchwikiSpot.objects.get().title, "Keep me")

    def test_missing_points_table_raises_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "bad.sqlite"
            con = sqlite3.connect(dump)
            con.execute("CREATE TABLE other (id INTEGER)")
            con.commit()
            con.close()
            with self.assertRaises(HitchmapDumpError):
                load_records_from_sqlite(dump)
        self.assertEqual(HitchwikiSpot.objects.count(), 0)

    def test_successful_sync_deactivates_missing_hitchmap_spots(self):
        HitchwikiSpot.objects.create(
            external_id=build_external_id(1),
            title="Old",
            location=Point(21.0, 52.0, srid=4326),
            is_active=True,
        )
        HitchwikiSpot.objects.create(
            external_id="manual:keep",
            title="Manual",
            location=Point(22.0, 53.0, srid=4326),
            is_active=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "dump.sqlite"
            _write_dump(
                dump,
                [
                    (2, 51.0, 20.0, 3.0, "PL", None, "new", "2024-01-01 00:00:00", 1, 0),
                ],
            )
            sync_hitchmap_spots_from_file(dump)

        self.assertFalse(HitchwikiSpot.objects.get(external_id=build_external_id(1)).is_active)
        self.assertTrue(HitchwikiSpot.objects.get(external_id=build_external_id(2)).is_active)
        self.assertTrue(HitchwikiSpot.objects.get(external_id="manual:keep").is_active)

    def test_download_cleans_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.sqlite"
            payload = b"x" * 2000

            class FakeResp:
                def read(self, n=-1):
                    if not hasattr(self, "_done"):
                        self._done = True
                        return payload
                    return b""

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            with mock.patch("eurorace.hitchwiki_spots_sync.urlopen", return_value=FakeResp()):
                size = download_hitchmap_dump("https://example.test/dump.sqlite", dest)
            self.assertEqual(size, 2000)
            self.assertTrue(dest.exists())
