import { useEffect } from "react";
import { monto, num, pct } from "../lib/format";
import type { Kpis } from "../lib/types";

/**
 * Chuleta para presentar, con la tecla G.
 *
 * Todas las cifras salen de /kpis, así que nunca se queda desfasada respecto a
 * lo que hay en pantalla. Lleva `data-guion` para poder excluirlo de capturas.
 */

interface Props {
  kpis?: Kpis;
  abierto: boolean;
  onCerrar: () => void;
}

export function GuionPitch({ kpis, abierto, onCerrar }: Props) {
  useEffect(() => {
    if (!abierto) return;
    const alPulsar = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCerrar();
    };
    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, [abierto, onCerrar]);

  if (!abierto || !kpis) return null;

  const r = kpis.reconciliacion;

  return (
    <>
      <div
        data-guion
        className="fixed inset-0 z-40 bg-black/45"
        onClick={onCerrar}
        aria-hidden
      />
      <aside
        data-guion
        className="filete-l fixed right-0 top-0 z-50 flex h-full w-[min(30rem,92vw)] flex-col overflow-y-auto bg-[var(--color-superficie)] shadow-[-24px_0_48px_rgba(0,0,0,.5)]"
      >
        <div className="filete-b flex items-baseline gap-3 px-5 py-3.5">
          <h2 className="rotulo">Guión del pitch</h2>
          <span className="ml-auto text-[10.5px] text-[var(--color-tinta-3)]">
            G o Esc para cerrar
          </span>
        </div>

        <div className="flex-1 px-5 py-4">
          <Punto
            n="1"
            titulo="Lo que el sistema ve hoy"
            cifra={`S/${monto(r.vista_a_pen)}`}
          >
            Es lo que reporta la cartera vencida al corte. Parece manejable.
          </Punto>

          <Punto
            n="2"
            titulo="Facturación destapa ISIS"
            cifra={`S/${monto(r.vista_b_pen)}`}
            acento
          >
            Hay un segundo sistema de facturación. Sus{" "}
            <B>{num(r.facturas_ocultas)} facturas</B> traen la fecha en otro
            formato, así que el reporte actual no las ve.{" "}
            <B>S/{monto(r.monto_oculto_pen)}</B> y ninguna está pagada.
          </Punto>

          <Punto
            n="3"
            titulo="Cobranzas concilia"
            cifra={`−S/${monto(r.monto_recuperado_pen)}`}
            acento
          >
            De esa deuda, <B>{num(r.pagos_recuperados)} pagos ya estaban
            cobrados</B>. No cruzaban por un cero de menos en el correlativo.
            <span className="mt-1.5 block font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-arena)]">
              maestro S300-<span className="text-[var(--color-ambar)]">0</span>248301
              <br />
              pago&nbsp;&nbsp;&nbsp;&nbsp; S300-248301
            </span>
          </Punto>

          <Punto
            n="4"
            titulo="Deuda real al corte"
            cifra={`S/${monto(r.vista_c_pen)}`}
            acento
          >
            Ni los S/{monto(r.vista_a_pen)} que se reportan, ni los S/
            {monto(r.vista_b_pen)} del susto. Sin identificar de verdad quedan{" "}
            <B>{num(kpis.pagos_sin_identificar)} pagos</B> por S/
            {monto(kpis.monto_sin_identificar_pen)}.
          </Punto>

          <div className="filete-t mt-4 pt-4">
            <div className="rotulo mb-2">Si preguntan</div>

            <Respuesta pregunta="¿Y si el modelo se inventa una cifra?">
              Ninguna cifra la calcula el modelo. Abre cualquier línea de
              trazabilidad y verás los argumentos y el linaje del cálculo. En la
              consulta, si el modelo cita un número que ninguna herramienta
              produjo, la redacción se descarta.
            </Respuesta>

            <Respuesta pregunta="¿Cubren los tres momentos de facturación?">
              El 1, asesoría previa, y el 3, rebaja post-pago. El 2 es emitir el
              documento: dejamos el insumo validado y listo, pero ejecutar la
              emisión necesita escritura sobre el facturador.
            </Respuesta>

            <Respuesta pregunta="¿Y si se cae Groq en mitad del demo?">
              El cierre se completa sin LLM con las mismas cifras. El
              interruptor de modo seguro lo fuerza a mano.
            </Respuesta>

            <Respuesta pregunta="¿De dónde sale la fuga?">
              {num(kpis.cuentas_sin_factura)} de {num(kpis.cuentas_activas)}{" "}
              cuentas con servicio activo ({pct(kpis.pct_fuga)}) no tienen
              ninguna factura emitida. Al ticket mediano son S/
              {monto(kpis.fuga_estimada_mes_pen)} por mes de ciclo.
            </Respuesta>
          </div>
        </div>
      </aside>
    </>
  );
}

function Punto({
  n,
  titulo,
  cifra,
  acento,
  children,
}: {
  n: string;
  titulo: string;
  cifra: string;
  acento?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="filete-b py-3 first:pt-0">
      <div className="flex items-baseline gap-2.5">
        <span className="font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-tinta-3)]">
          {n}
        </span>
        <span className="text-[13px] text-[var(--color-tinta)]">{titulo}</span>
        <span
          className="cifra ml-auto font-[family-name:var(--font-mono)] text-[13px]"
          style={{ color: acento ? "var(--color-ambar)" : "var(--color-tinta-2)" }}
        >
          {cifra}
        </span>
      </div>
      <p className="mt-1.5 pl-[22px] text-[12px] leading-relaxed text-[var(--color-tinta-2)]">
        {children}
      </p>
    </div>
  );
}

function Respuesta({
  pregunta,
  children,
}: {
  pregunta: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3">
      <p className="text-[12px] text-[var(--color-cobre)]">{pregunta}</p>
      <p className="mt-0.5 text-[11.5px] leading-relaxed text-[var(--color-tinta-2)]">
        {children}
      </p>
    </div>
  );
}

const B = ({ children }: { children: React.ReactNode }) => (
  <span className="text-[var(--color-tinta)]">{children}</span>
);
