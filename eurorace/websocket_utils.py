from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def send_task_assigned_notification(user_id, task_id, title):
    """
    Wysyła powiadomienie WebSocket o przypisaniu zadania do użytkownika.

    Args:
        user_id (int): ID użytkownika, do którego przypisano zadanie
        task_id (int): ID przypisanego zadania
        title (str): Tytuł zadania
    """
    channel_layer = get_channel_layer()
    user_group = f"user_{user_id}"

    async_to_sync(channel_layer.group_send)(
        user_group,
        {
            "type": "task_assigned",
            "task_id": task_id,
            "title": title
        }
    )


def send_task_status_updated_notification(user_id, task_id, status):
    """
    Wysyła powiadomienie WebSocket o aktualizacji statusu zadania.

    Args:
        user_id (int): ID użytkownika, który powinien otrzymać powiadomienie
        task_id (int): ID zadania, którego status został zaktualizowany
        status (str): Nowy status zadania
    """
    channel_layer = get_channel_layer()
    user_group = f"user_{user_id}"

    async_to_sync(channel_layer.group_send)(
        user_group,
        {
            "type": "task_status_updated",
            "task_id": task_id,
            "status": status
        }
    )
