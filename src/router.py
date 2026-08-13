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

from src.contracts import ResultadoTool
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


def clasificar_por_reglas(pregunta: str) -> Intencion:
    texto = pregunta.lower()
    mejor: tuple[str, dict] | None = None
    peso_max = 0

    for peso, patron, tool, args in REGLAS:
        if peso > peso_max and re.search(patron, texto):
            mejor, peso_max = (tool, dict(args)), peso

    if mejor is None:
        return Intencion(tool="resumen_facturacion", args={}, confianza=0.2)

    tool, args = mejor
    if (m := RE_RUC.search(pregunta)) and "ruc" in ESPECS[tool].args_schema.model_fields:
        args.setdefault("ruc", m.group(1))
    if (m := RE_TRAMO.search(pregunta)) and "tramo" in ESPECS[tool].args_schema.model_fields:
        args["tramo"] = m.group(1)

    return Intencion(tool=tool, args=args, confianza=min(1.0, peso_max / 4))


# --------------------------------------------------------------------------- #
# Clasificación asistida por LLM (con whitelist dura)
# --------------------------------------------------------------------------- #

PROMPT_ROUTER = (
    "Eres un router de herramientas. Devuelves SOLO un JSON válido con esta forma exacta:\n"
    '{"tool": "<nombre exacto del catálogo>", "args": {}}\n'
    "Prohibido inventar nombres de herramientas y prohibido calcular cifras.\n"
    "Si ninguna encaja, elige la más cercana del catálogo.\n\nCATÁLOGO:\n"
)


def clasificar(pregunta: str, llm=None) -> Intencion:
    """Clasifica la pregunta. El LLM propone; la whitelist dispone."""
    respaldo = clasificar_por_reglas(pregunta)
    if llm is None:
        return respaldo

    try:
        crudo = llm.call(
            [
                {"role": "system", "content": PROMPT_ROUTER + catalogo_texto()},
                {"role": "user", "content": pregunta},
            ]
        )
        bloque = re.search(r"\{.*\}", str(crudo), re.S)
        if not bloque:
            return respaldo
        datos = json.loads(bloque.group(0))
        tool = datos.get("tool")
        if tool in ESPECS:  # whitelist: nada fuera del catálogo se ejecuta
            args = _limpiar_args(tool, datos.get("args") or {}, pregunta)
            return Intencion(tool=tool, args=args, confianza=0.9, via="llm")
    except Exception:
        pass
    return respaldo


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


def responder(pregunta: str, llm=None) -> dict:
    """Responde una pregunta en lenguaje natural sin ceder el cálculo al LLM."""
    intencion = clasificar(pregunta, llm)
    res = ejecutar(intencion.tool, origen=AGENTE, **intencion.args)

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
