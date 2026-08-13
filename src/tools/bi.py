"""
SON-IA · Tools deterministas del Agente de Inteligencia de Negocio.

Convierte los hallazgos de Facturación y Cobranzas en decisiones con monto:
ratio cobrado/facturado, provisión de cobranza dudosa, mesa de aceleración de
recupero, adelanto operativo de caja y detección de anomalías.

Nota sobre la proyección de caja: FECHA_PAGO sólo cubre 2026-06-01 a 2026-07-31,
con un hueco de 12 días antes de la fecha de corte. Extrapolar esa serie
temporal sería inventar. En su lugar se estima la curva empírica de cobro
(distribución del rezago pago-vencimiento) y se aplica como función de riesgo
sobre el aging actual, que es lo que sí se puede sostener con la data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator

from src.contracts import MAX_FILAS_DETALLE, Alerta, ResultadoTool
from src.data_loader import (
    CORTE_DEL_DATASET,
    ORDEN_TRAMOS,
    PCD_TASAS,
    TOL_SALDO,
    get_datos,
    normalizar_fecha_corte,
)
from src.formato import num, pct, pen, top_montos
from src.tools.registro import ArgsConFechaCorte, entero_tolerante, registrar

AGENTE = "AGENTE_BI"


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class ArgsRatio(BaseModel):
    dias: int = Field(30, description="Ventana en días respecto al vencimiento. Por defecto 30.")

    _dias = field_validator("dias", mode="before")(entero_tolerante(30, minimo=1, maximo=365))


class ArgsCorte(ArgsConFechaCorte):
    """Sólo fecha de corte, ya normalizada por la base."""


class ArgsPriorizar(ArgsConFechaCorte):
    top: int = Field(15, description="Cuántos clientes devolver en el ranking.", ge=1, le=100)

    # El LLM manda top="" con toda naturalidad y pydantic lo rechazaba,
    # devolviendo un volcado de validación a la pantalla del usuario.
    _top = field_validator("top", mode="before")(entero_tolerante(15, minimo=1, maximo=100))


# --------------------------------------------------------------------------- #
# Curva empírica de cobro (compartida)
# --------------------------------------------------------------------------- #


def _curva_cobro() -> tuple[pd.Series, pd.DataFrame]:
    """Distribución acumulada del rezago entre pago y vencimiento.

    Devuelve (cdf por día, detalle de pagos cruzados). Es la base de la
    proyección: dice qué fracción del monto cobrado entra dentro de N días
    respecto de la fecha de vencimiento del documento.
    """
    d = get_datos()
    cruce = d.pagos.merge(
        d.facturas[["doc_k", "fecha_vto"]],
        left_on="doc_k_afectada",
        right_on="doc_k",
        how="inner",
    ).dropna(subset=["fecha_vto", "fecha_pago"])
    cruce["rezago"] = (cruce["fecha_pago"] - cruce["fecha_vto"]).dt.days

    total = cruce["monto_pagado"].sum()
    hitos = [0, 7, 15, 30, 60, 90, 180]
    cdf = pd.Series(
        {h: round(100 * cruce.loc[cruce["rezago"] <= h, "monto_pagado"].sum() / total, 2)
         for h in hitos},
        name="pct_monto_acumulado",
    )
    return cdf, cruce


def _prob_cobro_incremental(dias_vencido: float, ventana: int, cdf: pd.Series) -> float:
    """Probabilidad de cobrar en los próximos `ventana` días una factura que ya
    lleva `dias_vencido` vencida, usando la curva empírica como función de
    supervivencia: (F(d+v) - F(d)) / (1 - F(d)).
    """
    def f(x: float) -> float:
        return float(np.interp(x, cdf.index.astype(float), cdf.values)) / 100.0

    fd = min(f(dias_vencido), 0.999)
    fdv = min(f(dias_vencido + ventana), 0.999)
    if fd >= 0.999:
        return 0.0
    return max(0.0, min(1.0, (fdv - fd) / (1 - fd)))


# --------------------------------------------------------------------------- #
# 1 · Ratio cobrado / facturado
# --------------------------------------------------------------------------- #


@registrar(
    nombre="ratio_cobrado_facturado",
    agente=AGENTE,
    args_schema=ArgsRatio,
    etiqueta="Ratio cobrado/facturado y periodo medio de cobro",
    kpi="ratio_cobrado_facturado_30d",
    descripcion=(
        "Calcula el ratio cobrado/facturado global y dentro de una ventana de días respecto al "
        "vencimiento (por defecto 30), más el periodo medio de cobro hacia el vencimiento y la "
        "curva empírica de cobro. Úsala para '¿cómo va el ratio de cobranza?' o '¿en cuánto "
        "tiempo nos pagan?'."
    ),
)
def ratio_cobrado_facturado(dias: int = 30) -> ResultadoTool:
    d = get_datos()
    facturado = round(d.facturas["total"].sum(), 2)
    cobrado = round(d.pagos["monto_pagado"].sum(), 2)
    ratio = cobrado / facturado if facturado else 0.0

    cdf, cruce = _curva_cobro()
    dentro = cruce.loc[cruce["rezago"] <= dias, "monto_pagado"].sum()
    ratio_ventana = dentro / cruce["monto_pagado"].sum() if len(cruce) else 0.0

    rezago_medio = float(cruce["rezago"].mean())
    rezago_mediano = float(cruce["rezago"].median())
    texto_curva = " · ".join(f"≤{h}d {v}%" for h, v in cdf.items() if h in (0, 7, 15, 30, 60))

    resumen = (
        f"RATIO COBRADO/FACTURADO. Facturado {pen(facturado)} · cobrado {pen(cobrado)} → "
        f"ratio global {pct(ratio, 2)}. "
        f"Dentro de {dias} días del vencimiento se cobra el {pct(ratio_ventana, 2)} del monto "
        f"aplicado (KPI oficial de Cobranzas). "
        f"Periodo medio de cobro hacia el vencimiento: {rezago_medio:.1f} días de media, "
        f"{rezago_mediano:.0f} de mediana "
        f"({'se paga antes del vencimiento' if rezago_mediano < 0 else 'se paga después del vencimiento'}). "
        f"Curva empírica de cobro: {texto_curva}. "
        f"Base: {num(len(cruce))} pagos cruzados contra su factura."
    )

    alertas = []
    if ratio < 0.9:
        alertas.append(
            Alerta(
                severidad="media",
                titulo="Ratio cobrado/facturado por debajo del 90%",
                detalle=f"Ratio global {pct(ratio, 2)}: quedan {pen(facturado - cobrado)} sin cobrar",
                impacto_pen=round(facturado - cobrado, 2),
                kpi="ratio_cobrado_facturado_30d",
                accion="Revisar cartera vencida y partidas sin aplicar",
                responsable="Cobranzas",
            )
        )

    return ResultadoTool(
        tool="ratio_cobrado_facturado",
        agente=AGENTE,
        resumen=resumen,
        params={"dias": dias},
        metricas={
            "facturado_pen": facturado,
            "cobrado_pen": cobrado,
            "ratio_global": round(ratio * 100, 2),
            f"ratio_{dias}d": round(ratio_ventana * 100, 2),
            "brecha_pen": round(facturado - cobrado, 2),
            "periodo_medio_cobro_dias": round(rezago_medio, 1),
            "periodo_mediano_cobro_dias": round(rezago_mediano, 1),
            "pagos_cruzados": len(cruce),
            **{f"curva_cobro_{h}d": float(v) for h, v in cdf.items()},
        },
        columnas=["dias", "pct_monto_acumulado"],
        data=[{"dias": int(h), "pct_monto_acumulado": float(v)} for h, v in cdf.items()],
        data_filas_totales=len(cdf),
        alertas=alertas,
        trazas=[
            f"facturado = suma de {len(d.facturas)} facturas = {facturado:,.2f}",
            f"cobrado = suma de {len(d.pagos)} pagos = {cobrado:,.2f}",
            f"curva sobre {len(cruce)} pagos con vencimiento conocido",
        ],
    )


# --------------------------------------------------------------------------- #
# 2 · Provisión de cobranza dudosa
# --------------------------------------------------------------------------- #


@registrar(
    nombre="provision_cobranza_dudosa",
    agente=AGENTE,
    args_schema=ArgsCorte,
    etiqueta="Provisión de cobranza dudosa (PCD)",
    kpi="pcd",
    descripcion=(
        "Calcula la provisión de cobranza dudosa aplicando una matriz de tasas por tramo de "
        "aging (0% en 1-30, 25% en 31-60, 50% en 61-90, 100% en 90+). Devuelve la provisión "
        "por tramo y el total a constituir. Úsala para '¿cuánto hay que provisionar?' o "
        "'¿cuál es la PCD?'."
    ),
)
def provision_cobranza_dudosa(fecha_corte: str = CORTE_DEL_DATASET) -> ResultadoTool:
    d = get_datos()
    vencidas, _ = d.cartera(fecha_corte=fecha_corte, deducir_nc=True, conciliacion="canonica")
    aging = d.aging(vencidas)

    provision = round(float(aging["provision"].sum()), 2)
    cartera = round(float(aging["saldo"].sum()), 2)
    cobertura = provision / cartera if cartera else 0.0

    detalle_tramos = " | ".join(
        f"{t}: {pen(aging.loc[t, 'saldo'])} x {aging.loc[t, 'tasa_pcd']:.0%} = "
        f"{pen(aging.loc[t, 'provision'])}"
        for t in aging.index
    )

    resumen = (
        f"PROVISIÓN DE COBRANZA DUDOSA al {fecha_corte}. "
        f"Sobre una cartera vencida de {pen(cartera)}, la provisión a constituir es "
        f"{pen(provision)} ({pct(cobertura)} de cobertura). "
        f"Desglose: {detalle_tramos}. "
        f"Matriz aplicada: 1-30 0%, 31-60 25%, 61-90 50%, 90+ 100% (criterio conservador; "
        f"la ficha del reto no fija porcentajes, es parametrizable). "
        f"El tramo 90+ ({pen(aging.loc['90+', 'saldo'])}) se provisiona íntegro y es el "
        f"candidato natural para la mesa de aceleración de recupero."
    )

    return ResultadoTool(
        tool="provision_cobranza_dudosa",
        agente=AGENTE,
        resumen=resumen,
        params={"fecha_corte": fecha_corte},
        metricas={
            "fecha_corte": fecha_corte,
            "cartera_vencida_pen": cartera,
            "provision_pen": provision,
            "cobertura_pct": round(cobertura * 100, 2),
            **{
                f"provision_{t.replace('-', '_').replace('+', '_mas')}_pen": float(
                    aging.loc[t, "provision"]
                )
                for t in aging.index
            },
        },
        columnas=["tramo", "facturas", "saldo", "tasa_pcd", "provision"],
        data=aging.reset_index().to_dict("records"),
        data_filas_totales=len(aging),
        alertas=[
            Alerta(
                severidad="alta",
                titulo="Provisión de cobranza dudosa a constituir",
                detalle=f"{pen(provision)} sobre cartera vencida de {pen(cartera)}",
                impacto_pen=provision,
                kpi="pcd",
                accion="Constituir provisión y activar mesa de aceleración sobre el tramo 90+",
                responsable="Contabilidad / Cobranzas",
            )
        ],
        trazas=[
            f"cartera vencida al {fecha_corte} = {cartera:,.2f}",
            f"matriz PCD = {PCD_TASAS}",
            f"provisión = suma(saldo_tramo x tasa_tramo) = {provision:,.2f}",
        ],
    )


# --------------------------------------------------------------------------- #
# 3 · Mesa de aceleración de recupero
# --------------------------------------------------------------------------- #


@registrar(
    nombre="priorizar_recupero",
    agente=AGENTE,
    args_schema=ArgsPriorizar,
    etiqueta="Mesa de aceleración de recupero",
    kpi="reduccion_cxc",
    descripcion=(
        "Prioriza clientes para la gestión de cobranza combinando saldo vencido, antigüedad y "
        "estado SUNAT. Devuelve un ranking accionable con el monto recuperable y la "
        "concentración. Úsala para '¿a quién cobro primero?' o '¿cuáles son los mayores "
        "deudores?'."
    ),
)
def priorizar_recupero(fecha_corte: str = CORTE_DEL_DATASET, top: int = 15) -> ResultadoTool:
    d = get_datos()
    vencidas, _ = d.cartera(fecha_corte=fecha_corte, deducir_nc=True, conciliacion="canonica")

    if vencidas.empty:
        return ResultadoTool(
            tool="priorizar_recupero",
            agente=AGENTE,
            resumen=f"No hay cartera vencida al {fecha_corte}: nada que priorizar.",
            params={"fecha_corte": fecha_corte, "top": top},
            metricas={"clientes": 0, "cartera_vencida_pen": 0.0},
        )

    por_cliente = (
        vencidas.groupby("ruc")
        .agg(
            razon_social=("razon_social", "first"),
            facturas=("doc", "count"),
            saldo=("saldo", "sum"),
            dias_max=("dias_vencido", "max"),
            dias_prom=("dias_vencido", "mean"),
        )
        .reset_index()
    )
    por_cliente = d.clientes_enriquecidos(por_cliente, col_ruc="ruc")

    # Score de priorización: el saldo manda, la antigüedad pondera (más viejo =
    # más urgente pero menos probable), y el riesgo SUNAT escala la urgencia.
    por_cliente["factor_antiguedad"] = 1 + (por_cliente["dias_prom"] / 90).clip(0, 3)
    por_cliente["riesgo_sunat"] = np.where(
        por_cliente["sunat_estado_ruc"].isin(["NO HABIDO", "SIN MAESTRO"]), 1.3, 1.0
    )
    por_cliente["score"] = (
        por_cliente["saldo"] * por_cliente["factor_antiguedad"] * por_cliente["riesgo_sunat"]
    ).round(2)
    ranking = por_cliente.sort_values("score", ascending=False).head(top)

    cartera_total = round(float(vencidas["saldo"].sum()), 2)
    saldo_top = round(float(ranking["saldo"].sum()), 2)
    cobertura = saldo_top / cartera_total if cartera_total else 0.0

    lineas = " | ".join(
        f"{r.ruc} {pen(r.saldo)} ({int(r.facturas)} fact, {int(r.dias_prom)}d"
        f"{', NO HABIDO' if r.sunat_estado_ruc == 'NO HABIDO' else ''})"
        for r in ranking.head(5).itertuples()
    )

    resumen = (
        f"MESA DE ACELERACIÓN DE RECUPERO al {fecha_corte}. "
        f"{num(len(por_cliente))} clientes con saldo vencido por {pen(cartera_total)}. "
        f"Gestionando sólo los {num(len(ranking))} priorizados se cubre {pen(saldo_top)} "
        f"({pct(cobertura)} de la cartera vencida). "
        f"Top 5: {lineas}. "
        f"El score pondera saldo x antigüedad x riesgo SUNAT: prioriza dinero grande y viejo, "
        f"y escala 30% los clientes NO HABIDO o fuera del maestro."
    )

    cols = ["ruc", "razon_social", "facturas", "saldo", "dias_prom", "dias_max",
            "sunat_estado_ruc", "score"]
    detalle = ranking.reindex(columns=cols)

    return ResultadoTool(
        tool="priorizar_recupero",
        agente=AGENTE,
        resumen=resumen,
        params={"fecha_corte": fecha_corte, "top": top},
        metricas={
            "clientes_con_saldo": len(por_cliente),
            "cartera_vencida_pen": cartera_total,
            "top_n": len(ranking),
            "saldo_priorizado_pen": saldo_top,
            "cobertura_pct": round(cobertura * 100, 1),
            "mayor_deudor_ruc": str(ranking.iloc[0]["ruc"]),
            "mayor_deudor_pen": round(float(ranking.iloc[0]["saldo"]), 2),
        },
        columnas=cols,
        data=detalle.to_dict("records"),
        data_filas_totales=len(detalle),
        alertas=[
            Alerta(
                severidad="alta",
                titulo="Cartera concentrada: gestión focalizada de alto retorno",
                detalle=(
                    f"{len(ranking)} clientes concentran {pen(saldo_top)} "
                    f"({pct(cobertura)}) del saldo vencido"
                ),
                impacto_pen=saldo_top,
                kpi="reduccion_cxc",
                accion=f"Abrir mesa de recupero sobre los {len(ranking)} clientes priorizados",
                responsable="Cobranzas",
                clave="concentracion_cartera",
            )
        ],
        trazas=[
            f"cartera vencida al {fecha_corte} = {len(vencidas)} facturas / {cartera_total:,.2f}",
            f"agrupado por RUC -> {len(por_cliente)} clientes",
            "score = saldo x (1 + dias_prom/90 acotado a 3) x (1.3 si NO HABIDO o sin maestro)",
            f"top {top} cubre {cobertura:.1%} de la cartera",
        ],
    )


# --------------------------------------------------------------------------- #
# 4 · Adelanto operativo de caja
# --------------------------------------------------------------------------- #


@registrar(
    nombre="proyeccion_caja",
    agente=AGENTE,
    args_schema=ArgsCorte,
    etiqueta="Adelanto operativo de caja a 30/60/90",
    kpi="reduccion_cxc",
    descripcion=(
        "Proyecta la cobranza esperada a 30, 60 y 90 días aplicando la curva empírica de cobro "
        "sobre la cartera vencida y por vencer. Úsala para '¿cuánto vamos a cobrar el próximo "
        "mes?' o '¿cómo viene la caja?'."
    ),
)
def proyeccion_caja(fecha_corte: str = CORTE_DEL_DATASET) -> ResultadoTool:
    d = get_datos()
    # Se resuelve una vez y se usa el valor ya normalizado: más abajo entra en
    # un pd.Timestamp directo, que con el centinela sin resolver reventaría.
    fecha_corte = normalizar_fecha_corte(fecha_corte)
    vencidas, por_vencer = d.cartera(
        fecha_corte=fecha_corte, deducir_nc=True, conciliacion="canonica"
    )
    cdf, cruce = _curva_cobro()

    base = pd.concat(
        [
            vencidas[["saldo", "dias_vencido"]],
            por_vencer.assign(dias_vencido=lambda x: -(x["fecha_vto"] - pd.Timestamp(fecha_corte)).dt.days)[
                ["saldo", "dias_vencido"]
            ],
        ],
        ignore_index=True,
    )

    proyeccion = {}
    for ventana in (30, 60, 90):
        esperado = sum(
            fila.saldo * _prob_cobro_incremental(fila.dias_vencido, ventana, cdf)
            for fila in base.itertuples()
        )
        proyeccion[ventana] = round(esperado, 2)

    expuesto = round(float(base["saldo"].sum()), 2)
    riesgo = round(expuesto - proyeccion[90], 2)

    resumen = (
        f"ADELANTO OPERATIVO DE CAJA desde el {fecha_corte}. "
        f"Saldo total expuesto {pen(expuesto)} "
        f"({pen(vencidas['saldo'].sum())} vencido + {pen(por_vencer['saldo'].sum())} por vencer). "
        f"Cobranza esperada: {pen(proyeccion[30])} a 30 días, {pen(proyeccion[60])} a 60 días, "
        f"{pen(proyeccion[90])} a 90 días. "
        f"Quedaría en riesgo {pen(riesgo)} más allá de los 90 días. "
        f"Método: curva empírica de cobro sobre {num(len(cruce))} pagos históricos aplicada como "
        f"función de riesgo al aging actual. No se extrapola la serie temporal de pagos porque "
        f"sólo cubre {cruce['fecha_pago'].min():%Y-%m-%d} a {cruce['fecha_pago'].max():%Y-%m-%d}."
    )

    return ResultadoTool(
        tool="proyeccion_caja",
        agente=AGENTE,
        resumen=resumen,
        params={"fecha_corte": fecha_corte},
        metricas={
            "fecha_corte": fecha_corte,
            "saldo_expuesto_pen": expuesto,
            "vencido_pen": round(float(vencidas["saldo"].sum()), 2),
            "por_vencer_pen": round(float(por_vencer["saldo"].sum()), 2),
            "proyeccion_30d_pen": proyeccion[30],
            "proyeccion_60d_pen": proyeccion[60],
            "proyeccion_90d_pen": proyeccion[90],
            "en_riesgo_mas_90d_pen": riesgo,
        },
        columnas=["ventana_dias", "cobranza_esperada_pen"],
        data=[{"ventana_dias": k, "cobranza_esperada_pen": v} for k, v in proyeccion.items()],
        data_filas_totales=len(proyeccion),
        alertas=[
            Alerta(
                severidad="media",
                titulo="Saldo con baja probabilidad de cobro a 90 días",
                detalle=f"{pen(riesgo)} no se cobraría dentro de los próximos 90 días",
                impacto_pen=riesgo,
                kpi="reduccion_cxc",
                accion="Anticipar gestión sobre los tramos más antiguos",
                responsable="Cobranzas / Finanzas",
            )
        ],
        trazas=[
            f"base = {len(base)} documentos con saldo ({expuesto:,.2f})",
            f"curva empírica sobre {len(cruce)} pagos: {dict(cdf)}",
            "prob. incremental = (F(d+v) - F(d)) / (1 - F(d)) por documento",
        ],
    )


# --------------------------------------------------------------------------- #
# 5 · Anomalías
# --------------------------------------------------------------------------- #


class ArgsAnomalias(BaseModel):
    """Ojo con la descripción del filtro.

    Este es el único argumento de la tool, y un modelo que ve un tool-call con
    un solo argumento tiende a rellenarlo. Medido: en una corrida con agentes
    el LLM pasó 'critica' por su cuenta y se perdieron 2.048 de 2.105 registros
    y dos de las tres alertas; en la corrida anterior lo dejó vacío y salieron
    los 7 tipos. La misma demo daba resultados distintos según el humor del
    modelo.

    Agrava que el nombre engaña: 'critica' es el valor más RESTRICTIVO, no el
    mínimo. Por eso la descripción arranca diciendo que se deje vacío.
    """

    severidad_minima: str | None = Field(
        None,
        description=(
            "DÉJALO VACÍO salvo que te pidan expresamente filtrar. Vacío devuelve "
            "el cuadro completo de anomalías, que es lo que se necesita casi siempre. "
            "Si filtras, 'critica' es el valor MÁS restrictivo (solo deja pasar lo "
            "crítico) y 'baja' el más amplio."
        ),
    )

    @field_validator("severidad_minima", mode="before")
    @classmethod
    def _severidad(cls, v):
        """Cualquier cosa que no sea una severidad conocida significa no filtrar.

        Un modelo llegó a mandar `severidad_minima=1`, que pydantic rechazaba
        de plano. Ante la duda es mejor devolver el cuadro completo que un
        error o, peor, un recorte silencioso.
        """
        if v is None:
            return None
        texto = str(v).strip().lower()
        return texto if texto in {"critica", "alta", "media", "baja", "info"} else None


@registrar(
    nombre="detectar_anomalias",
    agente=AGENTE,
    args_schema=ArgsAnomalias,
    etiqueta="Anomalías de datos y de proceso",
    kpi="aseguramiento_ingresos",
    descripcion=(
        "Detecta inconsistencias en los datos y en el proceso: pagos en moneda distinta a la "
        "facturada, facturas sobrepagadas, documentos con monto cero o negativo, fechas con "
        "formato inconsistente entre sistemas, notas de crédito mayores a la factura y pagos "
        "duplicados. Úsala para '¿hay algo raro en los datos?' o '¿qué inconsistencias hay?'."
    ),
)
def detectar_anomalias(severidad_minima: str | None = None) -> ResultadoTool:
    d = get_datos()
    hallazgos: list[dict] = []

    def añadir(
        tipo: str,
        n: int,
        monto: float,
        detalle: str,
        severidad: str = "media",
        titulo: str = "",
    ) -> None:
        """Registra un hallazgo.

        `tipo` es la clave técnica, que va a las métricas y sirve de clave de
        deduplicación. `titulo` es cómo se llama en el informe: derivar el
        título del tipo daba cosas como "Anomalía: fecha vto formato
        inconsistente", que en una pantalla de dirección se lee como salida de
        depuración.
        """
        if n:
            hallazgos.append(
                {
                    "tipo": tipo,
                    "titulo": titulo or f"Anomalía: {tipo.replace('_', ' ')}",
                    "registros": int(n),
                    "monto_pen": round(float(monto), 2),
                    "detalle": detalle,
                    "severidad": severidad,
                }
            )

    # -- moneda ---------------------------------------------------------------
    usd = d.pagos[d.pagos["moneda"] != "PEN"]
    añadir(
        "pago_moneda_distinta",
        len(usd),
        usd["monto_pagado"].sum(),
        "Pagos en moneda distinta a PEN contra facturas emitidas en PEN. El tipo de cambio "
        "implícito es incoherente (hay pagos parciales): NO convertir automáticamente.",
        "alta",
        titulo="Pagos en moneda distinta a la facturada")

    # -- sobrepagos -----------------------------------------------------------
    saldos = d.saldos(deducir_nc=True, conciliacion="canonica")
    sobre = saldos[saldos["saldo"] < -TOL_SALDO]
    añadir(
        "factura_sobrepagada",
        len(sobre),
        -sobre["saldo"].sum(),
        "Facturas donde lo aplicado supera el total del documento: posible doble aplicación "
        "o pago a cuenta mal imputado.",
        "media",
        titulo="Facturas con más aplicado que su importe")

    # -- montos inválidos -----------------------------------------------------
    cero = d.facturas[d.facturas["total"].fillna(0) <= 0]
    añadir("factura_monto_invalido", len(cero), cero["total"].sum(),
           "Facturas con importe total cero o negativo.", "baja",
        titulo="Facturas con importe cero o negativo")

    sin_moneda = d.facturas[d.facturas["moneda"].isna()]
    añadir("factura_sin_moneda", len(sin_moneda), sin_moneda["total"].sum(),
           "Facturas sin moneda informada.", "baja",
        titulo="Facturas sin moneda informada")

    # -- fechas ---------------------------------------------------------------
    mal = d.diagnostico["facturas_fecha_malformada"]
    añadir(
        "fecha_vto_formato_inconsistente",
        mal["n"],
        mal["monto"],
        f"Facturas con FECHA_VTO en formato YYYYMMDD en vez de YYYY-MM-DD, todas del sistema "
        f"{list(mal['sistemas'])}. Un parseo de formato único las descarta y desaparecen de la "
        f"cartera: es la causa de que el reporte base subestime la deuda.",
        "critica",
        titulo="Facturas que el reporte actual no llega a ver")

    # -- notas de crédito -----------------------------------------------------
    nc_mayor = saldos[saldos["nc"] > saldos["total"] + TOL_SALDO]
    añadir("nota_credito_mayor_factura", len(nc_mayor), nc_mayor["nc"].sum(),
           "Notas de crédito por encima del importe de la factura afectada.", "alta",
        titulo="Notas de crédito por encima de la factura")

    nc_huerfana = d.notas_credito[
        ~d.notas_credito["doc_k_afectada"].isin(set(d.facturas["doc_k"]))
    ]
    añadir("nota_credito_sin_factura", len(nc_huerfana), nc_huerfana["monto"].sum(),
           "Notas de crédito que referencian una factura fuera del maestro.", "media",
        titulo="Notas de crédito sin factura en el maestro")

    # -- duplicados -----------------------------------------------------------
    dup = d.pagos[d.pagos.duplicated(subset=["factura_afectada", "fecha_pago", "monto_pagado"],
                                     keep=False)]
    añadir("pago_duplicado", len(dup), dup["monto_pagado"].sum(),
           "Pagos idénticos en documento, fecha e importe: posible doble carga.", "alta",
        titulo="Pagos idénticos cargados dos veces")

    # -- integridad de maestros ----------------------------------------------
    huerfanas = d.diagnostico["planta"]["lineas_activas_sin_cuenta"]
    añadir("linea_activa_sin_cuenta", huerfanas, 0.0,
           "Líneas móviles activas sin COD_CUENTA: no existe documento que emitir.", "alta",
        titulo="Líneas activas sin cuenta asignada")

    fuera = d.facturas[~d.facturas["ruc"].isin(set(d.clientes["ruc"]))]
    añadir("factura_ruc_fuera_maestro", len(fuera), fuera["total"].sum(),
           "Facturas emitidas a RUC ausente del maestro de clientes: imposible validar SUNAT.",
           "media",
        titulo="Facturas a RUC ausente del maestro")

    if severidad_minima:
        from src.contracts import PESO_SEVERIDAD

        tope = PESO_SEVERIDAD.get(str(severidad_minima).strip().lower(), 4)
        hallazgos = [h for h in hallazgos if PESO_SEVERIDAD[h["severidad"]] <= tope]

    df = pd.DataFrame(hallazgos)
    total_reg = int(df["registros"].sum()) if not df.empty else 0
    criticas = df[df["severidad"].isin(["critica", "alta"])] if not df.empty else pd.DataFrame()

    texto = " | ".join(
        f"{h['tipo']}: {h['registros']} reg" + (f" {pen(h['monto_pen'])}" if h["monto_pen"] else "")
        for h in hallazgos
    )
    resumen = (
        f"ANOMALÍAS DETECTADAS. {num(len(hallazgos))} tipos distintos sobre {num(total_reg)} "
        f"registros. {texto}. "
        f"{num(len(criticas))} tipos son de severidad crítica o alta. "
        f"La raíz común de las más caras es la coexistencia de dos sistemas de facturación "
        f"(AMDOCS e ISIS) sin normalización de formatos: fechas y correlativos distintos."
    )

    alertas = [
        Alerta(
            severidad=h["severidad"],  # type: ignore[arg-type]
            titulo=h["titulo"],
            detalle=h["detalle"],
            impacto_pen=h["monto_pen"],
            kpi="aseguramiento_ingresos",
            accion="Corregir en origen y añadir validación automática al ciclo",
            responsable="TI / Facturación",
            clave=h["tipo"],
        )
        for h in hallazgos
        if h["severidad"] in ("critica", "alta")
    ]

    return ResultadoTool(
        tool="detectar_anomalias",
        agente=AGENTE,
        resumen=resumen,
        metricas={
            "tipos_anomalia": len(hallazgos),
            "registros_afectados": total_reg,
            "monto_involucrado_pen": round(float(df["monto_pen"].sum()), 2) if not df.empty else 0.0,
            **{h["tipo"]: h["registros"] for h in hallazgos},
        },
        columnas=["tipo", "registros", "monto_pen", "severidad", "detalle"],
        data=hallazgos,
        data_filas_totales=len(hallazgos),
        alertas=alertas,
        trazas=[
            f"universo: {len(d.facturas)} facturas, {len(d.pagos)} pagos, "
            f"{len(d.notas_credito)} notas de crédito, {len(d.planta_unificada)} servicios",
            f"{len(hallazgos)} tipos de anomalía detectados sobre {total_reg} registros",
        ],
    )
