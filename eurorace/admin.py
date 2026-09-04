import csv
import io
import zipfile
from pathlib import Path

from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.crypto import get_random_string
from django.utils.html import format_html
from leaflet.admin import LeafletGeoAdmin
from rest_framework.authtoken.models import Token

from eurorace.models import (
    DetectedStop,
    HitchwikiRecommendation,
    HitchwikiSpot,
    HitchwikiSpotAI,
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
class RaceAdmin(LeafletGeoAdmin):
    list_display = ("name", "starts_at", "ends_at", "destination_name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "destination_name")
    change_form_template = "admin/eurorace/race/change_form.html"
    change_list_template = "admin/eurorace/race/change_list.html"
    fieldsets = (
        (
            "Podstawowe informacje",
            {
                "fields": ("name", "starts_at", "ends_at", "is_active"),
                "description": (
                    "Utwórz wyścig przed importem par i dodawaniem zadań. "
                    "Tylko jeden wyścig powinien być oznaczony jako aktywny."
                ),
            },
        ),
        (
            "Meta wyścigu",
            {
                "fields": ("destination_name", "destination"),
                "description": (
                    "Kliknij punkt mety na mapie — będzie widoczny na live trackerze "
                    "i w aplikacji mobilnej jako punkt orientacyjny dla uczestników."
                ),
            },
        ),
    )


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("display_name", "bib_number", "race", "account_user", "is_active", "created_at")
    list_filter = ("race", "is_active")
    search_fields = ("display_name", "bib_number", "account_user__username", "members__full_name")
    fields = (
        "race",
        "account_user",
        "display_name",
        "bib_number",
        "contact_email",
        "profile_photo",
        "is_active",
    )
    inlines = (TeamMemberInline, TeamStatisticsInline)
    change_list_template = "admin/eurorace/team/change_list.html"
    change_form_template = "admin/eurorace/team/change_form.html"

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
    list_display = ("title", "status", "assigned_to", "photo_count", "created_at")
    list_filter = ("status", "assigned_to")
    search_fields = ("title", "description")
    change_form_template = "admin/eurorace/task/change_form.html"
    change_list_template = "admin/eurorace/task/change_list.html"
    fieldsets = (
        (
            "Zadanie",
            {
                "fields": ("title", "description", "status"),
                "description": (
                    "Opisz zadanie jasno — para zobaczy tytuł i opis w aplikacji mobilnej. "
                    "Po zapisaniu zadanie zostanie przypisane do wszystkich kont par."
                ),
            },
        ),
        (
            "Lokalizacja",
            {
                "fields": ("location",),
                "description": "Opcjonalnie ustaw punkt na mapie, jeśli zadanie wiąże się z konkretnym miejscem.",
            },
        ),
        (
            "Zaawansowane",
            {
                "classes": ("collapse",),
                "fields": ("assigned_to",),
                "description": "Pole opcjonalne — zwykle nie trzeba go ustawiać ręcznie.",
            },
        ),
    )

    @admin.display(description="Zdjęcia")
    def photo_count(self, obj):
        count = obj.photos.count()
        if not count:
            return "0"
        gallery_url = reverse("admin:eurorace_taskphoto_gallery") + f"?task={obj.id}"
        return format_html('<a href="{}">{} zdj.</a>', gallery_url, count)


@admin.register(UserTask)
class UserTaskAdmin(admin.ModelAdmin):
    list_display = ("user", "task", "status", "assigned_at")
    list_filter = ("status", "task")
    search_fields = ("user__username", "task__title")


@admin.register(TaskPhoto)
class TaskPhotoAdmin(LeafletGeoAdmin):
    list_display = ("thumbnail", "task", "team_label", "uploaded_by", "uploaded_at", "download_link")
    list_filter = ("task", "uploaded_by", "uploaded_at")
    search_fields = ("task__title", "uploaded_by__username", "uploaded_by__race_team__display_name")
    readonly_fields = ("uploaded_at", "preview_large", "download_link")
    change_list_template = "admin/eurorace/taskphoto/change_list.html"
    fieldsets = (
        (
            "Zdjęcie z zadania",
            {
                "fields": ("preview_large", "task", "image", "uploaded_by", "uploaded_at", "location"),
                "description": (
                    "Zdjęcia są zwykle dodawane przez pary z aplikacji mobilnej. "
                    "Organizator może je przeglądać w galerii i pobierać."
                ),
            },
        ),
    )

    def get_urls(self):
        return [
            path("gallery/", self.admin_site.admin_view(self.gallery), name="eurorace_taskphoto_gallery"),
            path("<int:photo_id>/download/", self.admin_site.admin_view(self.download_photo), name="eurorace_taskphoto_download"),
        ] + super().get_urls()

    def _filtered_photos(self, request):
        photos = (
            TaskPhoto.objects.select_related("task", "uploaded_by", "uploaded_by__race_team")
            .order_by("-uploaded_at")
        )
        race_id = request.GET.get("race") or request.POST.get("race")
        team_id = request.GET.get("team") or request.POST.get("team")
        task_id = request.GET.get("task") or request.POST.get("task")
        if race_id:
            photos = photos.filter(uploaded_by__race_team__race_id=race_id)
        if team_id:
            photos = photos.filter(uploaded_by__race_team_id=team_id)
        if task_id:
            photos = photos.filter(task_id=task_id)
        return photos

    def _annotate_photo_labels(self, photos):
        for photo in photos:
            team = getattr(photo.uploaded_by, "race_team", None)
            photo.team_label = team.display_name if team else "Brak pary"
            photo.uploader_label = photo.uploaded_by.username if photo.uploaded_by else "Nieznany"
        return photos

    def gallery(self, request):
        photos = list(self._annotate_photo_labels(self._filtered_photos(request)))
        query_params = request.GET.copy()
        query_params.pop("download", None)
        query_string = query_params.urlencode()

        if request.GET.get("download") == "zip_all":
            if not photos:
                messages.warning(request, "Brak zdjęć do pobrania dla wybranych filtrów.")
            else:
                return self._zip_response(photos, "eurorace_task_photos.zip")

        if request.method == "POST" and request.POST.get("download") == "zip_selected":
            selected_ids = request.POST.getlist("photo_ids")
            selected_photos = [photo for photo in photos if str(photo.id) in selected_ids]
            if not selected_photos:
                messages.warning(request, "Nie zaznaczono żadnych zdjęć do pobrania.")
            else:
                return self._zip_response(selected_photos, "eurorace_task_photos_selected.zip")

        context = {
            **self.admin_site.each_context(request),
            "title": "Galeria zdjęć z zadań",
            "photos": photos,
            "photo_count": len(photos),
            "races": Race.objects.order_by("-is_active", "name"),
            "teams": Team.objects.select_related("race").order_by("bib_number", "display_name"),
            "tasks": Task.objects.order_by("title"),
            "selected_race": request.GET.get("race", ""),
            "selected_team": request.GET.get("team", ""),
            "selected_task": request.GET.get("task", ""),
            "query_string": query_string,
        }
        return TemplateResponse(request, "admin/eurorace/taskphoto/gallery.html", context)

    def download_photo(self, request, photo_id):
        photo = TaskPhoto.objects.filter(pk=photo_id).select_related("task", "uploaded_by").first()
        if not photo or not photo.image:
            raise Http404("Zdjęcie nie istnieje.")
        filename = self._safe_filename(photo)
        return FileResponse(photo.image.open("rb"), as_attachment=True, filename=filename)

    def _safe_filename(self, photo):
        team = getattr(photo.uploaded_by, "race_team", None)
        team_slug = (team.display_name if team else "para").replace(" ", "_")
        task_slug = photo.task.title.replace(" ", "_")[:40]
        extension = Path(photo.image.name).suffix or ".jpg"
        timestamp = photo.uploaded_at.strftime("%Y%m%d_%H%M%S")
        return f"{team_slug}_{task_slug}_{timestamp}{extension}"

    def _zip_response(self, photos, archive_name):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            used_names = set()
            for photo in photos:
                if not photo.image:
                    continue
                filename = self._safe_filename(photo)
                counter = 2
                while filename in used_names:
                    stem = Path(filename).stem
                    suffix = Path(filename).suffix
                    filename = f"{stem}_{counter}{suffix}"
                    counter += 1
                used_names.add(filename)
                with photo.image.open("rb") as image_file:
                    archive.writestr(filename, image_file.read())
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{archive_name}"'
        return response

    @admin.display(description="Podgląd")
    def thumbnail(self, obj):
        if not obj.image:
            return "-"
        return format_html(
            '<a href="{}" target="_blank"><img src="{}" style="height: 64px; width: 64px; object-fit: cover; border-radius: 6px;" /></a>',
            obj.image.url,
            obj.image.url,
        )

    @admin.display(description="Duży podgląd")
    def preview_large(self, obj):
        if not obj or not obj.image:
            return "-"
        return format_html(
            '<a href="{}" target="_blank"><img src="{}" style="max-width: 420px; max-height: 320px; object-fit: contain; border-radius: 8px; border: 1px solid #ddd;" /></a>',
            obj.image.url,
            obj.image.url,
        )

    @admin.display(description="Para")
    def team_label(self, obj):
        team = getattr(obj.uploaded_by, "race_team", None)
        return team.display_name if team else "-"

    @admin.display(description="Pobierz")
    def download_link(self, obj):
        if not obj.image:
            return "-"
        url = reverse("admin:eurorace_taskphoto_download", args=[obj.pk])
        return format_html('<a href="{}">Pobierz plik</a>', url)

    thumbnail.short_description = "Miniatura"


@admin.register(DetectedStop)
class DetectedStopAdmin(LeafletGeoAdmin):
    list_display = ("team", "started_at", "ended_at", "duration_seconds", "radius_meters")
    list_filter = ("team",)


@admin.register(HitchwikiSpot)
class HitchwikiSpotAdmin(LeafletGeoAdmin):
    list_display = (
        "title",
        "rating",
        "rating_count",
        "average_waiting_time_minutes",
        "is_active",
        "imported_at",
        "source_url",
    )
    list_filter = ("is_active",)
    search_fields = ("title", "description", "external_id")


@admin.register(HitchwikiRecommendation)
class HitchwikiRecommendationAdmin(admin.ModelAdmin):
    list_display = ("stop", "spot", "distance_meters", "score", "created_at")
    list_filter = ("spot",)


@admin.register(HitchwikiSpotAI)
class HitchwikiSpotAIAdmin(admin.ModelAdmin):
    list_display = (
        "spot",
        "predicted_wait_minutes",
        "uncertainty",
        "prediction_source",
        "model_version",
        "prediction_generated_at",
        "updated_at",
    )
    list_filter = ("prediction_source",)
    search_fields = ("spot__title", "spot__external_id", "model_version")
    raw_id_fields = ("spot",)
