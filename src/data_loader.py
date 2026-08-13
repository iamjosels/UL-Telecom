"""
SON-IA · Carga robusta de los 6 CSV del ciclo del ingreso B2B.

Esta es LA pieza crítica del sistema: toda cifra que el demo reporta nace aquí.
Si este módulo parsea mal, el resto miente en silencio. Por eso termina con
`_verificar_estructura()`, que convierte un error silencioso en un fallo ruidoso.

Trampas reales de esta data (verificadas sobre los archivos, no supuestas):

  1. COD_CUENTA / COD_CLIENTE traen ceros a la izquierda ("047674606") y largo
     variable. Todo se lee con dtype=str o los joins pierden filas en silencio.
  2. FECHA_VTO trae DOS formatos mezclados en la MISMA columna: 3,307 en
     "YYYY-MM-DD" y 57 en "YYYYMMDD". Un parseo de formato único descarta esas
     57 facturas (S/137,200, ninguna pagada). Las 57 son 100% SISTEMA=ISIS.
  3. El RUC se llama NRO_IDENTIFICACION_FISCAL en pagos y
     NUMERO_IDENTIFICACION_FISCAL en las otras cinco tablas.
  4. Los montos son texto con decimal de punto inicial (".85" -> 0.85).
  5. Planta fija usa "YYYY-MM-DD HH:MM:SS" con centinelas basura (1967-09-01,
     1970-01-01 05:31:00); planta móvil usa "DD/MM/YYYY".
  6. El maestro de clientes NO cubre toda la data (solo 1,493 de 3,364
     facturas). Todo join contra clientes es LEFT: "fuera del maestro" es un
     hallazgo, no un error.
  7. Los pagos de ISIS referencian el documento SIN el cero inicial del
     correlativo ("S300-248301" vs "S300-0248301" en el maestro). La clave
     canónica `canon_doc` lo resuelve con 0 colisiones en 3,364 facturas.
  8. Hay 2 líneas móviles ACTIVAS con COD_CUENTA nulo. Contar cuentas con
     `set()` mete ese nulo como si fuera una cuenta más: de ahí salen el
     "1,572" y el "423" de CONTEXT.md. Lo correcto es 1,571 cuentas activas
     identificables y 422 sin factura, y reportar las 2 líneas huérfanas como
     hallazgo propio: sin cuenta no hay documento que emitir, así que son
     100% no facturables.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Constantes de negocio
# --------------------------------------------------------------------------- #

RAIZ = Path(__file__).resolve().parents[1]

#: El dataset que viene con el repositorio. Es el origen de arranque y el que
#: se restaura cuando alguien descarta un corte subido.
DATA_DEMO = RAIZ / "data"

#: Carpeta viva. Cambia cuando se carga otro corte; `DATA` se conserva como
#: alias porque hay scripts que lo importan.
_ORIGEN: Path = DATA_DEMO
DATA = DATA_DEMO

#: Sidecar opcional dentro de la carpeta del dataset con la fecha de corte.
#: El demo lo lleva escrito para que sus cifras no se muevan de un día para
#: otro; un dataset sin él deriva el corte de sus propias fechas.
ARCHIVO_CORTE = "corte.txt"

#: Sentinela para los argumentos por defecto.
#:
#: Un valor por defecto de función se evalúa al importar el módulo, así que no
#: puede llevar una fecha que depende del dataset que esté cargado en ese
#: momento. Quien lo reciba lo resuelve con `fecha_corte_defecto()` en la
#: llamada, no antes.
CORTE_DEL_DATASET = "__corte_del_dataset__"

#: Umbral bajo el cual un saldo se considera cancelado. Los CONTEOS de facturas
#: son hipersensibles a este valor (476/487/504/516/520 según el umbral y el
#: modo); los MONTOS varían menos de S/0.30. Por eso el reporte lidera con
#: montos y siempre imprime la vista (A/B/C) junto a la cifra.
TOL_SALDO = 0.01

IGV_TASA = 0.18

#: Aging de cartera. Vencer hoy (dias = 0) NO cuenta como vencido.
ORDEN_TRAMOS = ["1-30", "31-60", "61-90", "90+"]
BINS_TRAMOS = [0, 30, 60, 90, np.inf]

#: Provisión de cobranza dudosa. No está definida en la ficha del reto ni en
#: CONTEXT.md; es el criterio conservador estándar en telco. Configurable.
PCD_TASAS = {"1-30": 0.00, "31-60": 0.25, "61-90": 0.50, "90+": 1.00}

ARCHIVOS = {
    "clientes": "001_TBL_CLIENTES_B2B.csv",
    "planta_fija": "002_TBL_PLANTA_FIJA_B2B.csv",
    "planta_movil": "003_TBL_PLANTA_MOVIL_B2B.csv",
    "pagos": "004_TBL_PAGOS_B2B.csv",
    "facturas": "005_TBL_FACTURAS_B2B.csv",
    "notas_credito": "006_TBL_NOTAS_CREDITO_B2B.csv",
}

#: keep_default_na=False + na_values=[""] es deliberado: si no, pandas
#: convierte un "NA"/"NULL" literal dentro de un RUC o código en NaN y rompe
#: un join sin avisar.
OPCIONES_LECTURA = dict(
    sep="|", encoding="latin-1", dtype=str, keep_default_na=False, na_values=[""]
)

#: Formatos probados EN ORDEN. Nunca usar infer_datetime_format: resuelve
#: "03/04/2024" como MM/DD por bloque de filas y en silencio.
FORMATOS_FECHA = (
    "%Y-%m-%d",
    "%Y%m%d",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d-%m-%Y",
)

FECHA_MIN = pd.Timestamp("1995-01-01")
FECHA_MAX = pd.Timestamp("2035-12-31")


# --------------------------------------------------------------------------- #
# Helpers de parseo
# --------------------------------------------------------------------------- #


def a_fecha(s: pd.Series, centinelas: bool = True) -> pd.Series:
    """Parser tolerante multi-formato, columna por columna.

    Prueba los formatos EXPLÍCITOS de FORMATOS_FECHA en orden, aplicando cada
    uno solo a las filas que aún no resolvieron. Es lo que recupera las 57
    facturas ISIS con FECHA_VTO en "YYYYMMDD".

    Con `centinelas=True` enmascara fechas fuera de [1995, 2035], que en planta
    fija son basura de migración (1967-09-01, 1970-01-01 05:31:00 = epoch Unix).
    """
    s = s.astype(str).str.strip().replace({"": None, "nan": None, "None": None, "NaT": None})
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")

    for fmt in FORMATOS_FECHA:
        faltan = out.isna() & s.notna()
        if not faltan.any():
            break
        out.loc[faltan] = pd.to_datetime(s[faltan], format=fmt, errors="coerce")

    if centinelas:
        out = out.mask((out < FECHA_MIN) | (out > FECHA_MAX))
    return out


def formato_detectado(s: pd.Series) -> dict[str, int]:
    """Cuenta cuántas filas matchean cada formato de fecha.

    Alimenta el diagnóstico y `detectar_anomalias()`: es la evidencia dura de
    que FECHA_VTO viene con dos formatos mezclados.
    """
    s = s.astype(str).str.strip()
    patrones = {
        "ISO": r"\d{4}-\d{2}-\d{2}",
        "YYYYMMDD": r"\d{8}",
        "DD/MM/YYYY": r"\d{2}/\d{2}/\d{4}",
        "ISO_HORA": r"\d{4}-\d{2}-\d{2} .+",
        "DDMM_HORA": r"\d{2}/\d{2}/\d{4} .+",
    }
    return {k: int(s.str.fullmatch(v).sum()) for k, v in patrones.items()}


def a_num(s: pd.Series) -> pd.Series:
    """Texto -> float. Maneja '.85' -> 0.85 y '1,234.56' -> 1234.56."""
    return pd.to_numeric(
        s.astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace(r"^\.", "0.", regex=True)
        .str.replace(r"^-\.", "-0.", regex=True)
        .replace({"": None, "nan": None, "None": None}),
        errors="coerce",
    )


_RE_DOC = re.compile(r"^([A-Z0-9]+)-0*(\d+)$")


def canon_doc(v) -> str:
    """Clave canónica de documento fiscal: normaliza el cero inicial.

    El maestro de facturas guarda 'S300-0248301'; el archivo de pagos de ISIS
    referencia 'S300-248301'. Ambos colapsan a 'S300-248301'.

    Verificado sobre la data real: 0 colisiones en las 3,364 facturas, y sube
    la conciliación pago->factura de 97.91% a 99.77% (66 pagos recuperados,
    S/106,157.92).
    """
    s = str(v).strip().upper()
    m = _RE_DOC.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return re.sub(r"[^0-9A-Z]", "", s)


def limpiar_texto(df: pd.DataFrame) -> pd.DataFrame:
    """Strip a toda columna de texto.

    Obligatorio, no cosmético: sin esto un RUC con espacio final cuenta como
    cliente distinto y "275 clientes afectados" se convierte en 277.
    """
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.strip().replace({"nan": None, "None": None, "": None})
    return df


#: Palabras que un LLM suele mandar en vez de una fecha ISO.
_PALABRAS_HOY = {
    "hoy",
    "today",
    "actual",
    "ahora",
    "now",
    "corte",
    "fecha de corte",
    "",
    CORTE_DEL_DATASET,
}


def normalizar_fecha_corte(valor, defecto: str | None = None) -> str:
    """Devuelve siempre una fecha válida en formato YYYY-MM-DD.

    El router deja que el LLM proponga los argumentos, y un modelo manda con
    naturalidad `fecha_corte="hoy"`. Sin esto, `pd.Timestamp("hoy")` lanza
    DateParseError y la respuesta al usuario se convierte en un traceback.
    Se acepta cualquiera de los formatos de la data y se cae al corte por
    defecto ante cualquier cosa que no se pueda interpretar.

    `defecto=None` significa "el corte del dataset cargado", resuelto aquí y no
    al importar el módulo: con otro dataset la fecha es otra.
    """
    if defecto is None:
        defecto = fecha_corte_defecto()
    if valor is None:
        return defecto
    texto = str(valor).strip()
    if texto.lower() in _PALABRAS_HOY or texto == CORTE_DEL_DATASET:
        return defecto
    fecha = a_fecha(pd.Series([texto]), centinelas=False).iloc[0]
    return defecto if pd.isna(fecha) else fecha.strftime("%Y-%m-%d")


def clasificar_aging(dias: pd.Series) -> pd.Series:
    """Días vencidos -> tramo de aging, como categoría ordenada.

    Bordes cerrados a la derecha: 30 -> '1-30'; 31 -> '31-60'; 90 -> '61-90';
    91 -> '90+'. dias <= 0 queda fuera (no está vencido).
    """
    tramos = pd.cut(
        dias, bins=BINS_TRAMOS, labels=ORDEN_TRAMOS, right=True, include_lowest=False
    )
    return tramos.astype("category").cat.set_categories(ORDEN_TRAMOS, ordered=True)


# --------------------------------------------------------------------------- #
# Normalización por tabla
# --------------------------------------------------------------------------- #

_REN_CLIENTES = {
    "SEGMENTO_PAIS": "segmento",
    "TIPO_DOCUMENTO": "tipo_documento",
    "NUMERO_IDENTIFICACION_FISCAL": "ruc",
    "RAZON_SOCIAL": "razon_social",
    "SUNAT_ESTADO_RUC": "sunat_estado_ruc",
    "SUNAT_ESTADO_CONTRIBUYENTE": "sunat_estado_contribuyente",
    "SUNAT_DEPARTAMENTO": "departamento",
    "SUNAT_PROVINCIA": "provincia",
    "SUNAT_DISTRITO": "distrito",
}

_REN_FIJA = {
    "SEGMENTO_PAIS": "segmento",
    "NUMERO_IDENTIFICACION_FISCAL": "ruc",
    "RAZON_SOCIAL": "razon_social",
    "COD_CLIENTE": "cod_cliente",
    "COD_CUENTA": "cod_cuenta",
    "CICLO": "ciclo",
    "FECHAALTA": "fecha_alta",
    "STATUS_DESC": "estado",
    "LN_PLAN_DESC": "plan_voz",
    "INT_PLAN_DESC": "plan_internet",
    "TV_PLAN_DESC": "plan_tv",
    "SUB_MAIN_OFFER_DESC": "oferta_principal",
    "ES_MOVISTARTOTAL": "es_movistar_total",
}

_REN_MOVIL = {
    "SEGMENTO_PAIS": "segmento",
    "NUMERO_IDENTIFICACION_FISCAL": "ruc",
    "RAZON_SOCIAL": "razon_social",
    "COD_CLIENTE": "cod_cliente",
    "COD_CUENTA": "cod_cuenta",
    "PRODUCTO": "producto",
    "FECHA_ALTA": "fecha_alta",
    "ESTADO_LINEA": "estado",
    "TIPO_LINEA": "tipo_linea",
    "PLAN_PRINCIPAL": "plan_principal",
    "PROM_DSCTO": "promocion_descuento",
    "Fecha_Fin_Permanencia": "fin_permanencia",
}

_REN_PAGOS = {
    "NRO_IDENTIFICACION_FISCAL": "ruc",  # ¡ojo! aquí se llama distinto
    "RAZON_SOCIAL": "razon_social",
    "COD_CLIENTE": "cod_cliente",
    "COD_CUENTA": "cod_cuenta",
    "SISTEMA": "sistema",
    "FACTURA_AFECTADA": "factura_afectada",
    "FECHA_PAGO": "fecha_pago",
    "MONEDA_FACTURA": "moneda",
    "SUBTOTAL": "subtotal",
    "IGV": "igv",
    "MONTO_PAGADO": "monto_pagado",
}

_REN_FACTURAS = {
    "NUMERO_IDENTIFICACION_FISCAL": "ruc",
    "RAZON_SOCIAL": "razon_social",
    "COD_CLIENTE": "cod_cliente",
    "COD_CUENTA": "cod_cuenta",
    "NRO_DOC_FISCAL": "doc",
    "FUENTE": "fuente",
    "SISTEMA": "sistema",
    "FECHA_EMISION": "fecha_emision",
    "FECHA_VTO": "fecha_vto",
    "MONEDA": "moneda",
    "CHARGE_NET_AMOUNT": "neto",
    "CHARGE_IGV_INVOICE": "igv",
    "CHARGE_TOTAL_AMOUNT": "total",
}

_REN_NC = {
    "NUMERO_IDENTIFICACION_FISCAL": "ruc",
    "RAZON_SOCIAL": "razon_social",
    "COD_CLIENTE": "cod_cliente",
    "COD_CUENTA": "cod_cuenta",
    "NRO_DOC_FISCAL": "doc",
    "FUENTE": "fuente",
    "SISTEMA": "sistema",
    "FACTURA_AFECTADA": "factura_afectada",
    "FECHAEMISION": "fecha_emision",
    "MONEDA": "moneda",
    "MONTO_SIN_IGV": "monto_sin_igv",
    "SUBTOTAL": "igv",  # en esta tabla SUBTOTAL es la porción de IGV
    "MONTO": "monto",
}


def _renombrar(df: pd.DataFrame, mapa: dict[str, str]) -> pd.DataFrame:
    """Renombra según el mapa y pasa el resto a snake_case."""
    resto = {c: c.lower() for c in df.columns if c not in mapa}
    return df.rename(columns={**mapa, **resto})


# --------------------------------------------------------------------------- #
# Contenedor de datos
# --------------------------------------------------------------------------- #


@dataclass
class Datos:
    """Las 6 tablas normalizadas + vistas derivadas, cacheadas en memoria."""

    clientes: pd.DataFrame
    planta_fija: pd.DataFrame
    planta_movil: pd.DataFrame
    pagos: pd.DataFrame
    facturas: pd.DataFrame
    notas_credito: pd.DataFrame
    planta_unificada: pd.DataFrame
    diagnostico: dict = field(default_factory=dict)

    #: Corte de ESTE dataset: el de `corte.txt` si lo trae, o el derivado de
    #: sus propias fechas. Deja de ser una constante del módulo porque deja de
    #: ser cierta en cuanto se carga otro corte.
    fecha_corte: str = ""
    #: Carpeta de la que salieron estas tablas.
    origen: str = ""

    # -- saldos ------------------------------------------------------------- #

    def saldos(
        self,
        deducir_nc: bool = True,
        conciliacion: str = "canonica",
        solo_fechas_validas: bool = False,
    ) -> pd.DataFrame:
        """Facturas + pagos + notas de crédito -> saldo por documento.

        Un solo código produce las tres vistas del demo:

        =====  ==========================================  ==================
        Vista  Parámetros                                  Cartera @ corte
        =====  ==========================================  ==================
        A      conciliacion="exacta", deducir_nc=False,    S/18,297.98
               solo_fechas_validas=True                    (baseline CONTEXT)
        B      conciliacion="exacta", deducir_nc=True      S/153,976.98
        C      conciliacion="canonica", deducir_nc=True    S/47,819.06
        =====  ==========================================  ==================

        `solo_fechas_validas=True` emula el parseo ingenuo de fecha: descarta
        las 57 facturas ISIS con FECHA_VTO en "YYYYMMDD", que es exactamente lo
        que hace el sistema actual.

        Parameters
        ----------
        deducir_nc:
            Restar las notas de crédito del saldo. True es lo contablemente
            correcto; False reproduce el baseline documentado.
        conciliacion:
            "exacta" cruza por el número de documento literal (la vista del
            sistema actual). "canonica" cruza por `canon_doc`, recuperando los
            66 pagos de ISIS con el cero inicial desalineado.
        solo_fechas_validas:
            Excluir las facturas cuya FECHA_VTO venía malformada.
        """
        if conciliacion not in ("exacta", "canonica"):
            raise ValueError(f"conciliacion debe ser 'exacta' o 'canonica', no {conciliacion!r}")

        f = self.facturas.copy()
        clave_fac = "doc" if conciliacion == "exacta" else "doc_k"
        clave_ref = "factura_afectada" if conciliacion == "exacta" else "doc_k_afectada"

        pagado = self.pagos.groupby(clave_ref)["monto_pagado"].sum()
        nc = self.notas_credito.groupby(clave_ref)["monto"].sum()

        f["pagado"] = f[clave_fac].map(pagado).fillna(0.0)
        f["nc"] = f[clave_fac].map(nc).fillna(0.0)
        f["saldo"] = (f["total"] - f["pagado"] - (f["nc"] if deducir_nc else 0.0)).round(2)

        f["estado_doc"] = np.select(
            [f["saldo"] <= TOL_SALDO, f["pagado"] <= 0],
            ["CANCELADA", "PENDIENTE"],
            default="PARCIAL",
        )

        if solo_fechas_validas:
            f = f[~f["fecha_vto_malformada"]]
        return f

    # -- cartera ------------------------------------------------------------ #

    def cartera(
        self,
        fecha_corte: str | pd.Timestamp = CORTE_DEL_DATASET,
        **kwargs,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Devuelve (vencidas_con_aging, por_vencer) al corte indicado.

        `kwargs` se pasan tal cual a :meth:`saldos`, así que la cartera hereda
        las tres vistas A/B/C.
        """
        # Normalizado aquí, que es el embudo por el que pasa toda la cartera:
        # así el centinela CORTE_DEL_DATASET se resuelve al corte del dataset
        # cargado y una llamada directa desde un script no revienta.
        corte = pd.Timestamp(normalizar_fecha_corte(fecha_corte))
        f = self.saldos(**kwargs)
        con_saldo = f[f["saldo"] > TOL_SALDO].copy()

        tiene_fecha = con_saldo["fecha_vto"].notna()
        vencidas = con_saldo[tiene_fecha & (con_saldo["fecha_vto"] < corte)].copy()
        por_vencer = con_saldo[tiene_fecha & (con_saldo["fecha_vto"] >= corte)].copy()

        vencidas["dias_vencido"] = (corte - vencidas["fecha_vto"]).dt.days
        vencidas["tramo"] = clasificar_aging(vencidas["dias_vencido"])
        return vencidas, por_vencer

    def aging(self, vencidas: pd.DataFrame) -> pd.DataFrame:
        """Resumen por tramo. observed=False para que un tramo vacío salga en
        cero y el aging sume visualmente en el reporte."""
        g = (
            vencidas.groupby("tramo", observed=False)["saldo"]
            .agg(facturas="count", saldo="sum")
            .reindex(ORDEN_TRAMOS)
            .fillna(0.0)
        )
        g["facturas"] = g["facturas"].astype(int)
        g["saldo"] = g["saldo"].round(2)
        g["tasa_pcd"] = [PCD_TASAS[t] for t in g.index]
        g["provision"] = (g["saldo"] * g["tasa_pcd"]).round(2)
        return g

    # -- planta ------------------------------------------------------------- #

    def cuentas_activas(self) -> set[str]:
        """COD_CUENTA distintos con al menos un servicio activo (fija o móvil).

        `.dropna()` es deliberado: 2 líneas móviles activas no tienen cuenta.
        Contarlas como una cuenta más es el error que produce el 1,572 de
        CONTEXT.md; se reportan aparte vía `lineas_activas_sin_cuenta`.
        """
        p = self.planta_unificada
        return set(p.loc[p["activo"], "cod_cuenta"].dropna())

    def cuentas_facturadas(self) -> set[str]:
        return set(self.facturas["cod_cuenta"].dropna())

    # -- clientes ----------------------------------------------------------- #

    def clientes_enriquecidos(self, df: pd.DataFrame, col_ruc: str = "ruc") -> pd.DataFrame:
        """LEFT join contra el maestro de clientes.

        Siempre LEFT: el maestro (1,000 clientes) cubre solo 1,493 de las 3,364
        facturas. Un cliente fuera del maestro es un hallazgo reportable, no
        una fila a descartar.
        """
        cols = [
            "ruc",
            "razon_social_maestro",
            "sunat_estado_ruc",
            "sunat_estado_contribuyente",
            "segmento",
            "departamento",
        ]
        maestro = self.clientes.rename(columns={"razon_social": "razon_social_maestro"})[cols]

        out = df.merge(maestro, left_on=col_ruc, right_on="ruc", how="left", suffixes=("", "_m"))
        out["fuera_del_maestro"] = out["sunat_estado_ruc"].isna()
        out["sunat_estado_ruc"] = out["sunat_estado_ruc"].fillna("SIN MAESTRO")
        return out


# --------------------------------------------------------------------------- #
# Construcción
# --------------------------------------------------------------------------- #


class DatasetInvalido(Exception):
    """El dataset no se puede usar, con el detalle de por qué.

    `problemas` va por archivo para que la interfaz pueda decir "a
    005_TBL_FACTURAS le falta FECHA_VTO" en vez de "error al cargar".
    """

    def __init__(self, problemas: dict[str, list[str]]):
        self.problemas = problemas
        detalle = "; ".join(f"{k}: {', '.join(v)}" for k, v in problemas.items())
        super().__init__(detalle or "dataset inválido")


#: Columnas que cada tabla tiene que traer sí o sí. Son las claves de los mapas
#: de renombrado: si una falta, el renombrado la deja fuera y el fallo aparece
#: mucho después, en un KeyError dentro de una tool. Mejor aquí y por su nombre.
def _columnas_requeridas() -> dict[str, set[str]]:
    return {
        "clientes": set(_REN_CLIENTES),
        "planta_fija": set(_REN_FIJA),
        "planta_movil": set(_REN_MOVIL),
        "pagos": set(_REN_PAGOS),
        "facturas": set(_REN_FACTURAS),
        "notas_credito": set(_REN_NC),
    }


def _cargar_crudos(origen: Path) -> dict[str, pd.DataFrame]:
    """Lee los 6 CSV y comprueba el esquema antes de construir nada."""
    problemas: dict[str, list[str]] = {}

    faltan = {k: v for k, v in ARCHIVOS.items() if not (origen / v).exists()}
    for k, v in faltan.items():
        problemas[v] = ["no está en la carpeta"]
    if problemas:
        raise DatasetInvalido(problemas)

    crudos: dict[str, pd.DataFrame] = {}
    for k, v in ARCHIVOS.items():
        try:
            crudos[k] = limpiar_texto(pd.read_csv(origen / v, **OPCIONES_LECTURA))
        except Exception as e:  # csv corrupto, separador distinto, encoding raro
            problemas[v] = [f"no se pudo leer: {type(e).__name__}"]

    requeridas = _columnas_requeridas()
    for k, df in crudos.items():
        ausentes = sorted(requeridas[k] - set(df.columns))
        if ausentes:
            problemas[ARCHIVOS[k]] = [f"falta la columna {c}" for c in ausentes]
        elif df.empty:
            problemas[ARCHIVOS[k]] = ["el archivo no tiene filas"]

    if problemas:
        raise DatasetInvalido(problemas)
    return crudos


def _derivar_fecha_corte(fac: pd.DataFrame, pag: pd.DataFrame) -> str:
    """El corte por defecto de un dataset sin `corte.txt`.

    `min(hoy, última fecha de los datos)`. Los dos casos que importan:

      - Datos vivos, con hoy dentro del horizonte -> hoy, que es lo que se
        espera de un cierre.
      - Datos históricos, todo en el pasado -> la última fecha real. Con "hoy"
        el aging saldría entero en 90+ y el reporte no diría nada.
    """
    candidatas = [
        fac["fecha_emision"].max(),
        fac["fecha_vto"].max(),
        pag["fecha_pago"].max(),
    ]
    validas = [c for c in candidatas if pd.notna(c)]
    ultima = max(validas) if validas else pd.Timestamp.today().normalize()
    return min(pd.Timestamp.today().normalize(), ultima).strftime("%Y-%m-%d")


def _corte_fijado(origen: Path) -> str | None:
    """La fecha escrita en `corte.txt`, si la carpeta la trae."""
    sidecar = origen / ARCHIVO_CORTE
    if not sidecar.exists():
        return None
    crudo = sidecar.read_text(encoding="utf-8").strip()
    fecha = a_fecha(pd.Series([crudo]), centinelas=False).iloc[0]
    return None if pd.isna(fecha) else fecha.strftime("%Y-%m-%d")


def _construir_planta_unificada(fija: pd.DataFrame, movil: pd.DataFrame) -> pd.DataFrame:
    """Planta fija ∪ planta móvil en un esquema común.

    El estado activo se llama distinto en cada tabla: 'Active' en fija,
    'Activo' en móvil. La unión por COD_CUENTA de las cuentas activas da 1,572,
    que es la base de la fuga de ingresos.
    """
    cols = ["cod_cuenta", "cod_cliente", "ruc", "razon_social", "segmento", "estado", "fecha_alta"]

    f = fija.reindex(columns=cols).copy()
    f["origen"] = "fija"
    f["activo"] = fija["estado"].eq("Active")
    f["plan"] = (
        fija[["plan_voz", "plan_internet", "plan_tv"]]
        .apply(lambda r: " + ".join(x for x in r if x), axis=1)
        .replace("", None)
    )

    m = movil.reindex(columns=cols).copy()
    m["origen"] = "movil"
    m["activo"] = movil["estado"].eq("Activo")
    m["plan"] = movil["plan_principal"]

    return pd.concat([f, m], ignore_index=True)


def _verificar_estructura(d: Datos) -> None:
    """Invariantes que valen para CUALQUIER corte, no solo para el del demo.

    Aquí antes convivían dos cosas distintas y eso hacía que el sistema no
    arrancara con otros datos:

      - Estructurales: que la clave canónica no colisione, que ninguna fecha de
        vencimiento quede sin parsear, que los importes sean números. Si algo de
        esto falla, el parseo está mal y todas las cifras mienten. Se quedan.
      - Constantes del dataset del demo: 3,364 facturas, S/447,964.58
        facturado, 1,571 cuentas activas. Eso es una prueba de regresión de un
        fixture concreto, no una propiedad de los datos, y con el corte de otro
        mes fallaban las siete a la vez. Se fueron a
        `tests/test_fixture_demo.py`, que es donde se comprueban.

    Se puede desactivar con SONIA_SIN_ASSERTS=1.
    """
    if os.getenv("SONIA_SIN_ASSERTS") == "1":
        return

    problemas: list[str] = []

    def chequear(cond: bool, msg: str) -> None:
        if not cond:
            problemas.append(msg)

    chequear(
        d.facturas["doc_k"].is_unique,
        "canon_doc genera colisiones entre facturas: revisar _RE_DOC",
    )
    chequear(
        d.facturas["fecha_vto"].notna().all(),
        f"{int(d.facturas['fecha_vto'].isna().sum())} FECHA_VTO sin parsear: "
        f"el formato no está en FORMATOS_FECHA",
    )
    chequear(
        d.facturas["total"].notna().all(),
        f"{int(d.facturas['total'].isna().sum())} importes de factura no son números",
    )
    chequear(
        d.pagos["monto_pagado"].notna().all(),
        f"{int(d.pagos['monto_pagado'].isna().sum())} importes de pago no son números",
    )
    chequear(
        d.planta_unificada["activo"].any(),
        "ninguna cuenta figura activa: revisar los valores de estado de planta",
    )

    if problemas:
        raise AssertionError(
            "Invariantes estructurales rotas — las cifras no son confiables:\n  - "
            + "\n  - ".join(problemas)
        )


def _construir(origen: Path) -> Datos:
    """Lee y normaliza las 6 tablas de una carpeta. No toca el cache."""
    crudos = _cargar_crudos(origen)

    # -- diagnóstico ANTES de normalizar (evidencia de los formatos crudos) --
    diagnostico = {
        "filas": {k: len(v) for k, v in crudos.items()},
        "formatos_fecha_vto": formato_detectado(crudos["facturas"]["FECHA_VTO"]),
        "formatos_fecha_alta_fija": formato_detectado(crudos["planta_fija"]["FECHAALTA"]),
        "formatos_fecha_alta_movil": formato_detectado(crudos["planta_movil"]["FECHA_ALTA"]),
        "sistemas_facturas": crudos["facturas"]["SISTEMA"].value_counts().to_dict(),
        "sistemas_pagos": crudos["pagos"]["SISTEMA"].value_counts().to_dict(),
    }

    # -- clientes ------------------------------------------------------------
    clientes = _renombrar(crudos["clientes"], _REN_CLIENTES)

    # -- planta --------------------------------------------------------------
    fija = _renombrar(crudos["planta_fija"], _REN_FIJA)
    fija["fecha_alta"] = a_fecha(fija["fecha_alta"])

    movil = _renombrar(crudos["planta_movil"], _REN_MOVIL)
    movil["fecha_alta"] = a_fecha(movil["fecha_alta"])
    movil["fin_permanencia"] = a_fecha(movil["fin_permanencia"])

    planta_unificada = _construir_planta_unificada(fija, movil)

    activas = planta_unificada[planta_unificada["activo"]]
    huerfanas = activas[activas["cod_cuenta"].isna()]
    diagnostico["planta"] = {
        "servicios_activos": len(activas),
        "cuentas_activas_identificables": int(activas["cod_cuenta"].nunique()),
        # Líneas activas sin cuenta: no hay documento posible que emitir.
        "lineas_activas_sin_cuenta": len(huerfanas),
        "rucs_lineas_sin_cuenta": sorted(huerfanas["ruc"].dropna().unique().tolist()),
    }

    # -- facturas ------------------------------------------------------------
    fac = _renombrar(crudos["facturas"], _REN_FACTURAS)
    for c in ("neto", "igv", "total"):
        fac[c] = a_num(fac[c])
    fac["fecha_emision"] = a_fecha(fac["fecha_emision"])
    # El flag se calcula ANTES de parsear: marca las facturas que el sistema
    # actual pierde por el formato "YYYYMMDD". Es el hallazgo del agente de
    # Facturación y la que habilita la vista A.
    fac["fecha_vto_malformada"] = pd.to_datetime(
        fac["fecha_vto"], format="%Y-%m-%d", errors="coerce"
    ).isna()
    fac["fecha_vto"] = a_fecha(fac["fecha_vto"])
    fac["doc_k"] = fac["doc"].map(canon_doc)

    # -- pagos ---------------------------------------------------------------
    pag = _renombrar(crudos["pagos"], _REN_PAGOS)
    for c in ("subtotal", "igv", "monto_pagado"):
        pag[c] = a_num(pag[c])
    pag["fecha_pago"] = a_fecha(pag["fecha_pago"])
    pag["doc_k_afectada"] = pag["factura_afectada"].map(canon_doc)

    # -- notas de crédito ----------------------------------------------------
    nc = _renombrar(crudos["notas_credito"], _REN_NC)
    for c in ("monto_sin_igv", "igv", "monto"):
        nc[c] = a_num(nc[c])
    nc["fecha_emision"] = a_fecha(nc["fecha_emision"])
    nc["doc_k"] = nc["doc"].map(canon_doc)
    nc["doc_k_afectada"] = nc["factura_afectada"].map(canon_doc)

    # -- conciliación: métricas para el diagnóstico --------------------------
    docs_exactos = set(fac["doc"])
    docs_canon = set(fac["doc_k"])
    match_exacto = pag["factura_afectada"].isin(docs_exactos)
    match_canon = pag["doc_k_afectada"].isin(docs_canon)
    diagnostico["conciliacion"] = {
        "pagos": len(pag),
        "match_exacto": int(match_exacto.sum()),
        "tasa_exacta": round(100 * match_exacto.mean(), 2),
        "match_canonico": int(match_canon.sum()),
        "tasa_canonica": round(100 * match_canon.mean(), 2),
        "recuperados": int((match_canon & ~match_exacto).sum()),
        "monto_recuperado": round(pag.loc[match_canon & ~match_exacto, "monto_pagado"].sum(), 2),
        "residual": int((~match_canon).sum()),
        "monto_residual": round(pag.loc[~match_canon, "monto_pagado"].sum(), 2),
    }
    diagnostico["facturas_fecha_malformada"] = {
        "n": int(fac["fecha_vto_malformada"].sum()),
        "monto": round(fac.loc[fac["fecha_vto_malformada"], "total"].sum(), 2),
        "sistemas": fac.loc[fac["fecha_vto_malformada"], "sistema"].value_counts().to_dict(),
    }

    fijado = _corte_fijado(origen)
    diagnostico["corte"] = {
        "fecha": fijado or _derivar_fecha_corte(fac, pag),
        "procedencia": "fijado en corte.txt" if fijado else "derivado de las fechas del dataset",
    }

    datos = Datos(
        clientes=clientes,
        planta_fija=fija,
        planta_movil=movil,
        pagos=pag,
        facturas=fac,
        notas_credito=nc,
        planta_unificada=planta_unificada,
        diagnostico=diagnostico,
        fecha_corte=diagnostico["corte"]["fecha"],
        origen=str(origen),
    )
    _verificar_estructura(datos)
    return datos


# --------------------------------------------------------------------------- #
# Cache y cambio de origen
# --------------------------------------------------------------------------- #
#
# Antes esto era `@lru_cache(maxsize=1)`, que lee una vez y no se puede
# invalidar sin reiniciar el proceso. Para poder cargar otro corte en caliente
# hace falta un cache explícito, y sobre todo que el cambio sea atómico: si el
# dataset nuevo no valida, el que estaba cargado se queda intacto. Un fallo al
# subir un archivo no puede dejar la aplicación sin datos.

_CACHE: Datos | None = None


def get_datos() -> Datos:
    """Las 6 tablas normalizadas del origen actual. Se lee del disco una vez."""
    global _CACHE
    if _CACHE is None:
        _CACHE = _construir(_ORIGEN)
    return _CACHE


def fecha_corte_defecto() -> str:
    """El corte del dataset cargado.

    No es una constante: depende de qué datos haya. Se resuelve en la llamada,
    que es la razón de existir de `CORTE_DEL_DATASET`.
    """
    return get_datos().fecha_corte


def usar_origen(carpeta: str | Path) -> Datos:
    """Cambia el dataset activo. Si el nuevo no valida, no se cambia nada.

    Levanta `DatasetInvalido` con el detalle por archivo, o `AssertionError` si
    pasa el esquema pero rompe una invariante estructural.
    """
    global _CACHE, _ORIGEN
    carpeta = Path(carpeta)
    nuevos = _construir(carpeta)  # si esto revienta, el cache sigue como estaba
    _CACHE, _ORIGEN = nuevos, carpeta
    return nuevos


def restaurar_demo() -> Datos:
    """Vuelve al dataset que trae el repositorio."""
    return usar_origen(DATA_DEMO)


def estado_origen() -> dict:
    """Qué dataset está cargado ahora, para el endpoint de estado."""
    d = get_datos()
    return {
        "origen": d.origen,
        "es_demo": Path(d.origen) == DATA_DEMO,
        "fecha_corte": d.fecha_corte,
        "corte_procedencia": d.diagnostico.get("corte", {}).get("procedencia", ""),
        "filas": d.diagnostico.get("filas", {}),
        "archivos": ARCHIVOS,
    }


def recargar() -> Datos:
    """Limpia el cache y vuelve a leer del disco."""
    global _CACHE
    _CACHE = None
    return get_datos()


# --------------------------------------------------------------------------- #
# Verificación manual: python -m src.data_loader
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import json
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    d = get_datos()
    print("=" * 72)
    print("SON-IA · data_loader — verificación")
    print("=" * 72)
    print(json.dumps(d.diagnostico, indent=2, ensure_ascii=False, default=str))

    print("\n--- Cuentas y fuga ---")
    act = d.planta_unificada[d.planta_unificada["activo"]]
    ctas_act = d.cuentas_activas()
    sin_fac = ctas_act - d.cuentas_facturadas()
    afectados = act[act["cod_cuenta"].isin(sin_fac)]["ruc"].nunique()
    print(f"cuentas activas identificables : {len(ctas_act)}   (esperado 1571)")
    print(f"activas sin factura            : {len(sin_fac)}    (esperado 422, {len(sin_fac)/len(ctas_act):.1%})")
    print(f"clientes afectados             : {afectados}    (esperado 274)")
    print(f"lineas activas SIN cod_cuenta  : {d.diagnostico['planta']['lineas_activas_sin_cuenta']}"
          f"      (no facturables)")

    print("\n--- Las tres vistas de la cartera al 2026-08-12 ---")
    vistas = {
        "A · lo que el sistema ve": dict(
            conciliacion="exacta", deducir_nc=False, solo_fechas_validas=True
        ),
        "B · fechas corregidas": dict(conciliacion="exacta", deducir_nc=True),
        "C · + conciliación canónica": dict(conciliacion="canonica", deducir_nc=True),
    }
    for nombre, kw in vistas.items():
        venc, porv = d.cartera(**kw)
        print(f"\n{nombre}: {len(venc)} facturas · S/{venc['saldo'].sum():,.2f}"
              f"   (por vencer {len(porv)} · S/{porv['saldo'].sum():,.2f})")
        print(d.aging(venc).to_string())
