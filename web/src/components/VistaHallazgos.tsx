import { monto, num } from "../lib/format";
import { BarrasEnfasis } from "../charts/BarrasEnfasis";
import { Columnas } from "../charts/Columnas";
import { Linea } from "../charts/Linea";
import type { AlertaCompleta, DetalleTools, Kpis, Severidad } from "../lib/types";
import type { PasoCorrida } from "../state/runReducer";

/**
 * Todo lo que el cierre encontró, en gráficos.
 *
 * Cada forma se elige por el trabajo que hace, no por variedad:
 * escalas ordenadas van en columnas con la rampa ámbar, la curva de cobro en
 * línea de una sola serie, la concentración con énfasis en uno, y las anomalías
 * en tabla porque sus dos magnitudes no correlacionan (57 registros valen
 * S/137K y 1.871 registros valen S/216K: en un solo eje eso engaña).
 */

interface Props {
  kpis?: Kpis;
  alertas: AlertaCompleta[];
  pasos: PasoCorrida[];
  detalle?: DetalleTools;
}

const COLOR_SEV: Record<Severidad, string> = {
  critica: "var(--color-terracota)",
  alta: "var(--color-cobre)",
  media: "var(--color-arena)",
  baja: "var(--color-tinta-3)",
  info: "var(--color-tinta-3)",
};

const metrica = (pasos: PasoCorrida[], tool: string, clave: string): number | undefined => {
  const m = pasos.find((p) => p.tool === tool)?.metricas?.[clave];
  const n = Number(m);
  return Number.isFinite(n) ? n : undefined;
};

export function VistaHallazgos({ kpis, alertas, pasos, detalle }: Props) {
  const hayCorrida = pasos.some((p) => p.estado === "ok");

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-px overflow-y-auto bg-[var(--filete)] xl:grid-cols-3">
      <Panel titulo="Antigüedad de la deuda" nota="la parte sólida es lo que se provisiona">
        {kpis ? (
          <Columnas
            columnas={(["1-30", "31-60", "61-90", "90+"] as const).map((t) => ({
              clave: t,
              rotulo: t,
              valor: kpis.aging[t]?.saldo ?? 0,
              // La provisión sale del backend; si esa herramienta aún no corrió
              // se estima con la matriz para no dejar el gráfico a medias.
              parte:
                metrica(pasos, "provision_cobranza_dudosa", provKey(t)) ??
                (kpis.aging[t]?.saldo ?? 0) * (TASA[t] ?? 0),
              nota: `${num(kpis.aging[t]?.facturas ?? 0)} f.`,
            }))}
            etiquetaTotal="saldo"
            etiquetaParte="provisión"
          />
        ) : (
          <Vacio />
        )}
      </Panel>

      <Panel
        titulo="Curva de cobro"
        nota="qué parte del dinero entra a cada plazo desde el vencimiento"
      >
        {hayCorrida ? (
          <Linea
            puntos={[0, 7, 15, 30, 60, 90, 180].flatMap((d) => {
              const v = metrica(pasos, "ratio_cobrado_facturado", `curva_cobro_${d}d`);
              return v === undefined ? [] : [{ x: d, y: v }];
            })}
            destacar={[30]}
          />
        ) : (
          <Vacio />
        )}
      </Panel>

      <Panel titulo="Adelanto operativo de caja" nota="cobranza esperada, acumulada">
        {hayCorrida ? (
          <Columnas
            columnas={[30, 60, 90].flatMap((d) => {
              const v = metrica(pasos, "proyeccion_caja", `proyeccion_${d}d_pen`);
              return v === undefined
                ? []
                : [{ clave: `${d}`, rotulo: `${d} d`, valor: v }];
            })}
          />
        ) : (
          <Vacio />
        )}
      </Panel>

      <Panel
        titulo="Concentración de la cartera"
        nota="a quién cobrar primero"
        className="xl:col-span-2"
      >
        {detalle?.priorizar_recupero?.data?.length ? (
          <BarrasEnfasis
            filas={detalle.priorizar_recupero.data.map((f) => ({
              clave: String(f.ruc),
              rotulo: String(f.ruc),
              valor: Number(f.saldo) || 0,
            }))}
            visibles={6}
            total={metrica(pasos, "cartera_vencida", "cartera_vencida_pen")}
            poblacion={metrica(pasos, "priorizar_recupero", "clientes_con_saldo")}
          />
        ) : (
          <Vacio />
        )}
      </Panel>

      {/* La nota dice POR QUÉ no se suman, no solo que no se suman: son un
          cobro pendiente de aplicar, una deuda y un flujo mensual. */}
      <Panel titulo="Cuadro de impacto" nota="un cobro, una deuda y un flujo: no se suman">
        {kpis ? <Partidas kpis={kpis} /> : <Vacio />}
        {alertas.length > 0 && (
          <ul className="filete-t mt-3 space-y-1.5 pt-3">
            {alertas.slice(0, 4).map((a, i) => (
              <li key={`${a.titulo}-${i}`} className="flex gap-2.5">
                <span
                  className="mt-[6px] h-[3px] w-3.5 shrink-0"
                  style={{ background: COLOR_SEV[a.severidad] }}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="min-w-0 flex-1 truncate text-[11.5px] text-[var(--color-tinta)]">
                      {a.titulo}
                    </span>
                    {a.impacto_pen > 0 && (
                      <span className="cifra shrink-0 font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-tinta-2)]">
                        S/{monto(a.impacto_pen)}
                      </span>
                    )}
                  </div>
                  {a.responsable && (
                    <div className="text-[10px] text-[var(--color-cobre)]">{a.responsable}</div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

/**
 * Anomalías, en tabla y no en gráfico.
 *
 * Sus dos magnitudes no correlacionan: 57 registros valen S/137.200 y 1.871
 * registros valen S/216.379. Cualquier gráfico de un solo eje contaría una de
 * las dos y daría a entender la otra.
 */
export function TablaAnomalias({ filas }: { filas: Array<Record<string, unknown>> }) {
  const orden = [...filas].sort((a, b) => Number(b.monto_pen ?? 0) - Number(a.monto_pen ?? 0));
  return (
    <table className="w-full text-[11px]">
      <thead>
        <tr className="text-[9px] uppercase tracking-[0.1em] text-[var(--color-tinta-3)]">
          <th className="pb-1.5 text-left font-medium">Tipo</th>
          <th className="pb-1.5 text-right font-medium">Registros</th>
          <th className="pb-1.5 text-right font-medium">Monto</th>
        </tr>
      </thead>
      <tbody>
        {orden.map((f, i) => (
          <tr key={i} className="filete-b last:border-b-0">
            <td className="py-1.5 pr-2">
              <span className="flex items-baseline gap-2">
                <span
                  className="inline-block h-[3px] w-3 shrink-0"
                  style={{ background: COLOR_SEV[(f.severidad as Severidad) ?? "info"] }}
                />
                <span className="min-w-0 truncate text-[var(--color-tinta-2)]">
                  {String(f.titulo ?? f.tipo)}
                </span>
                <span className="shrink-0 text-[9px] text-[var(--color-tinta-3)]">
                  {String(f.severidad)}
                </span>
              </span>
            </td>
            <td className="cifra py-1.5 text-right font-[family-name:var(--font-mono)] text-[var(--color-tinta-2)]">
              {num(Number(f.registros))}
            </td>
            <td className="cifra py-1.5 text-right font-[family-name:var(--font-mono)] text-[var(--color-tinta)]">
              {Number(f.monto_pen) > 0 ? `S/${monto(Number(f.monto_pen))}` : "·"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const TASA: Record<string, number> = { "1-30": 0, "31-60": 0.25, "61-90": 0.5, "90+": 1 };
const provKey = (t: string) =>
  `provision_${t.replace("-", "_").replace("+", "_mas")}_pen`;

function Panel({
  titulo,
  nota,
  className = "",
  children,
}: {
  titulo: string;
  nota?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`panel-dato flex flex-col bg-[var(--color-fondo)] px-5 py-4 ${className}`}>
      <div className="panel-dato-cab mb-3 flex flex-wrap items-baseline gap-2">
        <h3 className="rotulo">{titulo}</h3>
        {nota && <span className="text-[10px] text-[var(--color-tinta-3)]">{nota}</span>}
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </section>
  );
}

function Vacio() {
  return (
    <p className="text-[11px] text-[var(--color-tinta-3)]">
      Se rellena al cerrar el ciclo.
    </p>
  );
}

function Partidas({ kpis }: { kpis: Kpis }) {
  const r = kpis.reconciliacion;
  const filas = [
    { etiqueta: "Ya cobrado, sin aplicar", valor: r.monto_recuperado_pen, acento: true },
    { etiqueta: "Cartera vencida real", valor: r.vista_c_pen },
    { etiqueta: "Provisión de cobranza dudosa", valor: kpis.provision_pcd_pen, sangria: true },
    { etiqueta: "Fuga por no facturar", valor: kpis.fuga_estimada_mes_pen, nota: "al mes" },
    { etiqueta: "Facturación en ISIS no consolidada", valor: r.monto_oculto_pen },
    { etiqueta: "Sin identificar de verdad", valor: kpis.monto_sin_identificar_pen },
  ];
  return (
    <div>
      {filas.map((f) => (
        <div key={f.etiqueta} className="filete-b flex items-baseline gap-3 py-1.5 last:border-b-0">
          <span
            className={`min-w-0 flex-1 truncate text-[11.5px] ${f.sangria ? "pl-3 text-[var(--color-tinta-3)]" : "text-[var(--color-tinta-2)]"}`}
          >
            {f.etiqueta}
          </span>
          {/* El periodo va como nota y no dentro del nombre: el nombre del
              hallazgo tiene que ser idéntico al del KPI y al de la alerta. */}
          {"nota" in f && f.nota && (
            <span className="shrink-0 text-[10px] text-[var(--color-tinta-3)]">{f.nota}</span>
          )}
          <span
            className="cifra shrink-0 font-[family-name:var(--font-mono)] text-[11.5px]"
            style={{ color: f.acento ? "var(--color-rampa-2)" : "var(--color-tinta)" }}
          >
            S/{monto(f.valor)}
          </span>
        </div>
      ))}
    </div>
  );
}
