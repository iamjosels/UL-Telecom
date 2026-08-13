import { monto, num, pct } from "../lib/format";
import type { Kpis } from "../lib/types";

/**
 * Franja superior. Los valores se separan por filetes verticales, no por
 * tarjetas: la idea es que se lea como la cabecera de un terminal de
 * operaciones, con las cifras alineadas y sin cajas flotando.
 */

interface Props {
  kpis?: Kpis;
  cargando: boolean;
}

export function KpiBand({ kpis, cargando }: Props) {
  const celdas = [
    { rotulo: "Facturado", valor: kpis && monto(kpis.facturado_pen), nota: "S/" },
    { rotulo: "Cobrado", valor: kpis && monto(kpis.cobrado_pen), nota: "S/" },
    {
      rotulo: "Cobrado / facturado",
      valor: kpis && pct(kpis.ratio_cobrado_facturado, 2),
      barra: kpis?.ratio_cobrado_facturado,
    },
    { rotulo: "Provisión dudosa", valor: kpis && monto(kpis.provision_pcd_pen), nota: "S/" },
    {
      // Cifra titular del reto que hasta ahora no aparecía en ninguna parte.
      // Se muestra el antes y el después porque el salto ES el hallazgo.
      rotulo: "Conciliación de pagos",
      valor: kpis && pct(kpis.tasa_conciliacion_mejorada, 2),
      nota: kpis && `desde ${pct(kpis.tasa_conciliacion_actual, 2)}`,
      barra: kpis?.tasa_conciliacion_mejorada,
    },
    {
      rotulo: "Fuga por no facturar",
      valor: kpis && monto(kpis.fuga_estimada_mes_pen),
      nota: "S/ al mes",
    },
    {
      rotulo: "Cuentas sin facturar",
      valor: kpis && num(kpis.cuentas_sin_factura),
      nota: kpis && `de ${num(kpis.cuentas_activas)} activas`,
    },
  ];

  return (
    <div className="filete-b grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7">
      {celdas.map((c, i) => (
        <div
          key={c.rotulo}
          className={`px-6 py-3.5 ${i > 0 ? "xl:filete-l" : ""} ${i % 2 === 1 ? "filete-l xl:border-l" : ""}`}
        >
          <div className="rotulo mb-1.5 whitespace-nowrap">{c.rotulo}</div>
          {cargando || !c.valor ? (
            <div className="h-[26px] w-24 animate-pulse bg-[var(--color-superficie-2)]" />
          ) : (
            <div className="flex items-baseline gap-1.5">
              <span className="cifra font-[family-name:var(--font-display)] text-[22px] font-medium leading-none text-[var(--color-tinta)]">
                {c.valor}
              </span>
              {c.nota && (
                <span className="text-[11px] text-[var(--color-tinta-3)]">{c.nota}</span>
              )}
            </div>
          )}
          {c.barra !== undefined && !cargando && (
            <div className="mt-2 h-[2px] w-full bg-[var(--color-superficie-3)]">
              <div
                className="h-full bg-[var(--color-musgo)] transition-[width] duration-700"
                style={{ width: `${Math.min(100, c.barra)}%` }}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
