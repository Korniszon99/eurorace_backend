# EuroRace backend setup

The application uses Django REST Framework, GeoDjango/PostGIS and Django Channels. The current Compose file defines `backend`, `db` and `redis`. There is no separate `test` service.

## Local configuration

Create `backend/.env` locally. Match Django's database settings to the variables used by the Postgres container. Use your own local password and keep this file out of Git.

```dotenv
DEBUG=True
POSTGRES_DB=eurorace
POSTGRES_USER=postgres
POSTGRES_PASSWORD=replace-with-a-local-password
DB_NAME=eurorace
DB_USER=postgres
DB_PASSWORD=replace-with-a-local-password
DB_HOST=db
DB_PORT=5432
REDIS_URL=redis://redis:6379/0
```

The Compose file uses `postgis/postgis:15-3.3`; check that this image is available for your Docker architecture. It exposes the database and Redis ports as well as port 8000, so this configuration belongs on a trusted development machine.

## Start the services

From the repository root:

```bash
cd backend
docker compose up --build
```

The backend startup command runs migrations, collects static files and launches Daphne. It also currently runs `makemigrations`; review generated migrations before committing them. Application routes are defined in [eurorace/urls.py](eurorace/urls.py). The development API is at <http://localhost:8000/api/>.

## Tests

With the services running, use the existing backend service:

```bash
docker compose exec backend python manage.py test eurorace.tests
```

The suite exercises WebSocket location handling using Django's database test machinery. It requires a working PostGIS database and a database user permitted to create a test database. This command matches the checked-in service names; it has not been executed as part of the documentation update. Older helper scripts may still refer to a missing `test` service.

## Authentication and email behaviour

The current settings use username-based registration, disable mandatory email verification and use Django's console email backend. SMTP credentials are therefore not required by the current email backend. Token authentication is configured for REST requests. Review consumer permissions and WebSocket authentication separately before deployment; a test that injects a user into a connection scope does not prove the real authentication flow.

## Channel layer

`DEBUG=True` selects an in-memory channel layer. With debug disabled, the application selects Redis using `REDIS_URL`. An in-memory channel layer does not coordinate separate application processes.

## Deployment boundary

The checked-in settings contain a development secret and permissive host/CORS values. Move the secret to an environment variable and generate a new value, restrict hosts and origins, disable debug, configure HTTPS and review access to location data before public deployment. Do not treat the Docker setup alone as evidence that the application is production-ready.

Stop local services with `docker compose down`. The named database volume remains unless you explicitly remove it.
