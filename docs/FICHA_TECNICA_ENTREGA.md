# SON-IA · Ficha técnica de entrega

Documento de trabajo para redactar el ejecutivo del hackathon. **Todo lo que sigue está
extraído del código y de ejecuciones reales**, no de memoria ni de documentación previa.
Las cifras provienen de cuatro ejecuciones hechas el **2026-08-14** sobre el dataset de `data/`:

- `python validar_baseline.py` → paridad 9/9 con `docs/CONTEXT.md`.
- `python run_demo.py --deterministico` → corrida `20260814_004430_ae0a85`, 11/11 tools, 0 errores, 5.1 s.
- `python run_demo.py` (agentes sobre Groq) → corrida `20260814_004559_2405a1`, modo `hibrido`, 11/11 tools, 129.5 s.
- `python -m pytest tests/ -q` → 7 passed.

Donde algo **no existe en el código**, se dice explícitamente. Esas notas van marcadas
con **[NO EXISTE]** o **[OJO]**.

---

## 1 · Arquitectura real

### 1.1 Estructura de carpetas

```
UL Telecom/
├── api/
│   ├── main.py            FastAPI: 13 endpoints, SSE, subida de datasets
│   └── servidor.py        Envoltura de despliegue: API en /api + web/dist en la raíz
├── src/
│   ├── data_loader.py     Carga y normaliza los 6 CSV. Parser tolerante de fechas,
│   │                      clave canónica de documento, saldos, cartera, aging, asserts
│   ├── contracts.py       ResultadoTool y Alerta — la frontera hacia el LLM
│   ├── audit.py           LogAuditoria: JSONL en vivo + JSON consolidado
│   ├── plan.py            PLAN_DE_CIERRE (11 pasos) — fuente única de los dos caminos
│   ├── pipeline.py        Camino determinista: recorre el plan sin LLM
│   ├── crew.py            Orquestación CrewAI + red de seguridad + consolidación
│   ├── agents.py          3 agentes operadores + supervisor + LLMGroq saneado
│   ├── router.py          Lenguaje natural → tool, whitelist y guardarraíl numérico
│   ├── reporte.py         Informe consolidado (compartido por ambos caminos)
│   ├── formato.py         Helpers de presentación (pen/pct/num/aging) — sin aritmética
│   ├── voz.py             VOZ_ANALISTA + limpiar_relleno (filtro anti-muletillas)
│   └── tools/
│       ├── registro.py    Registro de tools + ejecutar()  ← EL EMBUDO
│       ├── crew_adapters.py  Envoltura CrewAI generada desde el registro
│       ├── facturacion.py    3 tools
│       ├── cobranzas.py      3 tools
│       └── bi.py             5 tools
├── web/                   Tablero React 19 + TypeScript + Vite 6 + Tailwind 4
│   └── src/
│       ├── App.tsx        4 vistas: Cierre · Hallazgos · Trazabilidad · Consulta
│       ├── charts/        Waterfall, Columnas, Línea, BarrasEnfasis (SVG propio)
│       ├── components/    14 componentes (AgentTrack, AuditLog, Chat, HeroCartera,
│       │                  SupervisorPanel, VistaHallazgos, PanelDatos, GuionPitch…)
│       ├── lib/           api.ts · sse.ts · destacados.ts · format.ts · types.ts
│       └── state/         runReducer.ts (máquina de estados del stream), useArco
├── data/                  6 CSV separados por `|`, latin-1, + corte.txt (2026-08-12)
├── docs/                  CONTEXT.md · ficha oficial del reto (PDF) · esta ficha
├── logs/                  Un par .jsonl + .json por corrida (auditoría)
├── tests/test_fixture_demo.py   7 tests de regresión del dataset del demo
├── run_demo.py            Demo de consola
├── validar_baseline.py    Paridad contra CONTEXT.md + reconciliación A→B→C
├── Dockerfile             Multi-etapa: build del front + runtime Python 3.11
└── render.yaml            Blueprint de Render (docker, plan free, healthcheck /api/)
```

### 1.2 Los agentes

Cuatro agentes CrewAI, definidos en `src/agents.py`. **Los cuatro corren sobre Groq**
a temperatura `0.1`.

| Agente (función) | `role` exacto | Modelo | Parámetros |
|---|---|---|---|
| `agente_facturacion()` | Especialista en Aseguramiento de Ingresos y Facturación B2B | `openai/gpt-oss-20b` (`SONIA_MODELO_RAPIDO`) | `max_tokens=700`, `max_iter=4`, `max_rpm=12`, `allow_delegation=False` |
| `agente_cobranzas()` | Analista de Cobranzas y Recaudo B2B | `openai/gpt-oss-20b` (`SONIA_MODELO_RAPIDO`) | `max_tokens=700`, `max_iter=4`, `max_rpm=12`, `allow_delegation=False` |
| `agente_bi()` | Analista de Inteligencia de Negocio del Ciclo de Ingresos | `openai/gpt-oss-120b` (`SONIA_MODELO_POTENTE`) | `max_tokens=1000`, `max_iter=6`, `max_rpm=8`, `allow_delegation=False` |
| `agente_supervisor()` | Supervisor del Ciclo de Ingresos B2B (SON-IA) | `openai/gpt-oss-120b` (`SONIA_MODELO_POTENTE`) | `max_tokens=1000`, `max_iter=6`, `max_rpm=8`, `allow_delegation=True`, **`tools=[]`** |
| *(chat, no es Agent)* | `llm_chat()` usado por `src/router.py` | `openai/gpt-oss-20b` (`SONIA_MODELO_CHAT`) | `max_tokens=500`, `reasoning_effort=low` |

**Goals (resumidos, literal del código):**

- **Facturación** — "Garantizar que todo servicio activo en planta fija y móvil se facture
  de forma oportuna y correcta. Operas el momento 1 del ciclo, la asesoría previa a la
  emisión: validas los insumos del PxQ, alertas los quiebres ANTES de emitir y dejas
  registro auditable de cada tarea."
- **Cobranzas** — "Conciliar lo cobrado contra lo facturado, ejecutar la rebaja automática
  post-pago, identificar las partidas bancarias huérfanas y medir la cartera vencida con
  aging 1-30 / 31-60 / 61-90 / 90+ días."
- **BI** — "Convertir los hallazgos de Facturación y Cobranzas en decisiones: ratio
  cobrado/facturado, provisión de cobranza dudosa, priorización para la mesa de aceleración
  de recupero, adelanto operativo de caja y detección de anomalías. Cuantificas el impacto
  en soles y propones la acción concreta."
- **Supervisor** — "Orquestar el cierre del ciclo delegando en los tres especialistas y
  consolidar un informe ejecutivo con los hallazgos priorizados por impacto en soles. NO
  ejecutas herramientas ni calculas nada: delegas, controlas y consolidas citando
  textualmente las cifras que te reportan tus agentes."

Los tres goals operadores terminan con la misma cláusula repetida a propósito
(`_REGLA_CIFRAS`): *"NUNCA calcules, estimes ni redondees cifras por tu cuenta… cítalas
EXACTAMENTE como te las devuelven"*.

**Por qué se reparten entre dos modelos** (documentado en el propio módulo): en el plan
gratuito de Groq el techo de tokens por minuto es **por modelo**, 8.000 TPM en cada gpt-oss.
Repartir no es un lujo, son dos bolsas de cuota en lugar de una: el `120b` lleva a quien
razona (supervisor y BI) y el `20b` a los dos especialistas y al chat. Cada turno de un
agente reenvía todo su bloc de notas (~2.200 tokens/petición) y los gpt-oss suman encima sus
tokens de razonamiento, así que la bolsa del `120b` se agota antes de cerrar los once pasos
y la corrida acaba en modo híbrido. Eso no es un fallo: es el escenario que la red de
seguridad existe para cubrir.

**El chat va con `reasoning_effort=low`, los agentes no.** El razonamiento se descuenta del
mismo `max_tokens` que la respuesta, así que un modelo que piensa de más se queda sin
presupuesto y devuelve `content` vacío — que es como CrewAI y el router ven "no hubo
respuesta". El chat hace dos llamadas por pregunta y las dos son de transcribir (elegir de un
catálogo cerrado y redactar sin añadir cifras), así que ahí el razonamiento no compra nada y
cuesta el triple de tokens: medido con el mismo prompt, 395 tokens de salida contra 114. En
los agentes del cierre sí se paga, porque ahí el modelo decide qué herramienta usar y en qué
orden.

`LLMGroq` (subclase de `crewai.LLM`) parchea dos incompatibilidades reales:
1. CrewAI 1.15 marca los mensajes con `cache_breakpoint` y define `strip_cache_breakpoint()`
   pero **nunca la llama** en la ruta LiteLLM; Groq valida el esquema estrictamente y
   rechaza la petición. Se limpia en `_format_messages_for_provider`.
2. Reintento propio ante 429 que **lee del error el tiempo de espera que indica Groq**
   ("try again in 15.07s") y espera eso (`SONIA_REINTENTOS_LLM`, 5 por defecto).
   `num_retries` de LiteLLM no cubría el caso: abortaba a los ~18 s sin llegar a esperar.

### 1.3 Orquestación (supervisor)

Controlada por `SONIA_PROCESO`, en `src/crew.py`.

**Modo `supervisado` (por defecto, y el que se demuestra):**

```
Crew(process=Process.sequential, agents=[facturacion, cobranzas, bi], tasks=[3 tareas])
       │
       ├─ Task 1 · FACTURACIÓN   → resumen_facturacion, detectar_servicios_no_facturados,
       │                            validar_clientes_sunat
       ├─ Task 2 · COBRANZAS     context=[Task 1]
       │                          → conciliar_pagos, pagos_no_identificados, cartera_vencida
       └─ Task 3 · BI            context=[Task 1, Task 2]
                                  → ratio_cobrado_facturado, detectar_anomalias,
                                    provision_cobranza_dudosa, priorizar_recupero,
                                    proyeccion_caja
       ↓
_consolidar_con_supervisor()  ← UNA sola llamada al LLM sobre los tres informes
```

- **Cómo delega:** el encadenado es por `context=[...]` entre tareas — cada tarea recibe la
  salida de las anteriores. Las descripciones de tarea nombran las herramientas exactas, el
  orden y prohíben repetirlas.
- **Cómo consolida:** el supervisor recibe (a) el **ranking de alertas ya ordenado en Python**
  por severidad e impacto en soles y (b) los tres informes. No se le pide que deduzca el
  ranking: pedírselo hacía que, al no encontrar las cifras en la prosa, repitiera cuatro
  veces la misma frase genérica. Se intenta primero con el modelo de razonamiento y, si su
  cuota está agotada, con el pequeño (bolsas de TPM independientes).
- El texto del supervisor pasa por el **mismo guardarraíl numérico del chat**
  (`numeros_fuera_de`): si cita un número que no está en su fuente, se descarta su lectura y
  el informe sale solo con las cifras deterministas. Luego pasa por `limpiar_relleno()`.

**Modo `jerarquico`:** `Crew(process=Process.hierarchical, manager_agent=agente_supervisor())`,
el patrón nativo de CrewAI donde el supervisor delega turno a turno. Está implementado y
funciona, pero reenvía el contexto acumulado en cada vuelta y agota los 12.000 TPM del plan
gratuito. Por eso no es el modo por defecto.

**Red de seguridad de la ejecución** (`ejecutar_cierre()`):
1. `crew.kickoff()` corre en un hilo daemon con `join(SONIA_TIMEOUT_CREW)`.
   **[OJO] El default en el código es 180 s; el `.env` local lo sube a 300 s.** El README
   dice 300 s, que es el valor del `.env`, no el del código.
2. Si el hilo se cuelga o lanza, se avisa por SSE y **se rellenan solo los pasos que faltan**
   (`ejecutar_pasos(faltantes)`). Lo que los agentes sí lograron se conserva.
3. `modo = "crew"` si no hubo fallo ni pasos omitidos; `"hibrido"` en cualquier otro caso.
4. La consolidación del supervisor se intenta **también** cuando el crew falló: es una sola
   llamada pequeña y el modo híbrido es el caso frecuente con la cuota apretada.
5. Cancelación cooperativa: `registro.pedir_cancelacion()` marca una bandera que se consulta
   en los dos puntos por donde pasa todo el trabajo — `ejecutar()` y `LLMGroq.call`.

### 1.4 Las 11 tools deterministas

Todas son funciones Python puras sobre pandas. **Ninguna habla con un LLM.** Todas devuelven
`ResultadoTool` y se registran con el decorador `@registrar(...)`.

Notación de tablas: `001 clientes` · `002 planta fija` · `003 planta móvil` · `004 pagos` ·
`005 facturas` · `006 notas de crédito`.

#### Agente de Facturación (`src/tools/facturacion.py`)

| # | Función | Qué calcula | Tablas |
|---|---|---|---|
| F1 | `resumen_facturacion(ruc=None)` | Escalera mensual de facturación, reparto por sistema origen y por fuente (cíclica/acíclica), notas de crédito como proxy de error operativo, ticket promedio | 005, 006 |
| F2 | `detectar_servicios_no_facturados(incluir_suspendidos=False)` | Cuentas con servicio activo que no tienen ninguna factura emitida, y la exposición mensual estimada (cuentas × ticket mediano) | 002, 003, 005 |
| F3 | `validar_clientes_sunat(ruc=None)` | Facturas a RUC NO HABIDO, a contribuyentes de baja/suspensión, facturas a RUC fuera del maestro, y control del PxQ (neto+IGV vs total, tasa fuera de 17-19%) | 005, 001 |

#### Agente de Cobranzas y Recaudo (`src/tools/cobranzas.py`)

| # | Función | Qué calcula | Tablas |
|---|---|---|---|
| C1 | `conciliar_pagos(conciliacion="canonica")` | Estado por documento (CANCELADA/PARCIAL/PENDIENTE) y saldo vivo, contrastando el cruce literal contra el canónico y el monto que se reclasifica de "deuda" a "cobrado sin aplicar" | 005, 004, 006 |
| C2 | `pagos_no_identificados(solo_recuperables=False)` | Pagos cuya `FACTURA_AFECTADA` no existe en el maestro, separando los recuperables por clave canónica de los realmente huérfanos, con nivel de confianza del match | 004, 005 |
| C3 | `cartera_vencida(fecha_corte, tramo=None, conciliacion="canonica")` | Cartera vencida al corte con aging 1-30/31-60/61-90/90+, lo por vencer, concentración por deudor y antigüedad media | 005, 004, 006 |

#### Agente de Inteligencia de Negocio (`src/tools/bi.py`)

| # | Función | Qué calcula | Tablas |
|---|---|---|---|
| B1 | `ratio_cobrado_facturado(dias=30)` | Ratio global cobrado/facturado, ratio dentro de N días del vencimiento, periodo medio de cobro y curva empírica acumulada | 005, 004 |
| B2 | `detectar_anomalias(severidad_minima=None)` | 10 comprobaciones de datos y de proceso (moneda, sobrepagos, montos inválidos, formato de fecha, NC huérfanas o mayores a la factura, pagos duplicados, líneas sin cuenta, RUC fuera del maestro) | 005, 004, 006, 002, 003, 001 |
| B3 | `provision_cobranza_dudosa(fecha_corte)` | Provisión por tramo aplicando la matriz 0% / 25% / 50% / 100% y la cobertura resultante | 005, 004, 006 |
| B4 | `priorizar_recupero(fecha_corte, top=15)` | Ranking de clientes por `score = saldo × (1 + días_prom/90 acotado a 3) × (1.3 si NO HABIDO o sin maestro)` y la cobertura del top-N | 005, 004, 006, 001 |
| B5 | `proyeccion_caja(fecha_corte)` | Cobranza esperada a 30/60/90 días aplicando la curva empírica como función de supervivencia sobre el aging actual | 005, 004, 006 |

**[OJO] Tres tools llevan un argumento opcional por una razón técnica, no de negocio:**
Groq rechaza un schema de tool con `properties` vacío (con el mensaje confuso *"'required'
present but 'properties' is missing"*), así que `validar_clientes_sunat`,
`pagos_no_identificados` y `detectar_anomalias` necesitaban al menos un parámetro.

**[OJO] `detectar_anomalias` define 10 comprobaciones; en este dataset disparan 7.** Las tres
que no aparecen (`nota_credito_mayor_factura`, `nota_credito_sin_factura`, `pago_duplicado`)
existen en el código y devuelven 0 registros con estos datos.

### 1.5 El embudo de auditoría

**Módulo del embudo: `src/tools/registro.py`, función `ejecutar()`.**
**Módulo del log: `src/audit.py`, clase `LogAuditoria` (instancia compartida `audit`).**

`ejecutar()` es el punto único por el que pasa **toda** invocación de tool, venga del crew,
del chat, del pipeline determinista o de la API. En un solo lugar ocurren cuatro cosas:

1. **Validar** y coaccionar los argumentos con pydantic **antes** de tocar datos.
2. **Auditar** la entrada (`audit.registrar_tool`).
3. **Registrar** el resultado completo en el registro que lee el dashboard (`_ULTIMOS`).
4. **Emitir** el evento que alimenta el stream SSE.

`ejecutar()` **nunca propaga una excepción**: un fallo puntual se convierte en un
`ResultadoTool(ok=False)` y degrada una sección del informe en vez de tumbar el demo. Si el
LLM alucina un nombre de herramienta, devuelve un resultado no-ok que enumera las disponibles.

**Qué registra cada entrada de auditoría** (`tipo: "tool"`):

```
corrida_id · ts · agente · tool · inputs · ok · error · duracion_ms ·
metricas · trazas · resumen · filas_detalle · alertas[severidad,titulo,impacto_pen]
```

Hay otros dos tipos de entrada: `tipo: "agente"` (delegaciones y salidas del LLM — se guarda
por trazabilidad, **ninguna cifra del informe sale de aquí**) y `tipo: "error"` (con traceback).

**Doble escritura:**
- `logs/auditoria_<corrida>.jsonl` — append línea a línea, en vivo, para que si el proceso
  muere a mitad del demo lo ya ejecutado quede en disco.
- `logs/auditoria_<corrida>.json` — consolidado al cerrar, con bloque `resumen`
  (`tools_ejecutadas`, `tools_ok`, `tools_error`, `duracion_total_ms`, `agentes`). Es lo que
  expone `GET /auditoria` y lo que se abre delante del jurado.

**El campo `trazas` es el linaje legible del cálculo.** Ejemplo real de `cartera_vencida`:
`"facturas con saldo > 0.01 y vencimiento anterior al corte -> 476"`.

### 1.6 Endpoints de la API

Definidos en `api/main.py`. **13 rutas.** (El README lista 7; esta es la lista completa real.)

| Método | Ruta | Qué devuelve |
|---|---|---|
| GET | `/` | Salud: `servicio`, `estado`, `llm_configurado` (bool), lista de endpoints |
| GET | `/tools` | Catálogo: `total` + por tool `nombre, agente, etiqueta, kpi, descripcion, argumentos` |
| GET | `/plan` | `PLAN_DE_CIERRE`: los 11 pasos con `id, agente, tool, titulo, momento, kpi, params` |
| GET | `/kpis?fecha_corte=` | Métricas de portada calculadas en directo, **sin ejecutar el crew** (facturado, cobrado, ratio, cartera, aging, PCD, fuga, conciliación, reconciliación A/B/C) |
| GET | `/diagnostico` | Perfil crudo de la data: filas por tabla, formatos de fecha detectados, sistemas, conciliación, facturas con fecha malformada, procedencia del corte |
| GET | `/resultados` | Última corrida **con el detalle fila a fila** (hasta 200 filas por tool) + métricas, columnas y trazas |
| GET | `/auditoria` | `audit.exportar()`: corrida + resumen + todas las entradas |
| GET | `/datos/estado` | Qué dataset está cargado, con qué corte y de dónde sale el corte |
| POST | `/datos/cargar` | Sube los 6 CSV (multipart, clave = nombre de tabla) + `fecha_corte` opcional. Valida en carpeta aparte y solo cambia el origen si valida. 422 con el detalle **por archivo** si falla |
| POST | `/datos/restaurar` | Vuelve al dataset del repositorio |
| POST | `/chat` | `{mensaje, usar_llm, contexto}` → respuesta, tool elegida (vacía si no se consultó nada), args, vía (`keywords`/`llm`/`seguimiento`/`sin_tool`), confianza, `clase`, `sugerencias`, `redactado_por_llm`, `redaccion_descartada`, `supuesto_ignorado`, métricas, trazas, alertas |
| **POST** | **`/run`** | **SSE.** Corre el cierre y transmite cada paso. `{objetivo, fecha_corte, deterministico}` |
| POST | `/run/detener` | Marca la bandera de cancelación. Responde `detenido: true` — aceptado, no consumado |

**Detalle del SSE (`POST /run`):** `crew.kickoff()` es bloqueante, así que corre en un worker
thread; el puente al bucle de eventos es `loop.call_soon_threadsafe(cola.put_nowait, evento)`.
El generador async drena la cola con `timeout=10.0` para emitir heartbeats, más `ping=15000`
de `EventSourceResponse`. Se emite exactamente un evento terminal.

**Tipos de evento SSE reales:**

```
corrida_inicio · paso_inicio · tool_inicio · tool_fin · tool_error ·
agente_mensaje · tarea_fin · aviso · corrida_fin · reporte_final ·
cancelado · error · ping · fin
```

`fin` es el **único** evento terminal: `corrida_fin` llega antes de `reporte_final`, y `error`
tampoco cierra el stream.

**Despliegue:** `api/servidor.py` monta la misma API bajo `/api` y sirve `web/dist` en la raíz,
de forma que en producción hay una sola URL y cero CORS. En desarrollo son dos procesos
(uvicorn 8000 + Vite 5173 con proxy `/api`).

### 1.7 El fallback determinista

**Fuente única:** `src/plan.py::PLAN_DE_CIERRE`. Los dos caminos consumen la misma lista —
`crew.py` la renderiza en las descripciones de tarea, `pipeline.py` la itera llamando
`ejecutar()`. Por eso el fallback **no es un demo degradado**: son los mismos pasos, las mismas
tools y las mismas cifras.

**Qué lo dispara (seis disparadores reales):**

1. `python run_demo.py --deterministico` o `POST /run {"deterministico": true}`.
2. **No hay una `GROQ_API_KEY` utilizable** → se avisa y se va directo a `ejecutar_plan()`.
   La clave se sanea antes de mirarla (`src/proveedor.py::clave_groq`): con comillas o con el
   salto de línea del copiar y pegar no vale, y Groq responde a eso lo mismo que a una clave
   revocada.
3. **El sondeo previo** dice que Groq no está utilizable (`estado_de_groq()`): la clave está
   rechazada, o el modelo configurado ya no está en el catálogo. Es un GET al catálogo, sin
   gastar tokens, y corta antes de arrancar en lugar de descubrirlo a mitad de corrida.
4. El crew **excede el timeout** (`hilo.join(TIMEOUT_CREW_S)` y sigue vivo).
5. El crew **lanza una excepción** (capturada como `BaseException` en el worker, porque
   LiteLLM lanza excepciones raras). En el aviso sale la causa en una frase, no el nombre de
   la clase: `BadRequestError` es lo que devuelve LiteLLM ante una clave inválida, y leído
   tal cual manda a buscar el fallo al sitio equivocado. El volcado entero queda en la
   auditoría (`src/proveedor.py::motivo_humano`).
6. El crew termina bien pero **omitió pasos del plan** → se rellenan solo los faltantes.

**Qué garantiza:**

- Las cifras son **idénticas**; lo único que falta es la narrativa redactada por el modelo.
- El relleno es **quirúrgico**: `faltantes = [p for p in PLAN_DE_CIERRE if p.tool not in ejecutadas]`.
  Lo que los agentes sí lograron se conserva y aparece en el informe.
- El log de auditoría sale igual de completo.
- El informe se arma siempre con `render_reporte()` sobre el registro de resultados, nunca
  desde la salida del LLM.
- El modo queda declarado en el informe y en el evento SSE: `deterministico` / `crew` / `hibrido`.

**[OJO] La cancelación desactiva la red de seguridad a propósito:** si el usuario pulsó
detener, rellenar los pasos que faltan sería exactamente lo contrario de lo que pidió, y
anunciarlo como "el crew falló" sería falso.

### 1.8 El guardarraíl del chat

Cuatro etapas separadas a propósito (`src/router.py`):

0. **¿ES UNA PREGUNTA SOBRE LOS DATOS?** Un saludo, un "gracias" o un "¿qué puedes hacer?"
   se contestan sin ejecutar nada, con `charla()`, y sin llamar al modelo. La comprobación va
   **después** de las reglas de palabras clave, no antes: *«hola, ¿cuánto tenemos por
   cobrar?»* es una pregunta con un saludo delante, y esa sí consulta.
1. **CLASIFICAR.** El LLM propone `{"tool": "...", "args": {}}` sobre un catálogo cerrado.
   La **whitelist es `_ESPECS`, el registro vivo de tools**: `if tool in ESPECS`. Cualquier
   nombre inventado se descarta y cae a `clasificar_por_reglas()`, 12 reglas de palabras clave
   con pesos que funcionan **sin API key**. El router puede además devolver `{"tool": null}`
   para lo que no es de este dominio.
2. **EJECUTAR.** Python corre la tool y produce las cifras.
3. **REDACTAR.** El LLM solo pone en prosa el resumen que ya trae los números.

**Cuando no se reconoce la pregunta, se dice.** `clasificar_por_reglas()` devuelve `None` en
vez de caer a `resumen_facturacion` con confianza 0.2, que es lo que hacía antes: *«hola»* y
*«¿cuál es la capital de Perú?»* recibían la escalera de facturación entera presentada como si
fuera la respuesta. Contestar otra cosa con aplomo es peor que no contestar, porque quien
pregunta no tiene forma de notarlo.

**Preguntas que se apoyan en la anterior.** *«¿y el tramo 31-60?»* no dice sobre qué. El
tablero manda el turno previo (`{pregunta, tool, args}`) y el router hereda esa herramienta,
pisando solo los argumentos que trae la pregunta nueva. Los argumentos heredados se filtran
contra el esquema de la tool: el turno anterior pudo usar otra, y colar un argumento ajeno la
haría fallar. La interfaz marca *«sigue la pregunta anterior»* — un seguimiento que no se ve
es indistinguible de una respuesta a otra cosa.

Además de las tres etapas hay **tres filtros**, y cada uno existe por un fallo observado:

**a) `_limpiar_args()` — el modelo no puede cambiar la pregunta.**
Los argumentos vacíos se descartan (el modelo rellena huecos por inercia: `top=""`, `ruc=null`).
Y los argumentos que cambian el **significado** de la pregunta (`fecha_corte`,
`incluir_suspendidos`, `conciliacion`, `severidad_minima`, `solo_recuperables`) solo pasan si
el usuario los pidió con palabras que casan un regex. Se vio a un modelo responder "¿a quién
le cobro primero?" inventándose el corte `2023-07-31`: las cifras eran reales, pero de otra
pregunta. Eso es peor que un error, porque parece correcto.

**b) `supuesto_no_soportado()` — premisas que ninguna tool acepta.**
Ninguna herramienta recibe una tasa, un escenario ni un horizonte futuro. Ante "proyéctame la
cartera con 10% de mora" el modelo respondió una vez *"Con un 10% de mora, la cobranza a 30
días sería S/34,918.63"*: las tres cifras eran reales, la premisa era falsa. Seis patrones
detectan porcentajes, condicionales, escenarios y horizontes con nombre; si alguno casa, el
modelo **no redacta** y se devuelve el resumen determinista, citando el fragmento literal.

**c) `numeros_inventados()` / `numeros_fuera_de()` — el guardarraíl numérico.**
Se extraen los números de la redacción, se normalizan (sin separadores de miles, sin ceros
finales) y se comparan contra el resumen **más** las métricas. Si alguno no sale de ahí, **se
descarta la redacción entera** y se devuelve el texto determinista. La tolerancia es
`TOLERANCIA_REDONDEO = 0.5`: un número solo se perdona si alguna cifra de la fuente redondea a
él — `26.86` justifica un `"27"`, nada justifica un `"67"` cuando la fuente dice `66`.

El mismo guardarraíl se aplica a la lectura ejecutiva del supervisor en `crew.py`. Se añadió
porque al supervisor **se le coló un "67 pagos" donde los datos decían 66**, en el bloque que
más se lee del informe.

**Y la frontera estructural, que es la razón de fondo:** `ResultadoTool.texto_para_llm()`
devuelve **únicamente** `.resumen`, recortado a 600 caracteres (`SONIA_RESUMEN_MAX_CHARS`) y
cortado en el último punto completo, nunca a medio carácter (truncar en seco partiría una
cifra por la mitad y el agente citaría "S/47,8"). El detalle fila a fila (`.data`) va a la API
y al dashboard, **nunca al modelo**. El LLM no puede citar una cifra que una función Python no
produjo, porque no la vio.

---

## 2 · Cifras finales verificadas

Corte: **2026-08-12** (fijado en `data/corte.txt`). Corrida `20260814_004430_ae0a85`.

### 2.1 El arco A → B → C de cartera vencida

| Vista | Qué es | Facturas | Monto |
|---|---|---:|---:|
| **A** | Lo que el sistema ve hoy (formato único de fecha, cruce literal de correlativo, sin deducir NC) | 487 | **S/18,297.69** |
| **B** | Con parseo tolerante de fechas: aparecen las 57 facturas de ISIS | 520 | **S/153,976.98** |
| **C** | Con conciliación canónica: se descuentan los pagos ya cobrados sin aplicar | 476 | **S/47,819.06** |

- A → B: **+57 facturas de ISIS por S/137,200.41** que hoy desaparecen del reporte.
- B → C: **−66 pagos por S/106,157.92** que ya estaban cobrados y no aplicados.
- **Deuda real al corte: S/47,819.06** (no S/18,297.69, ni S/153,976.98).
- Sin identificar de verdad: **8 pagos por S/131.48**.

### 2.2 Los cuatro hallazgos con monto

| Hallazgo | Monto | Volumen |
|---|---:|---|
| Fuga por servicios no facturados | **S/26,556.46** por mes de ciclo | **422** cuentas activas sin factura, de 1,571 (26.9%), que afectan a **274** clientes |
| Facturas ISIS invisibles | **S/137,200.41** | **57** facturas (100% `SISTEMA=ISIS`) |
| Pagos ya cobrados sin aplicar | **S/106,157.92** | **66** pagos |
| Facturas a RUC NO HABIDO | **S/2,414.79** | **21** facturas, a **11** clientes |

Detalle adicional de cada uno:

- **Fuga:** desglose por planta fija 341 / móvil 81. Ticket mediano por cuenta facturada
  S/62.93. Segmentos más golpeados: SEGMENTO_004 (392), SEGMENTO_002 (36), SEGMENTO_001 (23).
  Aparte: **2 líneas móviles ACTIVAS sin `COD_CUENTA`** — sin cuenta no hay documento que
  emitir, son 100% no facturables.
- **Partidas bancarias sin aplicar (el universo del que salen los 66):** **74 pagos por
  S/106,289.40** (2.09% del total de pagos). Origen: ISIS 67 / AMDOCS 7. Confianza del match:
  exacto_monto 42, revisar_moneda 20, sin_match 8, parcial 4. De ellos, **21 están en moneda
  distinta a PEN por S/12,248.79**.
- **RUC NO HABIDO:** el maestro tiene 18 RUC NO HABIDO. Además, 130 facturas (S/8,897.35) van
  a contribuyentes de baja o suspensión temporal, y 1,871 facturas (55.6%, S/216,379.53) se
  emitieron a RUC que **no está en el maestro**.

### 2.3 Ratio, PCD y aging

**Ratio cobrado/facturado**

| Métrica | Valor |
|---|---:|
| Ratio global (S/392,837.26 / S/447,964.58) | **87.69%** |
| Dentro de 30 días del vencimiento (KPI oficial de Cobranzas) | **83.59%** |
| Brecha sin cobrar | S/55,127.32 |
| Periodo medio de cobro hacia el vencimiento | +4.2 días de media, **−1 de mediana** (se paga antes de vencer) |
| Base del cálculo | 3,540 pagos cruzados contra su factura |

Curva empírica de cobro: ≤0d **48.23%** · ≤7d **68.06%** · ≤15d **77.79%** · ≤30d **83.59%** ·
≤60d **99.37%** · ≤90d 99.49% · ≤180d 99.84%.

**Provisión de cobranza dudosa — PCD total S/11,753.18 (24.58% de cobertura)**

| Tramo | Facturas | Saldo | Tasa | Provisión |
|---|---:|---:|---:|---:|
| 1-30 | 88 | S/20,664.08 | 0% | S/0.00 |
| 31-60 | 167 | S/16,003.31 | 25% | S/4,000.83 |
| 61-90 | 133 | S/6,798.64 | 50% | S/3,399.32 |
| 90+ | 88 | S/4,353.03 | 100% | S/4,353.03 |
| **Total vencido** | **476** | **S/47,819.06** | — | **S/11,753.18** |

Por vencer (aún no exigible): **61 facturas por S/5,987.13**.
Antigüedad media de la cartera vencida: **81.4 días**.

**[OJO] La matriz PCD (0/25/50/100) es un criterio conservador elegido por el equipo.** La
ficha del reto no fija porcentajes; está parametrizada en `PCD_TASAS` (`data_loader.py`).

### 2.4 Universo del dataset

| Concepto | Valor |
|---|---:|
| Total facturado | **S/447,964.58** |
| Total pagado | **S/392,837.26** |
| Aplicado a documento (modo canónico) | S/392,705.78 |
| Nº de facturas | **3,364** |
| Nº de pagos | **3,548** |
| Nº de clientes en el maestro | **1,000** |
| Nº de clientes distintos facturados (RUC) | 999 |
| Nº de cuentas facturadas | 1,672 |
| Notas de crédito | **196 por S/3,093.22** (0.69% de lo facturado) |
| Ticket promedio por documento | S/133.16 |
| Rango de emisión | 2023-04-18 a 2026-08-05 |

### 2.5 Otras cifras titulares que el demo muestra

**Conciliación y estado de documentos**

- Cruce literal: **3,474 de 3,548 pagos = 97.91%**. Cruce canónico: **3,540 = 99.77%**.
- Documentos: **2,827 CANCELADAS · 537 PARCIALES · 0 PENDIENTES** sobre 3,364.
- Saldo vivo total: **S/53,806.19** (bajo el algoritmo actual serían S/159,964.11 →
  **reclasificación de S/106,157.92**).

**Escalera de facturación (últimos 4 meses)**

| Mes | Documentos | Monto |
|---|---:|---:|
| 2026-05 | 609 | S/126,670.79 |
| 2026-06 | 1,555 | S/194,715.84 |
| 2026-07 | 1,036 | S/102,048.21 |
| 2026-08 | 47 | S/5,766.74 |

Por sistema origen: **AMDOCS 3,307 docs S/310,764.17** · **ISIS 57 docs S/137,200.41**.
Por fuente: FACTURACION ACICLICA 21 docs S/100,762.47 · FACTURACION CICLICA 3,343 docs
S/347,202.11.

**Concentración y mesa de recupero**

- **284 clientes** con saldo vencido.
- Top 10 deudores: **S/36,306.38 = 75.9%** de la cartera.
- Top 15 priorizados: **S/37,152.46 = 77.7%**.
- Mayores deudores: `2029902035` S/18,275.95 (6 fact, 47 d) · `2028712026` S/10,266.79
  (5 fact, 54 d) · `2098363854` S/3,567.21 (3 fact, 85 d).

**Adelanto operativo de caja**

- Saldo expuesto: **S/53,806.19**.
- Cobranza esperada: **S/34,918.63 a 30 d** · **S/44,520.84 a 60 d** · **S/46,757.06 a 90 d**.
- En riesgo más allá de 90 días: **S/7,049.13**.

**Anomalías: 7 tipos sobre 2,105 registros**

| Tipo | Registros | Monto |
|---|---:|---:|
| `factura_ruc_fuera_maestro` | 1,871 | S/216,379.53 |
| `factura_sobrepagada` | 152 | S/1,640.79 |
| `fecha_vto_formato_inconsistente` | 57 | S/137,200.41 |
| `pago_moneda_distinta` | 21 | S/12,248.79 |
| `linea_activa_sin_cuenta` | 2 | — |
| `factura_monto_invalido` | 1 | — |
| `factura_sin_moneda` | 1 | S/0.70 |

**Control del PxQ:** 69 facturas donde neto + IGV no cuadra con el total; 38 con tasa de IGV
fuera del rango 17-19% (esperado 18%).

### 2.6 Cuadro de impacto — **estas partidas NO se suman entre sí**

| Partida | Monto | Naturaleza |
|---|---:|---|
| Cobrado sin aplicar, recuperable de inmediato | S/106,157.92 | una vez |
| Cartera vencida real a gestionar | S/47,819.06 | al corte |
| … de la cual, provisión de cobranza dudosa | S/11,753.18 | contable |
| Fuga por no facturar | S/26,556.46 | **por mes** |
| Riesgo fiscal: facturas a RUC NO HABIDO | S/2,414.79 | acumulado |
| Partidas realmente sin identificar | S/131.48 | al corte |

Esto está codificado en `reporte.py::_cuadro_impacto()` y es deliberado: una partida es
dinero ya cobrado pendiente de aplicar, otra es deuda por cobrar y otra es un flujo que se
repite cada ciclo. **Sumar un cobro, una deuda y un flujo da un número sin significado**, y es
la primera pregunta que haría alguien que sepa del tema. Por el mismo motivo cada cifra tiene
**un solo nombre canónico** en todo el sistema (regla codificada en `src/voz.py`: "cartera
vencida" a secas es siempre el total; un tramo se nombra entero, "cartera vencida a más de
90 días").

---

## 3 · Stack y datos

### 3.1 Lenguajes, frameworks y librerías

**Backend — Python 3.11**

| Librería | Versión | Para qué se usa |
|---|---|---|
| `pandas` | **==2.1.3** | Núcleo determinista: **todas las cifras del demo salen de aquí**. Clavado a versión exacta a propósito |
| `numpy` | **==1.26.4** | Aging (`np.select`, `np.interp` para la curva de cobro), scoring de recupero. Anterior al ABI break de numpy 2.x, que pandas 2.1.3 no soporta |
| `python-dateutil` | ==2.8.2 | Soporte de parseo de fechas de pandas |
| `crewai[litellm]` | ==1.15.0 | Agentes, tareas y procesos (`sequential` / `hierarchical`). **El extra `[litellm]` es obligatorio**: sin él Groq no funciona |
| `fastapi` | >=0.115 | API HTTP, validación de peticiones, OpenAPI en `/api/docs` |
| `uvicorn[standard]` | >=0.34 | Servidor ASGI |
| `sse-starlette` | >=2.1 | `EventSourceResponse` para el streaming del cierre |
| `pydantic` | >=2.11.9,<2.13 | Schemas de argumentos de las 11 tools y validadores tolerantes ante la basura que manda el LLM (`top=""`, `fecha_corte="hoy"`) |
| `python-multipart` | >=0.0.9 | `POST /datos/cargar`. Declarada explícitamente: llegaba solo como transitiva de `mcp` |
| `python-dotenv` | >=1.1 | Carga del `.env` |
| `rich` | >=13.9 | Dependencia de la capa CLI |
| `pytest` | — | 7 tests de regresión del fixture del demo |

**Frontend — TypeScript**

| Librería | Versión | Para qué se usa |
|---|---|---|
| `react` / `react-dom` | ^19.0.0 | Tablero de 4 vistas (Cierre · Hallazgos · Trazabilidad · Consulta), navegables con teclas 1-4 |
| `vite` | ^6.0.0 | Dev server con proxy `/api` (que saca a CORS de la ecuación) y build de producción |
| `tailwindcss` + `@tailwindcss/vite` | ^4.0.0 | Estilos |
| `typescript` | ^5.7.0 | Tipado; `npm run build` corre `tsc -b` antes de compilar |
| `@fontsource-variable/*` | ^5.1.0 | Inter, JetBrains Mono y Space Grotesk empaquetadas (sin CDN) |

**[NO EXISTE] No hay librería de gráficos.** Waterfall, Columnas, Línea y BarrasEnfasis son
SVG escrito a mano en `web/src/charts/`. No hay Recharts, D3 ni Chart.js.

**Infraestructura**

- `Dockerfile` multi-etapa: `node:20-slim` construye el front, `python:3.11-slim` corre todo.
  Una sola imagen sirve la API bajo `/api` y el tablero en la raíz.
- `render.yaml`: Blueprint de Render (runtime docker, plan free, región oregon,
  healthcheck `/api/`, `GROQ_API_KEY` con `sync: false` para que Render la pida al desplegar
  y no quede escrita en el repositorio).

**Proveedor de LLM: Groq** (vía LiteLLM, dentro de CrewAI). Modelos `openai/gpt-oss-120b`
y `openai/gpt-oss-20b`. **[NO EXISTE] No hay fine-tuning, ni embeddings, ni RAG, ni base
vectorial** — `memory=False` en el Crew justamente para no arrastrar Chroma y sus llamadas de
red en el import.

### 3.2 Los 6 datasets

Separador `|`, encoding `latin-1`, todo leído con `dtype=str`. Moneda PEN, IGV 18%.

| Archivo | Filas | Qué contiene |
|---|---:|---|
| `001_TBL_CLIENTES_B2B.csv` | **1,000** | Maestro de clientes: RUC, razón social, segmento y estado SUNAT (estado del RUC y del contribuyente) más ubigeo |
| `002_TBL_PLANTA_FIJA_B2B.csv` | **943** | Servicios de planta fija por cuenta: ciclo, fecha de alta, estado (`Active`) y planes de voz / internet / TV |
| `003_TBL_PLANTA_MOVIL_B2B.csv` | **1,798** | Líneas móviles por cuenta: producto, fecha de alta, estado (`Activo`), tipo de línea, plan principal y fin de permanencia |
| `004_TBL_PAGOS_B2B.csv` | **3,548** | Pagos recibidos: factura afectada, fecha, moneda, subtotal, IGV, monto pagado y sistema origen |
| `005_TBL_FACTURAS_B2B.csv` | **3,364** | Facturas emitidas: nº de documento fiscal, cuenta, fuente (cíclica/acíclica), sistema, fecha de emisión y vencimiento, neto, IGV y total |
| `006_TBL_NOTAS_CREDITO_B2B.csv` | **196** | Notas de crédito: documento, factura afectada, fecha de emisión, monto sin IGV, IGV y monto |

Más `data/corte.txt`, un sidecar con la fecha de corte (`2026-08-12`). Si un dataset no lo
trae, el corte se deriva como `min(hoy, última fecha de los datos)`.

**Trampas de la data, todas manejadas en `data_loader.py`:**

1. `COD_CUENTA` / `COD_CLIENTE` traen ceros a la izquierda → todo con `dtype=str` o los joins
   pierden filas en silencio.
2. `FECHA_VTO` trae **dos formatos en la misma columna**: 3,307 en `YYYY-MM-DD` y 57 en
   `YYYYMMDD`. Parser tolerante que prueba formatos explícitos en orden.
   **Nunca `infer_datetime_format`**: resuelve `03/04/2024` como MM/DD por bloque y sin avisar.
3. El RUC se llama `NRO_IDENTIFICACION_FISCAL` en pagos y `NUMERO_IDENTIFICACION_FISCAL` en
   las otras cinco tablas.
4. Montos con decimal de punto inicial (`.85` → 0.85).
5. Planta fija usa `YYYY-MM-DD HH:MM:SS` con centinelas basura (`1970-01-01 05:31:00`, el
   epoch Unix); planta móvil usa `DD/MM/YYYY`. Se enmascara todo fuera de [1995, 2035].
6. El maestro de clientes cubre solo 1,493 de las 3,364 facturas → **todo join contra clientes
   es LEFT**, y "fuera del maestro" es un hallazgo reportable, no una fila a descartar.
7. Hace falta `.str.strip()` en todas las columnas de texto: sin eso, "274 clientes afectados"
   se convierte en 277.
8. `keep_default_na=False` + `na_values=[""]`: si no, pandas convierte un `"NA"` o `"NULL"`
   literal dentro de un RUC en `NaN` y rompe un join sin avisar.

**Invariantes que rompen ruidosamente al cargar** (`_verificar_estructura`): la clave canónica
no colisiona, ninguna `FECHA_VTO` queda sin parsear, los importes de factura y pago son
números, y hay al menos una cuenta activa. Si algo falla, se lanza `AssertionError` en vez de
reportar una cifra mala en silencio. Las constantes del dataset del demo (3,364 filas,
S/447,964.58, 1,571 cuentas) viven aparte, en `tests/test_fixture_demo.py`, para que el
sistema arranque con otros cortes.

### 3.3 La causa raíz técnica del hallazgo

> Existe un **segundo sistema de facturación, `ISIS`**, que convive con `AMDOCS` sin
> normalización de formatos, y esa única causa explica los tres síntomas más caros del
> dataset. Primero, las **57 facturas de ISIS traen `FECHA_VTO` en `YYYYMMDD`** mientras las
> 3,307 de AMDOCS vienen en `YYYY-MM-DD`: un parseo de formato único las descarta y
> **S/137,200.41 desaparecen del reporte de cartera**. Segundo, los **pagos de ISIS
> referencian el documento sin el cero inicial del correlativo** — el maestro guarda
> `S300-0248301` y el archivo de pagos dice `S300-248301` — así que el algoritmo de aplicación
> los da por huérfanos: **66 pagos por S/106,157.92 figuran como deuda estando ya cobrados**,
> y el sistema gatilla gestión de cobranza contra clientes que ya pagaron. La corrección es
> una clave canónica `PREFIJO-<entero sin ceros>` (`canon_doc`) que tiene **0 colisiones en
> las 3,364 facturas** y sube la conciliación de **97.91% a 99.77%**.

Evidencia dura, verificable en `GET /diagnostico`:

| Síntoma | Volumen | Causa raíz |
|---|---|---|
| Facturas con `FECHA_VTO` en `YYYYMMDD` | 57 · S/137,200.41 · ninguna pagada | **100% `SISTEMA=ISIS`** |
| Pagos "no identificados" | 74 · S/106,289.40 | **67 de los 74 son ISIS** |
| Pagos en moneda ≠ PEN contra facturas 100% PEN | 21 · S/12,248.79 | **los 21 son ISIS** |

Reparto de sistemas: facturas AMDOCS 3,307 / ISIS 57 · pagos AMDOCS 3,481 / ISIS 67.

**Y el remate para el pitch:** son tres lecturas del mismo dato, y cada agente destapa una.
El agente de Facturación descubre A→B (las facturas invisibles), el de Cobranzas descubre B→C
(los pagos ya cobrados), y el de BI identifica que ambas comparten causa. **El delta es la
propuesta de valor.**

---

## 4 · Estado de verificación

### 4.1 Los tres caminos

| Camino | Comando | Resultado (2026-08-14) |
|---|---|---|
| **Paridad con el baseline** | `python validar_baseline.py` | **PARIDAD OK · 9/9 cifras de `CONTEXT.md` reproducidas**, más 3 diferencias documentadas y explicadas. Código de salida 0 |
| **Demo determinista** | `python run_demo.py --deterministico` | **11 de 11 tools ejecutadas, 0 con error, en 5.1 s.** Informe completo. Auditoría en `logs/auditoria_20260814_004430_ae0a85.json` |
| **Demo con agentes sobre Groq** | `python run_demo.py` | **Modo `hibrido`, 129.5 s, 11 de 11 tools, 0 con error.** Los agentes ejecutaron 7 pasos; Groq cortó por límite de tokens/minuto y la red de seguridad completó los 4 restantes. El supervisor sí consolidó *(detalle en §4.2)* |
| **Regresión del fixture** | `python -m pytest tests/ -q` | **7 passed en 2.30 s** |

**Las 9 cifras de paridad reproducidas:** facturado S/447,965 · pagado S/392,837 · 196 notas
de crédito · 21 facturas a RUC NO HABIDO · 74 pagos no identificados · S/106 mil no
identificados · conciliación 97.9% · cartera vencida S/18,298 · cartera 90+ S/4,353.

**Las 3 diferencias conocidas, que no son errores:**

| Cifra | `CONTEXT.md` | SON-IA | Por qué |
|---|---:|---:|---|
| Cuentas con servicio activo | 1,572 | **1,571** | CONTEXT contó como cuenta el `COD_CUENTA` nulo de 2 líneas móviles activas. Sin cuenta no hay documento que emitir: se reportan aparte como no facturables |
| Cuentas activas sin factura | 423 | **422** | Mismo motivo (1 de las 423 era ese nulo) |
| Facturas en cartera vencida | 504 | **487** | El **monto coincide al céntimo** (S/18,297.69); el **conteo** depende del umbral de saldo (`TOL_SALDO = 0.01`) y no se reproduce ajustándolo. Por eso el informe lidera con montos |

### 4.2 Camino con Groq — qué pasó exactamente hoy

Corrida `20260814_004559_2405a1`, con `SONIA_PROCESO=supervisado` y ambos modelos de agente
en `llama-3.3-70b-versatile`. **Terminó en modo `hibrido` en 129.5 s, con 11 de 11
herramientas ejecutadas y 0 errores.** La secuencia real, leída del log de auditoría:

> Esta medición es del 14 de agosto y se deja tal cual, con el modelo que corrió entonces.
> Groq retiró los `llama-3.x` del catálogo el 17 de agosto y el sistema pasó a los `gpt-oss`;
> el reparto de modelos cambió, y las duraciones también (de 65 s a 191 s según lo que se
> haya gastado del minuto anterior). Lo que no cambió es el desenlace, que es lo que esta
> sección demuestra: 11 de 11 tools y cifras idénticas a la corrida determinista.

1. Los agentes de **Facturación** (3 tools) y **Cobranzas** (3 tools) completaron sus bloques
   con el LLM decidiendo las llamadas: 7 de las 11 tools se ejecutaron por decisión de un
   agente, incluida `ratio_cobrado_facturado` del bloque de BI.
2. En el bloque de BI, **Groq empezó a devolver 429 por tokens por minuto**. `LLMGroq.call`
   leyó del propio error el tiempo de espera y reintentó cinco veces (16.3 s, 12.3 s, 15.6 s,
   15.5 s, 18.7 s). El mensaje literal de Groq:
   `Limit 12000, Used 10795, Requested 4014`.
3. Agotados los reintentos, el crew lanzó. El worker lo capturó, emitió el aviso
   *"El crew falló (…). Completando de forma determinista"* y **la red de seguridad rellenó
   solo los 4 pasos que faltaban**: `detectar_anomalias`, `provision_cobranza_dudosa`,
   `priorizar_recupero` y `proyeccion_caja`.
4. **El supervisor sí consolidó**, en una sola llamada sobre los informes disponibles, y su
   lectura **pasó el guardarraíl numérico**: las tres cifras que cita (S/137,200.41,
   S/106,289.40, S/26,556.46) salen del ranking de alertas que se le entregó ya calculado.

Lectura ejecutiva que produjo el supervisor, literal:

> La coexistencia de dos sistemas de facturación sin normalización de formatos es la raíz
> común de los problemas. Esto genera discrepancias en la facturación y el cobro. La falta de
> normalización entre los sistemas de facturación AMDOCS e ISIS provoca problemas de
> conciliación y seguimiento de pagos.
>
> Facturación en ISIS no consolidada: S/137,200.41.
> Partidas bancarias sin aplicar: S/106,289.40.
> Fuga por no facturar: S/26,556.46.
>
> Normalizar el correlativo ISIS contra AMDOCS (TI).
> Revisar y aplicar partidas bancarias sin aplicar (Cobranzas).
> Identificar y facturar cuentas con servicio activo sin factura emitida (Facturación).
> Revisar y provisionar cartera vencida según matriz de provisión (Contabilidad).

**Todas las cifras del informe son idénticas a las de la corrida determinista.** El tiempo de
cómputo de las 11 herramientas fue de 7.4 s en total; los otros ~122 s son el LLM y las
esperas por cuota.

**Cómo presentar esto, que es lo honesto y además juega a favor:** hoy el modo `crew` puro no
se alcanzó — el plan gratuito de Groq no dio para los tres bloques seguidos. **La corrida
salió completa igual.** Es exactamente el escenario para el que se diseñó la red de seguridad,
y demuestra en vivo que el sistema no depende de que un LLM remoto se porte bien.

**[OJO] El `README.md` afirma "con la key buena corre en modo `crew` en ~65 s".** Eso ocurrió
en pruebas anteriores, pero **no es lo que pasa hoy** y depende del consumo de cuota previo
del minuto. Conviene no prometerlo en el pitch: lo que sí se puede prometer es que el cierre
termina completo en los dos escenarios.

**[OJO] El campo `modo` del JSON de auditoría dice `crew`** porque se escribe al *abrir* la
corrida; el modo final resuelto (`hibrido`) es el que aparece en el informe y en el evento SSE
`reporte_final`. Si alguien abre el log, es la única lectura que puede confundir.

### 4.3 Limitaciones y supuestos que hay que declarar

Esto es lo que conviene decir antes de que lo pregunten.

**Sobre los datos**

1. **El dataset es el que entrega la organización del reto**, con 6 CSV y corte fijado en
   `data/corte.txt` (2026-08-12). No es data productiva de Integratel y las cifras no deben
   presentarse como pérdidas reales de la compañía, sino como lo que el dataset del reto
   permite medir.
2. **El corte está clavado a propósito** para que las cifras del demo no se muevan de un día
   para otro. Con otro dataset, el corte se deriva de las propias fechas.
3. El maestro de clientes cubre **1,493 de 3,364 facturas**: en el 55.6% de los documentos
   **no se puede validar el estado SUNAT** antes de emitir. Es un hallazgo reportado, pero
   también un límite de lo que se puede afirmar sobre riesgo fiscal.

**Sobre lo que es cálculo y lo que es estimación**

4. **La fuga de S/26,556.46 es una estimación**, no facturación perdida contabilizada: es
   `422 cuentas × ticket mediano por cuenta facturada (S/62.93)`. Se usa la **mediana** y no
   la media a propósito, porque la media está inflada por las facturas grandes de ISIS y
   sobreestimaría la fuga casi al triple.
5. **La matriz PCD (0% / 25% / 50% / 100%) es un criterio conservador elegido por el equipo.**
   Ni la ficha del reto ni `CONTEXT.md` fijan porcentajes. Está parametrizada.
6. **La proyección de caja no extrapola la serie temporal de pagos**, porque `FECHA_PAGO` solo
   cubre 2026-06-01 a 2026-07-31 (con un hueco de 12 días antes del corte). Se usa la curva
   empírica de cobro como función de supervivencia sobre el aging actual. Es lo que la data
   sostiene; extrapolar sería inventar.
7. Los **conteos de facturas son hipersensibles al umbral de saldo** (476/487/504/516/520
   según umbral y modo); los **montos varían menos de S/0.30**. Por eso el informe lidera
   siempre con montos y muestra la vista (A/B/C) junto a la cifra.

**Sobre el alcance del sistema**

8. **SON-IA es de solo lectura: no escribe en ningún sistema.** No emite facturas, no aplica
   pagos, no genera ficheros de rebaja ni toca AMDOCS o ISIS. Diagnostica, cuantifica y
   prioriza; la ejecución de la corrección es una acción con responsable asignado en el informe.
9. **[NO EXISTE] El momento 2 del ciclo ("Ejecución automatizada", emitir el documento sin
   intervención humana) no está implementado.** La constante `MOMENTO_2` está declarada en
   `src/plan.py` pero **ningún paso del plan la usa**: los 11 pasos cubren el momento 1
   (asesoría previa a la emisión, 3 pasos) y el momento 3 (rebaja automática post-pago,
   2 pasos), más 6 pasos de análisis sin momento asignado. Esto es correcto declararlo: emitir
   documentos fiscales exige integración con el facturador y no era el alcance del prototipo.
10. **[NO EXISTE] No hay centralización ni clasificación de comunicaciones con clientes**
    (correos que confirman pagos), que `CONTEXT.md` menciona para Cobranzas y Recaudo. El
    dataset no trae ese canal.
11. **[NO EXISTE] No hay persistencia.** El registro de resultados y el dataset cargado viven
    en memoria del proceso; lo único que se escribe a disco son los logs de auditoría. No hay
    base de datos.
12. **Una corrida a la vez.** `POST /run` responde 409 si ya hay un cierre en curso, porque el
    registro de resultados es de módulo.
13. **La cancelación es cooperativa, no inmediata.** A un hilo de Python no se le puede dar
    muerte desde fuera: la parada ocurre en el siguiente punto de control (la próxima
    herramienta o la próxima llamada al modelo). Por eso `POST /run/detener` devuelve
    "aceptado", no "consumado".

**Sobre el LLM**

14. **El modelo nunca calcula.** Es la propiedad central y es **mecánica, no aspiracional**:
    el LLM solo ve `ResultadoTool.resumen` (600 caracteres máximo), nunca el detalle fila a
    fila. No puede citar una cifra que pandas no produjo porque no la vio.
15. **El prompt no es garantía, y el código lo asume.** Hay cuatro sitios donde imponer algo
    por prompt falló en pruebas reales y hubo que ponerle código determinista detrás:
    el guardarraíl numérico (el supervisor escribió "67 pagos" donde había 66), el filtro de
    supuestos (reetiquetó un saldo de hoy como "la cartera a diciembre"), `_limpiar_args`
    (se inventó una fecha de corte) y `limpiar_relleno` (siguió escribiendo "lo que
    representa" con la fórmula expresamente prohibida en el system prompt).
16. **Depende de un servicio externo con cuota.** El plan gratuito de Groq limita por tokens
    por minuto y por modelo. La arquitectura lo asume: modelos separados para chat y agentes,
    reintento que respeta el tiempo que indica Groq, y el camino determinista como red de
    seguridad. **El demo funciona sin API key.**
17. **Con datos de otro corte, las cifras cambian y los textos de los agentes también.** Lo
    que no cambia es el procedimiento: mismas 11 tools, mismo plan, mismo log de auditoría.

**Discrepancias documentación ↔ código detectadas al redactar esta ficha**

- El `README.md` dice que el timeout del crew es 300 s; **el default en `crew.py` es 180 s** y
  los 300 s vienen del `.env` local. Al desplegar sin `.env`, rige 180 s.
- El `README.md` lista **7 endpoints**; la API expone **13**.
- El `README.md` lista 6 tipos de evento SSE; el código emite **14**.
