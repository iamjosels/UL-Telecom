# SON-IA — Contexto del desafío (Reto 3 · AI Telecom Challenge)

> Documento de contexto de negocio para el equipo y para Claude Code. Es el **"por qué"** detrás del código.
> **No es una lista de requisitos a implementar** — el alcance técnico está en el prompt de build.
> Aquí va el marco del negocio, los KPI que la solución debe mover y los criterios con los que nos evalúan.

## El reto en una línea
Un ecosistema de **agentes de IA con skills especializados, coordinados por un agente supervisor (orquestador)**,
que opera el ciclo del ingreso B2B de Integratel de punta a punta: **Facturación, Cobranzas y Recaudo**.
Foco/MVP recomendado por la organización: **orquestador + 3 agentes core** (Facturación, Cobranzas, BI).
Se aceptan prototipos conceptuales sólidos, pero gana el que lo hace **tangible y ejecutable**.

## El ciclo del ingreso y los 3 momentos de facturación
Flujo objetivo de facturación (sirve de guion, sobre todo para el agente de Facturación):
1. **Asesoría previa a la emisión** — la IA extrae y valida la información que conforma el PxQ (precio × cantidad),
   prepara los formatos para validación del cliente y **alerta si hay quiebres**. Todo con criterios de auditoría.
2. **Ejecución automatizada** — con la aprobación del cliente, el agente emite el documento sin intervención humana
   (elimina errores de digitación y de llenado manual).
3. **Rebaja automática post-pago** — confirmado el pago, se actualiza el estado del documento; queda trazado
   quién emitió, cuándo, cuánto y cuándo se pagó.

Cobranzas y Recaudo: centralizar y clasificar las comunicaciones con clientes (sobre todo las que confirman pagos),
conciliar contra lo facturado, armar ficheros de rebajas y asegurar las partidas bancarias.

## KPI que la solución debe mover (las tools deben mapear a esto)
- **Facturación:** aseguramiento de ingresos (facturación oportuna y de calidad), tiempos de disponibilidad de la
  factura, reducción de notas de crédito por error operativo.
- **Cobranzas:** ratio cobrado/facturado a 30 días, periodo medio de cobro, provisión de cobranza dudosa (PCD).
- **Recaudo:** tiempo de identificación de depósitos, reducción de cuentas por cobrar, reducción de tiempos de
  conciliación bancaria.

## Escenarios demostrables con la data (cifras reales del dataset)
- **Fuga de ingresos:** 423 de 1,572 cuentas con servicio activo no tienen factura (27%).
- **Riesgo fiscal:** 21 facturas emitidas a clientes con RUC NO HABIDO (SUNAT).
- **Recaudo:** 74 pagos (~S/106K) sin identificar — referencian facturas fuera del maestro ("info dispersa").
- **Cartera vencida:** 504 facturas con saldo (S/18,298) con aging; S/4,353 a +90 días.
- **Conciliación:** 97.9% de pagos cruzan automáticamente con su factura.
- Facturado S/447,965 · Pagado S/392,837 · 196 notas de crédito.

## Principio rector: 0% de alucinaciones
Toda cifra la calculan **funciones deterministas** sobre la data; el LLM solo orquesta, decide y explica.
Cada acción queda en un **log de auditoría**. Es comprobable por logs — y es un diferencial clave frente a
equipos que dejan al modelo inventar números.

## Usuarios
Facturación, Cobranzas, TI, Planificación Comercial, Control de Gestión, Contabilidad, Finanzas,
Inteligencia de Negocio, Ventas y Atención al Cliente.

## Cómo nos evalúan (para mantener el foco en lo que gana)
**Innovación de la solución · Viabilidad técnica · Impacto esperado en el negocio · Claridad de la propuesta · Calidad del pitch.**
(En la preselección: comprensión del desafío, innovación, viabilidad, potencial de impacto, pitch.)