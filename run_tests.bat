@echo off
REM Stop any running containers
docker-compose down

REM Build and run the test service
docker-compose build test
docker-compose run --rm test

REM Clean up
docker-compose down