from django.contrib.auth.models import User
from django.contrib.gis.db import models as gis_models
from django.db import models
from django.db.models import Subquery, OuterRef
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Race(models.Model):
    name = models.CharField(max_length=255)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    destination = gis_models.PointField(
        null=True,
        blank=True,
        help_text=_("Destination point displayed on the live map."),
    )
    destination_name = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Human-readable destination label."),
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-is_active", "-starts_at", "name")

    def __str__(self):
        return self.name


class Team(models.Model):
    race = models.ForeignKey(Race, on_delete=models.CASCADE, related_name="teams")
    account_user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="race_team",
        help_text=_("Login used by the pair in the mobile app."),
    )
    display_name = models.CharField(max_length=255)
    bib_number = models.CharField(max_length=32, blank=True, db_index=True)
    contact_email = models.EmailField(blank=True)
    profile_photo = models.ImageField(
        upload_to="team_photos/%Y/%m/%d/",
        null=True,
        blank=True,
        help_text=_("Team profile photo shown on the live tracker."),
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("bib_number", "display_name")
        constraints = [
            models.UniqueConstraint(
                fields=("race", "bib_number"),
                name="unique_team_bib_number_per_race",
                condition=~models.Q(bib_number=""),
            )
        ]

    def __str__(self):
        if self.bib_number:
            return f"{self.bib_number} - {self.display_name}"
        return self.display_name


class TeamMember(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="members")
    full_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ("team", "full_name")

    def __str__(self):
        return self.full_name

class LocationManager(models.Manager):
    def latest_for_users(self):
        return self.get_queryset().filter(
            timestamp=Subquery(
                self.model.objects.filter(user=OuterRef("user")).order_by("-timestamp").values("timestamp")[:1]
            )
        )

    def latest_for_team_members(self, team=None):
        queryset = self.get_queryset()
        if team:
            queryset = queryset.filter(user=team.account_user)
        return queryset.filter(
            timestamp=Subquery(
                self.model.objects.filter(
                    user=OuterRef("user"),
                    team_member_id=OuterRef("team_member_id"),
                )
                .order_by("-timestamp")
                .values("timestamp")[:1]
            )
        )

    def authors(self):
        return self.get_queryset().authors()

    def editors(self):
        return self.get_queryset().editors()


class LocationReport(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    team_member = models.ForeignKey(
        TeamMember,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="location_reports",
        help_text=_("Team member this location belongs to."),
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    location = gis_models.PointField()
    altitude_m = models.FloatField(null=True, blank=True)
    accuracy_m = models.FloatField(null=True, blank=True)

    objects = LocationManager()

    def __str__(self):
        return _("Location of {} at {} {}").format(
            str(self.user.username),
            self.timestamp,
            (self.location.x, self.location.y)
        )


class TeamStatistics(models.Model):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, related_name="statistics")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    distance_meters = models.FloatField(default=0)
    elevation_gain_meters = models.FloatField(default=0)
    hitch_count = models.PositiveIntegerField(default=0)
    completed_tasks_count = models.PositiveIntegerField(default=0)
    last_calculated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "team statistics"

    def __str__(self):
        return _("Statistics for {}").format(self.team)


class DetectedStop(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="detected_stops")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    location = gis_models.PointField()
    radius_meters = models.FloatField(default=0)
    duration_seconds = models.PositiveIntegerField(default=0)
    recommendation_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-ended_at",)

    def __str__(self):
        return _("Stop for {} at {}").format(self.team, self.ended_at)


class HitchwikiSpot(models.Model):
    external_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    location = gis_models.PointField()
    rating = models.FloatField(null=True, blank=True)
    average_waiting_time_minutes = models.FloatField(null=True, blank=True)
    source_url = models.URLField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title",)

    def __str__(self):
        return self.title


class HitchwikiRecommendation(models.Model):
    stop = models.ForeignKey(DetectedStop, on_delete=models.CASCADE, related_name="recommendations")
    spot = models.ForeignKey(HitchwikiSpot, on_delete=models.CASCADE, related_name="recommendations")
    distance_meters = models.FloatField()
    score = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-score", "distance_meters")
        unique_together = ("stop", "spot")

    def __str__(self):
        return _("{} recommended for {}").format(self.spot, self.stop.team)
