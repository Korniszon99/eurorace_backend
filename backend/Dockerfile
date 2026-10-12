FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 libgdal32 libgeos-c1v5 curl && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY manage.py ./
COPY eurorace/ ./eurorace/
RUN pip install --no-cache-dir .
RUN useradd --create-home app && mkdir -p /app/static /media && chown -R app:app /app/static /media
USER app
EXPOSE 8000
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "eurorace.asgi:application"]
