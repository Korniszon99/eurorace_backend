# Używamy obrazu python:3.11-slim-bullseye jako podstawy
FROM python:3.11-slim-bullseye AS builder

# Ustaw zmienne środowiskowe dla lepszej wydajności
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# Zainstaluj niezbędne pakiety do budowania z GDAL
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    python3-gdal \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Ustaw zmienne środowiskowe dla GDAL
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal \
    C_INCLUDE_PATH=/usr/include/gdal

# Ustaw katalog roboczy
WORKDIR /app

# Skopiuj plik wymagań
COPY pyproject.toml /app/

# Zainstaluj wheel i pobierz zależności
# Zamiast próbować zbudować GDAL przez pip, użyjemy systemowego python3-gdal
RUN pip install --upgrade pip wheel setuptools && \
    pip wheel --wheel-dir=/app/wheels \
    django>=5.0.0 \
    dj-rest-auth[with-social]>=5.1.0 \
    django-environ>=0.11.2 \
    django-leaflet>=0.31.0 \
    django-rest-framework>=0.1.0 \
    drf-extra-fields>=3.7.0 \
    drf-spectacular[sidecar]>=0.28.0 \
    six>=1.17.0 \
    channels>=4.0.0 \
    channels-redis>=4.1.0 \
    psycopg2-binary>=2.9.9 \
    daphne>=4.0.0 \
    djangorestframework-gis>=1.0.0 \
    django-cors-headers>=4.3.0 \
    Pillow>=10.1.0

# Obraz końcowy
FROM python:3.11-slim-bullseye

# Ustaw zmienne środowiskowe
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Zainstaluj tylko niezbędne pakiety runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gdal-bin \
    python3-gdal \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Ustaw katalog roboczy
WORKDIR /app

# Skopiuj wheels
COPY --from=builder /app/wheels /app/wheels

# Zainstaluj zależności z wheels
RUN pip install --no-index --find-links=/app/wheels/ \
    django \
    dj-rest-auth \
    django-environ \
    django-leaflet \
    django-rest-framework \
    drf-extra-fields \
    drf-spectacular \
    six \
    channels \
    channels-redis \
    psycopg2-binary \
    daphne \
    djangorestframework-gis \
    django-cors-headers \
    Pillow \
    && rm -rf /app/wheels

# Najpierw skopiuj pyproject.toml przed kopiowaniem innych plików
COPY pyproject.toml /app/

# Skopiuj tylko niezbędne pliki projektu
COPY manage.py /app/
COPY eurorace/ /app/eurorace/

# Zainstaluj projekt jako pakiet
RUN pip install -e .

# Utwórz katalog na pliki statyczne
RUN mkdir -p /app/static

# Otwórz port
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Uruchom serwer
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "eurorace.asgi:application"]
