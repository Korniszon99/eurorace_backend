#!/bin/bash

# Stop any running containers
docker-compose down

# Start the database and redis services and wait for them to be healthy
echo "Starting database and redis services..."
docker-compose up -d db redis
echo "Waiting for services to be healthy..."

# Wait for db to be healthy
for i in {1..30}; do
  health=$(docker-compose ps -q db | xargs docker inspect -f '{{.State.Health.Status}}')
  if [ "$health" = "healthy" ]; then
    echo "Database is healthy!"
    break
  fi
  echo "Waiting for database to be healthy... ($i/30)"
  sleep 2
done

# Wait for redis to be healthy
for i in {1..30}; do
  health=$(docker-compose ps -q redis | xargs docker inspect -f '{{.State.Health.Status}}')
  if [ "$health" = "healthy" ]; then
    echo "Redis is healthy!"
    break
  fi
  echo "Waiting for redis to be healthy... ($i/30)"
  sleep 2
done

# Create test database and ensure PostGIS extensions are installed
echo "Creating test database and installing PostGIS extensions..."
docker-compose exec db psql -U postgres -c "CREATE DATABASE eurorace_test WITH OWNER postgres;" || true
docker-compose exec db psql -U postgres -d eurorace_test -c "CREATE EXTENSION IF NOT EXISTS postgis;" || true
docker-compose exec db psql -U postgres -d eurorace_test -c "CREATE EXTENSION IF NOT EXISTS postgis_topology;" || true

# Build and run the test service
docker-compose build test
docker-compose run --rm test

# Clean up
docker-compose down
