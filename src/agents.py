"""
SON-IA · Definición de los agentes.

Tres agentes operadores especializados y un supervisor que asigna, controla y
da seguimiento — la arquitectura que pide la ficha del reto.

Asignación de modelo. En el plan gratuito de Groq el límite de tokens por
minuto va **por modelo**, así que repartir agentes entre dos modelos no es un
lujo: son dos bolsas de cuota en lugar de una.

    openai/gpt-oss-120b   8.000 TPM   supervisor y BI
    openai/gpt-oss-20b    8.000 TPM   facturación, cobranzas y chat

Como cada turno de un agente reenvía todo su bloc de notas, una petición pesa
~2.200 tokens, y los gpt-oss suman encima sus tokens de razonamiento. Con 8.000
TPM el supervisor agota la bolsa del 120b antes de cerrar los once pasos: la
corrida acaba en modo híbrido, con la red de seguridad completando lo que falte.
Eso no es un fallo del cierre — es el escenario que la red existe para cubrir, y
las cifras salen idénticas a la corrida determinista.

Quien tenga plan de pago puede repartir distinto con SONIA_MODELO_RAPIDO.

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

from src.proveedor import clave_groq, sondear_groq
from src.tools import registro
from src.tools.crew_adapters import tools_de

_LOG = logging.getLogger("sonia.agents")

# Modelos verificados como vigentes en producción en Groq (2026-08-17).
#
# Los llama-3.x salieron del catálogo: la API responde `model_not_found` para
# llama-3.3-70b-versatile y llama-3.1-8b-instant. Los sustituyen los gpt-oss,
# que son los que quedan con tool-calling utilizable. El qwen3.6-27b se
# descartó porque escupe su bloque <think> dentro del contenido, y eso acaba
# en el informe.
#
# Reparto: el 120b para quien razona (supervisor y BI) y el 20b para los dos
# especialistas. No es solo por capacidad — el límite de TPM es POR MODELO, así
# que separarlos son dos bolsas en vez de una.
MODELO_RAZONAMIENTO = os.getenv("SONIA_MODELO_POTENTE", "openai/gpt-oss-120b")
MODELO_RAPIDO = os.getenv("SONIA_MODELO_RAPIDO", "openai/gpt-oss-20b")

_RE_ESPERA = re.compile(r"try again in ([\d.]+)s", re.IGNORECASE)


def estado_de_groq() -> tuple[bool, str, str]:
    """¿Se puede usar Groq con los modelos que este módulo tiene configurados?

    El sondeo vive en `src.proveedor` porque quien más lo necesita — la API, al
    decidir si hay LLM — no puede pagar los diecinueve segundos que cuesta
    importar CrewAI. Aquí sólo se le dicen los tres modelos que hay que buscar
    en el catálogo.
    """
    return sondear_groq({MODELO_RAZONAMIENTO, MODELO_RAPIDO, MODELO_CHAT})


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
            # Aquí se va el tiempo de un cierre con agentes, así que este es el
            # punto que decide cuánto tarda en obedecer un "detener". Se mira
            # también dentro del bucle: si la cancelación llega mientras se
            # espera un reintento por límite de tokens, no se vuelve a llamar.
            if registro.cancelacion_pedida():
                raise registro.CorridaCancelada("cierre detenido por el usuario")
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


#: Reintentos ante error 429. El plan gratuito de Groq da 8.000 tokens por
#: minuto en gpt-oss-120b (eran 12.000 con el 70b, así que ahora se llega antes)
#: y la delegación jerárquica lo alcanza con facilidad, porque el supervisor
#: reenvía el contexto acumulado en cada vuelta. Los gpt-oss además gastan
#: tokens de razonamiento que también cuentan.
#: El propio error indica el tiempo de espera ("try again in 1.6s"), así que
#: LiteLLM reintenta con backoff y la corrida se recupera sola. Cuando ni así
#: llega, la red de seguridad completa los pasos y el cierre termina igual.
REINTENTOS = int(os.getenv("SONIA_REINTENTOS_LLM", "5"))

#: Peticiones por minuto. Espaciarlas deja que la ventana de TPM se recupere.
RPM_RAPIDO = int(os.getenv("SONIA_RPM_RAPIDO", "12"))
RPM_POTENTE = int(os.getenv("SONIA_RPM_POTENTE", "8"))


def _llm(
    modelo: str,
    max_tokens: int = 900,
    temperatura: float = 0.1,
    razonamiento: str | None = None,
) -> LLM:
    """LLM de CrewAI apuntando a Groq vía LiteLLM.

    Temperatura baja: aquí no se busca creatividad sino que el agente transcriba
    con fidelidad lo que devolvió la herramienta.

    `razonamiento` es el `reasoning_effort` de los gpt-oss. Importa más de lo
    que parece: el razonamiento se descuenta del MISMO `max_tokens` que la
    respuesta, así que un modelo que piensa de más se queda sin presupuesto y
    devuelve `content` vacío — que es como CrewAI y el router ven "no hubo
    respuesta". Medido con el mismo prompt: 395 tokens de salida por defecto
    contra 114 en 'low', con el contenido igual de bueno.
    """
    extra = {"reasoning_effort": razonamiento} if razonamiento else {}
    return LLMGroq(
        model=f"groq/{modelo}",
        api_key=clave_groq(),
        temperature=temperatura,
        max_tokens=max_tokens,
        num_retries=REINTENTOS,  # se reenvía a LiteLLM vía additional_params
        **extra,
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
#: El prompt del chat es corto, así que el modelo pequeño va sobrado.
#:
#: Matiz desde que se cambió de familia: el chat comparte el 20b con los dos
#: especialistas, no tiene bolsa propia como cuando era el 8b. Lo que lo salva
#: es que quien agota la cuota en un cierre es el supervisor, y ese va en el
#: 120b. Comprobado el 2026-08-17: preguntando por el chat inmediatamente
#: después de un cierre, la redacción del LLM llega y pasa el guardarraíl.
MODELO_CHAT = os.getenv("SONIA_MODELO_CHAT", "openai/gpt-oss-20b")


def llm_chat() -> LLM:
    """El modelo del chat, con el razonamiento bajado a propósito.

    El chat hace DOS llamadas por pregunta — enrutar y redactar — y las dos son
    de transcribir, no de deducir: la tool se elige de un catálogo cerrado y la
    redacción no puede añadir ni una cifra. Pensar de más ahí no mejora la
    respuesta y cuesta el triple de tokens, que en el plan gratuito se traduce
    en 429 encadenados y en una pregunta que tarda medio minuto en contestar
    delante de quien mira.

    Los agentes del cierre NO llevan esto: ahí el modelo sí decide qué
    herramienta usar y en qué orden, y ese razonamiento se está pagando por algo.
    """
    return _llm(MODELO_CHAT, max_tokens=500, razonamiento="low")


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
