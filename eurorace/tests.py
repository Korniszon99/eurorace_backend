"""
Tests for the WebSocket location functionality.

These tests verify that:
1. WebSocket connections can be established
2. Location updates are properly processed and saved to the database
3. Users are correctly associated with their location reports

These tests use Django's TransactionTestCase to ensure proper database transaction handling
in the asynchronous test environment. This helps prevent database connection issues that
can occur when testing WebSocket consumers.

To run these tests:
1. Make sure all dependencies are installed:
   - djangorestframework-gis
   - channels
   - channels-redis (for production)
   - psycopg2-binary (for PostgreSQL connection)

2. Run the tests with:
   python manage.py test eurorace.tests

3. For running in Docker (recommended):
   docker-compose run --rm test
"""

import json
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from channels.testing import WebsocketCommunicator
from channels.db import database_sync_to_async
from django.contrib.gis.geos import Point
from eurorace.asgi import application
from eurorace.models import LocationReport


class LocationConsumerTests(TransactionTestCase):
    """
    Test cases for the LocationConsumer WebSocket functionality.
    """

    async def test_connect(self):
        """Test that a WebSocket connection can be established."""
        # Create a test user
        self.user = await self.create_test_user()

        # Connect to the WebSocket
        communicator = WebsocketCommunicator(application, "ws/location/")

        # Manually set the user in the scope (simulating authentication)
        communicator.scope["user"] = self.user

        connected, _ = await communicator.connect()

        # Check that the connection was accepted
        self.assertTrue(connected)

        # Close the connection
        await communicator.disconnect()

    async def test_location_update(self):
        """Test that location updates are properly processed and saved."""
        # Create a test user
        self.user = await self.create_test_user()

        # Connect to the WebSocket
        communicator = WebsocketCommunicator(application, "ws/location/")

        # Manually set the user in the scope (simulating authentication)
        communicator.scope["user"] = self.user

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Send a location update
        test_location = {
            "type": "location_update",
            "latitude": 52.2297,
            "longitude": 21.0122
        }
        await communicator.send_json_to(test_location)

        # Receive the response
        response = await communicator.receive_json_from()

        # Check that the response indicates success
        self.assertEqual(response["type"], "location_saved")
        self.assertTrue(response["success"])

        # Verify that the location was saved to the database
        location_saved = await self.location_exists(self.user, 52.2297, 21.0122)
        self.assertTrue(location_saved)

        # Close the connection
        await communicator.disconnect()

    async def asyncSetUp(self):
        """Set up before each test method."""
        # Ensure we have fresh database connections
        from django.db import connections
        for conn in connections.all():
            if not conn.is_usable():
                await database_sync_to_async(conn.connect)()
        await super().asyncSetUp()

    async def asyncTearDown(self):
        """Clean up after each test method."""
        # Close any open database connections
        from django.db import connections
        for conn in connections.all():
            await database_sync_to_async(conn.close)()
        await super().asyncTearDown()

    @database_sync_to_async
    def create_test_user(self):
        """Create a test user for the tests."""
        # Use a unique username for each test to avoid conflicts
        import uuid
        from django.db import connection

        # Ensure the connection is usable
        if not connection.is_usable():
            connection.connect()

        unique_id = str(uuid.uuid4())[:8]
        user = User.objects.create_user(
            username=f"testuser_{unique_id}",
            email=f"test_{unique_id}@example.com",
            password="testpassword"
        )

        # Explicitly commit the transaction
        connection.commit()

        return user

    @database_sync_to_async
    def location_exists(self, user, latitude, longitude):
        """Check if a location report exists for the given user and coordinates."""
        from django.db import connection
        from django.contrib.gis.measure import D

        # Ensure the connection is usable
        if not connection.is_usable():
            connection.connect()

        point = Point(longitude, latitude)
        # Use a tolerance for floating point comparison
        exists = LocationReport.objects.filter(
            user=user,
            location__distance_lte=(point, D(m=1))  # Within 1 meter
        ).exists()

        return exists


class LocationReportModelTests(TransactionTestCase):
    """
    Test cases for the LocationReport model.
    """

    def setUp(self):
        """Set up test data."""
        # Use a unique username for each test to avoid conflicts
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        self.user = User.objects.create_user(
            username=f"testuser_{unique_id}",
            email=f"test_{unique_id}@example.com",
            password="testpassword"
        )

    def tearDown(self):
        """Clean up after each test."""
        # Close any open database connections
        from django.db import connections
        for conn in connections.all():
            conn.close()

    def test_create_location_report(self):
        """Test creating a location report and associating it with a user."""
        # Create a location report
        point = Point(21.0122, 52.2297)
        location_report = LocationReport.objects.create(
            user=self.user,
            location=point
        )

        # Verify the location report was created
        self.assertEqual(LocationReport.objects.count(), 1)

        # Verify the location report is associated with the correct user
        self.assertEqual(location_report.user, self.user)

        # Verify the location coordinates are correct
        self.assertEqual(location_report.location.x, 21.0122)
        self.assertEqual(location_report.location.y, 52.2297)
