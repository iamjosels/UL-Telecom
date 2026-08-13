/**
 * Formato de cifras. Mismo criterio que src/formato.py en el backend, para que
 * una cifra se lea igual en la consola del demo y en el informe.
 */

const MILES = new Intl.NumberFormat("es-PE", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const ENTERO = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 0 });

/** 47819.06 -> "S/47,819.06" */
export function pen(valor: number | string | null | undefined): string {
  const n = Number(valor);
  if (!Number.isFinite(n)) return "S/0.00";
  return `S/${MILES.format(n)}`;
}

/** Sin el prefijo, para cuando la columna ya dice que son soles. */
export function monto(valor: number | string | null | undefined): string {
  const n = Number(valor);
  if (!Number.isFinite(n)) return "0.00";
  return MILES.format(n);
}

/** 137200.41 -> "S/137.2K"  ·  1250000 -> "S/1.25M" */
export function penCorto(valor: number | string | null | undefined): string {
  const n = Number(valor);
  if (!Number.isFinite(n)) return "S/0";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `S/${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `S/${(n / 1_000).toFixed(1)}K`;
  return `S/${n.toFixed(0)}`;
}

/** El backend ya manda porcentajes (87.69), no fracciones. */
export function pct(valor: number | string | null | undefined, decimales = 1): string {
  const n = Number(valor);
  if (!Number.isFinite(n)) return "0%";
  return `${n.toFixed(decimales)}%`;
}

export function num(valor: number | string | null | undefined): string {
  const n = Number(valor);
  if (!Number.isFinite(n)) return "0";
  return ENTERO.format(n);
}

/**
 * "2026-08-12T07:06:11" -> "07:06:11".
 * Las marcas del backend son locales y sin zona: no hay que añadirles Z.
 */
export function hora(iso: string | undefined): string {
  if (!iso) return "--:--:--";
  const t = iso.split("T")[1];
  return t ? t.slice(0, 8) : "--:--:--";
}

/** "2026-08-12" -> "12.08.26" */
export function fechaCorta(iso: string | undefined): string {
  if (!iso) return "";
  const [a, m, d] = iso.slice(0, 10).split("-");
  if (!a || !m || !d) return iso;
  return `${d}.${m}.${a.slice(2)}`;
}

export function ms(valor: number | undefined): string {
  const n = Number(valor);
  if (!Number.isFinite(n)) return "";
  return n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${Math.round(n)}ms`;
}

/** Lee una métrica del backend con seguridad: puede venir string o faltar. */
export function metrica(
  metricas: Record<string, number | string> | undefined,
  clave: string,
): number | undefined {
  if (!metricas) return undefined;
  const bruto = metricas[clave];
  if (bruto === undefined || bruto === null) return undefined;
  const n = Number(bruto);
  return Number.isFinite(n) ? n : undefined;
}
