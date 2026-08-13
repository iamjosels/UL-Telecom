"""
SON-IA · El plan de cierre de ciclo, como fuente única de verdad.

`PLAN_DE_CIERRE` lo consumen los DOS caminos de ejecución:

  - `src/crew.py` lo renderiza en las descripciones de las tareas de CrewAI,
  - `src/pipeline.py` lo itera llamando `ejecutar()` sin LLM.

Al vivir en un solo sitio, el fallback determinista no es un demo degradado:
son exactamente los mismos pasos, las mismas tools y las mismas cifras, con
narrativa de plantilla en vez de narrativa del modelo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FECHA_CORTE = "2026-08-12"
OBJETIVO_DEMO = "Cierra el ciclo del mes"

# Los tres momentos de facturación de la ficha del reto.
MOMENTO_1 = "1 · Asesoría previa a la emisión"
MOMENTO_2 = "2 · Ejecución automatizada"
MOMENTO_3 = "3 · Rebaja automática post-pago"

AGENTES = {
    "AGENTE_FACTURACION": "Facturación",
    "AGENTE_COBRANZAS": "Cobranzas y Recaudo",
    "AGENTE_BI": "Inteligencia de Negocio",
}


@dataclass(frozen=True)
class Paso:
    """Un paso del cierre: qué agente ejecuta qué tool, con qué parámetros."""

    id: str
    agente: str
    tool: str
    titulo: str
    params: dict = field(default_factory=dict)
    momento: str = ""
    kpi: str = ""


PLAN_DE_CIERRE: list[Paso] = [
    # -- Facturación: momento 1, asesoría previa a la emisión ---------------- #
    Paso(
        id="F1",
        agente="AGENTE_FACTURACION",
        tool="resumen_facturacion",
        titulo="Escalera de facturación del ciclo",
        momento=MOMENTO_1,
        kpi="aseguramiento_ingresos",
    ),
    Paso(
        id="F2",
        agente="AGENTE_FACTURACION",
        tool="detectar_servicios_no_facturados",
        titulo="Fuga por no facturar: servicios activos sin factura",
        momento=MOMENTO_1,
        kpi="aseguramiento_ingresos",
    ),
    Paso(
        id="F3",
        agente="AGENTE_FACTURACION",
        tool="validar_clientes_sunat",
        titulo="Riesgo tributario: RUC NO HABIDO y control del PxQ",
        momento=MOMENTO_1,
        kpi="reduccion_nc_error_operativo",
    ),
    # -- Cobranzas y Recaudo: momento 3, rebaja post-pago -------------------- #
    Paso(
        id="C1",
        agente="AGENTE_COBRANZAS",
        tool="conciliar_pagos",
        titulo="Conciliación y rebaja automática post-pago",
        params={"conciliacion": "canonica"},
        momento=MOMENTO_3,
        kpi="tiempo_conciliacion_bancaria",
    ),
    Paso(
        id="C2",
        agente="AGENTE_COBRANZAS",
        tool="pagos_no_identificados",
        titulo="Partidas bancarias sin aplicar",
        momento=MOMENTO_3,
        kpi="tiempo_identificacion_deposito",
    ),
    Paso(
        id="C3",
        agente="AGENTE_COBRANZAS",
        tool="cartera_vencida",
        titulo="Cartera vencida con aging al corte",
        params={"fecha_corte": FECHA_CORTE},
        kpi="reduccion_cxc",
    ),
    # -- Inteligencia de Negocio -------------------------------------------- #
    Paso(
        id="B1",
        agente="AGENTE_BI",
        tool="ratio_cobrado_facturado",
        titulo="Ratio cobrado/facturado y periodo medio de cobro",
        params={"dias": 30},
        kpi="ratio_cobrado_facturado_30d",
    ),
    Paso(
        id="B2",
        agente="AGENTE_BI",
        tool="detectar_anomalias",
        titulo="Anomalías de datos y de proceso",
        kpi="aseguramiento_ingresos",
    ),
    Paso(
        id="B3",
        agente="AGENTE_BI",
        tool="provision_cobranza_dudosa",
        titulo="Provisión de cobranza dudosa por aging",
        params={"fecha_corte": FECHA_CORTE},
        kpi="pcd",
    ),
    Paso(
        id="B4",
        agente="AGENTE_BI",
        tool="priorizar_recupero",
        titulo="Mesa de aceleración de recupero",
        params={"fecha_corte": FECHA_CORTE, "top": 15},
        kpi="reduccion_cxc",
    ),
    Paso(
        id="B5",
        agente="AGENTE_BI",
        tool="proyeccion_caja",
        titulo="Adelanto operativo de caja a 30/60/90 días",
        params={"fecha_corte": FECHA_CORTE},
        kpi="reduccion_cxc",
    ),
]


def pasos_de(agente: str) -> list[Paso]:
    return [p for p in PLAN_DE_CIERRE if p.agente == agente]


def paso_por_tool(tool: str) -> Paso | None:
    return next((p for p in PLAN_DE_CIERRE if p.tool == tool), None)


def tools_del_plan() -> list[str]:
    return [p.tool for p in PLAN_DE_CIERRE]
