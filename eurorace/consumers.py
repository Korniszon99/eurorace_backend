from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.gis.geos import Point
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from .models import LocationReport


class LocationConsumer(AsyncJsonWebsocketConsumer):
    """
    Event handler for device location coordinates
    """
    async def connect(self):
        # Token authentication as specified in the API documentation
        # Extract token from the subprotocols (["Token", "<token>"])
        if "subprotocols" in self.scope and len(self.scope["subprotocols"]) >= 2:
            subprotocols = self.scope["subprotocols"]
            # Look for the token
            for i in range(len(subprotocols)-1):
                if subprotocols[i] == "Token":
                    token_key = subprotocols[i+1]
                    user = await self.get_user_from_token(token_key)
                    if user:
                        self.user = user
                        # Add user to a group to receive updates
                        self.user_group = f"user_{user.id}"
                        await self.channel_layer.group_add(
                            self.user_group,
                            self.channel_name
                        )
                        await self.accept()
                        return

        # If authentication fails, close connection
        await self.close(code=4003)  # 4003: Authentication failed

    async def disconnect(self, close_code):
        # Remove from group if user was authenticated
        if hasattr(self, 'user_group'):
            await self.channel_layer.group_discard(
                self.user_group,
                self.channel_name
            )

    # Receive message from WebSocket
    async def receive_json(self, content):
        if content.get("type", None) == "location_update":
            latitude = content["latitude"]
            longitude = content["longitude"]

            # Save location to database
            await self.save_location(latitude, longitude)

            # Send acknowledgment to the client
            await self.send_json({
                "type": "location_saved",
                "success": True
            })

    @database_sync_to_async
    def save_location(self, latitude, longitude):
        """Save the location to the database"""
        point = Point(longitude, latitude)
        LocationReport.objects.create(
            user=self.user,
            location=point
        )

    @database_sync_to_async
    def get_user_from_token(self, token_key):
        """Get user from token"""
        try:
            token = Token.objects.get(key=token_key)
            return token.user
        except Token.DoesNotExist:
            return None

    # Handler for task_assigned message type
    async def task_assigned(self, event):
        """
        Send task assigned notification to the client
        """
        # Send message to WebSocket
        await self.send_json({
            "type": "task_assigned",
            "task_id": event["task_id"],
            "title": event["title"]
        })

    # Handler for task_status_updated message type
    async def task_status_updated(self, event):
        """
        Send task status update notification to the client
        """
        # Send message to WebSocket
        await self.send_json({
            "type": "task_status_updated",
            "task_id": event["task_id"],
            "status": event["status"]
        })
