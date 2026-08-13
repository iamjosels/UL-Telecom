# SON-IA · Dashboard

Consola de operaciones del ciclo del ingreso B2B. Muestra a los tres agentes
trabajando en vivo y recalcula la cartera vencida mientras lo hacen.

Todo lo que se ve sale del backend. No hay ni una cifra de negocio escrita en
el código del front.

---

## Levantarlo

Hacen falta dos terminales. Primero el backend, desde la raíz del proyecto:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn api.main:app --port 8000
```

Después el front:

```powershell
cd web
npm install
npm run dev
```

Y a http://localhost:5173.

La primera carga tarda un par de segundos porque el backend parsea los seis CSV
y valida sus invariantes antes de responder. A partir de ahí va instantáneo.

Vite proxea `/api` a `http://localhost:8000`, así que el navegador nunca cruza
orígenes y no hay CORS de por medio. Si el backend corre en otro sitio:

```powershell
$env:SONIA_API = "http://192.168.1.50:8000"; npm run dev
```

---

## Qué pasa cuando cierras el ciclo

El botón dispara `POST /run`, que devuelve un stream. Según llegan los eventos,
los agentes se van encendiendo, la trazabilidad crece y el número grande se
mueve tres veces:

```
A   S/ 18,297.69   lo que el sistema ve hoy
B   S/153,976.98   Facturación destapa 57 facturas del sistema ISIS
C   S/ 47,819.06   Cobranzas ve que S/106,157.92 ya estaba cobrado
```

Ese salto es el hallazgo. Existen dos sistemas de facturación que no cruzan
entre sí, y los pagos "huérfanos" no lo eran: el maestro guarda
`S300-0248301` y el pago referencia `S300-248301`, con un cero de menos.

Las tres cifras vienen del backend. A y B de la reconciliación que devuelve
`/kpis`, C del propio evento de `cartera_vencida`. Lo único que decide el front
es cuándo revelar cada una, porque en modo determinista el backend termina en
poco más de un segundo y el arco pasaría en un parpadeo.

Con **←** y **→** puedes recorrer los tres estados a mano y detenerte a
explicar cada salto. Con **G** se abre el guión del pitch: los cuatro puntos
con sus cifras y las respuestas a lo que suelen preguntar. Se cierra con G o
Esc y no sale en las capturas.

---

## De dónde sale cada cifra

Haz clic en cualquier línea de la trazabilidad y se abre. Ahí están los
argumentos con los que se llamó la herramienta y el linaje del cálculo, paso a
paso. Por ejemplo, al abrir el riesgo tributario:

```
ARGUMENTOS
  ruc = sin filtro
CÓMO SE CALCULÓ
  1  facturas = 3364 (LEFT join contra maestro de 1000 clientes)
  2  estado SUNAT NO HABIDO -> 21 facturas / 11 RUC
  3  sin contraparte en el maestro -> 1871 facturas
  4  control neto+IGV vs total -> 69 descuadres
```

Eso es lo que hace comprobable el "0% de alucinaciones": se puede seguir un
número desde las 3,364 facturas hasta el resultado sin leer una línea de
código.

---

## El supervisor

Debajo de los agentes queda su conclusión, en dos bloques separados a
propósito:

- **Consolidado**, armado con las alertas y las métricas. Es determinista y
  está siempre, también en modo seguro.
- **Lectura ejecutiva**, redactada por el modelo sobre esas mismas cifras. Solo
  aparece cuando corrieron los agentes.

Que estén separados es el argumento entero del proyecto: las cifras no dependen
del modelo, la prosa sí.

---

## Modo seguro

El interruptor de arriba a la derecha corre el cierre sin LLM. Mismas cifras,
un segundo, sin depender de la red ni de la cuota de Groq. Es lo que hay que
usar si el wifi de la sala está mal.

Aunque esté apagado, el front se protege solo:

- Si el camino con agentes falla, repite sin LLM y avisa.
- Si eso también falla, pide `/kpis` y pinta el arco completo en estático.
- Si ya hay un cierre corriendo, lo dice en vez de soltar un error crudo.
- En la consulta, si el LLM tarda más de quince segundos, responde con la cifra
  determinista y lo indica.

La pantalla no se queda en blanco.

---

## La consulta

El modelo elige la herramienta y redacta, pero no calcula. Cuando se inventa un
número, el backend descarta la redacción y devuelve la cifra determinista; aquí
se muestra la etiqueta correspondiente en vez de disimularlo.

La última pregunta sugerida es justamente la trampa: pedirle que proyecte la
cartera con 10% de mora. No existe herramienta que calcule eso, así que no sale
ninguna cifra inventada.

---

## Cómo está armado

```
src/
  lib/       sse.ts (parser del stream)  api.ts  types.ts  format.ts
  state/     runReducer.ts  useArco.ts  useCountUp.ts
  components/  Masthead  KpiBand  HeroCartera  AgentTrack
               AgingBars  Findings  AuditLog  Chat
```

Vite, React, TypeScript y Tailwind. Sin librería de gráficos: las barras de
antigüedad son SVG a mano, porque cualquier librería traería su propio aspecto
reconocible y pesaría más que el problema que resuelve. Las fuentes van
empaquetadas, así que tampoco dependen de internet.

Tres detalles del backend que condicionaron el código:

**Los eventos se serializan permitiendo `NaN`.** Un `NaN` viaja como token
desnudo y `JSON.parse` revienta. Cada frame se parsea aparte y se sanea antes,
para que un evento malo no tumbe la corrida entera.

**`paso_inicio` casi no llega en modo agentes.** El backend solo lo emite en el
camino determinista. Por eso el panel de agentes se arma desde `GET /plan` y se
marca con `tool_inicio` y `tool_fin`, que sí llegan siempre.

**La consulta comparte el bus de eventos con el cierre.** Preguntar mientras
corre un cierre inyecta eventos en el stream, así que se descarta todo lo que
venga con origen `AGENTE_CHAT`.

---

## Compilar para producción

```powershell
npm run build      # deja todo en dist/
npm run preview
```

`dist/` es estático y se puede servir desde donde sea, siempre que `/api`
apunte al backend.
