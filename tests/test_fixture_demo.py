"""
Prueba de regresión del dataset del demo.

Estas cifras vivían dentro de `data_loader._verificar_invariantes()` y hacían
que el sistema no arrancara con ningún otro corte: las siete fallaban a la vez.
No son propiedades de los datos, son las de ESTE fixture, así que su sitio es
un test.

Lo que sí se quedó en el cargador son las invariantes estructurales, que valen
para cualquier dataset: clave canónica sin colisiones, ninguna fecha de
vencimiento sin parsear, importes numéricos.

Correr con:  python -m pytest tests/test_fixture_demo.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_loader import DATA_DEMO, _construir  # noqa: E402

#: El corte del demo, escrito en data/corte.txt. Se fija aquí en vez de usar el
#: derivado: una prueba de regresión clava sus entradas o deja de comparar lo
#: mismo cada día que pasa.
CORTE = "2026-08-12"


@pytest.fixture(scope="module")
def d():
    return _construir(DATA_DEMO)


def test_conteo_de_filas(d):
    assert len(d.facturas) == 3364
    assert len(d.pagos) == 3548
    assert len(d.clientes) == 1000
    assert len(d.notas_credito) == 196


def test_totales(d):
    assert d.facturas["total"].sum() == pytest.approx(447964.58, abs=0.01)
    assert d.pagos["monto_pagado"].sum() == pytest.approx(392837.26, abs=0.01)


def test_cuentas_activas(d):
    """1,571, no 1,572.

    CONTEXT.md contaba como cuenta el COD_CUENTA nulo de 2 líneas móviles
    activas. `nunique()` lo excluye, que es lo correcto: sin cuenta no hay
    documento posible que emitir.
    """
    activas = d.planta_unificada.loc[d.planta_unificada["activo"], "cod_cuenta"].nunique()
    assert activas == 1571


def test_las_57_facturas_de_isis(d):
    """El hallazgo que habilita la vista A->B: FECHA_VTO en dos formatos."""
    malas = d.facturas["fecha_vto_malformada"]
    assert int(malas.sum()) == 57
    assert d.facturas.loc[malas, "sistema"].eq("ISIS").all()


def test_conciliacion_canonica(d):
    """canon_doc sube el match de pagos de 97.91% a 99.77%."""
    c = d.diagnostico["conciliacion"]
    assert c["tasa_exacta"] == pytest.approx(97.91, abs=0.01)
    assert c["tasa_canonica"] == pytest.approx(99.77, abs=0.01)
    assert c["recuperados"] == 66


def test_corte_fijado_en_el_sidecar(d):
    """El demo lleva su corte escrito para que las cifras no se muevan solas."""
    assert d.fecha_corte == CORTE
    assert d.diagnostico["corte"]["procedencia"] == "fijado en corte.txt"


def test_cartera_vencida_al_corte(d):
    """La cifra que lidera el dashboard."""
    vencidas, _ = d.cartera(fecha_corte=CORTE)
    assert vencidas["saldo"].sum() == pytest.approx(47819.06, abs=0.01)
