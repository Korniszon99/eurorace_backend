import csv

from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.crypto import get_random_string
from django.utils.html import format_html
from leaflet.admin import LeafletGeoAdmin
from rest_framework.authtoken.models import Token

from eurorace.models import (
    DetectedStop,
    HitchwikiRecommendation,
    HitchwikiSpot,
    LocationReport,
    Race,
    Team,
    TeamMember,
    TeamStatistics,
)
from eurorace.task_models import Task, TaskPhoto, UserTask


@admin.register(LocationReport)
class LocationReportAdmin(LeafletGeoAdmin):
    list_display = ("user", "location", "altitude_m", "accuracy_m", "timestamp")
    list_filter = ("user",)


class TeamMemberInline(admin.TabularInline):
    model = TeamMember
    extra = 2


class TeamStatisticsInline(admin.StackedInline):
    model = TeamStatistics
    extra = 0
    can_delete = False
    readonly_fields = (
        "started_at",
        "finished_at",
        "duration_seconds",
        "distance_meters",
        "elevation_gain_meters",
        "hitch_count",
        "completed_tasks_count",
        "last_calculated_at",
    )


@admin.register(Race)
class RaceAdmin(admin.ModelAdmin):
    list_display = ("name", "starts_at", "ends_at", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("display_name", "bib_number", "race", "account_user", "is_active", "created_at")
    list_filter = ("race", "is_active")
    search_fields = ("display_name", "bib_number", "account_user__username", "members__full_name")
    inlines = (TeamMemberInline, TeamStatisticsInline)
    change_list_template = "admin/eurorace/team/change_list.html"

    def get_urls(self):
        return [
            path("import-csv/", self.admin_site.admin_view(self.import_csv), name="eurorace_team_import_csv"),
        ] + super().get_urls()

    def import_csv(self, request):
        races = Race.objects.all()
        generated_credentials = []
        if request.method == "POST":
            csv_file = request.FILES.get("csv_file")
            race_id = request.POST.get("race")
            if not csv_file:
                messages.error(request, "Wybierz plik CSV.")
            else:
                race = Race.objects.filter(pk=race_id).first() or Race.objects.filter(is_active=True).first()
                if not race:
                    race = Race.objects.create(name="Eurorace", is_active=True)

                decoded = csv_file.read().decode("utf-8-sig").splitlines()
                reader = csv.DictReader(decoded)
                created = 0
                updated = 0
                with transaction.atomic():
                    for row in reader:
                        username = (row.get("username") or row.get("login") or "").strip()
                        if not username:
                            continue
                        password = (row.get("password") or "").strip()
                        password_was_generated = False
                        if not password:
                            password = get_random_string(12)
                            password_was_generated = True

                        user, user_created = User.objects.get_or_create(
                            username=username,
                            defaults={
                                "email": (row.get("contact_email") or row.get("email") or "").strip(),
                                "first_name": (row.get("team_name") or row.get("display_name") or username).strip()[:150],
                            },
                        )
                        user.set_password(password)
                        user.save()
                        Token.objects.get_or_create(user=user)
                        for task in Task.objects.all():
                            UserTask.objects.get_or_create(user=user, task=task)

                        team_name = (
                            row.get("team_name")
                            or row.get("display_name")
                            or row.get("name")
                            or username
                        ).strip()
                        Team.objects.update_or_create(
                            account_user=user,
                            defaults={
                                "race": race,
                                "display_name": team_name,
                                "bib_number": (row.get("bib_number") or row.get("number") or "").strip(),
                                "contact_email": (row.get("contact_email") or row.get("email") or "").strip(),
                                "is_active": True,
                            },
                        )
                        team = user.race_team
                        self._sync_team_member(
                            team,
                            row.get("member_1_name") or row.get("member1") or row.get("member_1"),
                            row.get("member_1_email"),
                            row.get("member_1_phone"),
                        )
                        self._sync_team_member(
                            team,
                            row.get("member_2_name") or row.get("member2") or row.get("member_2"),
                            row.get("member_2_email"),
                            row.get("member_2_phone"),
                        )

                        if password_was_generated:
                            generated_credentials.append({"username": username, "password": password})
                        if user_created:
                            created += 1
                        else:
                            updated += 1

                messages.success(request, f"Import zakończony. Utworzono: {created}, zaktualizowano: {updated}.")

        context = {
            **self.admin_site.each_context(request),
            "title": "Import kont par z CSV",
            "races": races,
            "generated_credentials": generated_credentials,
        }
        return TemplateResponse(request, "admin/eurorace/team/import_csv.html", context)

    def _sync_team_member(self, team, name, email=None, phone=None):
        if not name:
            return
        TeamMember.objects.update_or_create(
            team=team,
            full_name=name.strip(),
            defaults={
                "email": (email or "").strip(),
                "phone": (phone or "").strip(),
            },
        )


@admin.register(Task)
class TaskAdmin(LeafletGeoAdmin):
    list_display = ("title", "status", "assigned_to", "created_at")
    list_filter = ("status", "assigned_to")
    search_fields = ("title", "description")


@admin.register(UserTask)
class UserTaskAdmin(admin.ModelAdmin):
    list_display = ("user", "task", "status", "assigned_at")
    list_filter = ("status", "task")
    search_fields = ("user__username", "task__title")


@admin.register(TaskPhoto)
class TaskPhotoAdmin(LeafletGeoAdmin):
    list_display = ("thumbnail", "task", "uploaded_by", "uploaded_at")
    list_filter = ("task", "uploaded_by")

    def thumbnail(self, obj):
        if not obj.image:
            return "-"
        return format_html(
            '<a href="{}" target="_blank"><img src="{}" style="height: 64px; width: 64px; object-fit: cover;" /></a>',
            obj.image.url,
            obj.image.url,
        )

    thumbnail.short_description = "Zdjęcie"


@admin.register(DetectedStop)
class DetectedStopAdmin(LeafletGeoAdmin):
    list_display = ("team", "started_at", "ended_at", "duration_seconds", "radius_meters")
    list_filter = ("team",)


@admin.register(HitchwikiSpot)
class HitchwikiSpotAdmin(LeafletGeoAdmin):
    list_display = ("title", "rating", "average_waiting_time_minutes", "source_url")
    search_fields = ("title", "description", "external_id")


@admin.register(HitchwikiRecommendation)
class HitchwikiRecommendationAdmin(admin.ModelAdmin):
    list_display = ("stop", "spot", "distance_meters", "score", "created_at")
    list_filter = ("spot",)
