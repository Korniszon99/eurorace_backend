# Generated manually for Hitchmap local import fields.

import django.contrib.gis.db.models.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("eurorace", "0004_race_destination_team_photo_member_location"),
    ]

    operations = [
        migrations.AddField(
            model_name="hitchwikispot",
            name="rating_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hitchwikispot",
            name="source_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hitchwikispot",
            name="imported_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="hitchwikispot",
            name="is_active",
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AlterField(
            model_name="hitchwikispot",
            name="location",
            field=django.contrib.gis.db.models.fields.PointField(spatial_index=True, srid=4326),
        ),
    ]
