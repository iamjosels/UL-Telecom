"""
SON-IA · Tools deterministas.

Ninguna función de este paquete importa CrewAI ni habla con un LLM: son pandas
puro sobre los DataFrames del loader. La adaptación a CrewAI vive en
`crew_adapters.py` y se genera automáticamente desde el registro.

Importar este paquete registra las tres familias de tools (facturación,
cobranzas, BI) en el registro central.
"""

from src.tools import bi, cobranzas, facturacion  # noqa: F401  (efecto: registrar)
from src.tools.registro import catalogo, ejecutar, limpiar, registrar, ultimos

__all__ = ["ejecutar", "registrar", "catalogo", "ultimos", "limpiar"]
