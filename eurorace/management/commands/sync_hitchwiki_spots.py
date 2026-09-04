from django.core.management.base import BaseCommand, CommandError

from eurorace.hitchwiki_spots_sync import (
    HitchmapDumpError,
    sync_hitchmap_spots_from_file,
    sync_hitchmap_spots_from_url,
)


class Command(BaseCommand):
    help = (
        "Download Hitchmap dump.sqlite and upsert local HitchwikiSpot rows. "
        "Does not call the legacy HitchWiki HTTP API."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            default=None,
            help="Override Hitchmap dump URL (default: HITCHWIKI_SPOTS_DUMP_URL).",
        )
        parser.add_argument(
            "--file",
            default=None,
            help="Import from a local SQLite dump instead of downloading.",
        )

    def handle(self, *args, **options):
        try:
            if options["file"]:
                stats = sync_hitchmap_spots_from_file(options["file"])
            else:
                stats = sync_hitchmap_spots_from_url(options["url"])
        except HitchmapDumpError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Hitchmap sync OK: "
                f"created={stats.created} updated={stats.updated} "
                f"deactivated={stats.deactivated} valid={stats.valid} "
                f"skipped_invalid={stats.skipped_invalid} "
                f"skipped_filtered={stats.skipped_filtered} "
                f"bytes={stats.downloaded_bytes} "
                f"duration={stats.duration_seconds:.1f}s"
            )
        )
