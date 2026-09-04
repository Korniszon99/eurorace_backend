from django.contrib.gis.db import models as gis_models
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("eurorace", "0003_race_teams_tasks_statistics_hitchwiki"),
    ]

    operations = [
        migrations.AddField(
            model_name="race",
            name="destination",
            field=gis_models.PointField(
                blank=True,
                help_text="Destination point displayed on the live map.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="race",
            name="destination_name",
            field=models.CharField(
                blank=True,
                help_text="Human-readable destination label.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="team",
            name="profile_photo",
            field=models.ImageField(
                blank=True,
                help_text="Team profile photo shown on the live tracker.",
                null=True,
                upload_to="team_photos/%Y/%m/%d/",
            ),
        ),
        migrations.AddField(
            model_name="locationreport",
            name="team_member",
            field=models.ForeignKey(
                blank=True,
                help_text="Team member this location belongs to.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="location_reports",
                to="eurorace.teammember",
            ),
        ),
    ]
