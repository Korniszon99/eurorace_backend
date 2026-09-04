# Generated manually for HitchwikiSpotAI offline enrichment.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("eurorace", "0005_hitchwikispot_import_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="HitchwikiSpotAI",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("predicted_wait_minutes", models.FloatField()),
                ("uncertainty", models.FloatField(blank=True, null=True)),
                (
                    "prediction_source",
                    models.CharField(
                        choices=[("model", "Pretrained model"), ("heatmap", "Precomputed heatmap")],
                        max_length=16,
                    ),
                ),
                ("model_version", models.CharField(blank=True, max_length=255)),
                ("prediction_generated_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "spot",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai",
                        to="eurorace.hitchwikispot",
                    ),
                ),
            ],
            options={
                "verbose_name": "Hitchwiki spot AI",
                "verbose_name_plural": "Hitchwiki spot AI",
            },
        ),
    ]
