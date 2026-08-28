from django.contrib import admin
from leaflet.admin import LeafletGeoAdmin

from eurorace.models import LocationReport
from eurorace.task_models import Task, TaskPhoto


@admin.register(LocationReport)
class LocationReportAdmin(LeafletGeoAdmin):
    list_display = ("location", "timestamp")


@admin.register(Task)
class TaskAdmin(LeafletGeoAdmin):
    list_display = ("title", "status", "assigned_to", "created_at")
    list_filter = ("status", "assigned_to")
    search_fields = ("title", "description")


@admin.register(TaskPhoto)
class TaskPhotoAdmin(LeafletGeoAdmin):
    list_display = ("task", "uploaded_by", "uploaded_at")
    list_filter = ("task", "uploaded_by")
