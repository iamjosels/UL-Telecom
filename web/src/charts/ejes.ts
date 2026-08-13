/**
 * Escalas y utilidades de eje para los gráficos en SVG.
 *
 * Sin librería: con las formas que hacen falta aquí, cualquiera pesaría más
 * que el problema y traería su propio aspecto reconocible.
 */

/** Especificaciones fijas del método, iguales en todos los gráficos. */
export const MARCA = {
  /** Grosor máximo de barra. Nunca llenar el hueco: el sobrante es aire. */
  barraMax: 24,
  /** Extremo redondeado del dato; el lado de la línea base va cuadrado. */
  radio: 4,
  /** Grosor de línea. */
  linea: 2,
  /** Radio del marcador. El diámetro mínimo es 8. */
  marcador: 4.5,
  /** Hueco del color de la superficie entre marcas que se tocan. */
  hueco: 2,
  /** Anillo de superficie alrededor de los marcadores. */
  anillo: 2,
} as const;

/** Escala lineal de un dominio de datos a píxeles. */
export function escala(min: number, max: number, desde: number, hasta: number) {
  const rango = max - min || 1;
  return (v: number) => desde + ((v - min) / rango) * (hasta - desde);
}

/**
 * Marcas de eje en números redondos.
 *
 * Se buscan pasos de 1, 2, 2.5 o 5 por potencia de diez, que son los que la
 * gente lee sin traducir.
 */
export function ticks(max: number, cuantos = 4): number[] {
  if (!Number.isFinite(max) || max <= 0) return [0];
  const bruto = max / cuantos;
  const magnitud = 10 ** Math.floor(Math.log10(bruto));
  const norm = bruto / magnitud;
  const paso = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * magnitud;

  const salida: number[] = [];
  for (let v = 0; v <= max * 1.0001; v += paso) salida.push(Number(v.toFixed(6)));
  return salida;
}

/** Techo redondo por encima del máximo, para que la barra más alta respire. */
export function techo(max: number, cuantos = 4): number {
  const t = ticks(max, cuantos);
  const ultimo = t[t.length - 1] ?? max;
  if (ultimo >= max) return ultimo;
  const paso = (t[1] ?? max) - (t[0] ?? 0);
  return ultimo + paso;
}

/** 137200.41 -> "137.2K" · 1250000 -> "1.25M". Para marcas de eje. */
export function corto(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}K`;
  return v.toFixed(0);
}

/**
 * Rectángulo con el extremo del dato redondeado y la base cuadrada.
 *
 * Un `rx` normal redondearía también el arranque, que debe quedar pegado a la
 * línea base. Se dibuja el contorno a mano.
 */
export function barraVertical(x: number, y: number, w: number, h: number, r = MARCA.radio): string {
  const radio = Math.min(r, w / 2, Math.abs(h));
  if (h <= 0) return "";
  return [
    `M ${x} ${y + h}`,
    `V ${y + radio}`,
    `Q ${x} ${y} ${x + radio} ${y}`,
    `H ${x + w - radio}`,
    `Q ${x + w} ${y} ${x + w} ${y + radio}`,
    `V ${y + h}`,
    "Z",
  ].join(" ");
}

/** Igual, pero creciendo hacia la derecha desde una base vertical. */
export function barraHorizontal(x: number, y: number, w: number, h: number, r = MARCA.radio): string {
  const radio = Math.min(r, h / 2, Math.abs(w));
  if (w <= 0) return "";
  return [
    `M ${x} ${y}`,
    `H ${x + w - radio}`,
    `Q ${x + w} ${y} ${x + w} ${y + radio}`,
    `V ${y + h - radio}`,
    `Q ${x + w} ${y + h} ${x + w - radio} ${y + h}`,
    `H ${x}`,
    "Z",
  ].join(" ");
}

/** Barra que cae desde arriba: el extremo redondeado va abajo. */
export function barraColgante(x: number, y: number, w: number, h: number, r = MARCA.radio): string {
  const radio = Math.min(r, w / 2, Math.abs(h));
  if (h <= 0) return "";
  return [
    `M ${x} ${y}`,
    `V ${y + h - radio}`,
    `Q ${x} ${y + h} ${x + radio} ${y + h}`,
    `H ${x + w - radio}`,
    `Q ${x + w} ${y + h} ${x + w} ${y + h - radio}`,
    `V ${y}`,
    "Z",
  ].join(" ");
}

/** Polilínea suave para series de pocos puntos. */
export function ruta(puntos: Array<{ x: number; y: number }>): string {
  if (!puntos.length) return "";
  return puntos
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`)
    .join(" ");
}
