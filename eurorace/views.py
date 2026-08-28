from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.exceptions import PermissionDenied
from django.db.models import Min, Max, Count
from django.contrib.auth.models import User
from django.contrib.gis.geos import Point

from eurorace.models import LocationReport
from eurorace.task_models import Task, TaskPhoto, UserTask
from eurorace.serializers import (
    LocationReportSerializer, UserTrackResponseSerializer, UserTrackSerializer,
    TaskSerializer, TaskPhotoSerializer
)


class LocationReportViewSet(viewsets.ModelViewSet):
    queryset = LocationReport.objects.all()
    serializer_class = LocationReportSerializer
    permission_classes = [IsAuthenticated]

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
            # Administratorzy widzą wszystkie ukończone zadania
            tasks = Task.objects.filter(status='completed')
        else:
            # Zwykli użytkownicy widzą tylko swoje ukończone zadania (przez UserTask)
            # Pobieramy zadania ze statusem 'completed' przez relację all_tasks
            tasks = request.user.all_tasks.filter(status='completed')

        serializer = self.get_serializer(tasks, many=True)
        return Response(serializer.data)

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
