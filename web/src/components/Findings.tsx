import { monto, num } from "../lib/format";
import type { AlertaCompleta, Kpis, Severidad } from "../lib/types";

/**
 * Hallazgos.
 *
 * Las alertas vienen de reporte_final, que ya las entrega ordenadas por
 * severidad e impacto y deduplicadas por clave. No se suman entre sí: varias
 * describen el mismo dinero desde ángulos distintos, y un total inflado es
 * justo lo que un evaluador rompe con una pregunta.
 *
 * Encima va el cuadro de partidas que sí son independientes.
 */

interface Props {
  alertas: AlertaCompleta[];
  kpis?: Kpis;
}

const COLOR: Record<Severidad, string> = {
  critica: "var(--color-terracota)",
  alta: "var(--color-cobre)",
  media: "var(--color-arena)",
  baja: "var(--color-tinta-3)",
  info: "var(--color-tinta-3)",
};

export function Findings({ alertas, kpis }: Props) {
  return (
    <section className="filete-t px-6 py-5">
      <div className="flex items-baseline gap-3">
        <h2 className="rotulo">Hallazgos</h2>
        <span className="text-[11px] text-[var(--color-tinta-3)]">
          partidas independientes, no se suman entre sí
        </span>
      </div>

      {kpis && <Partidas kpis={kpis} />}

      {alertas.length > 0 && (
        <ul className="mt-5 space-y-px">
          {alertas.slice(0, 8).map((a, i) => (
            <li
              key={`${a.titulo}-${i}`}
              className="anim-entra flex gap-3 bg-[var(--color-superficie)]/40 px-3 py-2.5"
              style={{ animationDelay: `${Math.min(i * 40, 320)}ms` }}
            >
              <span
                className="mt-[7px] h-[3px] w-4 shrink-0"
                style={{ background: COLOR[a.severidad] }}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <span className="text-[12.5px] text-[var(--color-tinta)]">{a.titulo}</span>
                  {a.impacto_pen > 0 && (
                    <span className="cifra ml-auto font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-tinta-2)]">
                      S/{monto(a.impacto_pen)}
                    </span>
                  )}
                </div>

                {/* El detalle es donde el backend explica la causa raíz. Sin
                    esto, el hallazgo más caro del demo se queda en un título. */}
                {a.detalle && (
                  <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--color-tinta-2)]">
                    {a.detalle}
                  </p>
                )}

                <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                  {a.accion && (
                    <span className="text-[11px] text-[var(--color-tinta-3)]">{a.accion}</span>
                  )}
                  {a.responsable && (
                    <span className="text-[11px] text-[var(--color-cobre)]">{a.responsable}</span>
                  )}
                  {a.kpi && (
                    <span className="ml-auto border border-[var(--filete-fuerte)] px-1.5 py-px font-[family-name:var(--font-mono)] text-[9.5px] text-[var(--color-tinta-3)]">
                      {a.kpi.replace(/_/g, " ")}
                    </span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Partidas({ kpis }: { kpis: Kpis }) {
  const r = kpis.reconciliacion;
  const filas = [
    {
      etiqueta: "Ya cobrado, sin aplicar",
      valor: r.monto_recuperado_pen,
      nota: `${num(r.pagos_recuperados)} pagos, recuperables de inmediato`,
      acento: true,
    },
    {
      etiqueta: "Cartera vencida real",
      valor: r.vista_c_pen,
      nota: "al corte, después de conciliar",
    },
    {
      etiqueta: "Provisión de cobranza dudosa",
      valor: kpis.provision_pcd_pen,
      nota: "de la cartera anterior",
      sangria: true,
    },
    {
      etiqueta: "Fuga por no facturar",
      valor: kpis.fuga_estimada_mes_pen,
      nota: `${num(kpis.cuentas_sin_factura)} cuentas activas, por mes de ciclo`,
    },
    {
      etiqueta: "Facturación en ISIS no consolidada",
      valor: r.monto_oculto_pen,
      nota: `${num(r.facturas_ocultas)} documentos que el reporte actual no ve`,
    },
    {
      etiqueta: "Partidas sin identificar",
      valor: kpis.monto_sin_identificar_pen,
      nota: `${num(kpis.pagos_sin_identificar)} pagos sin contraparte real`,
    },
  ];

  return (
    <div className="mt-4">
      {filas.map((f) => (
        <div
          key={f.etiqueta}
          className="filete-b flex items-baseline gap-4 py-2 last:border-b-0"
        >
          <span
            className={`text-[12.5px] ${f.sangria ? "pl-4 text-[var(--color-tinta-3)]" : "text-[var(--color-tinta-2)]"}`}
          >
            {f.sangria && <span className="mr-1.5 text-[var(--color-tinta-3)]">de la cual</span>}
            {f.etiqueta}
          </span>
          <span className="hidden flex-1 border-b border-dotted border-[var(--filete)] sm:block" />
          <span className="min-w-0 text-right">
            <span
              className="cifra block font-[family-name:var(--font-mono)] text-[13px]"
              style={{ color: f.acento ? "var(--color-ambar)" : "var(--color-tinta)" }}
            >
              S/{monto(f.valor)}
            </span>
            <span className="block text-[10.5px] text-[var(--color-tinta-3)]">{f.nota}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
