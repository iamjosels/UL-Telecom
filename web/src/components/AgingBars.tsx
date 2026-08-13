import { monto, num } from "../lib/format";
import type { Kpis, Tramo } from "../lib/types";

/**
 * Aging de la cartera en cuatro tramos.
 *
 * Barras a mano, sin librería de charts: cualquiera traería su propio look
 * reconocible y pesaría más que el problema que resuelve. La provisión se pinta
 * dentro de la barra, porque el tramo y su provisión son la misma plata vista
 * de dos maneras.
 */

const TRAMOS: Tramo[] = ["1-30", "31-60", "61-90", "90+"];

/** Matriz de provisión del backend (PCD_TASAS en data_loader.py). */
const TASA_PCD: Record<Tramo, number> = {
  "1-30": 0,
  "31-60": 0.25,
  "61-90": 0.5,
  "90+": 1,
};

export function AgingBars({ kpis }: { kpis?: Kpis }) {
  if (!kpis) return null;

  const maximo = Math.max(...TRAMOS.map((t) => kpis.aging[t]?.saldo ?? 0), 1);

  return (
    <section className="filete-t px-6 py-5">
      <div className="flex items-baseline gap-3">
        <h2 className="rotulo">Antigüedad de la deuda</h2>
        <span className="text-[11px] text-[var(--color-tinta-3)]">
          la zona sólida es lo que se provisiona
        </span>
      </div>

      <div className="mt-4 space-y-2.5">
        {TRAMOS.map((t) => {
          const fila = kpis.aging[t];
          const saldo = fila?.saldo ?? 0;
          const facturas = fila?.facturas ?? 0;
          const ancho = (saldo / maximo) * 100;
          const tasa = TASA_PCD[t];

          return (
            <div key={t} className="flex items-center gap-3">
              <span className="w-[46px] shrink-0 font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-tinta-2)]">
                {t}
              </span>

              <div className="relative h-[18px] flex-1 bg-[var(--color-superficie-2)]">
                <div
                  className="absolute inset-y-0 left-0 transition-[width] duration-700"
                  style={{
                    width: `${ancho}%`,
                    background: "rgb(232 161 60 / .22)",
                  }}
                />
                {tasa > 0 && (
                  <div
                    className="absolute inset-y-0 left-0 transition-[width] duration-700"
                    style={{
                      width: `${ancho * tasa}%`,
                      background: "var(--color-cobre)",
                      opacity: 0.7,
                    }}
                  />
                )}
              </div>

              <span className="cifra w-[92px] shrink-0 text-right font-[family-name:var(--font-mono)] text-[11.5px] text-[var(--color-tinta)]">
                {monto(saldo)}
              </span>
              <span className="w-[52px] shrink-0 text-right font-[family-name:var(--font-mono)] text-[10.5px] text-[var(--color-tinta-3)]">
                {num(facturas)} f.
              </span>
              <span className="hidden w-[34px] shrink-0 text-right font-[family-name:var(--font-mono)] text-[10.5px] text-[var(--color-tinta-3)] sm:block">
                {tasa * 100}%
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
