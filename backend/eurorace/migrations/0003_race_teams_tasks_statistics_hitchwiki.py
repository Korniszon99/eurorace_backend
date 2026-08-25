# Generated for Eurorace race management features.

import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        ("eurorace", "0002_alter_locationreport_timestamp"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Race",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("starts_at", models.DateTimeField(blank=True, null=True)),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("-is_active", "-starts_at", "name")},
        ),
        migrations.CreateModel(
            name="Task",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField()),
                ("location", django.contrib.gis.db.models.fields.PointField(blank=True, null=True, srid=4326)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Oczekujące"),
                            ("in_progress", "W trakcie"),
                            ("completed", "Ukończone"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Team",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(max_length=255)),
                ("bib_number", models.CharField(blank=True, db_index=True, max_length=32)),
                ("contact_email", models.EmailField(blank=True, max_length=254)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "account_user",
                    models.OneToOneField(
                        help_text="Login used by the pair in the mobile app.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="race_team",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "race",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="teams",
                        to="eurorace.race",
                    ),
                ),
            ],
            options={"ordering": ("bib_number", "display_name")},
        ),
        migrations.CreateModel(
            name="HitchwikiSpot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_id", models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("location", django.contrib.gis.db.models.fields.PointField(srid=4326)),
                ("rating", models.FloatField(blank=True, null=True)),
                ("average_waiting_time_minutes", models.FloatField(blank=True, null=True)),
                ("source_url", models.URLField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("title",)},
        ),
        migrations.AddField(
            model_name="locationreport",
            name="accuracy_m",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="locationreport",
            name="altitude_m",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="TeamMember",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=255)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=64)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="members",
                        to="eurorace.team",
                    ),
                ),
            ],
            options={"ordering": ("team", "full_name")},
        ),
        migrations.CreateModel(
            name="UserTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Oczekujące"),
                            ("in_progress", "W trakcie"),
                            ("completed", "Ukończone"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_tasks",
                        to="eurorace.task",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"unique_together": {("user", "task")}},
        ),
        migrations.AddField(
            model_name="task",
            name="assigned_users",
            field=models.ManyToManyField(related_name="all_tasks", through="eurorace.UserTask", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="TaskPhoto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="task_photos/%Y/%m/%d/")),
                ("location", django.contrib.gis.db.models.fields.PointField(blank=True, null=True, srid=4326)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="photos",
                        to="eurorace.task",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_photos",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="TeamStatistics",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("duration_seconds", models.PositiveIntegerField(default=0)),
                ("distance_meters", models.FloatField(default=0)),
                ("elevation_gain_meters", models.FloatField(default=0)),
                ("hitch_count", models.PositiveIntegerField(default=0)),
                ("completed_tasks_count", models.PositiveIntegerField(default=0)),
                ("last_calculated_at", models.DateTimeField(default=timezone.now)),
                (
                    "team",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="statistics",
                        to="eurorace.team",
                    ),
                ),
            ],
            options={"verbose_name_plural": "team statistics"},
        ),
        migrations.CreateModel(
            name="DetectedStop",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField()),
                ("ended_at", models.DateTimeField()),
                ("location", django.contrib.gis.db.models.fields.PointField(srid=4326)),
                ("radius_meters", models.FloatField(default=0)),
                ("duration_seconds", models.PositiveIntegerField(default=0)),
                ("recommendation_generated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="detected_stops",
                        to="eurorace.team",
                    ),
                ),
            ],
            options={"ordering": ("-ended_at",)},
        ),
        migrations.CreateModel(
            name="HitchwikiRecommendation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("distance_meters", models.FloatField()),
                ("score", models.FloatField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "spot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recommendations",
                        to="eurorace.hitchwikispot",
                    ),
                ),
                (
                    "stop",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recommendations",
                        to="eurorace.detectedstop",
                    ),
                ),
            ],
            options={"ordering": ("-score", "distance_meters"), "unique_together": {("stop", "spot")}},
        ),
        migrations.AddConstraint(
            model_name="team",
            constraint=models.UniqueConstraint(
                condition=models.Q(("bib_number", ""), _negated=True),
                fields=("race", "bib_number"),
                name="unique_team_bib_number_per_race",
            ),
        ),
    ]
