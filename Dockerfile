# syntax=docker/dockerfile:1
#
# SON-IA · imagen única: la API y el tablero en el mismo contenedor.
#
# El backend guarda estado en memoria (el dataset cargado, el registro de
# resultados de las tools) y el cierre transmite por SSE durante decenas de
# segundos. Eso pide un proceso vivo, no funciones sin estado, y por eso esto
# es un contenedor y no un despliegue serverless.

# --- 1 · el tablero -----------------------------------------------------------
FROM node:20-slim AS front

WORKDIR /front
# Las dependencias primero: mientras no cambien, esta capa se reutiliza y el
# build no vuelve a bajar node_modules.
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build


# --- 2 · la aplicación --------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Sin esto CrewAI intenta salir a su telemetría en cada arranque y añade
    # segundos al primer despliegue.
    CREWAI_TELEMETRY_OPT_OUT=true \
    CREWAI_TRACING_ENABLED=false \
    OTEL_SDK_DISABLED=true

WORKDIR /app

# pandas y numpy traen rueda manylinux para cp311, así que no hace falta
# compilador. Si algún día se sube numpy a 2.x, esto deja de ser cierto.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY src/ ./src/
COPY data/ ./data/
COPY --from=front /front/dist ./web/dist

# Render inyecta PORT. La forma shell del CMD es deliberada: hace falta que la
# variable se expanda, y en forma exec llegaría como literal.
EXPOSE 8000
CMD uvicorn api.servidor:app --host 0.0.0.0 --port ${PORT:-8000}
