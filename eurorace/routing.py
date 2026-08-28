from django.urls import path
from . import consumers

websocket_urlpatterns = [
    # WebSocket route for location updates
    path("ws/location/", consumers.LocationConsumer.as_asgi()),
]
