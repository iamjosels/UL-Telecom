# SON-IA · Sinergia Operativa del Negocio — Integratel Agéntica

Ecosistema de agentes de IA que opera el ciclo del ingreso B2B de punta a punta —
**Facturación, Cobranzas y Recaudo** — coordinado por un agente supervisor.

> **Principio rector: 0% de alucinaciones.**
> El LLM nunca calcula ni inventa cifras. Toda cifra sale de funciones Python
> deterministas sobre los datos; el LLM solo decide, orquesta y explica. Cada
> ejecución queda en un log de auditoría con agente, herramienta, argumentos,
> métricas y timestamp. **Es comprobable abriendo `logs/`.**

---

## Arranque rápido

En esta máquina `python` resuelve a MSYS2, que no trae pandas. Hay que crear el
entorno desde el intérprete correcto:

```powershell
& "C:\Users\<usuario>\AppData\Local\Programs\Python\Python311\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1
python -c "import sys; print(sys.executable)"   # debe apuntar al .venv del proyecto

python -m pip install -U pip
python -m pip install -r requirements.txt

copy .env.example .env      # opcional: sin GROQ_API_KEY igual funciona
```

Y a correr:

```powershell
python validar_baseline.py            # reproduce las cifras de docs/CONTEXT.md
python run_demo.py --deterministico   # demo completo sin LLM (~2 s)
python run_demo.py                    # los 3 agentes + supervisor sobre Groq
uvicorn api.main:app --port 8000      # API para el dashboard
```

`run_demo.py` **funciona sin API key**: detecta que falta y ejecuta el mismo
plan de cierre de forma determinista. Las cifras son idénticas; lo único que
falta es la narrativa redactada por el modelo.

---

## El hallazgo

Perfilando la data apareció una causa raíz única detrás de los tres síntomas más
caros del dataset: existe un **segundo sistema de facturación, `ISIS`**, cuyos
documentos nunca cruzan bien contra `AMDOCS`.

| Síntoma | Causa raíz |
|---|---|
| 57 facturas con `FECHA_VTO` en `YYYYMMDD` (S/137,200, ninguna pagada) | 100% `SISTEMA=ISIS` |
| 74 pagos "no identificados" (S/106,289) | 67 son ISIS |
| 21 pagos en USD contra facturas 100% PEN | los 21 son ISIS |

Y el remate: **esos pagos no son huérfanos.** El maestro guarda
`S300-0248301`; el archivo de pagos referencia `S300-248301` — un cero inicial
en el correlativo. Una clave canónica `PREFIJO-<entero sin ceros>` tiene **0
colisiones** en las 3,364 facturas y sube la conciliación de **97.91% a 99.77%**.

Eso da tres lecturas del mismo dato, y cada agente destapa una:

```
A · Lo que el sistema ve hoy        487 fact    S/ 18,297.69   ← baseline de CONTEXT.md
B · Con parseo tolerante de fechas  520 fact    S/153,976.98   ← Agente Facturación
    +57 facturas de ISIS invisibles (S/137,200.41)
C · + conciliación canónica         476 fact    S/ 47,819.06   ← Agente Cobranzas
    −66 pagos ya cobrados sin aplicar (S/106,157.92)

Deuda real al corte: S/47,819.06   ·   sin identificar de verdad: 8 pagos / S/131.48
```

El informe muestra A→B→C explícitamente: **el delta es la propuesta de valor.**

---

## Arquitectura

```
                        ┌──────────────────────────┐
                        │   AGENTE SUPERVISOR      │  asigna · controla · consolida
                        │   llama-3.3-70b          │
                        └────────────┬─────────────┘
             ┌───────────────────────┼───────────────────────┐
     ┌───────┴────────┐     ┌────────┴────────┐     ┌────────┴────────┐
     │  FACTURACIÓN   │     │   COBRANZAS     │     │       BI        │
     │  3 tools       │     │  3 tools        │     │  5 tools        │
     └───────┬────────┘     └────────┬────────┘     └────────┬────────┘
             └───────────────────────┼───────────────────────┘
                          ┌──────────┴───────────┐
                          │  ejecutar()          │  ← EMBUDO ÚNICO
                          │  valida · audita ·   │
                          │  registra · emite    │
                          └──────────┬───────────┘
                          ┌──────────┴───────────┐
                          │  tools deterministas │  pandas puro, sin LLM
                          │  data_loader         │
                          └──────────────────────┘
```

**Toda** invocación pasa por `ejecutar()`, y ahí ocurren las cuatro cosas que
sostienen el principio rector: validación de argumentos, auditoría, registro de
resultados y emisión del evento SSE. Los adaptadores de CrewAI devuelven al
modelo **únicamente** `resultado.resumen` — un string armado con f-strings sobre
valores que calculó pandas. El detalle fila a fila nunca cruza esa frontera.

Por eso el "0% de alucinaciones" es mecánico y no aspiracional: el LLM no puede
citar una cifra que una función Python no produjo, porque no la vio.

### Estructura

```
src/
  data_loader.py     parser tolerante de fechas, clave canónica, saldos, aging, asserts
  contracts.py       ResultadoTool y Alerta (la frontera hacia el LLM)
  audit.py           log estructurado JSONL + export JSON
  plan.py            PLAN_DE_CIERRE — fuente única para los dos caminos
  pipeline.py        camino determinista
  crew.py            orquestador jerárquico + red de seguridad
  agents.py          los 3 agentes + supervisor
  router.py          lenguaje natural → tool, con guardarraíl numérico
  reporte.py         informe consolidado (compartido por ambos caminos)
  tools/
    registro.py      registro + ejecutar()  ← el embudo
    crew_adapters.py envoltura CrewAI generada desde el registro
    facturacion.py   cobranzas.py   bi.py
api/main.py          POST /run (SSE) · POST /chat · GET /kpis
run_demo.py          demo de consola
validar_baseline.py  paridad contra docs/CONTEXT.md
```

---

## Las 11 herramientas

| Agente | Herramienta | Qué responde |
|---|---|---|
| Facturación | `resumen_facturacion` | escalera de facturación, NC por error operativo |
| Facturación | `detectar_servicios_no_facturados` | fuga: cuentas activas sin factura |
| Facturación | `validar_clientes_sunat` | RUC NO HABIDO, control del PxQ e IGV |
| Cobranzas | `conciliar_pagos` | rebaja post-pago, algoritmo de aplicación |
| Cobranzas | `pagos_no_identificados` | partidas bancarias sin aplicar |
| Cobranzas | `cartera_vencida` | cartera con aging 1-30/31-60/61-90/90+ |
| BI | `ratio_cobrado_facturado` | ratio a 30 días, periodo medio de cobro |
| BI | `provision_cobranza_dudosa` | PCD por tramo |
| BI | `priorizar_recupero` | mesa de aceleración de recupero |
| BI | `proyeccion_caja` | adelanto operativo de caja a 30/60/90 |
| BI | `detectar_anomalias` | inconsistencias de datos y de proceso |

Los agentes cubren los **tres momentos de facturación** de la ficha del reto:
Facturación opera el momento 1 (asesoría previa a la emisión: valida el PxQ y
alerta quiebres) y Cobranzas el momento 3 (rebaja automática post-pago).

---

## API

| Endpoint | Qué hace |
|---|---|
| `POST /run` | corre el cierre y **transmite cada paso por SSE** |
| `POST /chat` | pregunta en lenguaje natural enrutada a las tools |
| `GET /kpis` | métricas de portada (no ejecuta el crew) |
| `GET /plan` | el plan de cierre, para pintar los pasos antes de correr |
| `GET /tools` | catálogo de herramientas |
| `GET /diagnostico` | perfil de la data: formatos, sistemas, conciliación |
| `GET /auditoria` | última corrida registrada |

```bash
curl -N -X POST localhost:8000/run  -H "Content-Type: application/json" \
     -d '{"objetivo":"Cierra el ciclo del mes"}'

curl -X POST localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"mensaje":"¿cuánto por cobrar a +90 días?"}'
```

Eventos SSE: `corrida_inicio · paso_inicio · tool_inicio · tool_fin ·
reporte_final · fin`, más `ping` de heartbeat cada 10 s.

### El chat no deja calcular al LLM

Tres etapas separadas a propósito: **(1)** el modelo elige una tool de un
catálogo cerrado — cualquier nombre fuera de la whitelist se descarta y cae a
reglas de palabras clave; **(2)** Python ejecuta y produce las cifras; **(3)** el
modelo solo redacta alrededor del resumen.

Y un guardarraíl al cierre: se extraen los números de la redacción y, si alguno
no está en el resumen ni en las métricas, **se descarta la redacción** y se
devuelve el texto determinista. Se puede demostrar en vivo con una pregunta
capciosa.

---

## Robustez

`run_demo.py` está pensado para no fallar delante de un jurado:

1. Sin `GROQ_API_KEY` → camino determinista directo (~2 s).
2. El crew corre en un hilo con timeout (`SONIA_TIMEOUT_CREW`, 300 s).
3. Ante un 429 de Groq se respeta el tiempo de espera que indica el propio error
   y se reintenta (`SONIA_REINTENTOS_LLM`).
4. Si aun así falla o se cuelga, **se rellenan solo los pasos que faltaron**: lo
   que los agentes sí lograron se conserva y el informe sale completo (modo
   `hibrido`).

Verificado en los dos escenarios: con una API key inválida el crew falla y se
completan los 11 pasos igual; con la key buena corre en modo `crew` en ~65 s.

El loader además comprueba invariantes al cargar (3364/3548/1000 filas, total
S/447,964.58, unicidad de la clave canónica, cero fechas sin parsear). Si algo
no cuadra, **rompe ruidosamente** en vez de reportar una cifra mala en silencio.

---

## Notas de integración con Groq y CrewAI

Tres cosas que costaron una tarde y que conviene no volver a descubrir:

**1. El modelo pequeño tiene la MITAD de presupuesto que el grande.** En el plan
gratuito de Groq el límite de tokens por minuto va por modelo:
`llama-3.1-8b-instant` 6.000 TPM contra `llama-3.3-70b-versatile` 12.000 TPM.
Como cada turno de un agente reenvía todo su bloc de notas, una petición pesa
~2.200 tokens y con 6.000 TPM sólo caben dos o tres por minuto. Poner los
agentes "ligeros" en el modelo rápido — que es lo intuitivo — hacía que la
corrida muriese a mitad del cierre. Con todo en el 70b, completa en ~65 s.

**2. CrewAI 1.15 rompe con Groq por `cache_breakpoint`.** Marca los mensajes con
esa propiedad (prompt caching estilo Anthropic) y define
`strip_cache_breakpoint()` para quitarla… pero **nunca la llama** en la ruta
LiteLLM. Groq valida el esquema de forma estricta y rechaza la petición entera.
Verificado en 1.15.0 y 1.15.15. Se sanea en `LLMGroq` (`src/agents.py`).

**3. Groq rechaza un schema de tool con `properties` vacío**, con el mensaje
confuso *"'required' present but 'properties' is missing"* (sí está, pero vacío).
Toda tool expuesta al LLM necesita al menos un argumento; por eso
`validar_clientes_sunat`, `pagos_no_identificados` y `detectar_anomalias`
llevan un filtro opcional — que además resultó útil.

Y una defensa que no es opcional: **el LLM manda `fecha_corte="hoy"`**. Los
schemas normalizan el argumento (`ArgsConFechaCorte`) porque un
`pd.Timestamp("hoy")` convierte una respuesta al usuario en un traceback.

Sobre la orquestación: `SONIA_PROCESO=supervisado` (por defecto) corre los tres
agentes en secuencia y el supervisor consolida en **una** llamada. Es lo que
cabe en el plan gratuito. `SONIA_PROCESO=jerarquico` usa el `Process.hierarchical`
nativo, donde el supervisor delega turno a turno: más fiel al patrón de CrewAI,
pero reenvía el contexto acumulado en cada vuelta y agota los 12.000 TPM.

---

## Trampas de la data (todas manejadas en `data_loader.py`)

1. `COD_CUENTA` / `COD_CLIENTE` traen **ceros a la izquierda** → todo se lee con
   `dtype=str` o los joins pierden filas en silencio.
2. `FECHA_VTO` trae **dos formatos en la misma columna** → parser tolerante que
   prueba formatos explícitos en orden. Nunca `infer_datetime_format`: resuelve
   `03/04/2024` como MM/DD por bloque y sin avisar.
3. El RUC se llama `NRO_IDENTIFICACION_FISCAL` en pagos y
   `NUMERO_IDENTIFICACION_FISCAL` en las otras cinco tablas.
4. Montos con decimal de punto inicial (`.85`).
5. Planta fija usa `YYYY-MM-DD HH:MM:SS` con centinelas basura (`1970-01-01
   05:31:00`); planta **móvil** usa `DD/MM/YYYY`.
6. El maestro de clientes cubre solo 1,493 de 3,364 facturas → todo join contra
   clientes es LEFT, y "fuera del maestro" es un hallazgo reportable.
7. Hace falta `.str.strip()` en todas las columnas de texto: sin eso, "274
   clientes afectados" se convierte en 277.

---

## Verificación

```powershell
python validar_baseline.py    # 9/9 cifras de CONTEXT.md reproducidas
```

Reproduce el baseline documentado con las mismas hipótesis del sistema actual, y
después muestra en qué difiere la lectura corregida y por qué. Tres diferencias
quedan documentadas explícitamente:

- **1,571 cuentas activas, no 1,572** — CONTEXT contó como cuenta el
  `COD_CUENTA` nulo de 2 líneas móviles activas. Sin cuenta no hay documento que
  emitir: se reportan aparte como no facturables.
- **422 sin factura, no 423** — mismo motivo.
- **487 facturas en cartera, no 504** — el *monto* coincide al céntimo
  (S/18,297.69); el *conteo* depende del umbral de saldo y no se reproduce
  ajustándolo. Por eso el informe lidera con montos.

---

## Datos

Seis CSV en `data/`, separador `|`, encoding `latin-1`: clientes (1,000),
planta fija (943), planta móvil (1,798), pagos (3,548), facturas (3,364) y
notas de crédito (196). Moneda PEN, IGV 18%. Fecha de corte del demo:
**2026-08-12**.

## Contexto de negocio

`docs/CONTEXT.md` y `docs/03. Desafío SON-IA_VF.pdf` — ficha oficial del Reto 3
del AI Telecom Challenge (Movistar + Universidad de Lima).
