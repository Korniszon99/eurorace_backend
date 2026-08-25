from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from django.db.models import Min, Max, Count
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import render

from eurorace.models import DetectedStop, HitchwikiRecommendation, LocationReport, Team
from eurorace.task_models import Task, TaskPhoto, UserTask
from eurorace.serializers import (
    LocationReportSerializer, UserTrackResponseSerializer, UserTrackSerializer,
    TaskSerializer, TaskPhotoSerializer, TeamSerializer, TeamStatisticsSerializer,
    HitchwikiRecommendationSerializer
)
from eurorace.services import get_user_team, process_location_report, update_team_statistics


class LocationReportViewSet(viewsets.ModelViewSet):
    queryset = LocationReport.objects.all()
    serializer_class = LocationReportSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        user = self.request.user
        if user.is_staff and serializer.validated_data.get("user"):
            report = serializer.save()
        else:
            report = serializer.save(user=user)
        process_location_report(report)

    @extend_schema(
        responses=LocationReportSerializer(many=True),
        description="Pobiera najnowsze lokalizacje wszystkich użytkowników"
    )
    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Endpoint zwracający najnowsze lokalizacje wszystkich użytkowników zgodnie z dokumentacją API"""
        # Pobierz najnowsze lokalizacje dla wszystkich użytkowników
        latest_locations = LocationReport.objects.latest_for_users()

        # Serializuj dane
        serializer = LocationReportSerializer(
            instance=latest_locations,
            many=True,
            context={'request': request}
        )

        return Response(serializer.data)

    @extend_schema(
        responses=UserTrackResponseSerializer,
        description="Pobiera historię lokalizacji zalogowanego użytkownika w formacie odpowiednim dla Google Maps polyline"
    )
    @action(detail=False, methods=['get'])
    def my_track(self, request):
        """
        Endpoint zwracający historię lokalizacji zalogowanego użytkownika
        w formacie odpowiednim dla Flutter Google Maps API
        """
        user = request.user

        # Pobierz wszystkie lokalizacje użytkownika posortowane chronologicznie
        locations = LocationReport.objects.filter(user=user).order_by('timestamp')

        if not locations.exists():
            return Response({
                'user_id': user.id,
                'username': user.username,
                'total_points': 0,
                'start_time': None,
                'end_time': None,
                'coordinates': []
            })

        # Oblicz statystyki
        stats = locations.aggregate(
            start_time=Min('timestamp'),
            end_time=Max('timestamp'),
            total_points=Count('id')
        )
        response_data = {
            'user_id': user.id,
            'username': user.username,
            'total_points': stats['total_points'],
            'start_time': stats['start_time'],
            'end_time': stats['end_time'],
            'coordinates': UserTrackSerializer(locations, many=True).data
        }
        return Response(response_data)

    @extend_schema(
        responses=UserTrackResponseSerializer,
        description="Pobiera historię lokalizacji wybranego użytkownika (tylko admin)"
    )
    @action(detail=False, methods=['get'], url_path='user-track/(?P<user_id>[^/.]+)')
    def user_track(self, request, user_id=None):
        """
        Endpoint zwracający historię lokalizacji wybranego użytkownika (tylko admin)
        """
        if not request.user.is_staff:
            return Response({'detail': 'Brak uprawnień administratora.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({'detail': 'Użytkownik nie istnieje.'}, status=status.HTTP_404_NOT_FOUND)
        locations = LocationReport.objects.filter(user=user).order_by('timestamp')
        if not locations.exists():
            return Response({
                'user_id': user.id,
                'username': user.username,
                'total_points': 0,
                'start_time': None,
                'end_time': None,
                'coordinates': []
            })
        stats = locations.aggregate(
            start_time=Min('timestamp'),
            end_time=Max('timestamp'),
            total_points=Count('id')
        )
        response_data = {
            'user_id': user.id,
            'username': user.username,
            'total_points': stats['total_points'],
            'start_time': stats['start_time'],
            'end_time': stats['end_time'],
            'coordinates': UserTrackSerializer(locations, many=True).data
        }
        return Response(response_data)


class TaskViewSet(viewsets.ModelViewSet):
    """
    ViewSet dla zadań (Task)

    Umożliwia pełną obsługę CRUD dla zadań z dodatkowymi akcjami dla zarządzania
    statusem zadania i przesyłania zdjęć.
    """
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Filtrowanie zadań dostępnych dla użytkownika
        # Administratorzy widzą wszystkie zadania, pozostali użytkownicy tylko swoje
        user = self.request.user
        if user.is_staff:
            return Task.objects.all()
        # Pobierz zadania przypisane do użytkownika przez UserTask
        return user.all_tasks.all()

    def perform_create(self, serializer):
        # Tylko administratorzy mogą tworzyć zadania
        if not self.request.user.is_staff:
            raise PermissionDenied("Tylko administratorzy mogą tworzyć zadania.")
        serializer.save()

    @extend_schema(
        description="Tworzenie nowego zadania",
        request={"application/json": {"schema": {"type": "object", "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "latitude": {"type": "number"},
            "longitude": {"type": "number"}
        }}}},
        responses={201: TaskSerializer}
    )
    @action(detail=False, methods=['post'], url_path='create-task')
    def create_task(self, request):
        """Endpoint do tworzenia nowego zadania - zgodny z dokumentacją API"""
        # Tylko administratorzy mogą tworzyć zadania
        if not request.user.is_staff:
            raise PermissionDenied("Tylko administratorzy mogą tworzyć zadania.")

        # Przygotuj dane do serializacji
        data = {
            'title': request.data.get('title'),
            'description': request.data.get('description'),
        }

        # Sprawdź, czy podano wszystkie wymagane pola
        if not data['title'] or not data['description']:
            return Response(
                {'error': 'Wymagane są pola: title, description'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Sprawdź, czy podano współrzędne
        lat = request.data.get('latitude')
        lng = request.data.get('longitude')
        if lat is not None and lng is not None:
            try:
                lat = float(lat)
                lng = float(lng)
                data['location'] = {'latitude': lat, 'longitude': lng}
            except (ValueError, TypeError):
                return Response(
                    {'error': 'Nieprawidłowy format współrzędnych'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            return Response(
                {'error': 'Nie podano współrzędnych (latitude, longitude)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Serializuj i zapisz zadanie
        serializer = self.get_serializer(data=data, context={'request': request})
        if serializer.is_valid():
            task = serializer.save()
            # Zadanie zostanie automatycznie przypisane do wszystkich użytkowników
            # przez metodę save() i sygnał post_save w modelu Task
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        description="Pobiera zadania przypisane do bieżącego użytkownika"
    )
    @action(detail=False, methods=['get'])
    def my_tasks(self, request):
        """Endpoint zwracający zadania przypisane do bieżącego użytkownika"""
        # Pobierz wszystkie zadania przypisane do użytkownika przez tabele UserTask
        tasks = request.user.all_tasks.all()
        serializer = self.get_serializer(tasks, many=True)
        return Response(serializer.data)

    @extend_schema(
        description="Pobiera ukończone zadania"
    )
    @action(detail=False, methods=['get'])
    def completed(self, request):
        """Endpoint zwracający ukończone zadania"""
        if request.user.is_staff:
            completed_ids = UserTask.objects.filter(status='completed').values_list('task_id', flat=True)
            tasks = Task.objects.filter(id__in=completed_ids).distinct()
        else:
            completed_ids = UserTask.objects.filter(
                user=request.user,
                status='completed'
            ).values_list('task_id', flat=True)
            tasks = Task.objects.filter(id__in=completed_ids)

        serializer = self.get_serializer(tasks, many=True)
        return Response(serializer.data)

    @extend_schema(
        description="Podsumowanie liczby zadań ukończonych przez bieżącego użytkownika"
    )
    @action(detail=False, methods=['get'])
    def completion_summary(self, request):
        total_tasks = request.user.all_tasks.count()
        completed_tasks = UserTask.objects.filter(user=request.user, status='completed').count()
        return Response({
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'pending_tasks': max(total_tasks - completed_tasks, 0),
        })

    @extend_schema(
        description="Aktualizacja statusu zadania",
        request={"application/json": {"schema": {"type": "object", "properties": {"status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}}}},
        responses={200: TaskSerializer}
    )
    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        """Endpoint do aktualizacji statusu zadania dla bieżącego użytkownika"""
        task = self.get_object()
        status_value = request.data.get('status')

        if status_value not in [choice[0] for choice in Task.STATUS_CHOICES]:
            return Response(
                {'error': 'Nieprawidłowa wartość statusu. Musi być jedna z: pending, in_progress, completed'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Znajdź i zaktualizuj UserTask dla bieżącego użytkownika
        user_task, created = UserTask.objects.get_or_create(
            user=request.user,
            task=task
        )
        user_task.status = status_value
        user_task.save()

        # Zwróć zaktualizowane zadanie
        serializer = self.get_serializer(task)
        return Response(serializer.data)

    @extend_schema(
        description="Dodanie zdjęcia do zadania",
        request={"multipart/form-data": {"schema": {"type": "object", "properties": {
            "photo": {"type": "string", "format": "binary"},
            "latitude": {"type": "number", "format": "float"},
            "longitude": {"type": "number", "format": "float"}
        }}}},
        responses={201: TaskPhotoSerializer}
    )
    @action(detail=True, methods=['post'])
    def upload_photo(self, request, pk=None):
        """Endpoint do dodawania zdjęcia do zadania zgodny z dokumentacją API"""
        task = self.get_object()

        # Sprawdź, czy żądanie zawiera plik zdjęcia
        if 'photo' not in request.FILES:
            return Response(
                {'error': 'Nie dostarczono zdjęcia'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Przygotuj dane dla zdjęcia
        photo_data = {
            'task': task.id,
            'image': request.FILES['photo']
        }

        # Dodaj lokalizację, jeśli podano współrzędne
        if 'latitude' in request.data and 'longitude' in request.data:
            try:
                lat = float(request.data['latitude'])
                lng = float(request.data['longitude'])
                photo_data['location'] = {
                    'latitude': lat,
                    'longitude': lng
                }
            except (ValueError, TypeError):
                return Response(
                    {'error': 'Nieprawidłowy format współrzędnych'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Serializuj i zapisz zdjęcie
        serializer = TaskPhotoSerializer(data=photo_data, context={'request': request})
        if serializer.is_valid():
            photo = serializer.save(uploaded_by=request.user)

            # Zaktualizuj status UserTask dla bieżącego użytkownika na 'completed'
            user_task, created = UserTask.objects.get_or_create(
                user=request.user,
                task=task
            )
            user_task.status = 'completed'
            user_task.save()

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TeamViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TeamSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return Team.objects.select_related("race", "account_user", "statistics").prefetch_related("members")
        return Team.objects.filter(account_user=self.request.user).select_related(
            "race", "account_user", "statistics"
        ).prefetch_related("members")

    @action(detail=False, methods=['get'])
    def me(self, request):
        team = get_user_team(request.user)
        if not team:
            return Response({'detail': 'Brak pary przypisanej do użytkownika.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(team)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        team = get_user_team(request.user)
        if not team:
            return Response({'detail': 'Brak pary przypisanej do użytkownika.'}, status=status.HTTP_404_NOT_FOUND)
        statistics = update_team_statistics(team)
        return Response(TeamStatisticsSerializer(statistics).data)

    @action(detail=False, methods=['get'])
    def recommendations(self, request):
        team = get_user_team(request.user)
        if not team:
            return Response({'detail': 'Brak pary przypisanej do użytkownika.'}, status=status.HTTP_404_NOT_FOUND)
        latest_stop = DetectedStop.objects.filter(team=team).order_by("-ended_at").first()
        if not latest_stop:
            return Response([])
        recommendations = HitchwikiRecommendation.objects.filter(stop=latest_stop).select_related("spot")
        serializer = HitchwikiRecommendationSerializer(recommendations, many=True)
        return Response(serializer.data)


def live_dashboard(request):
    return render(request, "eurorace/live_dashboard.html")


def live_dashboard_data(request):
    teams = Team.objects.filter(is_active=True).select_related("account_user", "statistics").prefetch_related("members")
    latest_locations = {
        report.user_id: report
        for report in LocationReport.objects.latest_for_users().select_related("user")
    }

    payload = []
    for team in teams:
        report = latest_locations.get(team.account_user_id)
        statistics = getattr(team, "statistics", None)
        completed_tasks = UserTask.objects.filter(user=team.account_user, status="completed").count()
        total_tasks = team.account_user.all_tasks.count()
        latest_stop = DetectedStop.objects.filter(team=team).order_by("-ended_at").first()
        recommendations = []
        if latest_stop:
            recommendations = HitchwikiRecommendationSerializer(
                HitchwikiRecommendation.objects.filter(stop=latest_stop).select_related("spot"),
                many=True,
            ).data

        payload.append({
            "team_id": team.id,
            "display_name": team.display_name,
            "bib_number": team.bib_number,
            "members": [member.full_name for member in team.members.all()],
            "location": None if not report else {
                "latitude": report.location.y,
                "longitude": report.location.x,
                "timestamp": report.timestamp.isoformat(),
                "altitude_m": report.altitude_m,
            },
            "statistics": None if not statistics else TeamStatisticsSerializer(statistics).data,
            "tasks": {
                "completed": completed_tasks,
                "total": total_tasks,
            },
            "latest_stop": None if not latest_stop else {
                "started_at": latest_stop.started_at.isoformat(),
                "ended_at": latest_stop.ended_at.isoformat(),
                "duration_seconds": latest_stop.duration_seconds,
                "radius_meters": latest_stop.radius_meters,
            },
            "recommendations": recommendations,
        })

    return JsonResponse({"teams": payload})
