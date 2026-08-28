from drf_extra_fields.geo_fields import PointField
from rest_framework import serializers
from dj_rest_auth.registration.serializers import RegisterSerializer
from django.contrib.gis.geos import Point

from eurorace.models import LocationReport
from eurorace.task_models import Task, TaskPhoto, UserTask


class CustomRegisterSerializer(RegisterSerializer):
    """Custom registration serializer to fix compatibility issues with allauth"""

    # Add the missing attribute that allauth expects
    _has_phone_field = False

    def save(self, request):
        """Override save method to handle user creation properly"""
        user = super().save(request)
        return user


class LocationSerializer(serializers.Serializer):
    """
    Serializer do obsługi współrzędnych geograficznych zgodnie z dokumentacją API
    """
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()

    def to_representation(self, instance):
        if instance:
            return {
                'latitude': instance.y,  # W Point, y to szerokość geograficzna (latitude)
                'longitude': instance.x  # W Point, x to długość geograficzna (longitude)
            }
        return None

    def to_internal_value(self, data):
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        if latitude is None or longitude is None:
            raise serializers.ValidationError({
                'location': 'Wymagane są oba pola: latitude i longitude.'
            })

        return Point(longitude, latitude)  # Point przyjmuje (x, y) -> (longitude, latitude)


class LocationReportSerializer(serializers.ModelSerializer):
    location = LocationSerializer()

    class Meta:
        fields = ("location", "timestamp", "user")
        model = LocationReport


class TaskPhotoSerializer(serializers.ModelSerializer):
    location = LocationSerializer(required=False, allow_null=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = TaskPhoto
        fields = ("id", "url", "uploaded_at", "location")
        read_only_fields = ("id",)

    def get_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None


class UserTaskStatusSerializer(serializers.ModelSerializer):
    """Serializer do pobierania statusu zadania dla konkretnego użytkownika"""
    class Meta:
        model = UserTask
        fields = ('status',)


class TaskSerializer(serializers.ModelSerializer):
    location = LocationSerializer()
    photos = TaskPhotoSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    assigned_to = serializers.StringRelatedField()
    user_status = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = (
            "id",
            "title",
            "description",
            "location",
            "status",
            "status_display",
            "user_status",
            "assigned_to",
            "created_at",
            "updated_at",
            "photos",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def get_user_status(self, obj):
        """Pobiera status zadania dla zalogowanego użytkownika"""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        try:
            user_task = UserTask.objects.get(user=request.user, task=obj)
            return user_task.status
        except UserTask.DoesNotExist:
            return 'pending'  # Domyślny status, jeśli nie znaleziono UserTask


class UserTrackSerializer(serializers.ModelSerializer):
    """Serializer dla danych trasy użytkownika zgodny z dokumentacją API"""
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()

    class Meta:
        model = LocationReport
        fields = ("latitude", "longitude", "timestamp")

    def get_latitude(self, obj):
        """Pobiera szerokość geograficzną (latitude) z punktu lokalizacji"""
        if obj.location:
            return obj.location.y
        return None

    def get_longitude(self, obj):
        """Pobiera długość geograficzną (longitude) z punktu lokalizacji"""
        if obj.location:
            return obj.location.x
        return None


class UserTrackResponseSerializer(serializers.Serializer):
    """Serializer dla odpowiedzi z endpointu trasy użytkownika zgodny z dokumentacją API"""
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    total_points = serializers.IntegerField()
    start_time = serializers.DateTimeField(allow_null=True)
    end_time = serializers.DateTimeField(allow_null=True)
    coordinates = UserTrackSerializer(many=True)
