"""
SON-IA · Helpers de formato para los resúmenes que lee el LLM y el reporte.

Todo lo que aquí se formatea ya viene calculado: estas funciones no hacen
aritmética de negocio, solo presentación.
"""

from __future__ import annotations

import pandas as pd


def pen(monto: float | int | None) -> str:
    """Formatea en soles: 47819.06 -> 'S/47,819.06'."""
    if monto is None or (isinstance(monto, float) and pd.isna(monto)):
        return "S/0.00"
    return f"S/{monto:,.2f}"


def pct(valor: float | None, decimales: int = 1) -> str:
    """0.269 -> '26.9%'. Recibe la fracción, no el porcentaje."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "0.0%"
    return f"{valor * 100:.{decimales}f}%"


def num(valor: float | int | None) -> str:
    """Entero con separador de miles: 3364 -> '3,364'."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "0"
    return f"{valor:,.0f}"


def tabla_top(df: pd.DataFrame, columna: str, n: int = 3, sep: str = ", ") -> str:
    """Top-N valores por frecuencia: "LIMA (412), AREQUIPA (88), CUSCO (31)"."""
    if df.empty or columna not in df.columns:
        return "sin datos"
    vc = df[columna].dropna().value_counts().head(n)
    if vc.empty:
        return "sin datos"
    return sep.join(f"{k} ({v:,})" for k, v in vc.items())


def top_montos(df: pd.DataFrame, clave: str, monto: str, n: int = 3) -> str:
    """Top-N por suma de un monto: "2029902035 S/18,275.95, ...".

    Útil para mostrar concentración de cartera en el resumen del LLM.
    """
    if df.empty or clave not in df.columns or monto not in df.columns:
        return "sin datos"
    g = df.groupby(clave)[monto].sum().sort_values(ascending=False).head(n)
    return ", ".join(f"{k} {pen(v)}" for k, v in g.items())


def linea_aging(aging: pd.DataFrame) -> str:
    """Aging en una línea compacta para el resumen del LLM.

    "1-30: 88 fact S/20,664.08 | 31-60: 167 fact S/16,003.31 | ..."
    """
    partes = [
        f"{tramo}: {int(fila['facturas'])} fact {pen(fila['saldo'])}"
        for tramo, fila in aging.iterrows()
    ]
    return " | ".join(partes)


def encabezado(titulo: str, ancho: int = 78, caracter: str = "=") -> str:
    """Encabezado de sección para el reporte de consola."""
    return f"{caracter * ancho}\n{titulo}\n{caracter * ancho}"


def bullet(texto: str, nivel: int = 0) -> str:
    return f"{'  ' * nivel}- {texto}"


def truncar(texto: str, limite: int, sufijo: str = "…") -> str:
    texto = texto.strip()
    return texto if len(texto) <= limite else texto[: limite - len(sufijo)] + sufijo
