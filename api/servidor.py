"""
SON-IA · Punto de entrada del despliegue.

En desarrollo son dos procesos: uvicorn sirve la API en el 8000 y Vite el front
en el 5173, proxeando `/api` al backend. En producción no hay Vite, así que el
front pediría a `/api` contra un servidor que no existe.

La salida es una sola aplicación: la misma API montada bajo `/api` y el build
del front en la raíz. Una URL, sin CORS y sin tener que configurar en ningún
sitio dónde vive el backend. `api.main:app` se queda intacto para el desarrollo
local y para los tests.

    desarrollo   uvicorn api.main:app --port 8000   +   npm run dev
    producción   uvicorn api.servidor:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.main import app as api

RAIZ = Path(__file__).resolve().parents[1]
DIST = RAIZ / "web" / "dist"

app = FastAPI(
    title="SON-IA",
    description="Ciclo del ingreso B2B. La API vive bajo /api; la raíz sirve el tablero.",
    # La documentación interactiva de esta capa sobra: la de la API está en
    # /api/docs, que es la que tiene algo que enseñar.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# El orden importa: el montaje de la raíz captura todo lo que no case antes.
app.mount("/api", api)

if DIST.exists():
    # html=True sirve index.html en la raíz y ante cualquier ruta desconocida,
    # que es lo que necesita una aplicación de una sola página.
    app.mount("/", StaticFiles(directory=DIST, html=True), name="tablero")
else:

    @app.get("/")
    def sin_build() -> JSONResponse:
        """Falta el build del front. Se dice en vez de devolver un 404 mudo."""
        return JSONResponse(
            status_code=503,
            content={
                "error": "No encuentro web/dist.",
                "solucion": "cd web && npm run build",
                "api": "La API sigue disponible en /api",
            },
        )
