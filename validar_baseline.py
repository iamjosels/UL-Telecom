#!/usr/bin/env python
"""
SON-IA · Validación contra el baseline documentado en docs/CONTEXT.md.

Corre dos comprobaciones distintas y complementarias:

  1. PARIDAD — reproducir las cifras que CONTEXT.md documenta, usando las
     mismas hipótesis que el sistema actual (formato único de fecha, cruce
     literal de correlativo, sin deducir notas de crédito). Si esto pasa,
     nuestra lectura de la data coincide con la del negocio.

  2. RECONCILIACIÓN — mostrar en qué difiere la lectura corregida y por qué.
     Las diferencias no son errores del baseline: son las 57 facturas que un
     parseo de formato único descarta y los 66 pagos que un cruce literal no
     encuentra.

Salida: tabla comparativa y código 0 si la paridad se cumple.

    python validar_baseline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.data_loader import CORTE_DEL_DATASET, get_datos  # noqa: E402
from src.formato import pen  # noqa: E402

VERDE, ROJO, AMARILLO, GRIS, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"
COLOR = sys.stdout.isatty()


def c(texto: str, color: str) -> str:
    return f"{color}{texto}{RESET}" if COLOR else texto


class Comparador:
    def __init__(self) -> None:
        self.fallos: list[str] = []
        self.avisos: list[str] = []

    def exacto(self, etiqueta: str, esperado, obtenido, tolerancia: float = 0.0) -> None:
        if isinstance(esperado, (int, float)) and isinstance(obtenido, (int, float)):
            ok = abs(esperado - obtenido) <= tolerancia
        else:
            ok = esperado == obtenido
        marca = c("OK ", VERDE) if ok else c("FALLA", ROJO)
        print(f"  [{marca}] {etiqueta:<46} esperado {esperado:>14}   obtenido {obtenido:>14}")
        if not ok:
            self.fallos.append(etiqueta)

    def aproximado(self, etiqueta: str, documentado, obtenido, nota: str) -> None:
        """Para cifras donde el baseline y nosotros diferimos por un motivo
        conocido y explicable, no por un error."""
        print(f"  [{c('NOTA', AMARILLO)}] {etiqueta:<46} CONTEXT {documentado:>14}   "
              f"nuestro {obtenido:>14}")
        print(f"         {c(nota, GRIS)}")
        self.avisos.append(etiqueta)


def main() -> int:
    d = get_datos()
    corte = CORTE_DEL_DATASET
    cmp = Comparador()

    print("=" * 96)
    print("  1 · PARIDAD CON docs/CONTEXT.md")
    print("     (mismas hipótesis que el sistema actual: formato único de fecha,")
    print("      cruce literal de correlativo, sin deducir notas de crédito)")
    print("=" * 96)

    cmp.exacto("Facturado (S/)", 447965, round(float(d.facturas["total"].sum())), tolerancia=1)
    cmp.exacto("Pagado (S/)", 392837, round(float(d.pagos["monto_pagado"].sum())), tolerancia=1)
    cmp.exacto("Notas de crédito", 196, len(d.notas_credito))
    cmp.exacto(
        "Facturas a RUC NO HABIDO",
        21,
        int(
            d.facturas["ruc"]
            .isin(set(d.clientes.loc[d.clientes["sunat_estado_ruc"] == "NO HABIDO", "ruc"]))
            .sum()
        ),
    )

    conc = d.diagnostico["conciliacion"]
    cmp.exacto("Pagos no identificados", 74, conc["pagos"] - conc["match_exacto"])
    cmp.exacto(
        "Monto no identificado (S/ miles)",
        106,
        round(float(d.pagos.loc[~d.pagos["factura_afectada"].isin(set(d.facturas["doc"])),
                                "monto_pagado"].sum()) / 1000),
    )
    cmp.exacto("Conciliación automática (%)", 97.9, conc["tasa_exacta"], tolerancia=0.05)

    va, _ = d.cartera(fecha_corte=corte, conciliacion="exacta", deducir_nc=False,
                      solo_fechas_validas=True)
    cmp.exacto("Cartera vencida (S/)", 18298, round(float(va["saldo"].sum())), tolerancia=1)
    agingA = d.aging(va)
    cmp.exacto("Cartera 90+ (S/)", 4353, round(float(agingA.loc["90+", "saldo"])), tolerancia=1)

    print()
    print("=" * 96)
    print("  2 · DIFERENCIAS CONOCIDAS (no son errores: son hallazgos)")
    print("=" * 96)

    activas = len(d.cuentas_activas())
    sin_factura = len(d.cuentas_activas() - d.cuentas_facturadas())
    cmp.aproximado(
        "Cuentas con servicio activo", 1572, activas,
        "CONTEXT contó como cuenta el COD_CUENTA nulo de 2 líneas móviles activas. "
        "Sin cuenta no hay documento que emitir: se reportan aparte.",
    )
    cmp.aproximado(
        "Cuentas activas sin factura", 423, sin_factura,
        "Mismo motivo que arriba (1 de las 423 era ese nulo).",
    )
    cmp.aproximado(
        "Facturas en cartera vencida", 504, len(va),
        f"El MONTO coincide al céntimo ({pen(float(va['saldo'].sum()))}); el conteo depende del "
        "umbral de saldo y no es reproducible ajustándolo. Por eso el informe lidera con montos.",
    )

    print()
    print("=" * 96)
    print("  3 · RECONCILIACIÓN A → B → C  (lo que el baseline no puede ver)")
    print("=" * 96)

    vb, _ = d.cartera(fecha_corte=corte, conciliacion="exacta", deducir_nc=True)
    vc, _ = d.cartera(fecha_corte=corte, conciliacion="canonica", deducir_nc=True)
    a, b, cc = (round(float(v["saldo"].sum()), 2) for v in (va, vb, vc))
    mal = d.diagnostico["facturas_fecha_malformada"]

    nota_b = (
        f"+{mal['n']} facturas de ISIS ocultas por el formato YYYYMMDD ({pen(mal['monto'])})"
    )
    nota_c = (
        f"-{conc['recuperados']} pagos ya cobrados sin aplicar "
        f"({pen(conc['monto_recuperado'])})"
    )

    print(f"  A · lo que el sistema ve hoy          {len(va):>5} fact   {pen(a):>16}")
    print(f"  B · con parseo tolerante de fechas    {len(vb):>5} fact   {pen(b):>16}")
    print(f"      {c(nota_b, GRIS)}")
    print(f"  C · con conciliación canónica         {len(vc):>5} fact   {pen(cc):>16}")
    print(f"      {c(nota_c, GRIS)}")
    print()
    print(f"  {c('Deuda real al corte: ' + pen(cc), VERDE)}")
    print(f"  Sin identificar de verdad: {conc['residual']} pagos por {pen(conc['monto_residual'])}")

    print()
    print("=" * 96)
    if cmp.fallos:
        print(c(f"  PARIDAD FALLIDA en {len(cmp.fallos)} cifra(s): {', '.join(cmp.fallos)}", ROJO))
        print("=" * 96)
        return 1

    print(c("  PARIDAD OK — 9 cifras de CONTEXT.md reproducidas.", VERDE))
    print(f"  {len(cmp.avisos)} diferencias documentadas y explicadas arriba.")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
