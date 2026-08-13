"""
SON-IA · Definición de los agentes.

Tres agentes operadores especializados y un supervisor que asigna, controla y
da seguimiento — la arquitectura que pide la ficha del reto.

Asignación de modelo: los cuatro agentes usan por defecto el modelo de
razonamiento, y la razón es contraintuitiva. En el plan gratuito de Groq el
límite de tokens por minuto va **por modelo**, y el modelo pequeño tiene la
MITAD de presupuesto que el grande:

    llama-3.1-8b-instant     6.000 TPM
    llama-3.3-70b-versatile 12.000 TPM

Como cada turno de un agente reenvía todo su bloc de notas, una petición pesa
~2.200 tokens y con 6.000 TPM sólo caben dos o tres por minuto: el modelo
"rápido" agotaba su cuota a mitad del cierre. Medido: con el 8b la corrida
terminaba en modo degradado; con el 70b completa en ~70 s.

Quien tenga plan de pago puede volver a repartir con SONIA_MODELO_RAPIDO.

Los goals repiten la misma instrucción en los tres: las cifras se citan tal como
las devuelve la herramienta, nunca se recalculan. Es redundante a propósito —
es la regla que sostiene el "0% de alucinaciones".
"""

from __future__ import annotations

import logging
import os
import re
import time

from crewai import LLM, Agent

from src.tools.crew_adapters import tools_de

_LOG = logging.getLogger("sonia.agents")

# Modelos verificados como vigentes en producción en Groq.
# Ambos apuntan al 70b por el reparto de TPM explicado arriba; son variables
# distintas para poder separarlos sin tocar código si se sube de plan.
MODELO_RAZONAMIENTO = os.getenv("SONIA_MODELO_POTENTE", "llama-3.3-70b-versatile")
MODELO_RAPIDO = os.getenv("SONIA_MODELO_RAPIDO", "llama-3.3-70b-versatile")

_RE_ESPERA = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)


def _segundos_de_espera(mensaje: str, defecto: float = 20.0) -> float:
    """Extrae del error de Groq cuántos segundos hay que esperar."""
    m = _RE_ESPERA.search(mensaje)
    if not m:
        return defecto
    try:
        return min(float(m.group(1)) + 1.5, 65.0)  # +1.5s de margen
    except ValueError:
        return defecto


class LLMGroq(LLM):
    """LLM de CrewAI saneado para Groq.

    CrewAI 1.15 marca los mensajes con la propiedad ``cache_breakpoint`` (prompt
    caching al estilo Anthropic) y define ``strip_cache_breakpoint()`` para
    quitarla antes de enviarlos... pero **nunca la llama** en la ruta LiteLLM,
    que es la que usa Groq. La API de Groq valida el esquema de forma estricta y
    rechaza la petición entera con:

        'messages.0' : property 'cache_breakpoint' is unsupported

    Verificado en 1.15.0 y en 1.15.15: la función existe y no tiene ni un solo
    llamador en todo el paquete.

    ``_format_messages_for_provider`` es el único punto por el que pasan todos
    los mensajes antes de salir hacia el proveedor, así que se limpia aquí. Si
    CrewAI lo corrige aguas arriba, esta sobrescritura se vuelve inocua.
    """

    def _format_messages_for_provider(self, messages):  # type: ignore[override]
        formateados = super()._format_messages_for_provider(messages)
        for mensaje in formateados:
            if isinstance(mensaje, dict):
                mensaje.pop("cache_breakpoint", None)
        return formateados

    def call(self, *args, **kwargs):  # type: ignore[override]
        """Reintento que respeta la espera que indica Groq.

        El plan gratuito limita por tokens por minuto (6.000 en el modelo rápido,
        12.000 en el de razonamiento) y un cierre completo los roza. El error de
        Groq trae el tiempo exacto de espera ("Please try again in 15.07s"), así
        que se espera eso y se reintenta.

        `num_retries` de LiteLLM no cubre este caso: se comprobó que la corrida
        aborta a los ~18 s sin llegar a esperar.
        """
        ultimo: Exception | None = None
        for intento in range(REINTENTOS):
            try:
                return super().call(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                mensaje = str(e)
                if "rate_limit" not in mensaje and "Rate limit" not in mensaje:
                    raise
                ultimo = e
                if intento == REINTENTOS - 1:
                    break
                espera = _segundos_de_espera(mensaje)
                _LOG.warning(
                    "Groq limitó por tokens/minuto; esperando %.1fs y reintentando "
                    "(intento %d de %d).", espera, intento + 2, REINTENTOS,
                )
                time.sleep(espera)
        raise ultimo  # type: ignore[misc]


#: Reintentos ante error 429. El plan gratuito de Groq limita a 12.000 tokens
#: por minuto en llama-3.3-70b y la delegación jerárquica lo alcanza con
#: facilidad, porque el supervisor reenvía el contexto acumulado en cada vuelta.
#: El propio error indica el tiempo de espera ("try again in 1.6s"), así que
#: LiteLLM reintenta con backoff y la corrida se recupera sola.
REINTENTOS = int(os.getenv("SONIA_REINTENTOS_LLM", "5"))

#: Peticiones por minuto. Espaciarlas deja que la ventana de TPM se recupere.
RPM_RAPIDO = int(os.getenv("SONIA_RPM_RAPIDO", "12"))
RPM_POTENTE = int(os.getenv("SONIA_RPM_POTENTE", "8"))


def _llm(modelo: str, max_tokens: int = 900, temperatura: float = 0.1) -> LLM:
    """LLM de CrewAI apuntando a Groq vía LiteLLM.

    Temperatura baja: aquí no se busca creatividad sino que el agente transcriba
    con fidelidad lo que devolvió la herramienta.
    """
    return LLMGroq(
        model=f"groq/{modelo}",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=temperatura,
        max_tokens=max_tokens,
        num_retries=REINTENTOS,  # se reenvía a LiteLLM vía additional_params
    )


def llm_rapido() -> LLM:
    return _llm(MODELO_RAPIDO, max_tokens=700)


def llm_potente() -> LLM:
    return _llm(MODELO_RAZONAMIENTO, max_tokens=1000)


#: Modelo del chat. Va aparte del de los agentes A PROPÓSITO.
#:
#: El límite de tokens por minuto de Groq es por modelo, así que si el chat
#: comparte modelo con el crew se queda sin cuota justo después de un cierre y
#: la redacción nunca llega: la respuesta cae siempre al camino determinista y
#: el guardarraíl no se puede demostrar en vivo.
#:
#: El prompt del chat es corto, así que el modelo pequeño va sobrado y además
#: tiene su propia bolsa de 6.000 TPM, intacta tras el cierre.
MODELO_CHAT = os.getenv("SONIA_MODELO_CHAT", "llama-3.1-8b-instant")


def llm_chat() -> LLM:
    return _llm(MODELO_CHAT, max_tokens=500)


_REGLA_CIFRAS = (
    "NUNCA calcules, estimes ni redondees cifras por tu cuenta: toda cifra la obtienes "
    "de tus herramientas y la citas EXACTAMENTE como te la devuelven, con su formato "
    "S/X,XXX.XX. Si un dato no está en la salida de una herramienta, di que no está "
    "disponible en lugar de inventarlo."
)


def agente_facturacion() -> Agent:
    return Agent(
        role="Especialista en Aseguramiento de Ingresos y Facturación B2B",
        goal=(
            "Garantizar que todo servicio activo en planta fija y móvil se facture de forma "
            "oportuna y correcta. Operas el momento 1 del ciclo, la asesoría previa a la "
            "emisión: validas los insumos del PxQ, alertas los quiebres ANTES de emitir y "
            "dejas registro auditable de cada tarea. " + _REGLA_CIFRAS
        ),
        backstory=(
            "Llevas años en el ciclo del ingreso de Integratel y aprendiste que la fuga de "
            "ingresos no se ve en el estado de resultados: se esconde en cuentas activas que "
            "nadie facturó y en documentos emitidos a RUC NO HABIDO que terminan en multas "
            "tributarias y en notas de crédito por error operativo. Tu obsesión son la "
            "escalera de facturación y el tiempo de disponibilidad de la factura hacia el "
            "cliente. Desconfías de los formatos: sabes que la información está dispersa "
            "entre plantillas de implantación y facturadores sin trazabilidad."
        ),
        tools=tools_de("AGENTE_FACTURACION"),
        llm=llm_rapido(),
        max_iter=4,
        max_rpm=RPM_RAPIDO,
        allow_delegation=False,  # crítico: si delega, el crew entra en bucle
        verbose=False,
        cache=False,
    )


def agente_cobranzas() -> Agent:
    return Agent(
        role="Analista de Cobranzas y Recaudo B2B",
        goal=(
            "Conciliar lo cobrado contra lo facturado, ejecutar la rebaja automática "
            "post-pago, identificar las partidas bancarias huérfanas y medir la cartera "
            "vencida con aging 1-30 / 31-60 / 61-90 / 90+ días. " + _REGLA_CIFRAS
        ),
        backstory=(
            "Vienes de armar ficheros de rebajas a mano y de perseguir depósitos sin "
            "identificar por correo y teléfono. Sabes que un pago no aplicado es doblemente "
            "caro: infla la cartera y dispara gestión de cobranza contra clientes que YA "
            "pagaron, lo que destruye la relación comercial. Peleas por el tiempo de "
            "identificación de depósitos y por mejorar el algoritmo de aplicación, porque "
            "has visto que la mayoría de las partidas 'perdidas' son en realidad problemas "
            "de formato entre sistemas."
        ),
        tools=tools_de("AGENTE_COBRANZAS"),
        llm=llm_rapido(),
        max_iter=4,
        max_rpm=RPM_RAPIDO,
        allow_delegation=False,
        verbose=False,
        cache=False,
    )


def agente_bi() -> Agent:
    return Agent(
        role="Analista de Inteligencia de Negocio del Ciclo de Ingresos",
        goal=(
            "Convertir los hallazgos de Facturación y Cobranzas en decisiones: ratio "
            "cobrado/facturado, provisión de cobranza dudosa, priorización para la mesa de "
            "aceleración de recupero, adelanto operativo de caja y detección de anomalías. "
            "Cuantificas el impacto en soles y propones la acción concreta. " + _REGLA_CIFRAS
        ),
        backstory=(
            "Traduces datos operativos al lenguaje de Control de Gestión, Contabilidad y "
            "Finanzas. Tu regla de oro: ningún hallazgo vale sin monto en soles, sin "
            "responsable y sin plazo. Tienes ojo para los patrones que delatan fallas de "
            "integración entre sistemas, porque sabes que un mismo error de formato suele "
            "explicar varios síntomas que el negocio vive como problemas separados."
        ),
        tools=tools_de("AGENTE_BI"),
        llm=llm_potente(),
        max_iter=6,
        max_rpm=RPM_POTENTE,
        allow_delegation=False,
        verbose=False,
        cache=False,
    )


def agente_supervisor() -> Agent:
    """El manager del proceso jerárquico.

    No lleva herramientas: CrewAI se lo exige al manager, y además es lo correcto
    conceptualmente — el supervisor asigna y consolida, no opera.
    """
    return Agent(
        role="Supervisor del Ciclo de Ingresos B2B (SON-IA)",
        goal=(
            "Orquestar el cierre del ciclo delegando en los tres especialistas y consolidar "
            "un informe ejecutivo con los hallazgos priorizados por impacto en soles. NO "
            "ejecutas herramientas ni calculas nada: delegas, controlas y consolidas citando "
            "textualmente las cifras que te reportan tus agentes."
        ),
        backstory=(
            "Coordinas Facturación, Cobranzas y Recaudo e Inteligencia de Negocio. Tu "
            "criterio de priorización es siempre el mismo: primero el dinero que ya se "
            "perdió, después el que está en riesgo, y después el que se puede recuperar hoy "
            "con una corrección operativa. Cierras siempre con acciones concretas y con un "
            "responsable por acción, porque un informe sin dueño no mueve un indicador."
        ),
        tools=[],
        llm=llm_potente(),
        max_iter=6,
        max_rpm=RPM_POTENTE,
        allow_delegation=True,  # sólo el supervisor delega
        verbose=False,
    )
