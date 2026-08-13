/**
 * Estado de una corrida de cierre, derivado de los eventos SSE.
 *
 * Dos decisiones que vienen de cómo emite el backend:
 *
 *  1. Los pasos se arman desde GET /plan, no desde los eventos `paso_inicio`.
 *     Ese evento solo lo emite el pipeline determinista (o los pasos de relleno
 *     del crew), así que en una corrida limpia con agentes pueden llegar cero.
 *     Los que sí llegan siempre son `tool_inicio` y `tool_fin`, y con el plan
 *     en mano se sabe a qué paso pertenece cada herramienta.
 *
 *  2. Se descarta todo evento con origen "AGENTE_CHAT". El chat comparte el bus
 *     de suscriptores con /run: preguntar durante un cierre inyecta sus tool
 *     events en este stream y ensuciaría el panel de agentes.
 */

import type {
  AlertaCompleta,
  ClaveAgente,
  EventoRun,
  Metricas,
  Modo,
  PasoPlan,
} from "../lib/types";

export type EstadoPaso = "pendiente" | "corriendo" | "ok" | "error";

export interface PasoCorrida extends PasoPlan {
  estado: EstadoPaso;
  resumen?: string;
  metricas?: Metricas;
  duracionMs?: number;
  filasDetalle?: number;
  alertas?: number;
}

export interface LineaAudit {
  clave: string;
  ts: string;
  agente: string;
  tool: string;
  etiqueta: string;
  duracionMs?: number;
  ok: boolean;
  enCurso: boolean;
  /** Argumentos ya validados con los que se llamó la herramienta. */
  inputs?: Record<string, unknown>;
  /** Linaje del cálculo, paso a paso. Es la prueba de que la cifra sale de
   *  Python: "facturas 3364 -> saldo>0.01 -> 476". */
  trazas?: string[];
  filasDetalle?: number;
  /** Texto del error cuando la herramienta falló. */
  error?: string;
}

/** Hasta qué punto del arco desbloquearon los eventos. 0=A, 1=B, 2=C. */
export type Etapa = 0 | 1 | 2;

export interface EstadoCorrida {
  fase: "inactivo" | "corriendo" | "terminado" | "fallido";
  modo?: Modo;
  runId?: string;
  pasos: PasoCorrida[];
  audit: LineaAudit[];
  alertas: AlertaCompleta[];
  avisos: string[];
  mensajes: { agente: string; texto: string }[];
  reporte?: string;
  /** Lectura ejecutiva del supervisor. Solo existe si corrió el LLM. */
  narrativa?: string;
  archivoAuditoria?: string;
  toolsOk?: number;
  toolsError?: number;
  error?: string;
  /** Etapa máxima habilitada por los eventos recibidos. */
  etapa: Etapa;
  /** Cartera de la vista C, tomada del propio evento de cartera_vencida. */
  carteraC?: number;
}

export type AccionCorrida =
  | { tipo: "plan"; pasos: PasoPlan[] }
  | { tipo: "arranca" }
  | { tipo: "evento"; evento: EventoRun }
  | { tipo: "falla"; mensaje: string }
  | { tipo: "reinicia" };

export const estadoInicial: EstadoCorrida = {
  fase: "inactivo",
  pasos: [],
  audit: [],
  alertas: [],
  avisos: [],
  mensajes: [],
  etapa: 0,
};

const AGENTE_CORTO: Record<string, string> = {
  AGENTE_FACTURACION: "FACT",
  AGENTE_COBRANZAS: "COBR",
  AGENTE_BI: "BI",
  AGENTE_CHAT: "CHAT",
  SUPERVISOR: "SUPV",
  sistema: "SIST",
};

export const abreviar = (agente: string): string =>
  AGENTE_CORTO[agente] ?? agente.replace("AGENTE_", "").slice(0, 4);

/** Herramientas cuyo fin desbloquea cada etapa del arco. */
const TOOL_ETAPA_B = "resumen_facturacion";
const TOOL_ETAPA_C = "cartera_vencida";

function marcarPaso(
  pasos: PasoCorrida[],
  tool: string,
  cambio: Partial<PasoCorrida>,
): PasoCorrida[] {
  let aplicado = false;
  return pasos.map((p) => {
    if (aplicado || p.tool !== tool) return p;
    aplicado = true;
    return { ...p, ...cambio };
  });
}

export function reducer(estado: EstadoCorrida, accion: AccionCorrida): EstadoCorrida {
  switch (accion.tipo) {
    case "plan":
      return {
        ...estado,
        pasos: accion.pasos.map((p) => ({ ...p, estado: "pendiente" as EstadoPaso })),
      };

    case "arranca":
      return {
        ...estado,
        fase: "corriendo",
        audit: [],
        alertas: [],
        avisos: [],
        mensajes: [],
        error: undefined,
        reporte: undefined,
        narrativa: undefined,
        etapa: 0,
        carteraC: undefined,
        pasos: estado.pasos.map((p) => ({
          ...p,
          estado: "pendiente" as EstadoPaso,
          resumen: undefined,
          metricas: undefined,
          duracionMs: undefined,
          alertas: undefined,
        })),
      };

    case "falla":
      return { ...estado, fase: "fallido", error: accion.mensaje };

    case "reinicia":
      return { ...estadoInicial, pasos: estado.pasos };

    case "evento":
      return aplicarEvento(estado, accion.evento);

    default:
      return estado;
  }
}

function aplicarEvento(estado: EstadoCorrida, ev: EventoRun): EstadoCorrida {
  switch (ev.tipo) {
    case "corrida_inicio":
      return { ...estado, fase: "corriendo", modo: ev.modo, runId: ev.run_id };

    case "tool_inicio": {
      // El chat comparte el bus con /run. Sus eventos no son de esta corrida.
      if (ev.origen === "AGENTE_CHAT") return estado;
      return {
        ...estado,
        pasos: marcarPaso(estado.pasos, ev.tool, { estado: "corriendo" }),
        audit: [
          ...estado.audit,
          {
            clave: `${ev.tool}-${ev.ts}-ini`,
            ts: ev.ts,
            agente: ev.agente,
            tool: ev.tool,
            etiqueta: ev.etiqueta,
            ok: true,
            enCurso: true,
            inputs: ev.inputs,
          },
        ],
      };
    }

    case "tool_fin": {
      if (ev.origen === "AGENTE_CHAT") return estado;

      const pasos = marcarPaso(estado.pasos, ev.tool, {
        estado: ev.ok ? "ok" : "error",
        resumen: ev.resumen,
        metricas: ev.metricas,
        duracionMs: ev.duracion_ms,
        filasDetalle: ev.filas_detalle,
        alertas: ev.alertas?.length ?? 0,
      });

      // La línea "en curso" se sustituye por la definitiva.
      const audit = estado.audit
        .filter((l) => !(l.tool === ev.tool && l.enCurso))
        .concat({
          clave: `${ev.tool}-${ev.ts}-fin`,
          ts: ev.ts,
          agente: ev.agente,
          tool: ev.tool,
          etiqueta: ev.etiqueta,
          duracionMs: ev.duracion_ms,
          ok: ev.ok,
          enCurso: false,
          inputs: ev.inputs,
          trazas: ev.trazas,
          filasDetalle: ev.filas_detalle,
          ...(ev.ok ? {} : { error: ev.resumen }),
        });

      let etapa = estado.etapa;
      let carteraC = estado.carteraC;

      if (ev.ok && ev.tool === TOOL_ETAPA_C) {
        const valor = Number(ev.metricas?.cartera_vencida_pen);
        if (Number.isFinite(valor)) carteraC = valor;
        etapa = 2;
      } else if (ev.ok && etapa < 1) {
        // Facturación destapa la vista B. Se acepta el fin de su primera
        // herramienta o el de todo su bloque, porque en modo crew el orden lo
        // decide el modelo.
        const facturacionLista = pasos
          .filter((p) => p.agente === "AGENTE_FACTURACION")
          .every((p) => p.estado === "ok" || p.estado === "error");
        if (ev.tool === TOOL_ETAPA_B || facturacionLista) etapa = 1;
      }

      return { ...estado, pasos, audit, etapa, carteraC };
    }

    case "tool_error":
      // Este evento trae una forma distinta de tool_fin: sin etiqueta, sin
      // inputs y sin duración. Antes se marcaba el paso y no dejaba rastro en
      // la trazabilidad, así que un error de argumentos era invisible.
      return {
        ...estado,
        pasos: marcarPaso(estado.pasos, ev.tool, { estado: "error", resumen: ev.resumen }),
        audit: [
          ...estado.audit.filter((l) => !(l.tool === ev.tool && l.enCurso)),
          {
            clave: `${ev.tool}-${ev.ts}-err`,
            ts: ev.ts,
            agente: ev.agente,
            tool: ev.tool,
            etiqueta: ev.tool,
            ok: false,
            enCurso: false,
            error: ev.resumen,
          },
        ],
      };

    case "aviso":
      return { ...estado, avisos: [...estado.avisos, ev.mensaje] };

    case "agente_mensaje":
    case "tarea_fin":
      return {
        ...estado,
        mensajes: [...estado.mensajes, { agente: ev.agente, texto: ev.texto }].slice(-6),
      };

    case "corrida_fin":
      return { ...estado, modo: ev.modo, archivoAuditoria: ev.auditoria };

    case "reporte_final":
      return {
        ...estado,
        modo: ev.modo,
        reporte: ev.reporte,
        narrativa: ev.narrativa ?? undefined,
        alertas: ev.alertas ?? [],
        toolsOk: ev.auditoria?.resumen?.tools_ok,
        toolsError: ev.auditoria?.resumen?.tools_error,
        // Si alguna herramienta no llegó a emitir, el arco igual se completa.
        etapa: 2,
      };

    case "error":
      return { ...estado, fase: "fallido", error: ev.mensaje };

    case "fin":
      // Único evento terminal. corrida_fin llega antes de reporte_final, y
      // error tampoco cierra el stream.
      return { ...estado, fase: estado.fase === "fallido" ? "fallido" : "terminado" };

    default:
      return estado;
  }
}

// --------------------------------------------------------------------------
// Derivados
// --------------------------------------------------------------------------

export interface ResumenAgente {
  clave: ClaveAgente;
  nombre: string;
  pasos: PasoCorrida[];
  activo: boolean;
  hechos: number;
  total: number;
  toolActual?: string;
  etiquetaActual?: string;
}

export const NOMBRE_AGENTE: Record<ClaveAgente, string> = {
  AGENTE_FACTURACION: "Facturación",
  AGENTE_COBRANZAS: "Cobranzas y Recaudo",
  AGENTE_BI: "Inteligencia de Negocio",
};

const ORDEN: ClaveAgente[] = ["AGENTE_FACTURACION", "AGENTE_COBRANZAS", "AGENTE_BI"];

export function agentesDe(estado: EstadoCorrida): ResumenAgente[] {
  return ORDEN.map((clave) => {
    const pasos = estado.pasos.filter((p) => p.agente === clave);
    const corriendo = pasos.find((p) => p.estado === "corriendo");
    return {
      clave,
      nombre: NOMBRE_AGENTE[clave],
      pasos,
      activo: Boolean(corriendo),
      hechos: pasos.filter((p) => p.estado === "ok" || p.estado === "error").length,
      total: pasos.length,
      toolActual: corriendo?.tool,
      etiquetaActual: corriendo?.titulo,
    };
  });
}
