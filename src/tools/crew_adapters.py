"""
SON-IA · Adaptadores de las tools deterministas hacia CrewAI.

Se generan automáticamente desde el registro, así que no hay dos listas que
mantener sincronizadas: registrar una función determinista basta para que el
agente correspondiente la reciba.

Aquí está la frontera del principio rector. `_run()` ejecuta la función, pero
devuelve al modelo ÚNICAMENTE `res.texto_para_llm()`, es decir el resumen ya
formateado sobre cifras calculadas por pandas. El detalle fila a fila se queda
en el registro de resultados, del lado de la API.

Se usa `BaseTool` con `args_schema` explícito en vez del decorador `@tool`: el
decorador infiere los argumentos de la firma y del docstring, lo que es frágil
cuando las clases se construyen dinámicamente.
"""

from __future__ import annotations

from crewai.tools import BaseTool

from src.tools.registro import EspecTool, catalogo, ejecutar


def _crear_tool(espec: EspecTool) -> BaseTool:
    """Construye la envoltura CrewAI de una tool determinista."""

    class _ToolSonIA(BaseTool):
        name: str = espec.nombre
        description: str = espec.descripcion
        args_schema: type = espec.args_schema

        def _run(self, **kwargs) -> str:
            resultado = ejecutar(espec.nombre, origen=espec.agente, **kwargs)
            return resultado.texto_para_llm()

    _ToolSonIA.__name__ = f"Tool_{espec.nombre}"
    _ToolSonIA.__doc__ = espec.descripcion
    return _ToolSonIA()


def tools_de(agente: str) -> list[BaseTool]:
    """Todas las tools registradas para un agente, listas para `Agent(tools=...)`."""
    return [_crear_tool(e) for e in catalogo(agente)]


def todas_las_tools() -> list[BaseTool]:
    return [_crear_tool(e) for e in catalogo()]
