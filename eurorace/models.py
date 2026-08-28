from django.db.models import Subquery, OuterRef
from django.utils.translation import gettext_lazy as _
from django.contrib.gis.db import models as gis_models
from django.db import models
from rest_framework.authtoken.admin import User
from eurorace.task_models import Task, TaskPhoto

class LocationManager(models.Manager):
    def latest_for_users(self):
        return self.get_queryset().filter(
            timestamp=Subquery(
                self.model.objects.filter(user=OuterRef("user")).order_by("-timestamp").values("timestamp")[:1]
            )
        )

    def authors(self):
        return self.get_queryset().authors()

    def editors(self):
        return self.get_queryset().editors()

class LocationReport(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    location = gis_models.PointField()

    objects = LocationManager()

    def __str__(self):
        return _("Location of {} at {} {}").format(
            str(self.user.username),
            self.timestamp,
            (self.location.x, self.location.y)
        )
