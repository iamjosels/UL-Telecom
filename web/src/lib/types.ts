/**
 * Tipos del backend de SON-IA.
 *
 * Escritos a mano a propósito: todos los endpoints están anotados `-> dict`,
 * así que /openapi.json no trae schemas de respuesta y cualquier generador
 * automático produciría `{}`. Esto se derivó leyendo api/main.py, reporte.py,
 * tools/registro.py, pipeline.py, crew.py y router.py.
 */

export type ClaveAgente = "AGENTE_FACTURACION" | "AGENTE_COBRANZAS" | "AGENTE_BI";

export type Severidad = "critica" | "alta" | "media" | "baja" | "info";

export type Modo = "deterministico" | "crew" | "hibrido";

export type Tramo = "1-30" | "31-60" | "61-90" | "90+";

/** Las métricas no tienen forma fija: varias tools generan claves dinámicas
 *  (facturado_isis_pen, ratio_30d, confianza_exacto_monto, un nombre por tipo
 *  de anomalía...). Se lee por clave conocida y siempre pasando por Number(). */
export type Metricas = Record<string, number | string>;

// --------------------------------------------------------------------------
// GET /kpis
// --------------------------------------------------------------------------

export interface Reconciliacion {
  vista_a_pen: number;
  vista_b_pen: number;
  vista_c_pen: number;
  facturas_ocultas: number;
  monto_oculto_pen: number;
  pagos_recuperados: number;
  monto_recuperado_pen: number;
}

export interface Kpis {
  ts: string;
  fecha_corte: string;
  facturado_pen: number;
  cobrado_pen: number;
  /** Ya viene en porcentaje (87.69), no como fracción. */
  ratio_cobrado_facturado: number;
  cartera_vencida_pen: number;
  por_vencer_pen: number;
  provision_pcd_pen: number;
  aging: Record<Tramo, { facturas: number; saldo: number }>;
  cuentas_activas: number;
  cuentas_sin_factura: number;
  /** Porcentaje (26.86). */
  pct_fuga: number;
  fuga_estimada_mes_pen: number;
  tasa_conciliacion_actual: number;
  tasa_conciliacion_mejorada: number;
  pagos_sin_identificar: number;
  monto_sin_identificar_pen: number;
  reconciliacion: Reconciliacion;
}

// --------------------------------------------------------------------------
// GET /plan
// --------------------------------------------------------------------------

export interface PasoPlan {
  id: string;
  agente: ClaveAgente;
  tool: string;
  titulo: string;
  momento: string;
  kpi: string;
  params: Record<string, unknown>;
}

export interface PlanCierre {
  objetivo: string;
  pasos: PasoPlan[];
}

// --------------------------------------------------------------------------
// Alertas: OJO, hay dos proyecciones distintas según de dónde vengan
// --------------------------------------------------------------------------

/** La que viaja en tool_fin y en /chat. Solo 3 campos. */
export interface AlertaBreve {
  severidad: Severidad;
  titulo: string;
  impacto_pen: number;
}

/** La de reporte_final. 7 campos, ya ordenada por severidad e impacto y
 *  deduplicada por clave. Es la que alimenta los hallazgos. */
export interface AlertaCompleta extends AlertaBreve {
  detalle: string;
  kpi: string;
  accion: string;
  responsable: string;
}

// --------------------------------------------------------------------------
// SSE POST /run
// --------------------------------------------------------------------------

export interface PeticionRun {
  objetivo?: string;
  fecha_corte?: string;
  deterministico?: boolean;
}

interface Base {
  run_id: string;
  ts: string;
}

export interface EvCorridaInicio extends Base {
  tipo: "corrida_inicio";
  objetivo: string;
  modo: Modo;
  fecha_corte: string;
  pasos: number;
}

/** Solo lo emite el pipeline determinista, o los pasos de relleno del crew.
 *  En una corrida limpia con agentes pueden llegar CERO. El panel de agentes
 *  no puede depender de esto. */
export interface EvPasoInicio extends Base {
  tipo: "paso_inicio";
  id: string;
  agente: ClaveAgente;
  titulo: string;
  momento: string;
  kpi: string;
}

export interface EvToolInicio extends Base {
  tipo: "tool_inicio";
  agente: ClaveAgente;
  /** Quién la invocó. "AGENTE_CHAT" cuando viene de una pregunta del chat:
   *  hay que filtrarlo o el panel de agentes se ensucia. */
  origen: string;
  tool: string;
  etiqueta: string;
  inputs: Record<string, unknown>;
}

export interface EvToolFin extends Base {
  tipo: "tool_fin";
  agente: ClaveAgente;
  origen: string;
  tool: string;
  etiqueta: string;
  inputs: Record<string, unknown>;
  resumen: string;
  metricas: Metricas;
  alertas: AlertaBreve[];
  trazas: string[];
  ok: boolean;
  duracion_ms: number;
  filas_detalle: number;
}

/** Forma distinta de tool_fin: sin etiqueta, inputs, metricas, ok ni origen. */
export interface EvToolError extends Base {
  tipo: "tool_error";
  agente: string;
  tool: string;
  resumen: string;
}

export interface EvAgenteMensaje extends Base {
  tipo: "agente_mensaje" | "tarea_fin";
  agente: string;
  texto: string;
}

/** La clave es `mensaje`, no `texto`, y no trae `agente`. */
export interface EvAviso extends Base {
  tipo: "aviso";
  mensaje: string;
}

export interface EvCorridaFin extends Base {
  tipo: "corrida_fin";
  modo: Modo;
  auditoria: string;
}

export interface EvReporteFinal extends Base {
  tipo: "reporte_final";
  reporte: string;
  modo: Modo;
  /** Lectura ejecutiva del supervisor, en markdown y sin envolver. Es null en
   *  el camino determinista, donde no hay LLM que redacte. */
  narrativa: string | null;
  /** Plano, con claves punteadas: "cartera_vencida.cartera_vencida_pen". */
  kpis: Metricas;
  alertas: AlertaCompleta[];
  auditoria: {
    corrida_id: string;
    objetivo: string;
    modo: string;
    inicio: string;
    fin: string;
    resumen: {
      tools_ejecutadas: number;
      tools_ok: number;
      tools_error: number;
      duracion_total_ms: number;
      agentes: string[];
    };
    archivo: string;
  };
}

export interface EvError extends Base {
  tipo: "error";
  mensaje: string;
}

/** Terminal. No trae `tipo`: hay que despachar por el nombre del evento SSE. */
export interface EvFin {
  tipo: "fin";
  run_id: string;
}

export type EventoRun =
  | EvCorridaInicio
  | EvPasoInicio
  | EvToolInicio
  | EvToolFin
  | EvToolError
  | EvAgenteMensaje
  | EvAviso
  | EvCorridaFin
  | EvReporteFinal
  | EvError
  | EvFin;

// --------------------------------------------------------------------------
// POST /chat
// --------------------------------------------------------------------------

export interface PeticionChat {
  mensaje: string;
  usar_llm?: boolean;
}

export interface RespuestaChat {
  respuesta: string;
  tool: string;
  args: Record<string, unknown>;
  via: "keywords" | "llm";
  confianza: number;
  /** true solo si el LLM redactó Y pasó el guardarraíl numérico. */
  redactado_por_llm: boolean;
  /** true cuando el guardarraíl rechazó la redacción por citar una cifra que
   *  ninguna herramienta produjo. Se muestra en la interfaz: es la prueba. */
  redaccion_descartada: boolean;
  /** Fragmento literal de la pregunta que pedía un supuesto que no se aplica. */
  supuesto_ignorado?: string | null;

  metricas: Metricas;
  trazas: string[];
  alertas: AlertaBreve[];
  filas_detalle: number;
  ok: boolean;
  ts: string;
}

// --------------------------------------------------------------------------
// GET /resultados
// --------------------------------------------------------------------------

/** Fila de detalle. Las claves dependen de `columnas` de cada herramienta. */
export type FilaDetalle = Record<string, string | number | boolean | null>;

export interface ResultadoDetalle {
  tool: string;
  agente: ClaveAgente;
  ok: boolean;
  params: Record<string, unknown>;
  metricas: Metricas;
  columnas: string[];
  /** Truncado a 200 filas por el backend; `filas_totales` trae el real. */
  data: FilaDetalle[];
  filas_totales: number;
  truncada: boolean;
  trazas: string[];
}

/** Vacío mientras no se haya corrido nada: el registro se limpia por corrida. */
export type DetalleTools = Partial<Record<string, ResultadoDetalle>>;

export interface RespuestaResultados {
  ts: string;
  corrida_id: string;
  tools: DetalleTools;
}

// --------------------------------------------------------------------------
// GET /
// --------------------------------------------------------------------------

export interface Salud {
  servicio: string;
  estado: string;
  llm_configurado: boolean;
  endpoints: string[];
}

// --------------------------------------------------------------------------
// Datasets
// --------------------------------------------------------------------------

/** Las 6 tablas del ciclo. Es la clave con la que viajan al backend. */
export type TablaId =
  | "clientes"
  | "planta_fija"
  | "planta_movil"
  | "pagos"
  | "facturas"
  | "notas_credito";

export interface EstadoDatos {
  ts: string;
  origen: string;
  es_demo: boolean;
  fecha_corte: string;
  /** "fijado en corte.txt" o "derivado de las fechas del dataset". */
  corte_procedencia: string;
  filas: Record<TablaId, number>;
  archivos: Record<TablaId, string>;
}
