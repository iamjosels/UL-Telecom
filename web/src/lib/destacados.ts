/**
 * Qué cifra enseñar de cada herramienta.
 *
 * El backend devuelve por herramienta entre 8 y 17 métricas, más un resumen en
 * prosa que se escribió para que lo leyera el LLM. La interfaz venía pintando
 * el párrafo y tirando las métricas: once bloques de texto que en una
 * presentación no lee nadie.
 *
 * Aquí se elige, para cada herramienta, la cifra que cuenta su historia. El
 * párrafo sigue disponible al desplegar el paso, pero deja de ser lo primero.
 */

import { monto, num, pct } from "./format";
import type { Metricas } from "./types";

export type Formato = "pen" | "num" | "pct" | "dias";

export interface Destacado {
  clave: string;
  rotulo: string;
  formato: Formato;
  /** Sufijo corto tras la cifra, p. ej. "cuentas" o "facturas". */
  unidad?: string;
}

/**
 * El titular de cada herramienta.
 *
 * Cuando la respuesta es el resumen crudo, el titular ya viene dentro del texto
 * y se separa al pintarlo. Cuando redacta el LLM, el titular desaparece: escribe
 * una frase normal. Esto lo repone, con las mismas palabras que usa el backend
 * (verificadas ejecutando el registro, no inventadas aquí).
 */
export const TITULOS: Record<string, string> = {
  resumen_facturacion: "Escalera de facturación",
  detectar_servicios_no_facturados: "Fuga de ingresos",
  validar_clientes_sunat: "Riesgo tributario en la emisión",
  conciliar_pagos: "Conciliación pago ↔ factura",
  pagos_no_identificados: "Partidas bancarias sin identificar",
  cartera_vencida: "Cartera vencida",
  ratio_cobrado_facturado: "Ratio cobrado/facturado",
  detectar_anomalias: "Anomalías detectadas",
  provision_cobranza_dudosa: "Provisión de cobranza dudosa",
  priorizar_recupero: "Mesa de aceleración de recupero",
  proyeccion_caja: "Adelanto operativo de caja",
};

export const DESTACADOS: Record<string, Destacado[]> = {
  resumen_facturacion: [
    { clave: "facturado_isis_pen", rotulo: "Fuera de AMDOCS", formato: "pen" },
    { clave: "facturas", rotulo: "Documentos emitidos", formato: "num" },
  ],
  detectar_servicios_no_facturados: [
    {
      clave: "cuentas_sin_factura",
      rotulo: "Cuentas activas sin facturar",
      formato: "num",
      unidad: "ctas",
    },
    { clave: "fuga_estimada_mes_pen", rotulo: "Fuga por ciclo", formato: "pen" },
  ],
  validar_clientes_sunat: [
    {
      clave: "facturas_no_habido",
      rotulo: "Facturas a RUC no habido",
      formato: "num",
      unidad: "fact",
    },
    { clave: "monto_no_habido_pen", rotulo: "Riesgo fiscal", formato: "pen" },
  ],
  conciliar_pagos: [
    { clave: "tasa_conciliacion_mejorada", rotulo: "Pagos aplicados", formato: "pct" },
    { clave: "reclasificado_pen", rotulo: "Reclasificado", formato: "pen" },
  ],
  pagos_no_identificados: [
    { clave: "monto_recuperable_pen", rotulo: "Ya cobrado, sin aplicar", formato: "pen" },
    { clave: "residuales", rotulo: "Sin identificar de verdad", formato: "num", unidad: "pagos" },
  ],
  cartera_vencida: [
    { clave: "cartera_vencida_pen", rotulo: "Cartera vencida real", formato: "pen" },
    { clave: "tramo_90_mas_pen", rotulo: "A más de 90 días", formato: "pen" },
  ],
  ratio_cobrado_facturado: [
    { clave: "ratio_global", rotulo: "Cobrado sobre facturado", formato: "pct" },
    { clave: "periodo_medio_cobro_dias", rotulo: "Periodo medio de cobro", formato: "dias" },
  ],
  detectar_anomalias: [
    { clave: "tipos_anomalia", rotulo: "Tipos de anomalía", formato: "num" },
    { clave: "registros_afectados", rotulo: "Registros afectados", formato: "num" },
  ],
  provision_cobranza_dudosa: [
    { clave: "provision_pen", rotulo: "Provisión a constituir", formato: "pen" },
    { clave: "cobertura_pct", rotulo: "Cobertura", formato: "pct" },
  ],
  priorizar_recupero: [
    { clave: "saldo_priorizado_pen", rotulo: "Concentrado en el top 15", formato: "pen" },
    { clave: "cobertura_pct", rotulo: "De la cartera", formato: "pct" },
  ],
  proyeccion_caja: [
    { clave: "proyeccion_30d_pen", rotulo: "Cobranza esperada a 30 d", formato: "pen" },
    { clave: "en_riesgo_mas_90d_pen", rotulo: "En riesgo tras 90 d", formato: "pen" },
  ],
};

export function formatear(valor: number, formato: Formato): string {
  switch (formato) {
    case "pen":
      return `S/${monto(valor)}`;
    case "pct":
      return pct(valor, 2);
    case "dias":
      return `${valor > 0 ? "+" : ""}${valor.toFixed(1)} d`;
    default:
      return num(valor);
  }
}

export interface CifraDestacada {
  rotulo: string;
  texto: string;
  unidad?: string;
}

/** Extrae de las métricas de una herramienta sus cifras de cabecera. */
export function destacadosDe(tool: string, metricas?: Metricas): CifraDestacada[] {
  const spec = DESTACADOS[tool];
  if (!spec || !metricas) return [];

  return spec.flatMap((d) => {
    const bruto = metricas[d.clave];
    if (bruto === undefined || bruto === null) return [];
    const n = Number(bruto);
    if (!Number.isFinite(n)) return [];
    return [
      {
        rotulo: d.rotulo,
        texto: formatear(n, d.formato),
        ...(d.unidad ? { unidad: d.unidad } : {}),
      },
    ];
  });
}
