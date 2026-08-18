"""
SON-IA · Enrutado de preguntas en lenguaje natural hacia las tools.

Tres etapas, en este orden y con esta separación de responsabilidades:

  1. CLASIFICAR — de la pregunta se deriva un nombre de tool y sus argumentos,
     siempre validados contra una whitelist cerrada. Puede hacerlo el LLM con
     salida estructurada; si no hay API key, si falla o si devuelve un nombre
     inventado, cae a reglas de palabras clave.
  2. EJECUTAR — Python corre la tool y produce las cifras.
  3. REDACTAR — el LLM sólo pone en prosa el resumen que ya trae los números.

Y un guardarraíl al final: se extraen los números de la redacción del modelo y,
si alguno no aparece en el resumen ni en las métricas, se descarta la redacción
y se devuelve el texto determinista. Eso convierte el "0% de alucinaciones" en
un invariante que se puede demostrar en vivo haciendo una pregunta capciosa.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from src.contracts import ResultadoTool, ahora
from src.tools.registro import catalogo_texto, ejecutar
from src.tools.registro import _ESPECS as ESPECS  # whitelist viva
from src.voz import VOZ_ANALISTA, limpiar_relleno

AGENTE = "AGENTE_CHAT"


class Intencion(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)
    confianza: float = 0.0
    via: str = "keywords"


# --------------------------------------------------------------------------- #
# Reglas de palabras clave (funcionan sin API key)
# --------------------------------------------------------------------------- #

#: (peso, patrón, tool, args). Gana el peso más alto que coincida.
REGLAS: list[tuple[int, str, str, dict]] = [
    (4, r"(\+\s*90|m[áa]s de 90|mayor(es)? a 90|sobre 90|noventa)", "cartera_vencida",
     {"tramo": "90+"}),
    (3, r"(cartera|vencid|aging|por cobrar|deuda|cxc|cuentas por cobrar|morosidad)",
     "cartera_vencida", {}),
    (4, r"((activ\w+|servicio\w*|cuenta\w*)[^.]{0,30}(no|sin)[^.]{0,20}factur|fuga|"
        r"no se (est[áa]n? )?factur|sin facturar)",
     "detectar_servicios_no_facturados", {}),
    (4, r"(no habido|sunat|riesgo (fiscal|tributari)|multa|habido)", "validar_clientes_sunat", {}),
    (4, r"((pago|dep[óo]sito|partida|abono)\w*[^.]{0,30}(no identificad|sin identificar|"
        r"hu[ée]rfan|sin aplicar|no aplicad))",
     "pagos_no_identificados", {}),
    (3, r"(concilia|rebaja|aplicaci[óo]n|cruce|match|partidas bancarias)", "conciliar_pagos", {}),
    (4, r"(provisi[óo]n|pcd|cobranza dudosa|incobrable|deterioro)",
     "provision_cobranza_dudosa", {}),
    (4, r"(prioriza|recupero|a qui[ée]n (le )?cobr|mesa de acelera|mayores deudores|"
        r"top deudor|primero)",
     "priorizar_recupero", {}),
    (4, r"(proyecci|caja|flujo|cash|cu[áa]nto (voy|vamos) a cobrar|pr[óo]xim\w+ mes)",
     "proyeccion_caja", {}),
    (4, r"(anomal|raro|inconsistenc|error(es)?|d[óo]lar|usd|moneda|sobrepag|duplicad)",
     "detectar_anomalias", {}),
    (3, r"(ratio|cobrado.{0,15}facturado|efectividad|periodo medio|dso|30 d[íi]as)",
     "ratio_cobrado_facturado", {}),
    (2, r"(factur|emiti|escalera|ciclo|cu[áa]nto (se )?factur)", "resumen_facturacion", {}),
]

RE_RUC = re.compile(r"\b(\d{10,11})\b")
RE_TRAMO = re.compile(r"\b(1-30|31-60|61-90|90\+)\b")

#: Fecha explícita y completa. A propósito NO acepta un mes suelto: ante "a
#: diciembre" el modelo se inventa el año, y un corte inventado da una
#: respuesta que parece correcta y es de otra cartera.
RE_FECHA_EN_TEXTO = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}")

#: Argumentos que cambian el SIGNIFICADO de la pregunta, no su presentación.
#: El modelo solo puede fijarlos si el usuario los pidió con estas palabras.
ARGS_CON_PERMISO: dict[str, re.Pattern[str]] = {
    "fecha_corte": RE_FECHA_EN_TEXTO,
    "incluir_suspendidos": re.compile(r"suspendid|de baja|cortad", re.IGNORECASE),
    "conciliacion": re.compile(r"concilia|correlativ|can[óo]nic|literal", re.IGNORECASE),
    "severidad_minima": re.compile(r"cr[íi]tic|grave|severidad|solo lo (m[áa]s )?urgente", re.IGNORECASE),
    "solo_recuperables": re.compile(r"recuperabl|que s[íi] cruzan|accionabl", re.IGNORECASE),
}


def _limpiar_args(tool: str, args: dict, pregunta: str) -> dict:
    """Deja pasar solo los argumentos que el modelo tiene derecho a fijar.

    Dos reglas, las dos aprendidas viendo respuestas malas de verdad:

    1. Los vacíos se descartan. El modelo rellena por inercia los huecos que ve
       (`top: ""`, `ruc: null`) y un vacío nunca significa nada.

    2. Los argumentos que cambian el significado de la pregunta necesitan que
       el usuario los haya pedido. Se vio a un modelo responder "¿a quién le
       cobro primero?" inventándose el corte 2023-07-31, y contestar "¿qué
       cuentas activas no se facturan?" activando `incluir_suspendidos`, que
       deja de responder lo que se preguntó. Las cifras seguían siendo reales;
       eran de otra pregunta. Eso es peor que un error, porque parece correcto.

    El `top` o el `ruc` no entran aquí: cambian el detalle de la respuesta, no
    lo que se está preguntando.
    """
    validos = set(ESPECS[tool].args_schema.model_fields)
    limpios: dict = {}

    for clave, valor in args.items():
        if clave not in validos:
            continue
        if valor is None or str(valor).strip() == "":
            continue
        permiso = ARGS_CON_PERMISO.get(clave)
        if permiso is not None and not permiso.search(pregunta):
            continue
        limpios[clave] = valor

    return limpios


def clasificar_por_reglas(pregunta: str) -> Intencion | None:
    """La tool que piden las palabras de la pregunta, o None si ninguna encaja.

    Devuelve None a propósito. Antes caía a `resumen_facturacion` con confianza
    0.2, y eso convertía "hola" y "¿cuál es la capital de Perú?" en un informe
    de facturación presentado como si fuera la respuesta. Contestar otra cosa
    con aplomo es peor que decir que no se entendió: quien pregunta no tiene
    forma de saber que le respondieron a otra cosa.
    """
    texto = pregunta.lower()
    mejor: tuple[str, dict] | None = None
    peso_max = 0

    for peso, patron, tool, args in REGLAS:
        if peso > peso_max and re.search(patron, texto):
            mejor, peso_max = (tool, dict(args)), peso

    if mejor is None:
        return None

    tool, args = mejor
    if (m := RE_RUC.search(pregunta)) and "ruc" in ESPECS[tool].args_schema.model_fields:
        args.setdefault("ruc", m.group(1))
    if (m := RE_TRAMO.search(pregunta)) and "tramo" in ESPECS[tool].args_schema.model_fields:
        args["tramo"] = m.group(1)

    return Intencion(tool=tool, args=args, confianza=min(1.0, peso_max / 4))


# --------------------------------------------------------------------------- #
# Lo que no es una pregunta sobre los datos
# --------------------------------------------------------------------------- #
#
# Un jurado lo primero que escribe es "hola", y hasta ahora eso devolvía la
# escalera de facturación entera. No era un fallo del modelo -- el modelo
# redactaba bien -- sino que el router estaba construido para aterrizar SIEMPRE
# en una tool del catálogo, así que un saludo se resolvía como la pregunta más
# cercana que hubiera.
#
# Esto se resuelve antes de tocar los datos y sin LLM. Es la misma razón de
# siempre: un prompt es una petición y aquí hace falta una garantía. Además una
# respuesta a "hola" que tarda dos segundos en llegar de Groq se lee peor que
# una instantánea.

#: Preguntas que se ofrecen cuando hay que sugerir algo. Las tres las resuelven
#: las REGLAS de arriba, sin depender de que haya LLM: lo que se ofrece se
#: puede cumplir siempre, también en modo seguro.
PREGUNTAS_EJEMPLO: tuple[str, ...] = (
    "¿Cuánto tenemos por cobrar a más de 90 días?",
    "¿Qué cuentas activas no se están facturando?",
    "¿A quién le cobro primero?",
)

#: Saludo a secas. Anclado a los dos extremos: "hola" es un saludo, pero
#: "hola, ¿cuánto llevamos cobrado?" es una pregunta con saludo delante, y esa
#: la contestan las reglas.
RE_SALUDO = re.compile(
    r"^[\s¡¿]*(hola|holi|buenas|buen(?:os|as)\s+(?:d[íi]as|tardes|noches)|hey|hi|"
    r"hello|qu[ée]\s+tal|saludos)[\s!¡.,?¿]*$",
    re.IGNORECASE,
)

#: Cierre de conversación: agradecimiento, conformidad o despedida.
RE_CORTESIA = re.compile(
    r"^[\s¡¿]*(?:(?:muchas|mil)\s+)?(gracias|ok|okey|okay|vale|perfecto|genial|"
    r"entendido|listo|de acuerdo|ad[íi]os|chau|hasta luego|nos vemos|bye)"
    r"[\s!¡.,?¿]*$",
    re.IGNORECASE,
)

#: "¿Qué puedes hacer?" y sus variantes. Esta NO va anclada: la pregunta por
#: las capacidades aparece dentro de frases más largas.
RE_CAPACIDADES = re.compile(
    r"(qu[ée]\s+(?:me\s+)?(?:puedes|sabes|haces)|"
    r"qu[ée]\s+(?:te\s+)?puedo\s+(?:preguntar|pedir|consultar)|"
    r"para\s+qu[ée]\s+sirves|qui[ée]n\s+eres|qu[ée]\s+eres|c[óo]mo\s+funcionas|"
    r"^[\s¿¡]*(?:ayuda|help|men[úu])[\s!.?¿¡]*$)",
    re.IGNORECASE,
)


def _lista_ejemplos() -> str:
    return " ".join(f"«{p}»" for p in PREGUNTAS_EJEMPLO)


def charla(pregunta: str) -> tuple[str, str] | None:
    """Lo que se contesta sin tocar los datos. Devuelve (clase, texto) o None.

    Sólo entra cuando ninguna regla de palabras clave reconoció la pregunta, así
    que un saludo con pregunta detrás sigue yendo a su herramienta.
    """
    if clasificar_por_reglas(pregunta) is not None:
        return None

    if RE_SALUDO.search(pregunta):
        return "saludo", (
            "Buenas. Soy SON-IA: respondo sobre el ciclo del ingreso de "
            "Integratel — facturación, cobranzas y recaudo — con las cifras del "
            f"cierre, no con estimaciones. Prueba con {_lista_ejemplos()}."
        )

    if RE_CAPACIDADES.search(pregunta):
        return "capacidades", (
            "Contesto sobre tres bloques del ciclo: facturación (escalera del "
            "mes, cuentas activas sin facturar, RUC no habidos), cobranzas y "
            "recaudo (conciliación pago-factura, partidas sin aplicar, cartera "
            "vencida por tramos) e inteligencia de negocio (ratio "
            "cobrado/facturado, provisión de cobranza dudosa, prioridad de "
            "recupero, proyección de caja y anomalías). Elijo la herramienta y "
            "redacto, pero la cifra la calcula Python y queda registrada. "
            f"Por ejemplo: {_lista_ejemplos()}."
        )

    if RE_CORTESIA.search(pregunta):
        return "cortesia", (
            "A la orden. Si quieres seguir tirando del hilo, "
            f"prueba con {_lista_ejemplos()}."
        )

    return None


# --------------------------------------------------------------------------- #
# Clasificación asistida por LLM (con whitelist dura)
# --------------------------------------------------------------------------- #

PROMPT_ROUTER = (
    "Eres un router de herramientas. Devuelves SOLO un JSON válido con esta forma exacta:\n"
    '{"tool": "<nombre exacto del catálogo>", "args": {}}\n'
    "Prohibido inventar nombres de herramientas y prohibido calcular cifras.\n"
    'Si la pregunta NO es sobre facturación, cobranzas, recaudo ni cartera, devuelve '
    '{"tool": null}. Es una respuesta válida y preferible a forzar una herramienta que '
    "no responde lo que se preguntó.\n"
    "Si la pregunta continúa la anterior (\"¿y a 90 días?\", \"¿y ese cliente?\"), "
    "resuélvela sobre el CONTEXTO que se te da.\n\nCATÁLOGO:\n"
)

#: Pregunta que se apoya en la anterior en vez de sostenerse sola: empieza por
#: "y", o es tan corta que no puede llevar sujeto.
RE_ELIPSIS = re.compile(r"^[\s¡¿]*y\b", re.IGNORECASE)


def _es_seguimiento(pregunta: str) -> bool:
    return bool(RE_ELIPSIS.search(pregunta)) or len(pregunta.split()) <= 4


def clasificar(pregunta: str, llm=None, contexto: dict | None = None) -> Intencion | None:
    """Clasifica la pregunta. El LLM propone; la whitelist dispone.

    `contexto` es el `{"pregunta": ..., "tool": ..., "args": {...}}` del turno
    anterior. Sirve para lo que una conversación real hace todo el rato: "¿y a
    90 días?" no dice sobre qué, y sin el turno anterior no hay forma de saberlo.

    Devuelve None cuando no se reconoce la pregunta. Ese None es el que permite
    contestar "no te he entendido" en vez de inventar una respuesta correcta a
    otra pregunta.
    """
    previo = (contexto or {}).get("tool")
    previo = previo if previo in ESPECS else None
    respaldo = clasificar_por_reglas(pregunta)

    # Sin LLM, la elipsis se resuelve heredando la herramienta anterior. Es lo
    # único honesto que se puede hacer con "¿y a 90 días?" sin un modelo, y
    # sigue siendo mejor que responder otra cosa: la interfaz marca que es un
    # seguimiento, así que se ve sobre qué se contestó.
    if llm is None:
        if respaldo is None and previo and _es_seguimiento(pregunta):
            return Intencion(tool=previo, args=_args_heredados(previo, contexto, pregunta),
                             confianza=0.5, via="seguimiento")
        return respaldo

    mensajes = [{"role": "system", "content": PROMPT_ROUTER + catalogo_texto()}]
    if contexto and previo:
        mensajes.append({
            "role": "user",
            "content": (
                f"CONTEXTO (turno anterior): pregunta «{contexto.get('pregunta', '')}», "
                f"herramienta {previo}, argumentos {json.dumps(contexto.get('args') or {})}"
            ),
        })
    mensajes.append({"role": "user", "content": pregunta})

    try:
        crudo = llm.call(mensajes)
        bloque = re.search(r"\{.*\}", str(crudo), re.S)
        if bloque:
            datos = json.loads(bloque.group(0))
            tool = datos.get("tool")
            if tool in ESPECS:  # whitelist: nada fuera del catálogo se ejecuta
                # Los permisos de argumento se miran contra las dos preguntas
                # cuando esto es un seguimiento: en "¿y solo los críticos?" la
                # palabra que da permiso está en el turno de antes.
                fuente = pregunta
                if previo and _es_seguimiento(pregunta):
                    fuente = f"{contexto.get('pregunta', '')} {pregunta}"
                args = _limpiar_args(tool, datos.get("args") or {}, fuente)
                via = "seguimiento" if tool == previo and _es_seguimiento(pregunta) else "llm"
                return Intencion(tool=tool, args=args, confianza=0.9, via=via)
            # `null` es una respuesta legítima del router: la pregunta no es de
            # este dominio. Solo se acepta si las reglas tampoco vieron nada.
            if tool is None and respaldo is None:
                return None
    except Exception:
        pass

    if respaldo is None and previo and _es_seguimiento(pregunta):
        return Intencion(tool=previo, args=_args_heredados(previo, contexto, pregunta),
                         confianza=0.5, via="seguimiento")
    return respaldo


def _args_heredados(tool: str, contexto: dict | None, pregunta: str) -> dict:
    """Los argumentos del turno anterior, más lo que traiga el nuevo.

    Se heredan solo los que la herramienta acepta: el turno anterior pudo usar
    otra, y colar un argumento ajeno la haría fallar.
    """
    validos = set(ESPECS[tool].args_schema.model_fields)
    args = {k: v for k, v in ((contexto or {}).get("args") or {}).items() if k in validos}
    if (m := RE_RUC.search(pregunta)) and "ruc" in validos:
        args["ruc"] = m.group(1)
    if (m := RE_TRAMO.search(pregunta)) and "tramo" in validos:
        args["tramo"] = m.group(1)
    return args


# --------------------------------------------------------------------------- #
# Guardarraíl numérico
# --------------------------------------------------------------------------- #

RE_NUMERO = re.compile(r"\d[\d,\.]*")


def _numeros(texto: str) -> set[str]:
    """Números normalizados: sin separadores de miles y sin ceros finales."""
    salida = set()
    for bruto in RE_NUMERO.findall(texto):
        limpio = bruto.replace(",", "").rstrip(".")
        if not limpio:
            continue
        try:
            valor = float(limpio)
        except ValueError:
            continue
        salida.add(f"{valor:.2f}".rstrip("0").rstrip("."))
    return salida


#: Margen que se acepta como redondeo. 26.86 -> "27" pasa; 66 -> "67" no.
TOLERANCIA_REDONDEO = 0.5


def numeros_fuera_de(redaccion: str, fuente: str) -> set[str]:
    """Números que aparecen en la redacción y no salen de su fuente.

    Lo usan los dos sitios donde escribe un modelo: el chat y la lectura
    ejecutiva del supervisor.

    Sobre la tolerancia. Antes se dejaba pasar cualquier entero de 0 a 100, con
    la idea de no marcar porcentajes redondeados ni referencias a tramos. Era
    demasiado ancha: el supervisor escribió "67 pagos no se aplican" donde los
    datos decían 66 y el guardarraíl lo dejó pasar por ser un número pequeño.
    Un conteo equivocado es exactamente lo que este control existe para atrapar.

    Ahora un número solo se perdona si ALGUNA cifra de la fuente redondea a él.
    26.86 justifica un "27"; nada justifica un "67" cuando la fuente dice 66.
    """
    permitidos = _numeros(fuente)
    sospechosos = _numeros(redaccion) - permitidos
    if not sospechosos:
        return set()

    valores_fuente = [float(n) for n in permitidos]
    inventados = set()
    for n in sospechosos:
        valor = float(n)
        if any(abs(valor - v) <= TOLERANCIA_REDONDEO for v in valores_fuente):
            continue  # es el redondeo de una cifra que sí está
        inventados.add(n)
    return inventados


def numeros_inventados(redaccion: str, res: ResultadoTool) -> set[str]:
    """Igual, para la salida de una herramienta concreta."""
    return numeros_fuera_de(
        redaccion, res.resumen + " " + json.dumps(res.metricas, default=str)
    )


# --------------------------------------------------------------------------
# El otro guardarraíl: supuestos que ninguna herramienta acepta
# --------------------------------------------------------------------------
#
# `numeros_inventados` valida cifras, no premisas, y esa rendija se puede
# cruzar: ante "proyéctame la cartera con 10% de mora" el modelo respondió una
# vez "Con un 10% de mora, la cobranza a 30 días sería S/34,918.63". Las tres
# cifras eran reales -- son la proyección base -- pero la frase se las atribuye
# a un supuesto que nadie aplicó. Números verificados, premisa falsa.
#
# Ninguna herramienta recibe una tasa, un escenario ni un horizonte futuro: los
# únicos argumentos son fecha_corte, top y unos cuantos booleanos. Así que un
# porcentaje o un condicional en la pregunta es, por construcción, algo que el
# sistema no puede honrar.

# Cada patrón captura la frase entera, no la palabra suelta: la interfaz cita
# el fragmento literal, y «10% de mora» es una respuesta mientras que «10%» no.
RE_SUPUESTOS: tuple[re.Pattern[str], ...] = (
    # "10% de mora", "12,5 % de incobrabilidad", "20 por ciento de mora"
    re.compile(r"\b\d{1,3}(?:[.,]\d+)?\s*(?:%|por\s*ciento)(?:\s+de\s+\w+)?", re.IGNORECASE),
    re.compile(r"\bqu[ée]\s+pasar[íi]a(?:\s+si)?", re.IGNORECASE),
    re.compile(r"\b(?:asumiendo|suponiendo|supongamos|asume)(?:\s+que)?", re.IGNORECASE),
    re.compile(
        r"\bsi\s+(?:la|el|los|las)\s+\w+\s+\w*(?:sub|baj|aument|cae|caer|mejor|empeor)\w*",
        re.IGNORECASE,
    ),
    # "escenario pesimista", "el peor escenario"
    re.compile(r"\b(?:peor|mejor)\s+escenario|\bescenario\s+\w+", re.IGNORECASE),
    # Horizonte con nombre. proyeccion_caja llega a 30/60/90 días desde el corte
    # y nada más: "a diciembre" o "a fin de año" caen fuera. Se pide con "a" o
    # "para", no con "en" -- "facturas emitidas en julio" es un filtro histórico
    # legítimo, no una proyección.
    re.compile(
        r"\b(?:a|para|hasta)\s+(?:fin(?:es)?\s+de\s+(?:a[ñn]o|mes)|enero|febrero|marzo|abril|"
        r"mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\b",
        re.IGNORECASE,
    ),
)


def supuesto_no_soportado(pregunta: str) -> str | None:
    """El fragmento de la pregunta que pide un supuesto que no se puede aplicar.

    Devuelve el texto literal para poder citarlo, no un booleano: decir "no
    acepto «10% de mora»" es una respuesta; decir "hay un supuesto" no lo es.
    """
    for patron in RE_SUPUESTOS:
        m = patron.search(pregunta)
        if m:
            return m.group(0).strip()
    return None


PROMPT_REDACTOR = (
    "Eres un analista del ciclo de ingresos B2B de una telco peruana. Respondes en español, en "
    "2 a 4 frases.\n"
    "REGLA ABSOLUTA: usa ÚNICAMENTE las cifras del BLOQUE DE DATOS. Está prohibido calcular, "
    "estimar, redondear distinto, sumar o añadir números que no estén ahí. Si el dato no "
    "aparece, di que no está disponible.\n"
    "REGLA 2: cada cifra conserva el periodo que trae el bloque. Está prohibido reetiquetarla "
    "con otra fecha u horizonte. Un saldo de hoy no es 'la cartera a diciembre'.\n"
    # La regla de nombres vive en VOZ_ANALISTA, que la comparten los dos
    # prompts. Tenerla aquí también solo garantizaba que un día divergieran.
    "\n" + VOZ_ANALISTA
)


def _sin_datos(texto: str, clase: str) -> dict:
    """Respuesta que no ejecutó ninguna herramienta.

    Mantiene la forma del resto para que la interfaz no necesite otro camino:
    lo que cambia es que `tool` va vacía y `clase` dice por qué.
    """
    return {
        "respuesta": texto,
        "tool": "",
        "args": {},
        "via": "sin_tool",
        "confianza": 0.0,
        "clase": clase,
        "sugerencias": list(PREGUNTAS_EJEMPLO),
        "redactado_por_llm": False,
        "redaccion_descartada": False,
        "supuesto_ignorado": None,
        "metricas": {},
        "trazas": [],
        "alertas": [],
        "filas_detalle": 0,
        "ok": True,
        "ts": ahora(),
    }


def responder(pregunta: str, llm=None, contexto: dict | None = None) -> dict:
    """Responde una pregunta en lenguaje natural sin ceder el cálculo al LLM."""
    # Saludo, cortesía o "¿qué sabes hacer?": se contesta y no se toca un dato.
    if (social := charla(pregunta)) is not None:
        clase, texto = social
        return _sin_datos(texto, clase)

    intencion = clasificar(pregunta, llm, contexto)

    # Ni las reglas ni el modelo reconocieron la pregunta. Decirlo es la
    # respuesta; elegir "la herramienta más cercana" era contestar con aplomo a
    # una pregunta que nadie hizo.
    if intencion is None:
        return _sin_datos(
            "No sé responder eso con los datos del cierre. Puedo con facturación, "
            "cobranzas y recaudo: por ejemplo " + _lista_ejemplos() + ".",
            "no_entendida",
        )

    res = ejecutar(intencion.tool, origen=AGENTE, **intencion.args)

    # La herramienta reventó. Su resumen en ese caso es "ERROR ejecutando
    # <tool>: <excepción>", que es exactamente el volcado que el resto del chat
    # se esfuerza en no enseñar.
    if not res.ok:
        salida = _sin_datos(
            f"No pude calcular {ESPECS[intencion.tool].etiqueta.lower()}: la herramienta "
            "falló con los datos cargados. Las demás siguen disponibles.",
            "fallo_tool",
        )
        salida.update({"tool": intencion.tool, "args": intencion.args,
                       "via": intencion.via, "ok": False, "ts": res.ts})
        return salida

    texto = res.resumen
    redactado_por_llm = False
    descartada = False
    supuesto = supuesto_no_soportado(pregunta)

    # Ante un supuesto que no se puede aplicar, el modelo no redacta y punto.
    #
    # Se intentó primero por prompt ("está prohibido reetiquetar una cifra con
    # otra fecha") y no aguanta: en una corrida obedecía y en la siguiente
    # escribía "la cartera a diciembre es S/53,806.19", que es el saldo de hoy
    # con una etiqueta temporal falsa. Un prompt es una petición, no una
    # garantía, y aquí hace falta una garantía. Se devuelve el resumen
    # determinista y la interfaz explica por qué.
    if llm is not None and res.ok and supuesto is None:
        try:
            propuesta = str(
                llm.call(
                    [
                        {"role": "system", "content": PROMPT_REDACTOR},
                        {
                            "role": "user",
                            "content": (
                                f"PREGUNTA: {pregunta}\n\n"
                                f"BLOQUE DE DATOS (única fuente permitida):\n{res.resumen}\n\n"
                                f"MÉTRICAS: {json.dumps(res.metricas, ensure_ascii=False, default=str)}"
                            ),
                        },
                    ]
                )
            ).strip()
            if propuesta and not numeros_inventados(propuesta, res):
                texto, redactado_por_llm = limpiar_relleno(propuesta), True
            elif propuesta:
                descartada = True  # el guardarraíl saltó: se devuelve el determinista
        except Exception:
            pass

    return {
        "respuesta": texto,
        "tool": intencion.tool,
        "args": intencion.args,
        "via": intencion.via,
        "confianza": intencion.confianza,
        "clase": None,
        "sugerencias": [],
        "redactado_por_llm": redactado_por_llm,
        "redaccion_descartada": descartada,
        "supuesto_ignorado": supuesto,
        "metricas": res.metricas,
        "trazas": res.trazas,
        "alertas": [
            {"severidad": a.severidad, "titulo": a.titulo, "impacto_pen": a.impacto_pen}
            for a in res.alertas
        ],
        "filas_detalle": res.data_filas_totales,
        "ok": res.ok,
        "ts": res.ts,
    }
