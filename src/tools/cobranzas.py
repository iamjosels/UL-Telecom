"""
SON-IA · Tools deterministas del Agente de Cobranzas y Recaudo.

Cubren el **momento 3 del ciclo, la rebaja automática post-pago**: cruzar el
pago contra el documento, actualizar su estado y dejar trazado quién emitió,
cuándo, cuánto y cuándo se pagó. Más la medición de la cartera vencida.

El hallazgo que estructura este módulo: los pagos del sistema ISIS referencian
el documento SIN el cero inicial del correlativo ("S300-248301" contra
"S300-0248301" en el maestro). El algoritmo de aplicación actual los da por
huérfanos; la clave canónica los recupera. Son S/106,157.92 que figuran como
deuda pero ya están cobrados.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from src.contracts import MAX_FILAS_DETALLE, Alerta, ResultadoTool
from src.data_loader import CORTE_DEL_DATASET, ORDEN_TRAMOS, TOL_SALDO, get_datos
from src.formato import linea_aging, num, pct, pen, top_montos
from src.tools.registro import ArgsConFechaCorte, booleano_tolerante, registrar

AGENTE = "AGENTE_COBRANZAS"


# --------------------------------------------------------------------------- #
# Schemas de argumentos
# --------------------------------------------------------------------------- #


class ArgsConciliar(BaseModel):
    conciliacion: str = Field(
        "canonica",
        description=(
            "'exacta' cruza por número de documento literal (lo que hace el sistema hoy); "
            "'canonica' normaliza el cero inicial del correlativo y recupera los pagos de ISIS."
        ),
    )


class ArgsCartera(ArgsConFechaCorte):
    tramo: str | None = Field(
        None,
        description="Filtrar a un tramo de aging: '1-30', '31-60', '61-90' o '90+'. Opcional.",
    )
    conciliacion: str = Field("canonica", description="'canonica' o 'exacta'.")

    @field_validator("conciliacion", mode="before")
    @classmethod
    def _validar_conciliacion(cls, v):
        # El LLM propone estos valores; cualquier cosa rara cae al modo correcto.
        return v if str(v).strip().lower() in ("canonica", "exacta") else "canonica"


# --------------------------------------------------------------------------- #
# 1 · Conciliación pago ↔ factura
# --------------------------------------------------------------------------- #


@registrar(
    nombre="conciliar_pagos",
    agente=AGENTE,
    args_schema=ArgsConciliar,
    etiqueta="Conciliación y rebaja automática post-pago",
    kpi="tiempo_conciliacion_bancaria",
    descripcion=(
        "Concilia los pagos recibidos contra las facturas emitidas y clasifica cada documento "
        "como CANCELADA, PARCIAL o PENDIENTE, calculando el saldo. Compara la tasa de "
        "conciliación del algoritmo actual contra la del algoritmo mejorado (que normaliza el "
        "correlativo) y cuantifica cuánto dinero se reclasifica de 'deuda' a 'cobrado sin "
        "aplicar'. Úsala para '¿cómo va la conciliación?' o '¿cuántas facturas están pagadas?'."
    ),
)
def conciliar_pagos(conciliacion: str = "canonica") -> ResultadoTool:
    d = get_datos()
    dg = d.diagnostico["conciliacion"]

    f = d.saldos(deducir_nc=True, conciliacion=conciliacion)
    estados = f["estado_doc"].value_counts().to_dict()
    saldo_total = round(f.loc[f["saldo"] > TOL_SALDO, "saldo"].sum(), 2)

    # La misma foto bajo el algoritmo actual, para poder contrastar.
    f_exacta = d.saldos(deducir_nc=True, conciliacion="exacta")
    saldo_exacta = round(f_exacta.loc[f_exacta["saldo"] > TOL_SALDO, "saldo"].sum(), 2)
    reclasificado = round(saldo_exacta - saldo_total, 2)

    total_facturado = round(d.facturas["total"].sum(), 2)
    total_pagado = round(d.pagos["monto_pagado"].sum(), 2)
    aplicado = round(f["pagado"].sum(), 2)

    resumen = (
        f"CONCILIACIÓN PAGO ↔ FACTURA (modo {conciliacion}). "
        f"Documentos: {num(estados.get('CANCELADA', 0))} CANCELADAS, "
        f"{num(estados.get('PARCIAL', 0))} PARCIALES, {num(estados.get('PENDIENTE', 0))} PENDIENTES "
        f"sobre {num(len(f))} facturas. Saldo vivo total {pen(saldo_total)}. "
        f"Facturado {pen(total_facturado)} · cobrado {pen(total_pagado)} · "
        f"aplicado a documento {pen(aplicado)}. "
        f"ALGORITMO DE APLICACIÓN: el cruce literal identifica {num(dg['match_exacto'])} de "
        f"{num(dg['pagos'])} pagos ({dg['tasa_exacta']}%); normalizando el cero inicial del "
        f"correlativo sube a {num(dg['match_canonico'])} ({dg['tasa_canonica']}%), recuperando "
        f"{num(dg['recuperados'])} pagos por {pen(dg['monto_recuperado'])}. "
        f"Eso reclasifica {pen(reclasificado)} de 'deuda' a 'cobrado sin aplicar': "
        f"la cartera pasa de {pen(saldo_exacta)} a {pen(saldo_total)}. "
        f"Quedan {num(dg['residual'])} pagos sin identificar por {pen(dg['monto_residual'])}."
    )

    alertas = [
        Alerta(
            severidad="critica",
            titulo="Pagos cobrados pero no aplicados al documento",
            detalle=(
                f"{dg['recuperados']} pagos por {pen(dg['monto_recuperado'])} no cruzan por "
                "diferencia de formato en el correlativo (cero inicial). Inflan la cartera y "
                "gatillan gestión de cobranza a clientes que ya pagaron."
            ),
            impacto_pen=dg["monto_recuperado"],
            kpi="mejora_algoritmo_aplicacion",
            accion="Normalizar el correlativo en el algoritmo de aplicación (previa revisión)",
            responsable="Recaudo / TI",
        )
    ]

    cols = ["doc", "ruc", "razon_social", "cod_cuenta", "sistema", "fecha_emision", "fecha_vto",
            "total", "pagado", "nc", "saldo", "estado_doc"]
    detalle = f[f["saldo"] > TOL_SALDO].reindex(columns=cols).sort_values("saldo", ascending=False)

    return ResultadoTool(
        tool="conciliar_pagos",
        agente=AGENTE,
        resumen=resumen,
        params={"conciliacion": conciliacion},
        metricas={
            "facturas": len(f),
            "canceladas": estados.get("CANCELADA", 0),
            "parciales": estados.get("PARCIAL", 0),
            "pendientes": estados.get("PENDIENTE", 0),
            "saldo_vivo_pen": saldo_total,
            "saldo_vivo_algoritmo_actual_pen": saldo_exacta,
            "reclasificado_pen": reclasificado,
            "facturado_pen": total_facturado,
            "cobrado_pen": total_pagado,
            "tasa_conciliacion_actual": dg["tasa_exacta"],
            "tasa_conciliacion_mejorada": dg["tasa_canonica"],
            "pagos_recuperados": dg["recuperados"],
            "monto_recuperado_pen": dg["monto_recuperado"],
            "pagos_residuales": dg["residual"],
        },
        columnas=cols,
        data=detalle.head(MAX_FILAS_DETALLE).to_dict("records"),
        data_filas_totales=len(detalle),
        data_truncada=len(detalle) > MAX_FILAS_DETALLE,
        alertas=alertas,
        trazas=[
            f"facturas = {len(f)} · pagos = {dg['pagos']} · notas de crédito = {len(d.notas_credito)}",
            f"cruce literal -> {dg['match_exacto']} pagos ({dg['tasa_exacta']}%)",
            f"cruce canónico -> {dg['match_canonico']} pagos ({dg['tasa_canonica']}%)",
            f"saldo = total - pagos - notas de crédito, umbral {TOL_SALDO}",
            f"saldo vivo: {saldo_exacta:,.2f} (actual) -> {saldo_total:,.2f} ({conciliacion})",
        ],
    )


# --------------------------------------------------------------------------- #
# 2 · Partidas sin identificar
# --------------------------------------------------------------------------- #


class ArgsPagosNoIdentificados(BaseModel):
    solo_recuperables: bool = Field(
        False,
        description=(
            "Devolver sólo las partidas que SÍ cruzan al normalizar el correlativo, "
            "es decir la cola de revisión accionable."
        ),
    )

    _flag = field_validator("solo_recuperables", mode="before")(booleano_tolerante)


@registrar(
    nombre="pagos_no_identificados",
    agente=AGENTE,
    args_schema=ArgsPagosNoIdentificados,
    etiqueta="Partidas bancarias sin identificar",
    kpi="tiempo_identificacion_deposito",
    descripcion=(
        "Lista los pagos cuya FACTURA_AFECTADA no existe en el maestro de facturas, es decir "
        "las partidas bancarias que el algoritmo de aplicación no logra cruzar. Separa las que "
        "SÍ se recuperan normalizando el correlativo de las que quedan realmente huérfanas. "
        "Úsala para '¿qué pagos están sin identificar?' o '¿cuánto dinero no se ha aplicado?'."
    ),
)
def pagos_no_identificados(solo_recuperables: bool = False) -> ResultadoTool:
    d = get_datos()
    pagos = d.pagos
    dg = d.diagnostico["conciliacion"]

    docs_exactos = set(d.facturas["doc"])
    docs_canon = set(d.facturas["doc_k"])

    huerfanos = pagos[~pagos["factura_afectada"].isin(docs_exactos)].copy()
    huerfanos["recuperable"] = huerfanos["doc_k_afectada"].isin(docs_canon)

    # Para los recuperables: contra qué documento cruzarían y si el monto cuadra.
    mapa_doc = d.facturas.set_index("doc_k")["doc"]
    mapa_total = d.facturas.set_index("doc_k")["total"]
    huerfanos["doc_propuesto"] = huerfanos["doc_k_afectada"].map(mapa_doc)
    huerfanos["total_factura"] = huerfanos["doc_k_afectada"].map(mapa_total)

    # Nivel de confianza del match, para que esto sea una cola de revisión y no
    # una aplicación automática de caja.
    def _confianza(fila) -> str:
        if not fila["recuperable"]:
            return "sin_match"
        if fila["moneda"] != "PEN":
            return "revisar_moneda"
        if pd.notna(fila["total_factura"]) and abs(fila["monto_pagado"] - fila["total_factura"]) <= 0.01:
            return "exacto_monto"
        return "parcial"

    huerfanos["confianza"] = huerfanos.apply(_confianza, axis=1)
    conf = huerfanos["confianza"].value_counts().to_dict()

    recuperables = huerfanos[huerfanos["recuperable"]]
    residuales = huerfanos[~huerfanos["recuperable"]]
    por_sistema = huerfanos["sistema"].value_counts().to_dict()
    usd = huerfanos[huerfanos["moneda"] != "PEN"]

    resumen = (
        f"PARTIDAS BANCARIAS SIN IDENTIFICAR. {num(len(huerfanos))} pagos por "
        f"{pen(huerfanos['monto_pagado'].sum())} referencian una factura que no está en el "
        f"maestro ({pct(len(huerfanos) / len(pagos), 2)} del total de pagos). "
        f"Origen: {por_sistema}. "
        f"DIAGNÓSTICO: {num(len(recuperables))} de ellos ({pen(recuperables['monto_pagado'].sum())}) "
        f"SÍ cruzan al normalizar el cero inicial del correlativo — no son partidas perdidas, "
        f"son un problema de formato entre ISIS y AMDOCS. "
        f"Confianza del match: {conf}. "
        f"Sólo {num(len(residuales))} pagos por {pen(residuales['monto_pagado'].sum())} quedan "
        f"realmente sin contraparte. "
        f"Atención: {num(len(usd))} de estos pagos están en moneda distinta a PEN "
        f"({pen(usd['monto_pagado'].sum())}) y requieren revisión de tesorería antes de aplicar."
    )

    alertas = [
        Alerta(
            severidad="alta",
            titulo="Partidas bancarias sin aplicar",
            detalle=(
                f"{len(huerfanos)} pagos por {pen(huerfanos['monto_pagado'].sum())} sin cruzar; "
                f"{len(recuperables)} recuperables por normalización de correlativo"
            ),
            impacto_pen=round(huerfanos["monto_pagado"].sum(), 2),
            kpi="tiempo_identificacion_deposito",
            accion="Abrir cola de revisión: aplicar los de confianza 'exacto_monto' primero",
            responsable="Recaudo",
        )
    ]
    if len(usd):
        alertas.append(
            Alerta(
                severidad="media",
                titulo="Pagos en moneda distinta a la facturada",
                detalle=(
                    f"{len(usd)} pagos en USD contra facturas emitidas en PEN. El tipo de "
                    "cambio implícito es incoherente: no convertir automáticamente."
                ),
                impacto_pen=round(usd["monto_pagado"].sum(), 2),
                kpi="tiempo_identificacion_deposito",
                accion="Validar con tesorería el tipo de cambio y la naturaleza del abono",
                responsable="Tesorería / Contabilidad",
                clave="pago_moneda_distinta",
            )
        )

    cols = ["factura_afectada", "doc_propuesto", "confianza", "ruc", "razon_social", "cod_cuenta",
            "sistema", "fecha_pago", "moneda", "monto_pagado", "total_factura"]
    base_detalle = recuperables if solo_recuperables else huerfanos
    detalle = base_detalle.reindex(columns=cols).sort_values("monto_pagado", ascending=False)

    return ResultadoTool(
        tool="pagos_no_identificados",
        agente=AGENTE,
        resumen=resumen,
        metricas={
            "pagos_no_identificados": len(huerfanos),
            "monto_no_identificado_pen": round(huerfanos["monto_pagado"].sum(), 2),
            "pct_sobre_pagos": round(100 * len(huerfanos) / len(pagos), 2),
            "recuperables": len(recuperables),
            "monto_recuperable_pen": round(recuperables["monto_pagado"].sum(), 2),
            "residuales": len(residuales),
            "monto_residual_pen": round(residuales["monto_pagado"].sum(), 2),
            "pagos_moneda_distinta": len(usd),
            "monto_moneda_distinta_pen": round(usd["monto_pagado"].sum(), 2),
            "tasa_conciliacion_actual": dg["tasa_exacta"],
            "tasa_conciliacion_mejorada": dg["tasa_canonica"],
            **{f"confianza_{k}": v for k, v in conf.items()},
        },
        columnas=cols,
        data=detalle.head(MAX_FILAS_DETALLE).to_dict("records"),
        data_filas_totales=len(detalle),
        data_truncada=len(detalle) > MAX_FILAS_DETALLE,
        alertas=alertas,
        trazas=[
            f"pagos = {len(pagos)}",
            f"FACTURA_AFECTADA fuera del maestro -> {len(huerfanos)} pagos",
            f"de esos, cruzan por clave canónica -> {len(recuperables)}",
            f"sin contraparte real -> {len(residuales)} pagos / {residuales['monto_pagado'].sum():,.2f}",
        ],
    )


# --------------------------------------------------------------------------- #
# 3 · Cartera vencida
# --------------------------------------------------------------------------- #


@registrar(
    nombre="cartera_vencida",
    agente=AGENTE,
    args_schema=ArgsCartera,
    etiqueta="Cartera vencida con aging",
    kpi="reduccion_cxc",
    descripcion=(
        "Calcula la cartera vencida a una fecha de corte: facturas con saldo cuyo vencimiento "
        "ya pasó, con aging en tramos 1-30, 31-60, 61-90 y 90+ días. Acepta filtrar por tramo "
        "(por ejemplo '90+'). Devuelve saldo por tramo, concentración por cliente y lo que "
        "está por vencer. Úsala para '¿cuánto tenemos por cobrar?' o '¿cuánto a más de 90 días?'."
    ),
)
def cartera_vencida(
    fecha_corte: str = CORTE_DEL_DATASET,
    tramo: str | None = None,
    conciliacion: str = "canonica",
) -> ResultadoTool:
    d = get_datos()
    vencidas, por_vencer = d.cartera(
        fecha_corte=fecha_corte, deducir_nc=True, conciliacion=conciliacion
    )

    if tramo:
        tramo = str(tramo).strip()
        if tramo not in ORDEN_TRAMOS:
            return ResultadoTool(
                tool="cartera_vencida",
                agente=AGENTE,
                resumen=(
                    f"ERROR: tramo '{tramo}' inválido. Los tramos válidos son: "
                    f"{', '.join(ORDEN_TRAMOS)}."
                ),
                params={"fecha_corte": fecha_corte, "tramo": tramo},
                ok=False,
                error="tramo_invalido",
            )
        vencidas = vencidas[vencidas["tramo"] == tramo]

    aging = d.aging(vencidas)
    total = round(vencidas["saldo"].sum(), 2)
    ambito = f"tramo {tramo}" if tramo else "todos los tramos"

    por_cliente = vencidas.groupby("ruc")["saldo"].sum().sort_values(ascending=False)
    top10 = round(por_cliente.head(10).sum(), 2)
    concentracion = top10 / total if total else 0.0

    # Con filtro de tramo el aging completo sólo añade ceros: se omite.
    texto_aging = "" if tramo else f"Aging: {linea_aging(aging)}. "

    resumen = (
        f"CARTERA VENCIDA al {fecha_corte} ({ambito}, conciliación {conciliacion}). "
        f"{num(len(vencidas))} facturas con saldo por {pen(total)}. "
        f"{texto_aging}"
        f"Por vencer (aún no exigible): {num(len(por_vencer))} facturas por "
        f"{pen(por_vencer['saldo'].sum())}. "
        f"Concentración: los 10 mayores deudores acumulan {pen(top10)} "
        f"({pct(concentracion)} de la cartera). Top 3: {top_montos(vencidas, 'ruc', 'saldo', 3)}. "
        f"Antigüedad media {vencidas['dias_vencido'].mean():.0f} días."
        if len(vencidas)
        else f"CARTERA VENCIDA al {fecha_corte} ({ambito}): sin facturas con saldo vencido."
    )

    alertas = []
    if total:
        saldo_90 = float(aging.loc["90+", "saldo"]) if "90+" in aging.index else 0.0
        if saldo_90:
            alertas.append(
                Alerta(
                    severidad="alta",
                    titulo="Cartera con más de 90 días de vencimiento",
                    detalle=(
                        f"{int(aging.loc['90+', 'facturas'])} facturas por {pen(saldo_90)} "
                        "con provisión al 100%"
                    ),
                    impacto_pen=saldo_90,
                    kpi="pcd",
                    accion="Escalar a mesa de aceleración de recupero",
                    responsable="Cobranzas",
                )
            )
        if concentracion > 0.5:
            alertas.append(
                Alerta(
                    severidad="media",
                    titulo="Alta concentración de la cartera vencida",
                    detalle=(
                        f"10 clientes concentran {pct(concentracion)} del saldo vencido: "
                        "la gestión focalizada tiene alto retorno"
                    ),
                    impacto_pen=top10,
                    kpi="reduccion_cxc",
                    accion="Priorizar gestión sobre el top-10 antes que sobre la cola larga",
                    responsable="Cobranzas",
                    clave="concentracion_cartera",
                )
            )

    cols = ["doc", "ruc", "razon_social", "cod_cuenta", "sistema", "fecha_emision", "fecha_vto",
            "dias_vencido", "tramo", "total", "pagado", "nc", "saldo", "estado_doc"]
    detalle = vencidas.reindex(columns=cols).sort_values("saldo", ascending=False)

    return ResultadoTool(
        tool="cartera_vencida",
        agente=AGENTE,
        resumen=resumen,
        params={"fecha_corte": fecha_corte, "tramo": tramo, "conciliacion": conciliacion},
        metricas={
            "fecha_corte": fecha_corte,
            "facturas_vencidas": len(vencidas),
            "cartera_vencida_pen": total,
            "facturas_por_vencer": len(por_vencer),
            "por_vencer_pen": round(por_vencer["saldo"].sum(), 2),
            "clientes_deudores": int(vencidas["ruc"].nunique()),
            "top10_pen": top10,
            "concentracion_top10": round(concentracion * 100, 1),
            "dias_vencido_promedio": round(float(vencidas["dias_vencido"].mean()), 1)
            if len(vencidas)
            else 0.0,
            **{
                f"tramo_{t.replace('-', '_').replace('+', '_mas')}_pen": float(
                    aging.loc[t, "saldo"]
                )
                for t in aging.index
            },
            **{
                f"tramo_{t.replace('-', '_').replace('+', '_mas')}_facturas": int(
                    aging.loc[t, "facturas"]
                )
                for t in aging.index
            },
        },
        columnas=cols,
        data=detalle.head(MAX_FILAS_DETALLE).to_dict("records"),
        data_filas_totales=len(detalle),
        data_truncada=len(detalle) > MAX_FILAS_DETALLE,
        alertas=alertas,
        trazas=[
            f"corte = {fecha_corte}, conciliación = {conciliacion}",
            f"facturas con saldo > {TOL_SALDO} y vencimiento anterior al corte -> {len(vencidas)}",
            f"aging por días vencidos: {dict(zip(aging.index, aging['facturas'].astype(int)))}",
            f"saldo vencido total = {total:,.2f}",
        ],
    )
