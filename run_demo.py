#!/usr/bin/env python
"""
SON-IA · Demo de consola: "Cierra el ciclo del mes".

    python run_demo.py                     # agentes CrewAI + Groq (fallback si falla)
    python run_demo.py --deterministico    # sin LLM: mismas cifras, sin depender de la red
    python run_demo.py --sin-color         # salida plana, para redirigir a archivo

Muestra a los tres agentes trabajando en vivo — qué herramienta llama cada uno,
con qué argumentos y qué cifra devuelve — y cierra con el informe consolidado.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# El reconfigure va ANTES de cualquier print: al redirigir la salida Windows
# vuelve a cp1252 y un simple "ó" revienta el demo a media ejecución.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# CrewAI imprime paneles de telemetría y trazas que rompen el layout de la
# consola. Hay que apagarlos ANTES de que se importe crewai (que aquí ocurre
# de forma diferida, dentro de main()).
os.environ.setdefault("CREWAI_TELEMETRY_OPT_OUT", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from src.plan import AGENTES, FECHA_CORTE, OBJETIVO_DEMO, PLAN_DE_CIERRE  # noqa: E402
from src.tools import registro  # noqa: E402

# --------------------------------------------------------------------------- #
# Presentación en consola
# --------------------------------------------------------------------------- #

COLORES = {
    "AGENTE_FACTURACION": "\033[96m",  # cian
    "AGENTE_COBRANZAS": "\033[93m",  # amarillo
    "AGENTE_BI": "\033[95m",  # magenta
    "SUPERVISOR": "\033[92m",  # verde
    "gris": "\033[90m",
    "rojo": "\033[91m",
    "negrita": "\033[1m",
    "reset": "\033[0m",
}

_usar_color = True


def c(texto: str, color: str) -> str:
    if not _usar_color:
        return texto
    return f"{COLORES.get(color, '')}{texto}{COLORES['reset']}"


def _envolver(texto: str, ancho: int, sangria: str) -> str:
    salida, linea = [], ""
    for palabra in texto.split():
        if len(linea) + len(palabra) + 1 > ancho:
            salida.append(sangria + linea)
            linea = palabra
        else:
            linea = f"{linea} {palabra}".strip()
    salida.append(sangria + linea)
    return "\n".join(salida)


def hacer_emisor(lento: float = 0.0):
    """Devuelve el callback que pinta el trabajo de los agentes en vivo."""

    def emitir(ev: dict) -> None:
        tipo = ev.get("tipo")

        if tipo == "corrida_inicio":
            print(c(f"\n{'=' * 78}", "gris"))
            print(c(f"  SON-IA · {ev.get('objetivo', '')}", "negrita"))
            print(f"  corte {ev.get('fecha_corte')}   ·   modo {ev.get('modo')}"
                  f"   ·   {ev.get('pasos')} pasos")
            print(c(f"{'=' * 78}", "gris"))

        elif tipo == "paso_inicio":
            agente = ev.get("agente", "")
            etiqueta = AGENTES.get(agente, agente)
            momento = f"   ({ev['momento']})" if ev.get("momento") else ""
            print()
            print(c(f"  ┌─ [{ev.get('id')}] AGENTE DE {etiqueta.upper()}", agente)
                  + c(momento, "gris"))
            print(c(f"  │  {ev.get('titulo', '')}", "gris"))

        elif tipo == "tool_inicio":
            args = ev.get("inputs") or {}
            texto = ", ".join(f"{k}={v!r}" for k, v in args.items() if v is not None)
            print(c(f"  │  → llamando {ev.get('tool')}({texto})", "gris"))

        elif tipo == "tool_fin":
            agente = ev.get("agente", "")
            marca = "✓" if ev.get("ok") else "✗"
            color = agente if ev.get("ok") else "rojo"
            print(c(f"  │  {marca} {ev.get('duracion_ms')} ms", color))
            print(_envolver(ev.get("resumen", ""), 72, "  │    "))
            for alerta in ev.get("alertas") or []:
                impacto = f"  S/{alerta['impacto_pen']:,.2f}" if alerta.get("impacto_pen") else ""
                print(c(f"  │    ⚠ [{alerta['severidad']}] {alerta['titulo']}{impacto}", "rojo"))
            print(c("  └─", agente))
            if lento:
                time.sleep(lento)

        elif tipo == "agente_mensaje":
            print(c(f"  · {ev.get('agente', '')}: {ev.get('texto', '')[:160]}", "gris"))

        elif tipo == "aviso":
            print(c(f"\n  [!] {ev.get('mensaje', '')}\n", "rojo"))

    return emitir


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> int:
    global _usar_color

    p = argparse.ArgumentParser(description="SON-IA · cierre de ciclo B2B")
    p.add_argument("--deterministico", action="store_true",
                   help="no usar LLM: ejecuta las tools en orden (mismas cifras)")
    p.add_argument("--objetivo", default=OBJETIVO_DEMO)
    p.add_argument("--fecha-corte", default=FECHA_CORTE)
    p.add_argument("--sin-color", action="store_true", help="salida plana sin códigos ANSI")
    p.add_argument("--lento", type=float, default=0.0,
                   help="pausa en segundos entre pasos, para la presentación")
    args = p.parse_args()

    _usar_color = not args.sin_color and sys.stdout.isatty()
    emitir = hacer_emisor(args.lento)
    registro.suscribir(emitir)

    # Saneada: una clave con comillas o con el salto de línea del copiar y
    # pegar no sirve, y aquí vale más decirlo antes de arrancar.
    from src.proveedor import clave_groq

    hay_key = bool(clave_groq())
    if not args.deterministico and not hay_key:
        print(c("\n  [!] No hay una GROQ_API_KEY utilizable en el entorno.", "rojo"))
        print(c("      Ejecutando en modo determinista: las cifras son las mismas,", "gris"))
        print(c("      lo único que falta es la narrativa redactada por el LLM.\n", "gris"))

    t0 = time.perf_counter()
    try:
        if args.deterministico or not hay_key:
            from src.pipeline import ejecutar_plan

            salida = ejecutar_plan(
                emitir=emitir, modo="deterministico",
                objetivo=args.objetivo, fecha_corte=args.fecha_corte,
            )
        else:
            from src.crew import ejecutar_cierre

            salida = ejecutar_cierre(
                emitir=emitir, objetivo=args.objetivo, fecha_corte=args.fecha_corte,
            )
    except KeyboardInterrupt:
        print(c("\n\n  Interrumpido por el usuario.\n", "rojo"))
        return 130
    finally:
        registro.desuscribir(emitir)

    print("\n")
    print(salida["reporte"])

    total = time.perf_counter() - t0
    aud = salida.get("auditoria", {})
    print()
    print(c(f"  Completado en {total:.1f}s   ·   modo {salida.get('modo')}", "negrita"))
    print(c(f"  Auditoría: {aud.get('archivo', 'n/d')}", "gris"))
    print(c(f"  {aud.get('resumen', {}).get('tools_ejecutadas', 0)} herramientas ejecutadas, "
            f"{aud.get('resumen', {}).get('tools_error', 0)} con error", "gris"))
    print()

    faltantes = len(PLAN_DE_CIERRE) - len(salida.get("resultados", {}))
    return 1 if faltantes else 0


if __name__ == "__main__":
    raise SystemExit(main())
