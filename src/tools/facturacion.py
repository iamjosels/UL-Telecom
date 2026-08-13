"""
SON-IA · Tools deterministas del Agente de Facturación.

Cubren el **momento 1 del ciclo, la asesoría previa a la emisión**: validar los
insumos del PxQ, alertar quiebres antes de emitir y dejar traza auditable.

Ninguna de estas funciones habla con un LLM. Devuelven `ResultadoTool`, cuyo
campo `.resumen` es lo único que después verá el modelo.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from src.contracts import MAX_FILAS_DETALLE, Alerta, ResultadoTool
from src.data_loader import IGV_TASA, get_datos
from src.formato import num, pct, pen, tabla_top, top_montos
from src.tools.registro import booleano_tolerante, registrar

AGENTE = "AGENTE_FACTURACION"


# --------------------------------------------------------------------------- #
# Schemas de argumentos
# --------------------------------------------------------------------------- #


class ArgsNoFacturados(BaseModel):
    incluir_suspendidos: bool = Field(
        False,
        description="Incluir también los servicios suspendidos, no solo los activos.",
    )

    _flag = field_validator("incluir_suspendidos", mode="before")(booleano_tolerante)


class ArgsResumenFacturacion(BaseModel):
    ruc: str | None = Field(
        None, description="RUC del cliente a analizar. Si se omite, resume toda la cartera."
    )


# --------------------------------------------------------------------------- #
# 1 · Fuga de ingresos
# --------------------------------------------------------------------------- #


@registrar(
    nombre="detectar_servicios_no_facturados",
    agente=AGENTE,
    args_schema=ArgsNoFacturados,
    etiqueta="Quiebres: servicios activos sin factura",
    kpi="aseguramiento_ingresos",
    descripcion=(
        "Detecta la fuga de ingresos: cuentas con servicio ACTIVO en planta fija o móvil "
        "que no tienen ninguna factura emitida. Devuelve el conteo de cuentas, los clientes "
        "afectados y la exposición estimada en soles por mes. Úsala para responder '¿qué "
        "cuentas activas no se están facturando?' o '¿cuánto estamos dejando de facturar?'."
    ),
)
def detectar_servicios_no_facturados(incluir_suspendidos: bool = False) -> ResultadoTool:
    d = get_datos()
    planta = d.planta_unificada
    base = planta if incluir_suspendidos else planta[planta["activo"]]

    ctas_base = set(base["cod_cuenta"].dropna())
    ctas_facturadas = d.cuentas_facturadas()
    sin_factura = ctas_base - ctas_facturadas

    det = base[base["cod_cuenta"].isin(sin_factura)].copy()
    clientes = det["ruc"].nunique()
    por_origen = det.groupby("origen")["cod_cuenta"].nunique().to_dict()

    # Ticket MEDIANO, no medio: la media está inflada por las facturas grandes
    # de ISIS y sobreestimaría la fuga casi al triple.
    facturado_por_cuenta = d.facturas.groupby("cod_cuenta")["total"].sum()
    documentos_por_cuenta = d.facturas.groupby("cod_cuenta")["doc"].count()
    ticket = float((facturado_por_cuenta / documentos_por_cuenta).median())
    fuga_mes = round(len(sin_factura) * ticket, 2)

    # Hallazgo aparte: líneas activas sin COD_CUENTA. Sin cuenta no hay
    # documento que emitir, así que no son "no facturadas" sino no facturables.
    huerfanas = d.diagnostico["planta"]["lineas_activas_sin_cuenta"]

    pct_fuga = len(sin_factura) / len(ctas_base) if ctas_base else 0.0
    ambito = "activo o suspendido" if incluir_suspendidos else "activo"

    resumen = (
        f"FUGA DE INGRESOS. {num(len(sin_factura))} de {num(len(ctas_base))} cuentas con "
        f"servicio {ambito} ({pct(pct_fuga)}) no tienen NINGUNA factura emitida. "
        f"Afecta a {num(clientes)} clientes (RUC). "
        f"Desglose por planta: {por_origen}. "
        f"Exposición estimada {pen(fuga_mes)} por mes de ciclo "
        f"(ticket mediano por cuenta facturada {pen(ticket)}). "
        f"Segmentos más golpeados: {tabla_top(det, 'segmento', 3)}. "
        f"Además hay {huerfanas} líneas ACTIVAS sin COD_CUENTA asignado: sin cuenta no existe "
        f"documento que emitir, son 100% no facturables y requieren corrección en el maestro."
    )

    alertas = [
        Alerta(
            severidad="critica",
            titulo="Fuga de ingresos por servicios activos no facturados",
            detalle=(
                f"{len(sin_factura)} cuentas activas sin factura ({pct(pct_fuga)}), "
                f"{clientes} clientes afectados"
            ),
            impacto_pen=fuga_mes,
            kpi="aseguramiento_ingresos",
            accion="Cruzar planta vs facturación y emitir el ciclo pendiente",
            responsable="Facturación",
        )
    ]
    if huerfanas:
        alertas.append(
            Alerta(
                severidad="alta",
                titulo="Líneas activas sin cuenta asignada",
                detalle=f"{huerfanas} líneas móviles activas sin COD_CUENTA: no facturables",
                kpi="aseguramiento_ingresos",
                accion="Regularizar el alta en el maestro de planta",
                responsable="TI / Implantación",
                clave="linea_activa_sin_cuenta",
            )
        )

    cols = ["cod_cuenta", "cod_cliente", "ruc", "razon_social", "origen", "estado", "plan",
            "segmento", "fecha_alta"]
    detalle = det.reindex(columns=cols)

    return ResultadoTool(
        tool="detectar_servicios_no_facturados",
        agente=AGENTE,
        resumen=resumen,
        metricas={
            "cuentas_evaluadas": len(ctas_base),
            "cuentas_sin_factura": len(sin_factura),
            "pct_fuga": round(pct_fuga * 100, 2),
            "clientes_afectados": int(clientes),
            "fuga_estimada_mes_pen": fuga_mes,
            "ticket_mediano_cuenta_pen": round(ticket, 2),
            "cuentas_sin_factura_fija": por_origen.get("fija", 0),
            "cuentas_sin_factura_movil": por_origen.get("movil", 0),
            "lineas_activas_sin_cuenta": huerfanas,
        },
        columnas=cols,
        data=detalle.head(MAX_FILAS_DETALLE).to_dict("records"),
        data_filas_totales=len(detalle),
        data_truncada=len(detalle) > MAX_FILAS_DETALLE,
        alertas=alertas,
        trazas=[
            f"planta unificada = {len(planta)} servicios (fija + móvil)",
            f"filtro {ambito} -> {len(base)} servicios, {len(ctas_base)} cuentas distintas",
            f"cuentas con al menos una factura = {len(ctas_facturadas)}",
            f"diferencia -> {len(sin_factura)} cuentas sin facturar / {len(detalle)} servicios",
            f"exposición = {len(sin_factura)} cuentas x ticket mediano {ticket:.2f}",
        ],
    )


# --------------------------------------------------------------------------- #
# 2 · Riesgo tributario
# --------------------------------------------------------------------------- #


class ArgsValidarSunat(BaseModel):
    ruc: str | None = Field(
        None, description="Acotar la validación a un RUC concreto. Si se omite, valida todo."
    )


@registrar(
    nombre="validar_clientes_sunat",
    agente=AGENTE,
    args_schema=ArgsValidarSunat,
    etiqueta="Riesgo tributario: RUC NO HABIDO e IGV",
    kpi="reduccion_nc_error_operativo",
    descripcion=(
        "Valida el estado SUNAT de los clientes facturados y la consistencia del IGV. "
        "Reporta facturas emitidas a RUC en estado NO HABIDO (riesgo de multa tributaria y "
        "de rechazo del crédito fiscal), clientes con baja o suspensión en SUNAT, facturas "
        "cuyo RUC no está en el maestro, y descuadres entre neto + IGV y el total. Úsala para "
        "'¿hay clientes con problemas en SUNAT?' o '¿qué riesgo fiscal tenemos?'."
    ),
)
def validar_clientes_sunat(ruc: str | None = None) -> ResultadoTool:
    d = get_datos()
    fac = d.clientes_enriquecidos(d.facturas, col_ruc="ruc")

    if ruc:
        ruc = str(ruc).strip()
        fac = fac[fac["ruc"] == ruc]
        if fac.empty:
            return ResultadoTool(
                tool="validar_clientes_sunat",
                agente=AGENTE,
                resumen=f"No hay facturas emitidas al RUC {ruc} en el dataset.",
                params={"ruc": ruc},
                metricas={"facturas_no_habido": 0, "monto_no_habido_pen": 0.0},
                trazas=[f"filtro ruc={ruc} -> 0 facturas"],
            )

    no_habido = fac[fac["sunat_estado_ruc"] == "NO HABIDO"]
    monto_nh = round(no_habido["total"].sum(), 2)
    rucs_nh = no_habido["ruc"].nunique()

    # Contribuyentes de baja o suspendidos: facturarles también es riesgoso.
    estados_riesgo = ["BAJA DE OFICIO", "BAJA DEFINITIVA", "BAJA PROV. POR OFICI",
                      "SUSPENSION TEMPORAL"]
    contrib_riesgo = fac[fac["sunat_estado_contribuyente"].isin(estados_riesgo)]

    fuera_maestro = fac[fac["fuera_del_maestro"]]

    # Consistencia del PxQ: neto + IGV debe cuadrar con el total, y la tasa debe
    # rondar el 18%. Es exactamente la validación del "momento 1".
    calc = (fac["neto"].fillna(0) + fac["igv"].fillna(0)).round(2)
    descuadre = fac[(calc - fac["total"]).abs() > 0.01]
    con_neto = fac[fac["neto"].fillna(0) > 0].copy()
    con_neto["tasa"] = con_neto["igv"].fillna(0) / con_neto["neto"]
    tasa_rara = con_neto[(con_neto["tasa"] < 0.17) | (con_neto["tasa"] > 0.19)]

    total_rucs_nh_maestro = int(
        (d.clientes["sunat_estado_ruc"] == "NO HABIDO").sum()
    )

    resumen = (
        f"RIESGO TRIBUTARIO EN LA EMISIÓN. "
        f"{num(len(no_habido))} facturas por {pen(monto_nh)} emitidas a {num(rucs_nh)} clientes "
        f"con RUC NO HABIDO en SUNAT (el maestro tiene {total_rucs_nh_maestro} RUC NO HABIDO). "
        f"{num(len(contrib_riesgo))} facturas ({pen(contrib_riesgo['total'].sum())}) van a "
        f"contribuyentes de baja o suspensión temporal. "
        f"{num(len(fuera_maestro))} facturas ({pct(len(fuera_maestro) / len(fac))}) se emitieron a "
        f"RUC que NO está en el maestro de clientes: no se puede validar su estado SUNAT. "
        f"Control de PxQ: {num(len(descuadre))} facturas donde neto + IGV no cuadra con el total y "
        f"{num(len(tasa_rara))} con tasa de IGV fuera del rango 17-19% (esperado {pct(IGV_TASA, 0)}). "
        f"Clientes NO HABIDO con más monto: {top_montos(no_habido, 'ruc', 'total', 3)}."
    )

    alertas = [
        Alerta(
            severidad="critica",
            titulo="Facturas emitidas a clientes con RUC NO HABIDO",
            detalle=f"{len(no_habido)} facturas a {rucs_nh} clientes NO HABIDO en SUNAT",
            impacto_pen=monto_nh,
            kpi="reduccion_nc_error_operativo",
            accion="Bloquear emisión a RUC NO HABIDO y evaluar regularización ante SUNAT",
            responsable="Facturación / Contabilidad",
        )
    ]
    if len(fuera_maestro):
        alertas.append(
            Alerta(
                severidad="media",
                titulo="Facturación a RUC fuera del maestro de clientes",
                detalle=(
                    f"{len(fuera_maestro)} facturas sin contraparte en el maestro: "
                    "imposible validar estado SUNAT antes de emitir"
                ),
                impacto_pen=round(fuera_maestro["total"].sum(), 2),
                kpi="aseguramiento_ingresos",
                accion="Completar el maestro de clientes (info dispersa entre sistemas)",
                responsable="TI / Comercial",
            )
        )
    if len(descuadre) or len(tasa_rara):
        alertas.append(
            Alerta(
                severidad="media",
                titulo="Descuadres de IGV en documentos emitidos",
                detalle=(
                    f"{len(descuadre)} facturas con neto + IGV != total; "
                    f"{len(tasa_rara)} con tasa fuera de 17-19%"
                ),
                kpi="reduccion_nc_error_operativo",
                accion="Revisar parametrización del cálculo antes del próximo ciclo",
                responsable="Facturación / TI",
            )
        )

    cols = ["doc", "ruc", "razon_social", "cod_cuenta", "sistema", "fuente", "fecha_emision",
            "total", "sunat_estado_ruc", "sunat_estado_contribuyente"]
    detalle = no_habido.reindex(columns=cols).sort_values("total", ascending=False)

    return ResultadoTool(
        tool="validar_clientes_sunat",
        agente=AGENTE,
        resumen=resumen,
        metricas={
            "facturas_no_habido": len(no_habido),
            "monto_no_habido_pen": monto_nh,
            "clientes_no_habido": int(rucs_nh),
            "rucs_no_habido_en_maestro": total_rucs_nh_maestro,
            "facturas_contribuyente_riesgo": len(contrib_riesgo),
            "monto_contribuyente_riesgo_pen": round(contrib_riesgo["total"].sum(), 2),
            "facturas_fuera_maestro": len(fuera_maestro),
            "pct_fuera_maestro": round(100 * len(fuera_maestro) / len(fac), 2),
            "facturas_descuadre_igv": len(descuadre),
            "facturas_tasa_igv_anomala": len(tasa_rara),
        },
        columnas=cols,
        data=detalle.head(MAX_FILAS_DETALLE).to_dict("records"),
        data_filas_totales=len(detalle),
        data_truncada=len(detalle) > MAX_FILAS_DETALLE,
        alertas=alertas,
        trazas=[
            f"facturas = {len(fac)} (LEFT join contra maestro de {len(d.clientes)} clientes)",
            f"estado SUNAT NO HABIDO -> {len(no_habido)} facturas / {rucs_nh} RUC",
            f"sin contraparte en el maestro -> {len(fuera_maestro)} facturas",
            f"control neto+IGV vs total -> {len(descuadre)} descuadres",
        ],
    )


# --------------------------------------------------------------------------- #
# 3 · Escalera de facturación
# --------------------------------------------------------------------------- #


@registrar(
    nombre="resumen_facturacion",
    agente=AGENTE,
    args_schema=ArgsResumenFacturacion,
    etiqueta="Escalera de facturación del ciclo",
    kpi="aseguramiento_ingresos",
    descripcion=(
        "Resume la facturación emitida: total facturado, número de documentos, evolución mes "
        "a mes (escalera de facturación), reparto por sistema origen y por fuente (cíclica vs "
        "acíclica), y notas de crédito emitidas. Acepta un RUC opcional para acotar el análisis "
        "a un cliente. Úsala para '¿cuánto facturamos?' o '¿cómo viene el ciclo?'."
    ),
)
def resumen_facturacion(ruc: str | None = None) -> ResultadoTool:
    d = get_datos()
    fac = d.facturas
    nc = d.notas_credito
    ambito = "toda la cartera"

    if ruc:
        ruc = str(ruc).strip()
        fac = fac[fac["ruc"] == ruc]
        nc = nc[nc["ruc"] == ruc]
        ambito = f"el cliente RUC {ruc}"
        if fac.empty:
            return ResultadoTool(
                tool="resumen_facturacion",
                agente=AGENTE,
                resumen=f"No hay facturas emitidas para {ambito} en el dataset.",
                params={"ruc": ruc},
                metricas={"facturas": 0, "facturado_pen": 0.0},
                trazas=[f"filtro ruc={ruc} -> 0 facturas"],
            )

    total = round(fac["total"].sum(), 2)
    monto_nc = round(nc["monto"].sum(), 2)

    # Escalera de facturación: evolución mensual por fecha de emisión.
    escalera = (
        fac.dropna(subset=["fecha_emision"])
        .groupby(fac["fecha_emision"].dt.to_period("M"))["total"]
        .agg(documentos="count", monto="sum")
        .sort_index()
    )
    ultimos_meses = escalera.tail(4)
    texto_escalera = " | ".join(
        f"{p}: {int(r['documentos'])} docs {pen(r['monto'])}" for p, r in ultimos_meses.iterrows()
    )

    por_sistema = fac.groupby("sistema")["total"].agg(["count", "sum"])
    por_fuente = fac.groupby("fuente")["total"].agg(["count", "sum"])
    texto_sistema = ", ".join(
        f"{s}: {int(r['count'])} docs {pen(r['sum'])}" for s, r in por_sistema.iterrows()
    )
    texto_fuente = ", ".join(
        f"{s}: {int(r['count'])} docs {pen(r['sum'])}" for s, r in por_fuente.iterrows()
    )

    ratio_nc = monto_nc / total if total else 0.0

    resumen = (
        f"ESCALERA DE FACTURACIÓN — {ambito}. "
        f"Emitidas {num(len(fac))} facturas por {pen(total)} "
        f"(rango {fac['fecha_emision'].min():%Y-%m-%d} a {fac['fecha_emision'].max():%Y-%m-%d}). "
        f"Últimos meses: {texto_escalera}. "
        f"Por sistema origen: {texto_sistema}. Por fuente: {texto_fuente}. "
        f"Notas de crédito: {num(len(nc))} por {pen(monto_nc)} ({pct(ratio_nc, 2)} de lo "
        f"facturado), indicador de refacturación por error operativo. "
        f"Ticket promedio por documento {pen(total / len(fac))}."
    )

    alertas = []
    if "ISIS" in por_sistema.index and len(por_sistema) > 1:
        isis = por_sistema.loc["ISIS"]
        alertas.append(
            Alerta(
                severidad="alta",
                titulo="Facturación repartida entre dos sistemas sin integrar",
                detalle=(
                    f"{int(isis['count'])} documentos ({pen(isis['sum'])}) provienen de ISIS, "
                    "con formato de fecha y de correlativo distinto al de AMDOCS"
                ),
                impacto_pen=round(float(isis["sum"]), 2),
                kpi="aseguramiento_ingresos",
                accion="Normalizar la integración ISIS -> AMDOCS (fechas y correlativos)",
                responsable="TI",
            )
        )

    cols = ["doc", "ruc", "razon_social", "cod_cuenta", "sistema", "fuente", "fecha_emision",
            "fecha_vto", "total"]
    detalle = fac.reindex(columns=cols).sort_values("fecha_emision", ascending=False)

    return ResultadoTool(
        tool="resumen_facturacion",
        agente=AGENTE,
        resumen=resumen,
        params={"ruc": ruc},
        metricas={
            "facturas": len(fac),
            "facturado_pen": total,
            "notas_credito": len(nc),
            "monto_notas_credito_pen": monto_nc,
            "ratio_nc_sobre_facturado": round(ratio_nc * 100, 3),
            "ticket_promedio_pen": round(total / len(fac), 2),
            "clientes_facturados": int(fac["ruc"].nunique()),
            "cuentas_facturadas": int(fac["cod_cuenta"].nunique()),
            **{f"facturado_{s.lower()}_pen": round(float(r["sum"]), 2)
               for s, r in por_sistema.iterrows()},
        },
        columnas=cols,
        data=detalle.head(MAX_FILAS_DETALLE).to_dict("records"),
        data_filas_totales=len(detalle),
        data_truncada=len(detalle) > MAX_FILAS_DETALLE,
        alertas=alertas,
        trazas=[
            f"ámbito: {ambito} -> {len(fac)} facturas",
            f"suma CHARGE_TOTAL_AMOUNT = {total:,.2f}",
            f"notas de crédito asociadas = {len(nc)} por {monto_nc:,.2f}",
        ],
    )
