from django.contrib.gis.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class Task(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Oczekujące'),
        ('in_progress', 'W trakcie'),
        ('completed', 'Ukończone'),
    )

    title = models.CharField(max_length=255)
    description = models.TextField()
    location = models.PointField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tasks')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    assigned_users = models.ManyToManyField(User, through='UserTask', related_name='all_tasks')

    def __str__(self):
        return self.title

    def get_status_display(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    def save(self, *args, **kwargs):
        """Nadpisana metoda save, która przypisuje zadanie do wszystkich użytkowników po utworzeniu"""
        is_new = self.pk is None  # Sprawdź, czy to nowy obiekt (bez ID)
        # Najpierw zapisz zadanie
        super().save(*args, **kwargs)

        # Jeśli to nowy obiekt, przypisz go do wszystkich użytkowników
        if is_new:
            self.assign_to_all_users()

    def assign_to_all_users(self):
        """Przypisuje zadanie do wszystkich użytkowników w systemie"""
        from .websocket_utils import send_task_assigned_notification

        users = User.objects.all()
        user_tasks = []
        for user in users:
            # Twórz tylko jeśli takie przypisanie jeszcze nie istnieje
            if not UserTask.objects.filter(user=user, task=self).exists():
                user_tasks.append(UserTask(user=user, task=self))
                # Wyślij powiadomienie WebSocket do użytkownika
                send_task_assigned_notification(user.id, self.id, self.title)

        # Masowe tworzenie obiektów UserTask
        if user_tasks:
            UserTask.objects.bulk_create(user_tasks)


class UserTask(models.Model):
    """Model reprezentujący przypisanie zadania do użytkownika"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_tasks')
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='user_tasks')
    assigned_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Task.STATUS_CHOICES, default='pending')

    class Meta:
        unique_together = ('user', 'task')  # Jeden użytkownik może być przypisany do zadania tylko raz

    def __str__(self):
        return f"{self.user.username} - {self.task.title}"

    def save(self, *args, **kwargs):
        """Nadpisana metoda save, która wysyła powiadomienie o zmianie statusu"""
        from .websocket_utils import send_task_status_updated_notification

        # Sprawdź czy to aktualizacja istniejącego obiektu
        is_update = self.pk is not None

        # Jeśli to aktualizacja, pobierz oryginalny obiekt
        if is_update:
            original = UserTask.objects.get(pk=self.pk)
            old_status = original.status
        else:
            old_status = None

        # Zapisz zmiany
        super().save(*args, **kwargs)

        # Jeśli status się zmienił, wyślij powiadomienie
        if is_update and old_status != self.status:
            send_task_status_updated_notification(
                self.user.id,
                self.task.id,
                self.status
            )


class TaskPhoto(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='task_photos/%Y/%m/%d/')
    location = models.PointField(null=True, blank=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='uploaded_photos')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Photo for {self.task.title}"


# Signal do automatycznego przypisywania zadania do wszystkich użytkowników po jego utworzeniu
# Ten sygnał jest dodatkowym zabezpieczeniem, gdyby metoda save została pominięta
@receiver(post_save, sender=Task)
def assign_task_to_all_users(sender, instance, created, **kwargs):
    """Przypisuje nowo utworzone zadanie do wszystkich użytkowników."""
    if created:  # Tylko dla nowo utworzonych zadań
        # Wywołaj metodę assign_to_all_users na instancji zadania
        instance.assign_to_all_users()
