"""
SON-IA · Camino de ejecución determinista.

Recorre `PLAN_DE_CIERRE` llamando `ejecutar()` paso a paso, sin LLM. Es la red
de seguridad del demo: si falta GROQ_API_KEY, si Groq limita por cuota o si el
crew entra en bucle, esto produce el informe completo con las mismas cifras y
el mismo log de auditoría.

También lo usa `crew.py` para rellenar los pasos que el crew no llegó a hacer.
"""

from __future__ import annotations

from collections.abc import Callable

from src.audit import audit
from src.contracts import ResultadoTool
from src.plan import FECHA_CORTE, OBJETIVO_DEMO, PLAN_DE_CIERRE, Paso
from src.reporte import kpis_planos, render_reporte
from src.tools import registro

Emisor = Callable[[dict], None] | None


def ejecutar_pasos(pasos: list[Paso], emitir: Emisor = None) -> dict[str, ResultadoTool]:
    """Ejecuta una lista de pasos en orden. `ejecutar()` ya audita y emite los
    eventos de tool; aquí sólo se añade el evento de encabezado del paso."""
    for paso in pasos:
        if emitir:
            emitir(
                {
                    "tipo": "paso_inicio",
                    "id": paso.id,
                    "agente": paso.agente,
                    "titulo": paso.titulo,
                    "momento": paso.momento,
                    "kpi": paso.kpi,
                }
            )
        registro.ejecutar(paso.tool, origen=paso.agente, **paso.params)
    return registro.ultimos()


def ejecutar_plan(
    emitir: Emisor = None,
    modo: str = "deterministico",
    objetivo: str = OBJETIVO_DEMO,
    fecha_corte: str = FECHA_CORTE,
    narrativa: str | None = None,
    abrir_corrida: bool = True,
) -> dict:
    """Corre el cierre completo y devuelve reporte + resultados + auditoría."""
    if abrir_corrida:
        registro.limpiar()
        audit.iniciar_corrida(objetivo=objetivo, modo=modo)

    if emitir:
        emitir({"tipo": "corrida_inicio", "objetivo": objetivo, "modo": modo,
                "fecha_corte": fecha_corte, "pasos": len(PLAN_DE_CIERRE)})

    resultados = ejecutar_pasos(PLAN_DE_CIERRE, emitir)

    reporte = render_reporte(
        resultados, modo=modo, narrativa=narrativa, fecha_corte=fecha_corte, objetivo=objetivo
    )
    audit.cerrar_corrida()
    # exportar() trae el bloque "resumen" con los contadores; cerrar_corrida()
    # sólo devuelve la cabecera de la corrida.
    resumen_auditoria = {k: v for k, v in audit.exportar().items() if k != "entradas"}
    ruta = audit.guardar_json()

    if emitir:
        emitir({"tipo": "corrida_fin", "modo": modo, "auditoria": str(ruta)})

    return {
        "reporte": reporte,
        "modo": modo,
        "objetivo": objetivo,
        "fecha_corte": fecha_corte,
        "resultados": {k: v.to_dict_ligero() for k, v in resultados.items()},
        "kpis": kpis_planos(resultados),
        "alertas": [
            {
                "severidad": a.severidad,
                "titulo": a.titulo,
                "detalle": a.detalle,
                "impacto_pen": a.impacto_pen,
                "kpi": a.kpi,
                "accion": a.accion,
                "responsable": a.responsable,
            }
            for a in registro.alertas_ordenadas()
        ],
        "auditoria": {**resumen_auditoria, "archivo": str(ruta)},
    }
