"""
SON-IA · Lo que hay que saber de Groq antes de llamarlo.

Este módulo existe separado de `src.agents` por una razón medida: importar
`src.agents` arrastra CrewAI y tarda diecinueve segundos. El healthcheck de la
API y la decisión de "¿hay LLM utilizable?" no pueden pagar eso, así que aquí
va sólo lo que no necesita CrewAI para nada — la clave, el sondeo del catálogo
y la traducción de los fallos de Groq al castellano.

Las tres piezas responden a la misma avería. Una clave caducada en el entorno
de producción se manifestaba como dos avisos rojos seguidos en el tablero:

    La clave de Groq no es válida. El cierre se completó sin LLM...
    El supervisor no pudo consolidar (BadRequestError)...

Parecen dos problemas y son uno. Peor: el segundo no dice cuál. Groq responde
400 `invalid_api_key` a una clave mala — no 401 — y LiteLLM lo envuelve en
`BadRequestError`, que se lee como "la petición estaba mal formada" cuando la
petición era perfecta. De ahí las tres funciones: sanear la clave antes de
usarla, comprobarla ANTES de arrancar (sin gastar un token) y, si aun así algo
falla en marcha, contarlo por lo que es y no por el nombre de la clase.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

#: Marcador de `.env.example`. Copiar el fichero y no rellenarlo deja aquí algo
#: con pinta de clave que no lo es, y el cierre se va por el camino del LLM
#: para estrellarse contra Groq tres pasos después.
_MARCADOR = "gsk_tu_clave_aqui"

#: Segundos para el sondeo. Es un GET al catálogo, sin tokens: si no contesta
#: en este tiempo el problema no es la clave, es la red, y entonces no se
#: bloquea nada.
TIMEOUT_SONDEO_S = float(os.getenv("SONIA_TIMEOUT_SONDEO", "5"))

_CATALOGO = "https://api.groq.com/openai/v1/models"

#: Hay que identificarse. Delante de la API de Groq hay un Cloudflare que
#: responde 403 (`error code: 1010`) al User-Agent que urllib pone por defecto,
#: y ese 403 con la clave BUENA se lee igual que una clave rechazada. Medido:
#: mismo GET, misma clave, 403 sin esta cabecera y 200 con ella.
_CABECERA_AGENTE = "SON-IA/1.0 (+cierre del ciclo de ingresos)"

#: Veredictos ya emitidos, indexados por clave y modelos. Se sondea una vez por
#: proceso, no en cada corrida ni en cada pregunta del chat. Va indexado por la
#: clave a propósito: si se corrige y se reinicia el servicio, el sondeo se
#: repite solo.
_SONDEOS: dict[tuple[str, tuple[str, ...]], tuple[bool, str]] = {}


def clave_groq() -> str | None:
    """La clave saneada, o None si no hay ninguna utilizable.

    Se limpia antes de usarla porque las dos formas habituales de romperla son
    de copiar y pegar: el panel de Render se queda con el salto de línea final
    si se pega con Enter, y `GROQ_API_KEY="gsk_..."` en un `.env` mete las
    comillas dentro del valor. Groq responde lo mismo en ambos casos que ante
    una clave revocada, así que el aviso acaba acusando a una clave que estaba
    bien escrita en el sitio equivocado.
    """
    bruta = (os.getenv("GROQ_API_KEY") or "").strip().strip("\"'").strip()
    if not bruta or bruta == _MARCADOR:
        return None
    return bruta


def sondear_groq(modelos: set[str]) -> tuple[bool, str, str]:
    """¿Se puede usar Groq ahora mismo? Devuelve (utilizable, motivo, detalle).

    El sondeo distingue lo que los mensajes de LiteLLM confunden: 401 es la
    clave, y un modelo que no está en el catálogo es el catálogo — que en Groq
    se mueve, los llama-3.x desaparecieron de un día para otro. Cualquier otra
    cosa NO bloquea: ante un 429, un proxy o un DNS caído se deja correr el
    cierre, que para eso tiene red de seguridad. Un sondeo sirve para evitar
    trabajo inútil, no para prohibirlo.

    El motivo es la frase que se puede leer en pantalla y va vacío cuando se
    puede usar; el detalle es la instrucción para arreglarlo, que interesa en
    la auditoría y estorba en el tablero.
    """
    clave = clave_groq()
    if clave is None:
        return (
            False,
            "No hay una GROQ_API_KEY utilizable.",
            "Definir GROQ_API_KEY sin comillas ni espacios alrededor.",
        )

    indice = (clave, tuple(sorted(modelos)))
    if (cacheado := _SONDEOS.get(indice)) is not None:
        return cacheado

    veredicto = _consultar_catalogo(clave, modelos)
    _SONDEOS[indice] = veredicto
    return veredicto


def _consultar_catalogo(clave: str, modelos: set[str]) -> tuple[bool, str, str]:
    peticion = urllib.request.Request(
        _CATALOGO,
        headers={"Authorization": f"Bearer {clave}", "User-Agent": _CABECERA_AGENTE},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SONDEO_S) as respuesta:
            catalogo = {m.get("id") for m in json.load(respuesta).get("data", [])}
    except urllib.error.HTTPError as e:
        # Sólo se acusa a la clave cuando Groq dice que es la clave. El resto de
        # 4xx puede ser el Cloudflare de delante, y mandar a modo determinista
        # una corrida que habría funcionado es peor que el fallo que se intenta
        # evitar: en la duda, se deja correr.
        cuerpo = _leer(e)
        if e.code == 401 or "invalid_api_key" in cuerpo:
            return (
                False,
                "La clave de Groq no es válida.",
                f"Groq la rechaza (HTTP {e.code}): hay que regenerarla y volver a ponerla "
                f"en el entorno. Respuesta: {cuerpo[:200]}",
            )
        return True, "", ""
    except Exception:  # noqa: BLE001 — sin red, DNS, proxy, Groq caído
        return True, "", ""

    if faltan := sorted(modelos - catalogo):
        return (
            False,
            f"Groq ya no sirve {', '.join(faltan)}.",
            "Apuntar SONIA_MODELO_POTENTE / _RAPIDO / _CHAT a modelos del catálogo vigente.",
        )
    return True, "", ""


#: Se clasifica por el cuerpo del error de Groq, que es estable, y no por el
#: tipo de excepción de LiteLLM, que no lo es: la misma avería llega como
#: BadRequestError, AuthenticationError o APIError según la versión.
_MOTIVOS = (
    (r"invalid.?api.?key|\bauthentication", "la clave de Groq no es válida"),
    (r"rate.?limit|\b429\b", "Groq agotó la cuota por minuto"),
    (r"model_not_found|does not exist", "el modelo ya no está en el catálogo de Groq"),
    (r"None or empty", "el modelo devolvió una respuesta vacía"),
    (r"timeout|timed out", "Groq no respondió a tiempo"),
    (r"context.{0,20}length|too large", "el informe no cabe en la ventana del modelo"),
)


def _leer(e: urllib.error.HTTPError) -> str:
    """El cuerpo del error, si se deja leer. Nunca revienta por esto."""
    try:
        return e.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def motivo_humano(e: BaseException | None) -> str:
    """Traduce el fallo del LLM a algo que se pueda leer en el tablero.

    El nombre de la clase de LiteLLM no le dice nada a quien está mirando, y en
    el caso más frecuente además engaña. Si no se reconoce el error se devuelve
    el nombre de la clase entre paréntesis: es feo, pero es honesto, y significa
    que hay un caso nuevo que clasificar aquí. Se deja genérico porque esto
    también traduce fallos que no son del modelo — el volcado completo queda en
    la auditoría.
    """
    if e is None:
        return "el modelo devolvió una respuesta vacía"

    texto = f"{type(e).__name__}: {e}"
    for patron, motivo in _MOTIVOS:
        if re.search(patron, texto, re.IGNORECASE):
            return motivo
    return f"fallo inesperado ({type(e).__name__})"


def es_fallo_de_clave(e: BaseException | None) -> bool:
    """Si la clave no sirve, reintentar con otro modelo no arregla nada."""
    return motivo_humano(e) == "la clave de Groq no es válida"
