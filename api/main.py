"""
SON-IA · API HTTP para el dashboard.

    POST /run    corre el cierre y TRANSMITE los pasos por SSE
    POST /chat   pregunta en lenguaje natural enrutada a las tools
    GET  /kpis   métricas para el dashboard (no ejecuta el crew)
    GET  /tools  catálogo de herramientas deterministas
    GET  /auditoria  última corrida registrada

Detalle de diseño del streaming: `Crew.kickoff()` es bloqueante, así que corre
en un worker thread. El puente hacia el bucle de eventos es
`loop.call_soon_threadsafe(cola.put_nowait, evento)`; el generador async drena
la cola con timeout para emitir heartbeats y no morir detrás de un proxy.

Los eventos que el dashboard NECESITA (qué agente, qué tool, qué argumentos, qué
cifras) salen de nuestro propio embudo de ejecución, no del bus de CrewAI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import threading
import uuid
from pathlib import Path

import pandas as pd

from dotenv import load_dotenv

load_dotenv()

# Apagar telemetría antes de que se importe crewai (import diferido más abajo).
os.environ.setdefault("CREWAI_TELEMETRY_OPT_OUT", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sse_starlette.sse import EventSourceResponse  # noqa: E402

from src.audit import audit  # noqa: E402
from src.contracts import ahora  # noqa: E402
from src.data_loader import (  # noqa: E402
    ARCHIVOS,
    CORTE_DEL_DATASET,
    RAIZ,
    DatasetInvalido,
    estado_origen,
    fecha_corte_defecto,
    get_datos,
    restaurar_demo,
    usar_origen,
)
from src.plan import OBJETIVO_DEMO, PLAN_DE_CIERRE  # noqa: E402
from src.proveedor import clave_groq, motivo_humano  # noqa: E402 — ligero, sin CrewAI
from src.reporte import kpis_dashboard  # noqa: E402
from src.router import charla, responder  # noqa: E402
from src.tools import registro  # noqa: E402

_LOG = logging.getLogger("sonia.api")


def _precalentar_llm() -> None:
    """Importa CrewAI en segundo plano, nada más arrancar.

    `src.agents` tarda diecinueve segundos en importarse y ese coste lo pagaba
    entera la PRIMERA pregunta del chat, dentro de su petición. El tablero
    corta a los 15 s y reintenta sin modelo, así que la primera respuesta salía
    siempre como volcado de la herramienta — justo la que más se mira.

    En un hilo daemon: si falla o tarda, el arranque y el healthcheck no se
    enteran. Y no se hace si no hay clave, porque entonces no se va a usar.
    """
    if not clave_groq():
        return
    try:
        import src.agents  # noqa: F401, PLC0415
    except Exception:  # noqa: BLE001
        _LOG.warning("No se pudo precalentar la capa de agentes", exc_info=True)


threading.Thread(target=_precalentar_llm, name="precalentar-llm", daemon=True).start()

app = FastAPI(
    title="SON-IA",
    description=(
        "Ecosistema de agentes de IA para Facturación, Cobranzas y Recaudo B2B. "
        "Toda cifra proviene de funciones deterministas; el LLM orquesta y explica."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dashboard local del hackathon
    allow_methods=["*"],
    allow_headers=["*"],
)

#: Centinela de fin de stream. Es un objeto propio para que ningún payload
#: JSON malformado pueda confundirse con la señal de terminación.
FIN = object()

#: Una corrida a la vez: el registro de resultados es de módulo.
_corrida_en_curso = threading.Lock()


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #


class PeticionRun(BaseModel):
    objetivo: str = Field(OBJETIVO_DEMO, description="Objetivo para el supervisor.")
    fecha_corte: str = Field(
        default_factory=fecha_corte_defecto, description="Fecha de corte YYYY-MM-DD."
    )
    deterministico: bool = Field(False, description="Forzar el camino sin LLM.")


class PeticionChat(BaseModel):
    mensaje: str = Field(..., description="Pregunta en lenguaje natural.")
    usar_llm: bool = Field(True, description="Dejar que el LLM redacte la respuesta.")
    contexto: dict | None = Field(
        None,
        description=(
            "Turno anterior: {pregunta, tool, args}. Permite resolver preguntas "
            "que se apoyan en la de antes ('¿y a 90 días?')."
        ),
    )


# --------------------------------------------------------------------------- #
# Salud y catálogo
# --------------------------------------------------------------------------- #


@app.get("/")
def raiz() -> dict:
    return {
        "servicio": "SON-IA",
        "estado": "ok",
        # `clave_groq()` y no `os.getenv`: una clave con comillas o con el salto
        # de línea del copiar y pegar no está configurada, está rota, y decir
        # aquí que sí lo está manda a buscar el fallo al sitio equivocado.
        # Aquí no se sondea a Groq: esto es el healthcheck y tiene que ser
        # instantáneo.
        "llm_configurado": bool(clave_groq()),
        "endpoints": ["/run (SSE)", "/chat", "/kpis", "/tools", "/auditoria", "/docs"],
    }


@app.get("/tools")
def listar_tools() -> dict:
    return {
        "total": len(registro.catalogo()),
        "tools": [
            {
                "nombre": e.nombre,
                "agente": e.agente,
                "etiqueta": e.etiqueta,
                "kpi": e.kpi,
                "descripcion": e.descripcion,
                "argumentos": list(e.args_schema.model_fields),
            }
            for e in registro.catalogo()
        ],
    }


def _json_seguro(valor):
    """Deja un valor listo para JSONResponse, que es estricto.

    El detalle de las herramientas viene de pandas y trae dos cosas que rompen
    la serialización: `pd.Timestamp` (que el codificador no conoce) y `NaN`
    (que no es JSON válido y con `allow_nan=False` lanza, devolviendo un 500).
    Visto de verdad en `pagos_no_identificados`, donde `doc_propuesto` y
    `total_factura` son NaN en las filas sin contraparte.
    """
    if valor is None:
        return None
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else None
    if isinstance(valor, (str, int, bool)):
        return valor
    if isinstance(valor, dict):
        return {k: _json_seguro(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_json_seguro(v) for v in valor]
    if valor is pd.NaT or (hasattr(valor, "isoformat")):
        try:
            return valor.isoformat()
        except Exception:  # noqa: BLE001
            return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    return str(valor)


@app.get("/resultados")
def resultados() -> dict:
    """Resultados de la última corrida, con el detalle fila a fila.

    Los eventos SSE solo llevan el conteo de filas, así que sin esto el
    dashboard no puede dibujar el ranking de clientes ni la tabla de anomalías.
    Aquí se expone lo que el registro ya guarda en memoria.

    Devuelve `{}` mientras no se haya corrido nada: el registro se vacía al
    empezar cada cierre.
    """
    return {
        "ts": ahora(),
        "corrida_id": audit.corrida_id,
        "tools": {
            nombre: {
                "tool": res.tool,
                "agente": res.agente,
                "ok": res.ok,
                "params": res.params,
                "metricas": _json_seguro(res.metricas),
                "columnas": res.columnas,
                "data": _json_seguro(res.data),
                "filas_totales": res.data_filas_totales,
                "truncada": res.data_truncada,
                "trazas": res.trazas,
            }
            for nombre, res in registro.ultimos().items()
        },
    }


@app.get("/kpis")
def kpis(fecha_corte: str = CORTE_DEL_DATASET) -> dict:
    """Métricas de portada. Se calculan en directo, sin pasar por el crew."""
    try:
        datos = kpis_dashboard(fecha_corte)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error calculando KPIs: {e}") from e
    return {"ts": ahora(), **datos}


@app.get("/diagnostico")
def diagnostico() -> dict:
    """Perfil de la data cargada: formatos de fecha, sistemas, conciliación."""
    return get_datos().diagnostico


@app.get("/auditoria")
def auditoria() -> dict:
    return audit.exportar()


# --------------------------------------------------------------------------- #
# Datasets
# --------------------------------------------------------------------------- #
#
# El sistema arrancaba clavado a `data/`, con seis nombres de archivo fijos y
# siete constantes del dataset del demo comprobadas al cargar. Con el corte de
# otro mes fallaban las siete a la vez y la aplicación no levantaba.
#
# Aquí se sube un corte propio. El orden importa: los archivos se dejan en una
# carpeta de preparación, se valida ahí, y solo si valida se cambia el origen.
# Un archivo mal formado no puede dejar el dashboard sin datos.

DIR_SUBIDAS = RAIZ / ".datos_subidos"


def _limpiar_subidas_viejas(conservar: Path | None = None) -> None:
    """Deja solo el corte en uso. Las subidas descartadas no valen nada."""
    if not DIR_SUBIDAS.exists():
        return
    for hijo in DIR_SUBIDAS.iterdir():
        if hijo.is_dir() and hijo != conservar:
            shutil.rmtree(hijo, ignore_errors=True)


def _cambiar_dataset(accion) -> dict:
    """Ejecuta el cambio y deja el estado derivado coherente.

    Los resultados de las tools se vacían siempre: son cifras del dataset
    anterior y dejarlas a la vista mientras la portada ya muestra otras es peor
    que no mostrar nada.
    """
    if _corrida_en_curso.locked():
        raise HTTPException(
            status_code=409,
            detail="Hay un cierre en curso. Espera a que termine para cambiar los datos.",
        )
    try:
        accion()
    except DatasetInvalido as e:
        raise HTTPException(
            status_code=422,
            detail={"motivo": "esquema", "problemas": e.problemas},
        ) from e
    except AssertionError as e:
        raise HTTPException(
            status_code=422,
            detail={"motivo": "estructura", "problemas": {"datos": str(e).splitlines()}},
        ) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"No se pudo cargar: {e}") from e

    registro.limpiar()
    return {"ts": ahora(), **estado_origen()}


@app.get("/datos/estado")
def datos_estado() -> dict:
    """Qué dataset está cargado, con qué corte y de dónde sale ese corte."""
    return {"ts": ahora(), **estado_origen()}


@app.post("/datos/cargar")
async def datos_cargar(
    clientes: UploadFile = File(...),
    planta_fija: UploadFile = File(...),
    planta_movil: UploadFile = File(...),
    pagos: UploadFile = File(...),
    facturas: UploadFile = File(...),
    notas_credito: UploadFile = File(...),
    fecha_corte: str = Form(""),
) -> dict:
    """Sube los 6 CSV de un corte propio.

    Cada archivo llega bajo el nombre de su tabla, no por su nombre de archivo:
    el emparejado lo hace la interfaz y el usuario puede corregirlo antes de
    enviar. Así un CSV renombrado sigue funcionando.
    """
    subidos = {
        "clientes": clientes,
        "planta_fija": planta_fija,
        "planta_movil": planta_movil,
        "pagos": pagos,
        "facturas": facturas,
        "notas_credito": notas_credito,
    }

    destino = DIR_SUBIDAS / uuid.uuid4().hex[:12]
    destino.mkdir(parents=True, exist_ok=True)
    for clave, archivo in subidos.items():
        (destino / ARCHIVOS[clave]).write_bytes(await archivo.read())

    # El corte es una decisión de negocio, no un dato: si lo indican, manda.
    # Si no, el cargador lo deriva de las fechas del propio dataset.
    if fecha_corte.strip():
        (destino / "corte.txt").write_text(fecha_corte.strip(), encoding="utf-8")

    try:
        estado = _cambiar_dataset(lambda: usar_origen(destino))
    except HTTPException:
        shutil.rmtree(destino, ignore_errors=True)
        raise

    _limpiar_subidas_viejas(conservar=destino)
    return estado


@app.post("/datos/restaurar")
def datos_restaurar() -> dict:
    """Vuelve al dataset del repositorio."""
    estado = _cambiar_dataset(restaurar_demo)
    _limpiar_subidas_viejas()
    return estado


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #


@app.post("/chat")
def chat(peticion: PeticionChat) -> dict:
    """Pregunta en lenguaje natural. El LLM elige la tool y redacta; nunca calcula."""
    # Un saludo o un "¿qué puedes hacer?" se contestan sin modelo, así que no
    # hay por qué construirlo: `src.agents` arrastra CrewAI y son diecinueve
    # segundos la primera vez. Justo lo que peor se ve, porque es lo primero
    # que la gente escribe.
    if charla(peticion.mensaje) is not None:
        return responder(peticion.mensaje)

    llm = None
    if peticion.usar_llm and clave_groq():
        try:
            from src.agents import estado_de_groq, llm_chat

            # Si Groq no está utilizable se contesta con el resumen
            # determinista y ya está. Sin esta comprobación, cada pregunta
            # gastaba dos viajes de ida y vuelta condenados a fallar antes de
            # llegar a la misma respuesta.
            if estado_de_groq()[0]:
                # Modelo aparte del que usan los agentes: su cuota de tokens por
                # minuto es independiente y sigue intacta después de un cierre.
                llm = llm_chat()
        except Exception:
            llm = None
    return responder(peticion.mensaje, llm=llm, contexto=peticion.contexto)


# --------------------------------------------------------------------------- #
# Run con streaming SSE
# --------------------------------------------------------------------------- #


@app.post("/run")
async def run(peticion: PeticionRun, request: Request):
    """Corre el cierre del ciclo transmitiendo cada paso por SSE."""
    if _corrida_en_curso.locked():
        raise HTTPException(status_code=409, detail="Ya hay una corrida en curso.")

    loop = asyncio.get_running_loop()
    cola: asyncio.Queue = asyncio.Queue()
    run_id = uuid.uuid4().hex[:8]

    def emitir(evento: dict) -> None:
        """Se llama desde el worker thread: hay que cruzar al bucle de eventos."""
        evento.setdefault("run_id", run_id)
        evento.setdefault("ts", ahora())
        try:
            loop.call_soon_threadsafe(cola.put_nowait, evento)
        except RuntimeError:
            pass  # el bucle ya cerró: el cliente se fue

    def worker() -> None:
        with _corrida_en_curso:
            # Una cancelación de la corrida anterior mataría esta nada más
            # empezar. Se limpia aquí, dentro del candado, no en el endpoint.
            registro.reiniciar_cancelacion()
            try:
                if peticion.deterministico or not clave_groq():
                    from src.pipeline import ejecutar_plan

                    salida = ejecutar_plan(
                        emitir=emitir, modo="deterministico",
                        objetivo=peticion.objetivo, fecha_corte=peticion.fecha_corte,
                    )
                else:
                    from src.crew import ejecutar_cierre

                    salida = ejecutar_cierre(
                        emitir=emitir, objetivo=peticion.objetivo,
                        fecha_corte=peticion.fecha_corte,
                    )
                if registro.cancelacion_pedida():
                    # Se detuvo a mitad. NO se emite reporte_final: ese evento
                    # significa "el cierre cuadra", y aquí faltan pasos. Lo que
                    # ya se calculó sigue en el registro y en el tablero.
                    emitir({"tipo": "cancelado", "mensaje": "Cierre detenido."})
                    return
                emitir(
                    {
                        "tipo": "reporte_final",
                        "reporte": salida["reporte"],
                        "modo": salida["modo"],
                        "kpis": salida["kpis"],
                        "alertas": salida["alertas"],
                        "auditoria": salida["auditoria"],
                        # La lectura ejecutiva del supervisor, en markdown y sin
                        # envolver. Dentro de `reporte` va a 74 columnas y con
                        # sangría, así que de ahí no se puede recuperar limpia.
                        # Es None en el camino determinista.
                        "narrativa": salida.get("narrativa"),
                    }
                )
            except registro.CorridaCancelada:
                # Salió por el punto del LLM. Es lo pedido, no un fallo.
                emitir({"tipo": "cancelado", "mensaje": "Cierre detenido."})
            except BaseException as e:  # noqa: BLE001
                # Una cancelación puede llegar envuelta por CrewAI o LiteLLM,
                # que capturan y reempaquetan lo que lanza una herramienta.
                if registro.cancelacion_pedida():
                    emitir({"tipo": "cancelado", "mensaje": "Cierre detenido."})
                else:
                    # El volcado de LiteLLM son varias líneas con el JSON de
                    # Groq dentro; en pantalla se pone la causa en una frase y
                    # el original se deja en el log del servidor.
                    _LOG.exception("El cierre se interrumpió")
                    emitir({
                        "tipo": "error",
                        "mensaje": f"El cierre se interrumpió: {motivo_humano(e)}.",
                    })
            finally:
                # El evento "fin" lo emite el centinela al final del generador,
                # así el cliente recibe exactamente uno.
                try:
                    loop.call_soon_threadsafe(cola.put_nowait, FIN)
                except RuntimeError:
                    pass

    async def generador():
        registro.suscribir(emitir)
        try:
            loop.run_in_executor(None, worker)
            while True:
                try:
                    evento = await asyncio.wait_for(cola.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue

                if evento is FIN:
                    yield {"event": "fin", "data": json.dumps({"run_id": run_id})}
                    break
                if await request.is_disconnected():
                    break
                yield {
                    "event": evento.get("tipo", "mensaje"),
                    "data": json.dumps(evento, ensure_ascii=False, default=str),
                }
        finally:
            # Siempre, incluso si el cliente cortó: si no, los emisores se
            # acumulan entre corridas y una recarga de página los multiplica.
            registro.desuscribir(emitir)

    return EventSourceResponse(generador(), ping=15000)


@app.post("/run/detener")
def detener() -> dict:
    """Pide que el cierre en curso pare.

    No mata nada: marca la bandera y el worker sale en el siguiente punto de
    control, que es la próxima herramienta o la próxima llamada al modelo. Por
    eso responde 202 y no 200: está aceptado, no consumado.
    """
    if not _corrida_en_curso.locked():
        return {"ts": ahora(), "detenido": False, "motivo": "no hay ningún cierre en curso"}
    registro.pedir_cancelacion()
    return {"ts": ahora(), "detenido": True}


@app.get("/plan")
def plan() -> dict:
    """El plan de cierre, para que el dashboard pinte los pasos antes de correr."""
    return {
        "objetivo": OBJETIVO_DEMO,
        "pasos": [
            {
                "id": p.id,
                "agente": p.agente,
                "tool": p.tool,
                "titulo": p.titulo,
                "momento": p.momento,
                "kpi": p.kpi,
                "params": p.params,
            }
            for p in PLAN_DE_CIERRE
        ],
    }
