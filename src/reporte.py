"""
SON-IA · Render del reporte consolidado de cierre de ciclo.

Este módulo es idéntico para los dos caminos de ejecución: consume el registro
de resultados (`registro.ultimos()`) y arma el informe. Si el crew corrió, su
narrativa se añade como comentario ejecutivo; si no corrió, el informe sale
completo igual. **Ninguna cifra del reporte proviene del LLM.**

La sección central es la reconciliación A→B→C, que es el hallazgo del demo:
cuánta deuda no ve el sistema actual, y cuánta de la que ve ya está cobrada.
"""

from __future__ import annotations

from src.audit import audit
from src.contracts import ResultadoTool
from src.data_loader import CORTE_DEL_DATASET, get_datos, normalizar_fecha_corte
from src.formato import encabezado, num, pct, pen
from src.plan import AGENTES, PLAN_DE_CIERRE
from src.tools import registro

ANCHO = 78


def _tres_vistas(fecha_corte: str = CORTE_DEL_DATASET) -> tuple[str, dict]:
    """Reconciliación A→B→C de la cartera vencida.

    A = lo que ve el sistema hoy (parseo ingenuo de fecha, sin deducir notas de
        crédito, cruce literal de correlativo).
    B = con el parseo tolerante de fechas: aparecen las facturas de ISIS.
    C = además con el cruce canónico: se descuenta lo ya cobrado sin aplicar.
    """
    fecha_corte = normalizar_fecha_corte(fecha_corte)
    d = get_datos()

    va, _ = d.cartera(
        fecha_corte=fecha_corte,
        conciliacion="exacta",
        deducir_nc=False,
        solo_fechas_validas=True,
    )
    vb, _ = d.cartera(fecha_corte=fecha_corte, conciliacion="exacta", deducir_nc=True)
    vc, _ = d.cartera(fecha_corte=fecha_corte, conciliacion="canonica", deducir_nc=True)

    a, b, c = (round(v["saldo"].sum(), 2) for v in (va, vb, vc))
    mal = d.diagnostico["facturas_fecha_malformada"]
    conc = d.diagnostico["conciliacion"]

    lineas = [
        encabezado(f"RECONCILIACIÓN DE CARTERA · tres lecturas del mismo dato ({fecha_corte})"),
        "",
        f"  A · Lo que el sistema ve hoy        {len(va):>5} facturas   {pen(a):>16}",
        "      (fecha en formato único, cruce literal de correlativo)",
        "",
        f"  B · Con parseo tolerante de fechas  {len(vb):>5} facturas   {pen(b):>16}",
        f"      + {mal['n']} facturas del sistema {'/'.join(mal['sistemas'])} que traen FECHA_VTO en",
        f"        formato YYYYMMDD y hoy desaparecen del reporte  ({pen(mal['monto'])})",
        "",
        f"  C · Con conciliación canónica       {len(vc):>5} facturas   {pen(c):>16}",
        f"      − {conc['recuperados']} pagos por {pen(conc['monto_recuperado'])} que YA estaban cobrados",
        "        pero no aplicados por un cero inicial en el correlativo",
        "",
        "  " + "-" * (ANCHO - 4),
        f"  Deuda real al corte: {pen(c)}   (no {pen(a)}, ni {pen(b)})",
        f"  Sin identificar de verdad: {conc['residual']} pagos por {pen(conc['monto_residual'])}",
    ]
    return "\n".join(lineas), {
        "vista_a_pen": a,
        "vista_b_pen": b,
        "vista_c_pen": c,
        "facturas_ocultas": mal["n"],
        "monto_oculto_pen": mal["monto"],
        "pagos_recuperados": conc["recuperados"],
        "monto_recuperado_pen": conc["monto_recuperado"],
    }


def _seccion_agente(agente: str, resultados: dict[str, ResultadoTool]) -> str:
    """Bloque de un agente con el resumen textual de cada tool que ejecutó."""
    pasos = [p for p in PLAN_DE_CIERRE if p.agente == agente]
    lineas = [encabezado(f"AGENTE DE {AGENTES.get(agente, agente).upper()}", caracter="-")]

    for paso in pasos:
        res = resultados.get(paso.tool)
        if res is None:
            lineas.append(f"\n  [{paso.id}] {paso.titulo}\n      (no ejecutado)")
            continue
        marca = "" if res.ok else "  [ERROR]"
        momento = f"   ·   momento {paso.momento}" if paso.momento else ""
        lineas.append(f"\n  [{paso.id}] {paso.titulo}{marca}{momento}")
        for parrafo in _envolver(res.resumen, ANCHO - 6):
            lineas.append(f"      {parrafo}")
    return "\n".join(lineas)


def _envolver(texto: str, ancho: int) -> list[str]:
    """Word wrap simple, sin dependencias."""
    salida: list[str] = []
    for bloque in texto.split("\n"):
        linea = ""
        for palabra in bloque.split():
            if len(linea) + len(palabra) + 1 > ancho:
                salida.append(linea)
                linea = palabra
            else:
                linea = f"{linea} {palabra}".strip()
        salida.append(linea)
    return salida


def _seccion_alertas() -> str:
    """Alertas de toda la corrida, por severidad y luego por dinero."""
    alertas = registro.alertas_ordenadas()
    if not alertas:
        return ""
    lineas = [encabezado("ALERTAS ACCIONABLES (por severidad e impacto en soles)")]
    for i, a in enumerate(alertas, 1):
        impacto = f"   {pen(a.impacto_pen)}" if a.impacto_pen else ""
        lineas.append(f"\n  {i:>2}. [{a.severidad.upper():<8}] {a.titulo}{impacto}")
        for parrafo in _envolver(a.detalle, ANCHO - 8):
            lineas.append(f"        {parrafo}")
        if a.accion:
            lineas.append(f"        -> {a.accion}"
                          + (f"  ({a.responsable})" if a.responsable else ""))
    return "\n".join(lineas)


def kpis_planos(resultados: dict[str, ResultadoTool] | None = None) -> dict:
    """Métricas de todas las tools en un solo diccionario, para GET /kpis."""
    resultados = resultados if resultados is not None else registro.ultimos()
    planos: dict = {}
    for nombre, res in resultados.items():
        for clave, valor in res.metricas.items():
            planos[f"{nombre}.{clave}"] = valor
    return planos


def kpis_dashboard(fecha_corte: str = CORTE_DEL_DATASET) -> dict:
    """Las cifras de portada del dashboard, calculadas siempre en directo."""
    # Resuelto aquí porque este valor SALE hacia el front en la respuesta.
    fecha_corte = normalizar_fecha_corte(fecha_corte)
    d = get_datos()
    _, vistas = _tres_vistas(fecha_corte)
    vc, porv = d.cartera(fecha_corte=fecha_corte, conciliacion="canonica", deducir_nc=True)
    aging = d.aging(vc)

    facturado = round(d.facturas["total"].sum(), 2)
    cobrado = round(d.pagos["monto_pagado"].sum(), 2)
    ctas_activas = d.cuentas_activas()
    sin_factura = ctas_activas - d.cuentas_facturadas()

    facturado_cuenta = d.facturas.groupby("cod_cuenta")["total"].sum()
    docs_cuenta = d.facturas.groupby("cod_cuenta")["doc"].count()
    ticket = float((facturado_cuenta / docs_cuenta).median())

    return {
        "fecha_corte": fecha_corte,
        "facturado_pen": facturado,
        "cobrado_pen": cobrado,
        "ratio_cobrado_facturado": round(100 * cobrado / facturado, 2),
        "cartera_vencida_pen": round(float(vc["saldo"].sum()), 2),
        "por_vencer_pen": round(float(porv["saldo"].sum()), 2),
        "provision_pcd_pen": round(float(aging["provision"].sum()), 2),
        "aging": {
            t: {"facturas": int(aging.loc[t, "facturas"]), "saldo": float(aging.loc[t, "saldo"])}
            for t in aging.index
        },
        "cuentas_activas": len(ctas_activas),
        "cuentas_sin_factura": len(sin_factura),
        "pct_fuga": round(100 * len(sin_factura) / len(ctas_activas), 2),
        "fuga_estimada_mes_pen": round(len(sin_factura) * ticket, 2),
        "tasa_conciliacion_actual": d.diagnostico["conciliacion"]["tasa_exacta"],
        "tasa_conciliacion_mejorada": d.diagnostico["conciliacion"]["tasa_canonica"],
        "pagos_sin_identificar": d.diagnostico["conciliacion"]["residual"],
        "monto_sin_identificar_pen": d.diagnostico["conciliacion"]["monto_residual"],
        "reconciliacion": vistas,
    }


def render_reporte(
    resultados: dict[str, ResultadoTool] | None = None,
    modo: str = "deterministico",
    narrativa: str | None = None,
    fecha_corte: str = CORTE_DEL_DATASET,
    objetivo: str = "Cierra el ciclo del mes",
) -> str:
    """Arma el informe consolidado. Las cifras salen del registro, no del LLM."""
    fecha_corte = normalizar_fecha_corte(fecha_corte)
    resultados = resultados if resultados is not None else registro.ultimos()

    etiquetas_modo = {
        "crew": "agentes CrewAI + Groq",
        "hibrido": "agentes CrewAI con relleno determinista",
        "deterministico": "pipeline determinista (sin LLM)",
    }

    partes = [
        encabezado(f"SON-IA · {objetivo.upper()}"),
        f"  Fecha de corte : {fecha_corte}",
        f"  Modo           : {etiquetas_modo.get(modo, modo)}",
        f"  Corrida        : {audit.corrida_id}",
        f"  Tools          : {len(resultados)} de {len(PLAN_DE_CIERRE)} ejecutadas",
        "",
    ]

    texto_vistas, _ = _tres_vistas(fecha_corte)
    partes.append(texto_vistas)
    partes.append("")

    for agente in AGENTES:
        partes.append(_seccion_agente(agente, resultados))
        partes.append("")

    alertas = _seccion_alertas()
    if alertas:
        partes.extend([alertas, ""])

    if narrativa:
        partes.extend(
            [
                encabezado("LECTURA EJECUTIVA DEL SUPERVISOR"),
                "  (redactada por el LLM sobre las cifras de arriba; no las recalcula)",
                "",
                *(f"  {linea}" for linea in _envolver(narrativa, ANCHO - 4)),
                "",
            ]
        )

    partes.extend([_cuadro_impacto(resultados), ""])

    partes.extend(
        [
            encabezado("TRAZABILIDAD"),
            "  Toda cifra de este informe proviene de funciones deterministas sobre los CSV.",
            "  El LLM no calcula: orquesta y explica. Cada ejecución quedó registrada con",
            "  agente, herramienta, argumentos, métricas y timestamp en logs/.",
            "=" * ANCHO,
        ]
    )
    return "\n".join(partes)


def _cuadro_impacto(resultados: dict[str, ResultadoTool]) -> str:
    """Cuadro de impacto con partidas que NO se solapan entre sí.

    Deliberadamente no se suma el `impacto_pen` de las alertas, ni siquiera
    ahora que ninguna repite el importe de otra. La razón dejó de ser el doble
    conteo y pasó a ser conceptual: estas partidas miden cosas que no se
    agregan. S/106,157.92 es dinero que ya entró y solo falta aplicar;
    S/47,819.06 es deuda por cobrar; S/26,556.46 es un flujo mensual que se
    repite cada ciclo. Sumar un cobro, una deuda y un flujo da un número sin
    significado, y es la primera pregunta que haría alguien que sepa del tema.
    """

    def m(tool: str, clave: str, defecto: float = 0.0) -> float:
        res = resultados.get(tool)
        return float(res.metricas.get(clave, defecto)) if res else defecto

    fuga = m("detectar_servicios_no_facturados", "fuga_estimada_mes_pen")
    recuperable = m("conciliar_pagos", "monto_recuperado_pen")
    cartera = m("cartera_vencida", "cartera_vencida_pen")
    pcd = m("provision_cobranza_dudosa", "provision_pen")
    fiscal = m("validar_clientes_sunat", "monto_no_habido_pen")
    residual = m("pagos_no_identificados", "monto_residual_pen")

    filas = [
        ("Cobrado sin aplicar, recuperable de inmediato", recuperable, "una vez"),
        ("Cartera vencida real a gestionar", cartera, "al corte"),
        ("   de la cual, provisión de cobranza dudosa", pcd, "contable"),
        ("Fuga por no facturar", fuga, "por mes"),
        ("Riesgo fiscal: facturas a RUC NO HABIDO", fiscal, "acumulado"),
        ("Partidas realmente sin identificar", residual, "al corte"),
    ]

    lineas = [encabezado("CUADRO DE IMPACTO (partidas no solapadas)"), ""]
    for etiqueta, valor, nota in filas:
        lineas.append(f"  {etiqueta:<48}{pen(valor):>16}   {nota}")
    lineas.extend(
        [
            "",
            "  Estas partidas no se suman entre sí. Una es dinero ya cobrado pendiente de",
            "  aplicar, otra es deuda por cobrar y otra es un flujo que se repite cada mes.",
        ]
    )
    return "\n".join(lineas)
