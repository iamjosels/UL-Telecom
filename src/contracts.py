"""
SON-IA · Contratos de datos entre las tools deterministas y el resto del sistema.

`ResultadoTool` es la frontera donde se hace cumplir el principio rector: el LLM
recibe ÚNICAMENTE el campo `.resumen`, un string construido con f-strings sobre
valores que calculó pandas. El detalle (`.data`) nunca cruza esa frontera — va a
la API y al dashboard, no al modelo.

Eso convierte "0% de alucinaciones" en algo mecánico y no aspiracional: el LLM
no puede citar una cifra que una función Python no produjo, porque no la vio.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

#: Tope del texto que ve el LLM.
#:
#: Es el parámetro de coste más importante del sistema. Cada resultado de tool
#: se queda en el bloc de notas del agente y se reenvía en TODOS sus turnos
#: siguientes, así que un resumen largo se paga muchas veces. Con el plan
#: gratuito de Groq (6.000 tokens/minuto en el modelo rápido) eso es la
#: diferencia entre completar el cierre y chocar con el límite.
#:
#: Recortar aquí no degrada el informe: el reporte se arma desde el registro de
#: resultados con `res.resumen` COMPLETO. Esto sólo limita lo que cruza hacia el
#: modelo, que es exactamente lo que se quiere acotar.
RESUMEN_MAX_CHARS = int(os.getenv("SONIA_RESUMEN_MAX_CHARS", "600"))

#: Tope de filas de detalle que se serializan hacia la API.
MAX_FILAS_DETALLE = 200

Severidad = Literal["critica", "alta", "media", "baja", "info"]

#: Orden para priorizar alertas en el reporte consolidado.
PESO_SEVERIDAD: dict[str, int] = {
    "critica": 0,
    "alta": 1,
    "media": 2,
    "baja": 3,
    "info": 4,
}


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Alerta:
    """Hallazgo accionable con impacto cuantificado en soles.

    `impacto_pen` es lo que permite ordenar el reporte por dinero en vez de por
    orden de ejecución, y `kpi` ancla cada alerta a un indicador de la ficha del
    reto (aseguramiento_ingresos, pcd, tiempo_identificacion_deposito, ...).
    """

    severidad: Severidad
    titulo: str
    detalle: str = ""
    impacto_pen: float = 0.0
    kpi: str = ""
    accion: str = ""
    responsable: str = ""
    #: Clave de deduplicación. Dos tools pueden detectar el mismo hecho desde
    #: ángulos distintos (p. ej. las líneas activas sin cuenta las ve tanto
    #: Facturación como el detector de anomalías); si comparten `clave`, el
    #: reporte muestra una sola alerta.
    clave: str = ""

    def __post_init__(self) -> None:
        if self.severidad not in PESO_SEVERIDAD:
            raise ValueError(
                f"severidad {self.severidad!r} inválida; use una de {list(PESO_SEVERIDAD)}"
            )
        if not self.clave:
            self.clave = self.titulo.strip().lower()

    @property
    def peso(self) -> int:
        return PESO_SEVERIDAD[self.severidad]


@dataclass
class ResultadoTool:
    """Lo que devuelve toda función determinista del sistema.

    Attributes
    ----------
    resumen:
        Texto con las cifras ya calculadas. **Lo único que ve el LLM.**
    metricas:
        Escalares auditables (los que consume ``GET /kpis`` y el dashboard).
    data:
        Detalle fila a fila, truncado. Va a la API; **nunca al LLM**.
    trazas:
        Linaje legible del cálculo, p. ej. ``"facturas 3364 -> saldo>0.01 -> 476"``.
        Es lo que permite a un jurado seguir el número sin leer el código.
    """

    tool: str
    agente: str
    resumen: str
    params: dict[str, Any] = field(default_factory=dict)
    metricas: dict[str, Any] = field(default_factory=dict)
    columnas: list[str] = field(default_factory=list)
    data: list[dict] = field(default_factory=list)
    data_filas_totales: int = 0
    data_truncada: bool = False
    alertas: list[Alerta] = field(default_factory=list)
    trazas: list[str] = field(default_factory=list)
    ok: bool = True
    error: str | None = None
    duracion_ms: int = 0
    ts: str = field(default_factory=ahora)

    # -- vistas ------------------------------------------------------------- #

    def texto_para_llm(self) -> str:
        """El único string que cruza la frontera hacia el modelo.

        Se corta en el último punto completo dentro del tope, no a medio
        carácter: truncar en seco partiría una cifra por la mitad y el agente
        citaría "S/47,8" como si fuera el dato.

        Se avisa de que existe detalle sin entregarlo, para que el agente no
        intente reconstruirlo de memoria.
        """
        txt = self.resumen
        if len(txt) > RESUMEN_MAX_CHARS:
            recortado = txt[:RESUMEN_MAX_CHARS]
            corte = recortado.rfind(". ")
            txt = (recortado[: corte + 1] if corte > RESUMEN_MAX_CHARS // 2 else recortado).rstrip()
        if self.data_filas_totales:
            txt += (
                f"\n[detalle: {self.data_filas_totales} filas en el registro de resultados; "
                "no las listes ni las inventes]"
            )
        return txt

    def to_dict(self) -> dict:
        """JSON-safe completo, para la API y el log de auditoría."""
        d = asdict(self)
        d["alertas"] = [asdict(a) for a in self.alertas]
        return d

    def to_dict_ligero(self) -> dict:
        """Sin `data`: es lo que viaja por SSE y lo que se guarda en auditoría."""
        d = self.to_dict()
        d.pop("data", None)
        return d

    @property
    def impacto_total_pen(self) -> float:
        return round(sum(a.impacto_pen for a in self.alertas), 2)


def error_tool(tool: str, agente: str, mensaje: str, params: dict | None = None) -> ResultadoTool:
    """Constructor de resultado fallido. Las tools nunca lanzan hacia arriba:
    un fallo se convierte en un resultado con ``ok=False`` para que el reporte
    y la auditoría queden completos igual."""
    return ResultadoTool(
        tool=tool,
        agente=agente,
        resumen=f"ERROR en {tool}: {mensaje}",
        params=params or {},
        ok=False,
        error=mensaje,
    )
