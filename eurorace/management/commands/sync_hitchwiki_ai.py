from django.core.management.base import BaseCommand, CommandError

from eurorace.hitchwiki_ai_offline import (
    AdvisoryLockBusy,
    HitchwikiAIError,
    sync_hitchwiki_ai,
)


class Command(BaseCommand):
    help = (
        "Offline AI enrichment for HitchwikiSpot rows. "
        "Uses pretrained Hitchwiki GP model when available, else heatmap parquet. "
        "Never runs inside request/WebSocket paths."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            choices=("auto", "model", "heatmap"),
            default=None,
            help="Override HITCHWIKI_AI_MODE for this run.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help="Prediction/upsert batch size (default: HITCHWIKI_AI_BATCH_SIZE).",
        )

    def handle(self, *args, **options):
        try:
            stats = sync_hitchwiki_ai(mode=options["mode"], batch_size=options["batch_size"])
        except AdvisoryLockBusy as exc:
            raise CommandError(str(exc)) from exc
        except HitchwikiAIError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Hitchwiki AI sync OK: "
                f"mode={stats.mode} source={stats.prediction_source} "
                f"version={stats.model_version} processed={stats.processed} "
                f"upserted={stats.upserted} skipped={stats.skipped} "
                f"failed={stats.failed} duration={stats.duration_seconds:.1f}s "
                f"peak_rss_mb={stats.peak_rss_mb}"
            )
        )
