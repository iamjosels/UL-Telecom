"""
SON-IA · Cómo tiene que sonar todo lo que escribe un modelo.

Vive en su propio módulo porque lo usan dos prompts que no pueden importarse
entre sí: el del supervisor (`src/crew.py`, que arrastra CrewAI entero) y el del
redactor del chat (`src/router.py`, que tiene que seguir siendo ligero). Tenerlo
duplicado garantizaba que un día cambiara en un sitio y no en el otro.

El problema que resuelve no es de estilo. Sin esta guía el modelo produce el
registro reconocible de un asistente de IA: guiones largos como conector,
"es importante destacar", "solución robusta". Las cifras siguen siendo
correctas, pero el texto delata el proyecto como generado, y en una evaluación
eso pesa tanto como el contenido.
"""

VOZ_ANALISTA = (
    "CÓMO ESCRIBIR. Hablas como un analista de facturación con años en el puesto, no como un "
    "consultor ni como un asistente.\n"
    "PROHIBIDO: el guion largo como conector, escribe punto y seguido. Relleno del tipo 'lo que "
    "representa', 'es importante destacar', 'cabe mencionar', 'en resumen', 'esto indica que'. "
    "Fórmulas de venta: 'robusto', 'potenciar', 'aprovechar', 'sinergia', 'sin fisuras', "
    "'solución integral'. Preámbulos del tipo 'se debe proceder a'. Repetir una frase que ya "
    "escribiste: si no tienes nada más que decir, termina.\n"
    "OBLIGATORIO: frases cortas. Vocabulario del oficio: cartera vencida, conciliación, "
    "provisión, recupero, partidas sin aplicar, correlativo, aging. En las acciones, verbo en "
    "infinitivo y al grano ('Normalizar el correlativo ISIS contra AMDOCS'), nunca 'se debe "
    "proceder a normalizar'.\n"
    # El ejemplo NO lleva huecos numéricos, y es deliberado.
    #
    # Primero tuvo cifras reales ("57 facturas y 66 pagos") y el modelo copiaba
    # la frase entera: correcta con el dataset del demo, falsa con cualquier
    # otro. Después se pusieron como N y M, y entonces el modelo rellenaba los
    # huecos adivinando: escribió "67 pagos" tres corridas seguidas donde los
    # datos decían 66. Un ejemplo con espacios para números es una invitación a
    # inventarlos, así que el ejemplo enseña solo el ritmo de la frase.
    "Ejemplo del ritmo que se busca, sin cifras a propósito: 'Dos sistemas de facturación no "
    "cruzan. De ahí salen los hallazgos más caros.'\n"
    "CIFRAS: no escribas ningún número que no venga en los datos que te pasan. Si una cifra no "
    "está, no la menciones. Nunca la deduzcas ni la aproximes.\n"
    # La regla vivía solo en el prompt del chat, y el supervisor escribió
    # "recaudar la cartera vencida de S/4,353.03", que es el tramo de 90+ con el
    # nombre del total. Mismo término para dos cifras distintas es justo lo que
    # rompe la credibilidad de todo el informe.
    "NOMBRES: 'cartera vencida' a secas es SIEMPRE el total vencido con saldo tras "
    "conciliación. Si hablas de un tramo, nómbralo entero: 'cartera vencida a más de 90 días'. "
    "Nunca llames 'cartera vencida' a un tramo, ni uses dos nombres distintos para el mismo "
    "hallazgo: usa el nombre exacto con el que te llega."
)


# --------------------------------------------------------------------------- #
# El filtro, porque el prompt no basta
# --------------------------------------------------------------------------- #
#
# Con la guía de arriba el modelo obedece casi siempre, pero "casi" no sirve:
# en la corrida de prueba seguía escribiendo "lo que representa el 26.9%" con
# la fórmula expresamente prohibida en el system prompt. Un prompt es una
# petición; esto es la garantía.
#
# Solo se tocan conectores y muletillas. Nada que altere una cifra ni el
# sentido de una frase.

import re

_MULETILLAS: tuple[tuple[re.Pattern[str], str], ...] = (
    # "..., lo que representa el 26.9%" -> "..., el 26.9%"
    (re.compile(r",?\s*lo que (?:representa|significa|equivale a|supone)\s+", re.IGNORECASE), ", "),
    (re.compile(r"\b(?:es importante destacar|cabe destacar|cabe mencionar|cabe señalar)\s+que\s+", re.IGNORECASE), ""),
    (re.compile(r"\b(?:en resumen|en conclusión|en síntesis)[,:]?\s+", re.IGNORECASE), ""),
    (re.compile(r"\besto indica que\s+", re.IGNORECASE), ""),
    (re.compile(r"\bse debe(?:rá)? proceder a\s+", re.IGNORECASE), ""),
    # El guion largo como conector pasa a punto y seguido.
    (re.compile(r"\s+—\s+"), ". "),
)


def limpiar_relleno(texto: str) -> str:
    """Quita las muletillas de asistente que el prompt pidió evitar.

    Conservador a propósito: si una sustitución dejara la frase rara, es mejor
    no hacerla. Por eso no se tocan adjetivos sueltos ('robusto') sino solo
    construcciones enteras que se pueden borrar sin perder información.
    """
    if not texto:
        return texto
    for patron, reemplazo in _MULETILLAS:
        texto = patron.sub(reemplazo, texto)

    texto = re.sub(r"[ \t]{2,}", " ", texto)
    texto = re.sub(r"\s+([.,;:])", r"\1", texto)

    # Quitar la muletilla deja la frase empezando en minúscula ("la cartera
    # vencida asciende a..."), y eso se lee peor que la muletilla que quitamos.
    # Se recapitaliza al inicio del texto, de cada línea y tras punto.
    texto = re.sub(
        r"(^|[.!?]\s+|\n\s*[-·]?\s*)([a-záéíóúñü])",
        lambda m: m.group(1) + m.group(2).upper(),
        texto,
    )
    return texto.strip()
