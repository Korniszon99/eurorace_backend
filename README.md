# EuroRace — Geospatial Event Backend

**A Django API for event tasks, participant location reports and real-time updates.**

Python · Django REST Framework · PostGIS · Channels · Redis · Daphne

The backend combines spatial data storage, token authentication, event tasks, uploaded task photos and WebSocket notifications. It demonstrates the application engineering surrounding spatial and visual data; it is a supporting portfolio project rather than an AI model implementation.

## Architecture

REST requests are served through Django REST Framework; location data uses PostGIS. Channels handles WebSocket events, with Redis as the production channel layer. The application lives in **`backend/`**. Its `pyproject.toml` is the authoritative dependency manifest.

## Local setup

```bash
git clone https://github.com/Korniszon99/eurorace_backend.git
cd eurorace_backend/backend
cp .env.example .env
docker compose up --build
```

The template configures a local PostGIS service, Redis and explicit debug mode. Use a new database for the first smoke test. The supplied Compose file is a development setup and includes a source bind mount.

For a native installation, use Python 3.12, PostgreSQL with PostGIS, Redis and system GDAL/GEOS libraries. Install with `python -m pip install -e .` from `backend/`; set the corresponding database variables, then run migrations and Daphne.

## Interface

| Interface | Location |
| --- | --- |
| Authentication | `/api/auth/` |
| Location reports | `/api/location-reports/` |
| Tasks | `/api/tasks/` |
| OpenAPI / Swagger UI | `/api/schema/`, `/api/schema/swagger-ui/` |
| Location WebSocket | `/ws/location/` |

WebSocket clients offer the `Token` subprotocol followed by their token. All credentials belong in the runtime environment. [API details](backend/API_DOCUMENTATION.md).

Location records are scoped to their owner by default; administrators can inspect all records. The latest-all-participants endpoint requires admin access. REST writes cannot impersonate another user. Task create/update/delete require staff permissions; user task status and photo actions remain separate.

## Verification

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```

Run integration tests against PostGIS. CI installs GIS libraries, provisions PostGIS/Redis and checks migrations and WebSocket tests. A local source audit cannot substitute for a passing database integration run.

## Production requirements

Set `DEBUG=0`, a strong random `SECRET_KEY`, explicit `ALLOWED_HOSTS`, database credentials and `CORS_ALLOWED_ORIGINS`. Keep PostGIS and Redis on private networking, terminate TLS, serve static/media files correctly and back up both the database and uploads. Run `python manage.py check --deploy` and verify the frontend against the revised authorization rules before deployment.

Remaining deployment work includes operational monitoring, token lifecycle/rotation, rate limits and a policy for location retention. The authentication email configuration is still a development console backend. **Status: prototype with hardening changes; production readiness depends on passing integration CI and deployment configuration.** [Security notes](SECURITY.md).
