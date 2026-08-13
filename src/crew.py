"""
SON-IA · Orquestador jerárquico con red de seguridad.

El supervisor delega en los tres agentes operadores y consolida. Pero un demo
que depende de que un LLM remoto se porte bien no es un demo: el plan gratuito
de Groq limita por tokens/minuto, la delegación jerárquica puede entrar en
bucle y un tool-call malformado tumba la corrida.

Por eso `ejecutar_cierre()` tiene tres propiedades deliberadas:

  1. Si no hay GROQ_API_KEY, va directo al camino determinista.
  2. El crew corre en un hilo con timeout. Si falla o se cuelga, se sigue.
  3. Lo que el crew SÍ logró se conserva: sólo se rellenan los pasos que
     faltaron. Un fallo parcial deja igualmente trabajo real de los agentes en
     pantalla, y el informe sale completo.

En los tres casos el informe se arma con `render_reporte()` sobre el registro de
resultados, así que las cifras son idénticas: lo único que cambia es si hay o no
narrativa redactada por el modelo.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

from crewai import Crew, Process, Task

from src.agents import (
    RPM_POTENTE,
    agente_bi,
    agente_cobranzas,
    agente_facturacion,
    agente_supervisor,
)
from src.audit import audit
from src.pipeline import ejecutar_pasos
from src.plan import FECHA_CORTE, OBJETIVO_DEMO, PLAN_DE_CIERRE
from src.reporte import kpis_planos, render_reporte
from src.tools import registro

Emisor = Callable[[dict], None] | None

TIMEOUT_CREW_S = int(os.getenv("SONIA_TIMEOUT_CREW", "180"))

#: Modo de orquestación. Ver la nota de arriba: "supervisado" es el que cabe en
#: el plan gratuito de Groq; "jerarquico" es el proceso nativo de CrewAI.
PROCESO = os.getenv("SONIA_PROCESO", "supervisado").strip().lower()


PROMPT_SUPERVISOR = (
    "Eres el Supervisor del Ciclo de Ingresos B2B de Integratel. Recibes los informes de tus "
    "tres agentes operadores y produces la LECTURA EJECUTIVA del cierre.\n\n"
    "REGLA ABSOLUTA: usa ÚNICAMENTE las cifras que aparecen en los informes. Está prohibido "
    "calcular, sumar, estimar o redondear distinto. Si necesitas una cifra que no está, dilo.\n\n"
    "Estructura tu respuesta en 4 bloques breves y en español:\n"
    "1. DIAGNÓSTICO: ¿comparten los hallazgos una causa raíz común? Nómbrala.\n"
    "2. LO MÁS URGENTE: los 3 hallazgos con más dinero en juego, con su cifra.\n"
    "3. DECISIONES: qué hay que aprobar hoy.\n"
    "4. ACCIONES: 4 acciones concretas, cada una con su responsable "
    "(Facturación / Cobranzas / Recaudo / TI / Contabilidad).\n"
    "Máximo 20 líneas en total."
)


def _informes_desde_resultados() -> list[str]:
    """Arma los informes por agente a partir de los resúmenes de las tools.

    Es el plan B cuando el crew no llegó a producir sus salidas por tarea. Los
    resúmenes ya están calculados y son deterministas, así que el supervisor
    puede consolidar igual: pierde la prosa de los agentes, no las cifras.
    """
    from src.plan import AGENTES

    resultados = registro.ultimos()
    informes: list[str] = []

    for clave, nombre in AGENTES.items():
        piezas = [
            r.resumen
            for r in resultados.values()
            if r.agente == clave and r.ok and r.resumen
        ]
        if piezas:
            informes.append(f"INFORME DE {nombre.upper()}\n" + "\n".join(piezas))
    return informes


def _consolidar_con_supervisor(salidas: list[str], emitir: Emisor = None) -> str | None:
    """Una única llamada al supervisor para la lectura ejecutiva.

    En `Process.hierarchical` el supervisor reenvía el contexto acumulado en cada
    delegación, y eso agota el techo de 12.000 tokens por minuto del plan
    gratuito de Groq antes de terminar. Aquí el supervisor sigue existiendo y
    sigue consolidando, pero lo hace en UNA llamada sobre los tres informes ya
    producidos: mismo rol, una fracción de los tokens.
    """
    from src.agents import llm_chat, llm_potente

    informes = "\n\n".join(s for s in salidas if s)
    if not informes.strip():
        return None

    if emitir:
        emitir({"tipo": "agente_mensaje", "agente": "SUPERVISOR",
                "texto": "Consolidando los tres informes en la lectura ejecutiva..."})

    mensajes = [
        {"role": "system", "content": PROMPT_SUPERVISOR},
        {"role": "user", "content": f"INFORMES DE LOS AGENTES:\n\n{informes}"},
    ]

    # Se intenta primero con el modelo de razonamiento y, si su cuota está
    # agotada, con el pequeño. El límite de tokens por minuto de Groq es POR
    # MODELO, así que el pequeño conserva su bolsa intacta justo cuando el
    # grande acaba de gastarse la suya en el cierre. Sin este segundo intento
    # el supervisor se queda mudo precisamente en las corridas apretadas.
    ultimo: Exception | None = None
    for construir, etiqueta in ((llm_potente, "razonamiento"), (llm_chat, "rápido")):
        try:
            texto = str(construir().call(mensajes)).strip()
            if texto:
                audit.registrar_agente("SUPERVISOR", "consolidacion", texto[:500],
                                       modelo=etiqueta)
                return texto
        except Exception as e:  # noqa: BLE001
            ultimo = e

    _aviso(emitir, f"El supervisor no pudo consolidar ({type(ultimo).__name__ if ultimo else 'sin salida'}). "
                   "El informe sale igual con las cifras deterministas.")
    return None


def _aviso(emitir: Emisor, mensaje: str) -> None:
    if emitir:
        emitir({"tipo": "aviso", "mensaje": mensaje})
    audit.registrar_agente("SUPERVISOR", "aviso", mensaje)


# --------------------------------------------------------------------------- #
# Construcción del crew
# --------------------------------------------------------------------------- #


def construir_crew(fecha_corte: str = FECHA_CORTE) -> Crew:
    facturacion = agente_facturacion()
    cobranzas = agente_cobranzas()
    bi = agente_bi()

    tarea_facturacion = Task(
        description=(
            f"Cierre del ciclo, bloque FACTURACIÓN (fecha de corte {fecha_corte}).\n"
            "Ejecuta EXACTAMENTE estas herramientas, UNA SOLA VEZ cada una y en este orden:\n"
            "  1) resumen_facturacion\n"
            "  2) detectar_servicios_no_facturados\n"
            "  3) validar_clientes_sunat\n"
            "No repitas una herramienta ya ejecutada. No recalcules ni redondees: cita los "
            "montos exactamente como te los devuelve cada herramienta."
        ),
        expected_output=(
            "Máximo 12 líneas en español, en tres bloques: ESCALERA DE FACTURACIÓN, "
            "QUIEBRES / FUGA DE INGRESOS y RIESGO TRIBUTARIO. Cada bloque con su cifra exacta "
            "en formato S/X,XXX.XX, el conteo de registros y una acción recomendada. "
            "Sin tablas de detalle."
        ),
        agent=facturacion,
    )

    tarea_cobranzas = Task(
        description=(
            f"Cierre del ciclo, bloque COBRANZAS Y RECAUDO (fecha de corte {fecha_corte}).\n"
            "Ejecuta EXACTAMENTE estas herramientas, UNA SOLA VEZ cada una y en este orden:\n"
            "  1) conciliar_pagos\n"
            "  2) pagos_no_identificados\n"
            "  3) cartera_vencida\n"
            "Contrasta la tasa de conciliación del algoritmo actual contra la del mejorado y "
            "explica cuánto dinero se reclasifica de 'deuda' a 'cobrado sin aplicar'. "
            "No recalcules ninguna cifra."
        ),
        expected_output=(
            "Máximo 12 líneas en español, en tres bloques: CONCILIACIÓN (tasa antes y después, "
            "y monto reclasificado), PARTIDAS SIN IDENTIFICAR (cantidad y monto) y CARTERA "
            "VENCIDA (total y los cuatro tramos de aging). Cifras textuales de las herramientas."
        ),
        agent=cobranzas,
        context=[tarea_facturacion],
    )

    tarea_bi = Task(
        description=(
            f"Cierre del ciclo, bloque INTELIGENCIA DE NEGOCIO (fecha de corte {fecha_corte}).\n"
            "Ejecuta EXACTAMENTE estas herramientas, UNA SOLA VEZ cada una:\n"
            "  ratio_cobrado_facturado, detectar_anomalias, provision_cobranza_dudosa, "
            "priorizar_recupero, proyeccion_caja.\n"
            "Llama a detectar_anomalias SIN argumentos: necesitas el cuadro completo. "
            "Si filtras por severidad pierdes la mayor parte de los hallazgos. "
            "Prioriza al redactar, no al pedir los datos.\n"
            "Con los bloques previos de Facturación y Cobranzas, determina si los hallazgos "
            "comparten una causa raíz común y cuantifícala en soles."
        ),
        expected_output=(
            "Informe ejecutivo de máximo 25 líneas en español con cuatro secciones: "
            "(1) DIAGNÓSTICO con la causa raíz identificada; (2) HALLAZGOS priorizados por "
            "impacto en soles; (3) PCD y proyección de caja; (4) TOP 5 ACCIONES, cada una con "
            "su responsable (Facturación / Cobranzas / Recaudo / TI / Contabilidad). "
            "Toda cifra citada literalmente de las herramientas."
        ),
        agent=bi,
        context=[tarea_facturacion, tarea_cobranzas],
    )

    comun = dict(
        agents=[facturacion, cobranzas, bi],
        tasks=[tarea_facturacion, tarea_cobranzas, tarea_bi],
        verbose=False,
        # memory=False evita traer Chroma y sus llamadas de red en el import,
        # que es un modo de fallo real en Windows y no aporta nada aquí.
        memory=False,
        cache=False,
        max_rpm=RPM_POTENTE,
        planning=False,
    )

    if PROCESO == "jerarquico":
        return Crew(process=Process.hierarchical, manager_agent=agente_supervisor(), **comun)
    return Crew(process=Process.sequential, **comun)


# --------------------------------------------------------------------------- #
# Puente opcional con el bus de eventos de CrewAI
# --------------------------------------------------------------------------- #


def _enganchar_bus(emitir: Emisor):
    """Añade color al stream con la charla del LLM.

    Todo va envuelto en try/except y los atributos se leen con getattr: los
    nombres de campo del bus de CrewAI no están documentados y cambian entre
    versiones. El stream que el demo NECESITA sale de nuestro propio embudo de
    tools, no de aquí.
    """
    if emitir is None:
        return None
    try:
        from crewai.events import (  # type: ignore[import-not-found]
            AgentExecutionStartedEvent,
            BaseEventListener,
            TaskCompletedEvent,
        )
    except Exception:
        return None

    class _Listener(BaseEventListener):  # type: ignore[misc, valid-type]
        def setup_listeners(self, bus):
            def _handler(tipo):
                def _h(source, event):
                    try:
                        agente = getattr(getattr(event, "agent", None), "role", "supervisor")
                        texto = getattr(event, "task_prompt", None) or getattr(
                            event, "output", ""
                        )
                        emitir({"tipo": tipo, "agente": str(agente),
                                "texto": str(texto)[:300]})
                    except Exception:
                        pass

                return _h

            for evento, tipo in (
                (AgentExecutionStartedEvent, "agente_mensaje"),
                (TaskCompletedEvent, "tarea_fin"),
            ):
                try:
                    bus.on(evento)(_handler(tipo))
                except Exception:
                    pass

    try:
        return _Listener()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Ejecución con red de seguridad
# --------------------------------------------------------------------------- #


def ejecutar_cierre(
    emitir: Emisor = None,
    objetivo: str = OBJETIVO_DEMO,
    fecha_corte: str = FECHA_CORTE,
) -> dict:
    """Corre el cierre con agentes; completa de forma determinista si hace falta."""
    from src.pipeline import ejecutar_plan  # import diferido: evita ciclo

    if not os.getenv("GROQ_API_KEY"):
        _aviso(emitir, "Sin GROQ_API_KEY: modo determinista (mismas cifras, sin narrativa LLM).")
        return ejecutar_plan(emitir=emitir, modo="deterministico",
                             objetivo=objetivo, fecha_corte=fecha_corte)

    registro.limpiar()
    audit.iniciar_corrida(objetivo=objetivo, modo="crew")
    if emitir:
        emitir({"tipo": "corrida_inicio", "objetivo": objetivo, "modo": "crew",
                "fecha_corte": fecha_corte, "pasos": len(PLAN_DE_CIERRE)})

    _enganchar_bus(emitir)
    caja: dict = {}

    def _worker() -> None:
        try:
            crew = construir_crew(fecha_corte)
            salida = crew.kickoff(inputs={"fecha_corte": fecha_corte})
            caja["salida"] = str(salida)
            # Los informes por tarea son lo que consolida el supervisor.
            caja["por_tarea"] = [
                str(t) for t in (getattr(salida, "tasks_output", None) or [])
            ] or [str(salida)]
        except BaseException as e:  # noqa: BLE001 — litellm lanza excepciones raras
            caja["error"] = f"{type(e).__name__}: {e}"

    hilo = threading.Thread(target=_worker, name="crew-sonia", daemon=True)
    hilo.start()
    hilo.join(TIMEOUT_CREW_S)

    colgado = hilo.is_alive()
    fallo = colgado or "error" in caja
    if colgado:
        _aviso(emitir, f"El crew excedió {TIMEOUT_CREW_S}s. Completando de forma determinista.")
    elif "error" in caja:
        _aviso(emitir, f"El crew falló ({caja['error']}). Completando de forma determinista.")

    # Rellenar SOLO lo que falte: el trabajo real de los agentes se conserva.
    ejecutadas = set(registro.ultimos())
    faltantes = [p for p in PLAN_DE_CIERRE if p.tool not in ejecutadas]
    if faltantes:
        if not fallo:
            _aviso(emitir, f"El crew omitió {len(faltantes)} pasos del plan. Completando.")
        ejecutar_pasos(faltantes, emitir)

    modo = "crew" if not fallo and not faltantes else "hibrido"
    resultados = registro.ultimos()

    # El supervisor consolida lo que produjeron los agentes. En modo jerárquico
    # ya consolidó él mismo durante la delegación, así que se usa su salida.
    #
    # Se intenta consolidar TAMBIÉN cuando el crew falló. Es una sola llamada
    # pequeña, y con la cuota de Groq apretada el modo híbrido es el caso
    # frecuente: si no se intentara, el supervisor se quedaría mudo justo en las
    # corridas donde más falta hace explicar qué pasó. Las cifras no dependen
    # de esto, solo la prosa.
    narrativa: str | None = None
    if not fallo and PROCESO == "jerarquico":
        narrativa = caja.get("salida")
    else:
        informes = caja.get("por_tarea") or _informes_desde_resultados()
        narrativa = _consolidar_con_supervisor(informes, emitir)

    reporte = render_reporte(
        resultados, modo=modo, narrativa=narrativa,
        fecha_corte=fecha_corte, objetivo=objetivo,
    )
    audit.cerrar_corrida()
    resumen_auditoria = {k: v for k, v in audit.exportar().items() if k != "entradas"}
    ruta = audit.guardar_json()

    if emitir:
        emitir({"tipo": "corrida_fin", "modo": modo, "auditoria": str(ruta)})

    return {
        "reporte": reporte,
        "modo": modo,
        "objetivo": objetivo,
        "fecha_corte": fecha_corte,
        "narrativa": narrativa,
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
