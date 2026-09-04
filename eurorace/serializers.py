from drf_extra_fields.geo_fields import PointField
from rest_framework import serializers
from dj_rest_auth.registration.serializers import RegisterSerializer
from django.contrib.auth.models import User
from django.contrib.gis.geos import Point

from eurorace.models import LocationReport
from eurorace.models import HitchwikiRecommendation, HitchwikiSpot, Race, Team, TeamMember, TeamStatistics
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
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False)
    team_member = serializers.PrimaryKeyRelatedField(
        queryset=TeamMember.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        fields = ("location", "timestamp", "user", "team_member", "altitude_m", "accuracy_m")
        model = LocationReport
        read_only_fields = ("timestamp",)

    def create(self, validated_data):
        return LocationReport.objects.create(**validated_data)


class TaskPhotoSerializer(serializers.ModelSerializer):
    location = LocationSerializer(required=False, allow_null=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = TaskPhoto
        fields = ("id", "task", "image", "url", "uploaded_at", "location")
        read_only_fields = ("id", "url", "uploaded_at")
        extra_kwargs = {
            "image": {"write_only": True},
            "task": {"write_only": True},
        }

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
    team_member_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = LocationReport
        fields = ("latitude", "longitude", "timestamp", "altitude_m", "accuracy_m", "team_member_id")

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


class RaceSerializer(serializers.ModelSerializer):
    destination = LocationSerializer(required=False, allow_null=True)

    class Meta:
        model = Race
        fields = ("id", "name", "starts_at", "ends_at", "destination", "destination_name", "is_active")
        read_only_fields = fields


class TeamMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamMember
        fields = ("id", "full_name", "email", "phone")


class TeamStatisticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamStatistics
        fields = (
            "started_at",
            "finished_at",
            "duration_seconds",
            "distance_meters",
            "elevation_gain_meters",
            "hitch_count",
            "completed_tasks_count",
            "last_calculated_at",
        )


class TeamSerializer(serializers.ModelSerializer):
    members = TeamMemberSerializer(many=True, read_only=True)
    statistics = TeamStatisticsSerializer(read_only=True)
    race = RaceSerializer(read_only=True)
    username = serializers.CharField(source="account_user.username", read_only=True)
    profile_photo_url = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = (
            "id",
            "race",
            "display_name",
            "bib_number",
            "contact_email",
            "profile_photo_url",
            "is_active",
            "username",
            "members",
            "statistics",
        )
        read_only_fields = ("id", "username", "statistics", "profile_photo_url")

    def get_profile_photo_url(self, obj):
        if not obj.profile_photo:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.profile_photo.url)
        return obj.profile_photo.url


class HitchwikiSpotSerializer(serializers.ModelSerializer):
    location = LocationSerializer()

    class Meta:
        model = HitchwikiSpot
        fields = (
            "id",
            "external_id",
            "title",
            "description",
            "location",
            "rating",
            "average_waiting_time_minutes",
            "source_url",
        )


class HitchwikiRecommendationSerializer(serializers.ModelSerializer):
    spot = HitchwikiSpotSerializer(read_only=True)

    class Meta:
        model = HitchwikiRecommendation
        fields = ("id", "spot", "distance_meters", "score", "created_at")
