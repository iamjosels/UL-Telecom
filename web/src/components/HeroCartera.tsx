import { monto, num } from "../lib/format";
import { Waterfall, type PasoCascada } from "../charts/Waterfall";
import { useCountUp } from "../state/useCountUp";
import type { Etapa } from "../state/runReducer";
import type { Reconciliacion } from "../lib/types";

/**
 * El número héroe y la cascada.
 *
 * Las tres cifras salen del backend: A y B de la reconciliación de /kpis, C del
 * propio evento de cartera_vencida. Lo único que decide el front es cuándo
 * revelar cada una.
 *
 * Los saltos de la cascada se calculan RESTANDO los totales. El salto A→B mide
 * la diferencia real entre las dos vistas, no los S/137,200.41 que suman las
 * facturas de ISIS, que es una cifra parecida pero distinta. Si la cascada no
 * cuadra, miente.
 */

/**
 * Qué agente desbloquea cada etapa del arco.
 *
 * No es decorativo ni está elegido aquí: son los mismos dueños que fija
 * `runReducer.ts` con `TOOL_ETAPA_B` (resumen_facturacion, de Facturación) y
 * `TOOL_ETAPA_C` (cartera_vencida, de Cobranzas). A es el punto de partida, el
 * dato que ya tenía el sistema, así que no lo movió nadie.
 */
const QUIEN_MUEVE: Record<Etapa, string> = {
  0: "",
  1: "Facturación",
  2: "Cobranzas",
};

interface Props {
  reconciliacion?: Reconciliacion;
  carteraC?: number;
  etapa: Etapa;
  manual: boolean;
  onIr: (e: Etapa) => void;
  corriendo: boolean;
}

export function HeroCartera({
  reconciliacion,
  carteraC,
  etapa,
  manual,
  onIr,
  corriendo,
}: Props) {
  const r = reconciliacion;

  const totales = [
    r?.vista_a_pen ?? 0,
    r?.vista_b_pen ?? 0,
    carteraC ?? r?.vista_c_pen ?? 0,
  ];

  const pasos: PasoCascada[] = [
    { clave: "A", rotulo: "Lo que ve el sistema", total: totales[0]! },
    {
      clave: "B",
      rotulo: "Facturación en ISIS",
      total: totales[1]!,
      causa: r ? `${num(r.facturas_ocultas)} facturas de ISIS sin consolidar` : "",
    },
    {
      clave: "C",
      rotulo: "Deuda real",
      total: totales[2]!,
      causa: r ? `${num(r.pagos_recuperados)} pagos ya cobrados` : "",
    },
  ];

  const pies = [
    "Cruce literal del correlativo, con la fecha en un solo formato.",
    r ? `Aparecen ${num(r.facturas_ocultas)} facturas emitidas en ISIS que el reporte base no consolida.` : "",
    r ? `${num(r.pagos_recuperados)} pagos ya estaban cobrados: faltaba aplicarlos.` : "",
  ];

  const valor = totales[etapa] ?? totales[0]!;
  const animado = useCountUp(valor);
  const asentado = Math.abs(animado - valor) < 0.5;

  return (
    <section className="heroe-seccion w-full px-6 py-4">
      <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="rotulo">Cartera vencida</h2>
            {/* Quién movió el número. Es la mitad de la historia: sin esto el
                héroe cambia solo y parece magia, en vez de el resultado de que
                un agente concreto acaba de encontrar algo. */}
            {QUIEN_MUEVE[etapa] && (
              <span
                key={etapa}
                className="anim-entra text-[10.5px] text-[var(--color-cobre)]"
              >
                lo movió {QUIEN_MUEVE[etapa]}
              </span>
            )}
            {corriendo && (
              <span className="anim-late text-[10.5px] text-[var(--color-rampa-2)]">
                recalculando
              </span>
            )}
          </div>

          <div className="mt-1.5 flex items-baseline gap-2.5">
            <span className="font-[family-name:var(--font-display)] text-[clamp(1.1rem,2vw,1.6rem)] font-medium leading-none text-[var(--color-tinta-3)]">
              S/
            </span>
            <span
              // Ancho fijo solo mientras cuenta: con figuras proporcionales el
              // número baila de ancho en cada fotograma. Al posarse pasa a
              // proporcionales, que es como debe verse una cifra grande.
              className={`heroe-cifra font-[family-name:var(--font-display)] font-bold leading-[0.86] tracking-[-0.035em] text-[var(--color-rampa-2)] ${
                asentado ? "" : "cifra-animando"
              }`}
              style={{ fontSize: "clamp(2.75rem, 5.2vw, 4.5rem)" }}
            >
              {monto(animado)}
            </span>
          </div>

          <p className="mt-2 max-w-sm text-[12px] leading-relaxed text-[var(--color-tinta-2)]">
            <span className="text-[var(--color-tinta)]">{pasos[etapa]?.rotulo}.</span>{" "}
            {pies[etapa]}
          </p>

          <p className="heroe-pie mt-2.5 text-[10.5px] text-[var(--color-tinta-3)]">
            {manual ? "Recorriendo a mano" : "Avance automático"}. <Tecla>←</Tecla>{" "}
            <Tecla>→</Tecla> entre los tres estados.
          </p>
        </div>

        <div className="grafico-cascada min-w-0 flex-1" style={{ minWidth: "380px" }}>
          <Waterfall
            pasos={pasos}
            hasta={etapa}
            onIr={(i) => onIr(i as Etapa)}
          />
        </div>
      </div>
    </section>
  );
}

function Tecla({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="mx-[1px] inline-flex h-[15px] min-w-[15px] items-center justify-center border border-[var(--filete-fuerte)] px-1 font-[family-name:var(--font-mono)] text-[9.5px] text-[var(--color-tinta-2)]">
      {children}
    </kbd>
  );
}
