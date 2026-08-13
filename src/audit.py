"""
SON-IA · Log de auditoría estructurado.

El principio "0% de alucinaciones" solo vale si es *comprobable*. Este módulo es
la prueba: cada ejecución de tool deja una entrada con agente, tool, inputs,
métricas devueltas, trazas del cálculo, duración y timestamp.

Se escribe en dos formatos a la vez:
  - JSONL en vivo (``logs/auditoria_<corrida>.jsonl``), append línea a línea, de
    modo que si el proceso muere a mitad del demo lo ya ejecutado queda en disco.
  - JSON consolidado al cerrar la corrida, que es lo que expone la API y lo que
    se puede abrir delante del jurado.

No hay estado global oculto: el log es un objeto, pero se expone una instancia
compartida `audit` porque el registro de tools la necesita desde cualquier capa.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from src.contracts import ResultadoTool, ahora

RAIZ = Path(__file__).resolve().parents[1]
DIR_LOGS = RAIZ / "logs"


class LogAuditoria:
    """Registro append-only de todo lo que hace el sistema.

    Thread-safe: el crew corre en un worker thread mientras la API drena eventos
    desde el event loop.
    """

    def __init__(self, dir_logs: Path = DIR_LOGS) -> None:
        self.dir_logs = dir_logs
        self._lock = threading.RLock()
        self._entradas: list[dict] = []
        self._corrida: dict[str, Any] = {}
        self._archivo: Path | None = None

    # -- ciclo de vida de una corrida --------------------------------------- #

    def iniciar_corrida(self, objetivo: str = "", modo: str = "deterministico") -> str:
        """Abre una corrida nueva y devuelve su id."""
        with self._lock:
            corrida_id = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
            self._entradas = []
            self._corrida = {
                "corrida_id": corrida_id,
                "objetivo": objetivo,
                "modo": modo,
                "inicio": ahora(),
                "fin": None,
            }
            self.dir_logs.mkdir(parents=True, exist_ok=True)
            self._archivo = self.dir_logs / f"auditoria_{corrida_id}.jsonl"
            self._escribir_linea({"tipo": "corrida_inicio", **self._corrida})
            return corrida_id

    def cerrar_corrida(self) -> dict:
        with self._lock:
            self._corrida["fin"] = ahora()
            self._corrida["entradas"] = len(self._entradas)
            self._escribir_linea({"tipo": "corrida_fin", **self._corrida})
            return dict(self._corrida)

    @property
    def corrida_id(self) -> str:
        return self._corrida.get("corrida_id", "sin_corrida")

    # -- registro ----------------------------------------------------------- #

    def registrar_tool(self, res: ResultadoTool) -> dict:
        """Registra una ejecución de tool. Guarda métricas y trazas, no el
        detalle: el detalle vive en el registro de resultados, aquí interesa la
        cadena de decisiones."""
        entrada = {
            "tipo": "tool",
            "corrida_id": self.corrida_id,
            "ts": res.ts,
            "agente": res.agente,
            "tool": res.tool,
            "inputs": res.params,
            "ok": res.ok,
            "error": res.error,
            "duracion_ms": res.duracion_ms,
            "metricas": res.metricas,
            "trazas": res.trazas,
            "resumen": res.resumen,
            "filas_detalle": res.data_filas_totales,
            "alertas": [
                {"severidad": a.severidad, "titulo": a.titulo, "impacto_pen": a.impacto_pen}
                for a in res.alertas
            ],
        }
        return self._agregar(entrada)

    def registrar_agente(self, agente: str, evento: str, detalle: str = "", **extra) -> dict:
        """Registra actividad del LLM (delegaciones, salidas de tarea).

        Se guarda por trazabilidad, pero ninguna cifra del reporte sale de aquí.
        """
        return self._agregar(
            {
                "tipo": "agente",
                "corrida_id": self.corrida_id,
                "ts": ahora(),
                "agente": agente,
                "evento": evento,
                "detalle": detalle,
                **extra,
            }
        )

    def registrar_error(self, contexto: str, agente: str, inputs: dict, traza: str) -> dict:
        return self._agregar(
            {
                "tipo": "error",
                "corrida_id": self.corrida_id,
                "ts": ahora(),
                "agente": agente,
                "contexto": contexto,
                "inputs": inputs,
                "traceback": traza,
            }
        )

    def _agregar(self, entrada: dict) -> dict:
        with self._lock:
            self._entradas.append(entrada)
            self._escribir_linea(entrada)
            return entrada

    def _escribir_linea(self, entrada: dict) -> None:
        """Append al JSONL. Un fallo de disco no debe tumbar el demo."""
        if self._archivo is None:
            return
        try:
            with self._archivo.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entrada, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass

    # -- consulta y export -------------------------------------------------- #

    def entradas(self, tipo: str | None = None) -> list[dict]:
        with self._lock:
            if tipo is None:
                return list(self._entradas)
            return [e for e in self._entradas if e.get("tipo") == tipo]

    def exportar(self) -> dict:
        with self._lock:
            tools = [e for e in self._entradas if e.get("tipo") == "tool"]
            return {
                **self._corrida,
                "resumen": {
                    "tools_ejecutadas": len(tools),
                    "tools_ok": sum(1 for e in tools if e.get("ok")),
                    "tools_error": sum(1 for e in tools if not e.get("ok")),
                    "duracion_total_ms": sum(e.get("duracion_ms", 0) for e in tools),
                    "agentes": sorted({e.get("agente", "") for e in tools if e.get("agente")}),
                },
                "entradas": list(self._entradas),
            }

    def guardar_json(self, ruta: Path | None = None) -> Path:
        """Vuelca la corrida consolidada. Devuelve la ruta escrita."""
        self.dir_logs.mkdir(parents=True, exist_ok=True)
        destino = ruta or self.dir_logs / f"auditoria_{self.corrida_id}.json"
        destino.write_text(
            json.dumps(self.exportar(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return destino


#: Instancia compartida. El registro de tools escribe aquí desde cualquier capa
#: (CLI, crew, API) sin tener que pasarla como parámetro.
audit = LogAuditoria()
