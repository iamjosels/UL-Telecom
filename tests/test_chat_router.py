"""
Pruebas del enrutado del chat, sin LLM.

Todas corren por el camino determinista (`llm=None`) a propósito: es el que
tiene que aguantar solo, y es el único que se puede afirmar en un test. Lo que
el modelo aporta encima —resolver una elipsis o elegir mejor la herramienta—
se prueba a mano contra Groq, porque depende de un servicio de terceros.

Lo que se fija aquí es la conducta que se rompió en producción: un saludo
devolvía la escalera de facturación entera, porque el router estaba construido
para aterrizar SIEMPRE en una herramienta del catálogo.

Correr con:  python -m pytest tests/test_chat_router.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.router import clasificar_por_reglas, responder  # noqa: E402


# --------------------------------------------------------------------------- #
# Lo que no es una pregunta sobre los datos
# --------------------------------------------------------------------------- #


def test_saludo_no_consulta_datos():
    r = responder("Hola")
    assert r["tool"] == ""
    assert r["clase"] == "saludo"
    assert r["metricas"] == {}
    assert r["sugerencias"], "un saludo sin salida propone algo"


def test_saludo_con_pregunta_detras_si_consulta():
    """«hola, ¿cuánto tenemos por cobrar?» es una pregunta, no un saludo.

    Es el caso que obliga a que la rama social vaya DESPUÉS de las reglas de
    palabras clave y no antes.
    """
    r = responder("hola, ¿cuánto tenemos por cobrar?")
    assert r["tool"] == "cartera_vencida"
    assert r["clase"] is None


def test_capacidades_y_cortesia():
    assert responder("¿qué puedes hacer?")["clase"] == "capacidades"
    assert responder("gracias")["clase"] == "cortesia"


def test_fuera_de_dominio_lo_dice():
    """Antes esto devolvía `resumen_facturacion` con confianza 0.2.

    Responder otra cosa con aplomo es peor que no responder: quien pregunta no
    tiene forma de saber que le contestaron a algo que no preguntó.
    """
    r = responder("¿cuál es la capital de Perú?")
    assert r["tool"] == ""
    assert r["clase"] == "no_entendida"


def test_reglas_devuelven_none_cuando_no_reconocen():
    assert clasificar_por_reglas("cuéntame un chiste") is None
    assert clasificar_por_reglas("¿a quién le cobro primero?") is not None


# --------------------------------------------------------------------------- #
# Seguimiento
# --------------------------------------------------------------------------- #


def test_seguimiento_hereda_la_herramienta_anterior():
    """«¿y el tramo 31-60?» no dice de qué habla; el turno anterior sí."""
    previo = responder("¿Cuánto tenemos por cobrar a más de 90 días?")
    assert previo["args"] == {"tramo": "90+"}

    ctx = {"pregunta": "¿Cuánto tenemos por cobrar a más de 90 días?",
           "tool": previo["tool"], "args": previo["args"]}
    r = responder("¿y el tramo 31-60?", contexto=ctx)

    assert r["tool"] == "cartera_vencida"
    assert r["via"] == "seguimiento"
    assert r["args"]["tramo"] == "31-60", "el tramo nuevo pisa al heredado"


def test_seguimiento_sin_contexto_no_inventa():
    """La misma pregunta suelta no puede resolverse, y se dice."""
    r = responder("¿y el tramo 31-60?")
    assert r["clase"] == "no_entendida"


def test_no_hereda_argumentos_de_otra_herramienta():
    """El turno anterior pudo usar otra tool; colar su argumento la rompería."""
    ctx = {"pregunta": "¿qué cuentas no se facturan?",
           "tool": "detectar_servicios_no_facturados",
           "args": {"incluir_suspendidos": True}}
    r = responder("¿y eso?", contexto=ctx)
    assert r["tool"] == "detectar_servicios_no_facturados"
    assert set(r["args"]) <= {"incluir_suspendidos", "fecha_corte"}


# --------------------------------------------------------------------------- #
# Los dos guardarraíles siguen en pie
# --------------------------------------------------------------------------- #


def test_supuesto_no_soportado_sigue_marcandose():
    r = responder("Proyéctame la cartera vencida a diciembre con 10% de mora")
    assert r["supuesto_ignorado"]
    assert r["redactado_por_llm"] is False


def test_tramo_invalido_no_devuelve_el_volcado():
    """'all' significa 'no filtres', y antes salía «ERROR: tramo 'all' inválido»."""
    r = responder("dame la cartera del tramo all")
    assert r["ok"] is True
    assert "ERROR" not in r["respuesta"]
