"""
SON-IA · Registro de tools y punto único de ejecución.

`ejecutar()` es el embudo por el que pasa TODA invocación de una tool, venga del
crew, del chat, del pipeline determinista o de la API. En un solo lugar ocurren
las cuatro cosas que sostienen el principio rector:

  1. se validan y coaccionan los argumentos con pydantic ANTES de tocar datos,
  2. se escribe la entrada de auditoría,
  3. se guarda el resultado completo en el registro que lee el dashboard,
  4. se emite el evento que alimenta el stream SSE.

Como todo pasa por aquí, la trazabilidad no depende de que cada tool "se acuerde"
de registrarse. Y como `ejecutar()` nunca propaga excepciones, un fallo puntual
degrada una sección del reporte en vez de tumbar el demo.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from src.audit import audit
from src.contracts import ResultadoTool, ahora
from src.data_loader import CORTE_DEL_DATASET, fecha_corte_defecto, normalizar_fecha_corte

# --------------------------------------------------------------------------- #
# Estado del registro
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EspecTool:
    """Metadatos de una tool determinista."""

    nombre: str
    agente: str
    descripcion: str
    args_schema: type[BaseModel]
    etiqueta: str = ""
    kpi: str = ""


_ESPECS: dict[str, EspecTool] = {}
_ULTIMOS: dict[str, ResultadoTool] = {}
_FUNCIONES: dict[str, Callable[..., ResultadoTool]] = {}
_SUSCRIPTORES: list[Callable[[dict], None]] = []
_LOCK = threading.RLock()


class SinArgumentos(BaseModel):
    """Schema para tools sin parámetros.

    Ojo: Groq rechaza un schema con `properties` vacío ("'required' present but
    'properties' is missing"), así que ninguna tool expuesta al LLM debería usar
    este schema tal cual. Se mantiene para tools internas.
    """


def entero_tolerante(defecto: int, minimo: int | None = None, maximo: int | None = None):
    """Validador `before` para argumentos enteros que propone el LLM.

    Los modelos mandan con naturalidad `top=""`, `top=null` o `top="quince"`.
    Sin esto pydantic rechaza la llamada y el usuario recibe un volcado del
    error de validación en lugar de una respuesta.

    Los valores fuera de rango se acotan en vez de rechazarse: quien pide
    `top=999` está pidiendo "todos", y devolver el máximo es más útil que un
    error.
    """

    def _validar(v):
        if v is None or isinstance(v, bool) or (isinstance(v, str) and not v.strip()):
            n = defecto
        else:
            try:
                n = int(float(str(v).strip()))
            except (TypeError, ValueError):
                n = defecto
        if minimo is not None:
            n = max(minimo, n)
        if maximo is not None:
            n = min(maximo, n)
        return n

    return _validar


def booleano_tolerante(v):
    """Mismo problema con los booleanos: llegan como "", "true", "sí", 1."""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    texto = str(v).strip().lower()
    if not texto:
        return False
    return texto in {"true", "1", "si", "sí", "yes", "y", "verdadero"}


class ArgsConFechaCorte(BaseModel):
    """Base para toda tool que recibe una fecha de corte.

    El validador es imprescindible, no cosmético: el router deja que el LLM
    proponga los argumentos y los modelos mandan `fecha_corte="hoy"` con toda
    naturalidad. Sin normalizar, eso revienta en `pd.Timestamp`.
    """

    # `default_factory`, no un valor: un default literal se congela al importar
    # el módulo y seguiría apuntando al corte del dataset que hubiera entonces.
    # Además pydantic no pasa los defaults por el validador, así que un
    # centinela aquí llegaría crudo hasta la tool.
    fecha_corte: str = Field(
        default_factory=fecha_corte_defecto,
        description="Fecha de corte en formato YYYY-MM-DD. Por defecto, la del cierre.",
    )

    @field_validator("fecha_corte", mode="before")
    @classmethod
    def _normalizar_fecha(cls, v):
        return normalizar_fecha_corte(v)


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #


def registrar(
    nombre: str,
    agente: str,
    descripcion: str,
    args_schema: type[BaseModel] = SinArgumentos,
    etiqueta: str = "",
    kpi: str = "",
):
    """Decorador que inscribe una función determinista en el catálogo.

    `descripcion` es lo que lee el LLM para decidir cuándo usar la tool, así que
    conviene que hable en términos de negocio, no de implementación.
    """

    def decorador(fn: Callable[..., ResultadoTool]) -> Callable[..., ResultadoTool]:
        with _LOCK:
            _ESPECS[nombre] = EspecTool(
                nombre=nombre,
                agente=agente,
                descripcion=descripcion.strip(),
                args_schema=args_schema,
                etiqueta=etiqueta or nombre.replace("_", " "),
                kpi=kpi,
            )
            _FUNCIONES[nombre] = fn
        return fn

    return decorador


def catalogo(agente: str | None = None) -> list[EspecTool]:
    """Tools registradas, opcionalmente filtradas por agente."""
    with _LOCK:
        especs = list(_ESPECS.values())
    return [e for e in especs if agente is None or e.agente == agente]


def catalogo_texto(agente: str | None = None) -> str:
    """Catálogo en texto plano, para el prompt del router de `/chat`."""
    return "\n".join(
        f"- {e.nombre}({', '.join(e.args_schema.model_fields) or 'sin argumentos'}): {e.descripcion}"
        for e in catalogo(agente)
    )


# --------------------------------------------------------------------------- #
# Suscriptores (SSE / consola)
# --------------------------------------------------------------------------- #


def suscribir(cb: Callable[[dict], None]) -> Callable[[dict], None]:
    with _LOCK:
        _SUSCRIPTORES.append(cb)
    return cb


def desuscribir(cb: Callable[[dict], None]) -> None:
    with _LOCK:
        if cb in _SUSCRIPTORES:
            _SUSCRIPTORES.remove(cb)


def emitir(evento: dict) -> None:
    """Publica un evento a todos los suscriptores.

    Un sink roto (cliente SSE que cerró la pestaña) jamás debe tumbar una tool,
    de ahí el try/except por suscriptor.
    """
    evento.setdefault("ts", ahora())
    with _LOCK:
        sinks = list(_SUSCRIPTORES)
    for cb in sinks:
        try:
            cb(evento)
        except Exception:  # noqa: BLE001 — aislar el sink es el objetivo
            pass


# --------------------------------------------------------------------------- #
# Ejecución
# --------------------------------------------------------------------------- #


def ejecutar(nombre: str, origen: str = "sistema", **kwargs: Any) -> ResultadoTool:
    """Ejecuta una tool registrada. **Nunca lanza excepción.**

    Parameters
    ----------
    nombre:
        Clave del catálogo. Si no existe, devuelve un resultado con ``ok=False``
        que enumera las disponibles (útil cuando el LLM alucina un nombre).
    origen:
        Quién la invoca, para la auditoría: un agente, "AGENTE_CHAT", "sistema".
    """
    with _LOCK:
        espec = _ESPECS.get(nombre)
        fn = _FUNCIONES.get(nombre)

    if espec is None or fn is None:
        disponibles = ", ".join(sorted(_ESPECS)) or "ninguna"
        res = ResultadoTool(
            tool=nombre,
            agente=origen,
            resumen=(
                f"ERROR: la herramienta '{nombre}' no existe. "
                f"Herramientas disponibles: {disponibles}."
            ),
            params=kwargs,
            ok=False,
            error="tool_no_encontrada",
        )
        audit.registrar_tool(res)
        emitir({"tipo": "tool_error", "agente": origen, "tool": nombre, "resumen": res.resumen})
        return res

    # 1) validar/coaccionar argumentos ANTES de tocar datos
    try:
        validados = espec.args_schema(**kwargs).model_dump()
    except ValidationError as e:
        # Los validadores tolerantes de cada schema absorben la basura habitual
        # del LLM, así que llegar aquí es raro. Aun así el mensaje se redacta
        # en lenguaje llano: `e.errors()` volcaba en pantalla del usuario un
        # diccionario de pydantic con URLs de documentación incluidas.
        campos = ", ".join(
            f"{'.'.join(str(x) for x in err.get('loc', ())) or 'argumento'}"
            for err in e.errors()
        )
        res = ResultadoTool(
            tool=nombre,
            agente=espec.agente,
            resumen=(
                f"No pude ejecutar '{espec.etiqueta}': los valores recibidos para "
                f"{campos} no son válidos. Vuelve a preguntar sin precisar ese detalle."
            ),
            params=kwargs,
            ok=False,
            error="argumentos_invalidos",
        )
        audit.registrar_tool(res)
        emitir({"tipo": "tool_error", "agente": espec.agente, "tool": nombre, "resumen": res.resumen})
        return res

    emitir(
        {
            "tipo": "tool_inicio",
            "agente": espec.agente,
            "origen": origen,
            "tool": nombre,
            "etiqueta": espec.etiqueta,
            "inputs": validados,
        }
    )

    # 2) ejecutar, midiendo
    t0 = time.perf_counter()
    try:
        res = fn(**validados)
        if not isinstance(res, ResultadoTool):  # contrato roto por la tool
            raise TypeError(f"{nombre} devolvió {type(res).__name__}, esperaba ResultadoTool")
    except Exception as e:  # noqa: BLE001 — degradar, no tumbar el demo
        res = ResultadoTool(
            tool=nombre,
            agente=espec.agente,
            resumen=f"ERROR ejecutando {nombre}: {type(e).__name__}: {e}",
            params=validados,
            ok=False,
            error=f"{type(e).__name__}: {e}",
        )
        audit.registrar_error(nombre, espec.agente, validados, traceback.format_exc())

    res.duracion_ms = int((time.perf_counter() - t0) * 1000)
    res.params = validados
    res.agente = espec.agente

    # 3) registrar + 4) emitir
    with _LOCK:
        _ULTIMOS[nombre] = res
    audit.registrar_tool(res)
    emitir(
        {
            "tipo": "tool_fin",
            "agente": espec.agente,
            "origen": origen,
            "tool": nombre,
            "etiqueta": espec.etiqueta,
            "inputs": validados,
            "resumen": res.resumen,
            "metricas": res.metricas,
            "alertas": [
                {"severidad": a.severidad, "titulo": a.titulo, "impacto_pen": a.impacto_pen}
                for a in res.alertas
            ],
            "trazas": res.trazas,
            "ok": res.ok,
            "duracion_ms": res.duracion_ms,
            "filas_detalle": res.data_filas_totales,
        }
    )
    return res


# --------------------------------------------------------------------------- #
# Resultados acumulados
# --------------------------------------------------------------------------- #


def ultimos() -> dict[str, ResultadoTool]:
    """Último resultado de cada tool ejecutada en la corrida actual."""
    with _LOCK:
        return dict(_ULTIMOS)


def obtener(nombre: str) -> ResultadoTool | None:
    with _LOCK:
        return _ULTIMOS.get(nombre)


def limpiar() -> None:
    """Vacía los resultados acumulados (inicio de una corrida nueva)."""
    with _LOCK:
        _ULTIMOS.clear()


def alertas_ordenadas() -> list:
    """Alertas de la corrida, deduplicadas, por severidad y luego por impacto.

    Primero lo crítico y, dentro de cada nivel, primero donde hay más dinero.
    Dos tools pueden reportar el mismo hecho desde ángulos distintos; se
    conserva la versión más severa de cada `clave`.
    """
    todas = [a for res in ultimos().values() for a in res.alertas]
    ordenadas = sorted(todas, key=lambda a: (a.peso, -a.impacto_pen))

    vistas: dict[str, Any] = {}
    for a in ordenadas:
        vistas.setdefault(a.clave, a)
    return list(vistas.values())
