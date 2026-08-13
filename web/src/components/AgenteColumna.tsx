import { useState } from "react";
import { ms } from "../lib/format";
import { destacadosDe } from "../lib/destacados";
import type { PasoCorrida, ResumenAgente } from "../state/runReducer";

/**
 * Un agente y lo que encontró, en cifras.
 *
 * Antes esto era el título del paso más su resumen en prosa recortado a una
 * línea. El párrafo sigue ahí, pero detrás de un despliegue: lo primero que se
 * ve son las dos cifras que cuentan la historia de cada herramienta.
 */

interface Props {
  agente: ResumenAgente;
  corriendo: boolean;
}

export function AgenteColumna({ agente, corriendo }: Props) {
  const completo = agente.total > 0 && agente.hechos === agente.total;
  const conError = agente.pasos.some((p) => p.estado === "error");

  const filete = agente.activo
    ? "var(--color-rampa-2)"
    : conError
      ? "var(--color-terracota)"
      : completo
        ? "var(--color-musgo)"
        : "var(--filete-fuerte)";

  return (
    <section
      className="flex min-w-0 flex-col border-l-2 bg-[var(--color-superficie)]/35 py-2.5 pl-4 pr-3 transition-colors duration-300"
      style={{ borderLeftColor: filete }}
    >
      <header className="flex items-baseline gap-2">
        <h3
          className="truncate text-[12.5px] font-medium transition-colors duration-300"
          style={{
            color: agente.activo || completo ? "var(--color-tinta)" : "var(--color-tinta-2)",
          }}
        >
          {agente.nombre}
        </h3>
        <span className="cifra shrink-0 font-[family-name:var(--font-mono)] text-[10.5px] text-[var(--color-tinta-3)]">
          {agente.hechos}/{agente.total}
        </span>
        <span className="ml-auto shrink-0 text-[10.5px]">
          {agente.activo ? (
            <span className="anim-late text-[var(--color-rampa-2)]">trabajando</span>
          ) : completo ? (
            <span className="text-[var(--color-musgo)]">listo</span>
          ) : corriendo ? (
            <span className="text-[var(--color-tinta-3)]">en espera</span>
          ) : null}
        </span>
      </header>

      <div className="mt-2 space-y-[7px]">
        {agente.pasos.map((p) => (
          <Paso key={p.id} paso={p} />
        ))}
      </div>
    </section>
  );
}

function Paso({ paso }: { paso: PasoCorrida }) {
  const [abierto, setAbierto] = useState(false);
  const cifras = destacadosDe(paso.tool, paso.metricas);
  const hecho = paso.estado === "ok" || paso.estado === "error";

  const color =
    paso.estado === "ok"
      ? "var(--color-musgo)"
      : paso.estado === "error"
        ? "var(--color-terracota)"
        : paso.estado === "corriendo"
          ? "var(--color-rampa-2)"
          : "var(--color-superficie-3)";

  return (
    <div>
      <button
        type="button"
        onClick={() => paso.resumen && setAbierto((v) => !v)}
        disabled={!paso.resumen}
        className="flex w-full items-baseline gap-2 text-left disabled:cursor-default"
      >
        <span
          className={`mt-[5px] size-[5px] shrink-0 ${paso.estado === "corriendo" ? "anim-late" : ""}`}
          style={{ background: color }}
        />
        <span
          className="min-w-0 flex-1 truncate text-[11px]"
          style={{
            color: hecho ? "var(--color-tinta-2)" : "var(--color-tinta-3)",
          }}
        >
          {paso.titulo}
        </span>
        {paso.momento && (
          <span className="shrink-0 border border-[var(--filete)] px-1 font-[family-name:var(--font-mono)] text-[8.5px] text-[var(--color-tinta-3)]">
            M{paso.momento.charAt(0)}
          </span>
        )}
        {paso.duracionMs !== undefined && (
          <span className="cifra shrink-0 font-[family-name:var(--font-mono)] text-[9px] text-[var(--color-tinta-3)]">
            {ms(paso.duracionMs)}
          </span>
        )}
      </button>

      {/* Las cifras, que es lo que antes se perdía dentro del párrafo. */}
      {cifras.length > 0 && (
        <div className="anim-entra mt-0.5 grid grid-cols-2 gap-x-3 pl-[13px]">
          {cifras.map((c) => (
            <div key={c.rotulo} className="min-w-0">
              <div className="truncate text-[8.5px] uppercase tracking-[0.07em] text-[var(--color-tinta-3)]">
                {c.rotulo}
              </div>
              <div className="truncate font-[family-name:var(--font-display)] text-[14px] font-medium leading-[1.15] text-[var(--color-tinta)]">
                {c.texto}
                {c.unidad && (
                  <span className="ml-1 text-[9.5px] font-normal text-[var(--color-tinta-3)]">
                    {c.unidad}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {abierto && paso.resumen && (
        <p className="anim-entra mt-1.5 pl-[13px] text-[10.5px] leading-relaxed text-[var(--color-tinta-3)]">
          {paso.resumen}
        </p>
      )}
    </div>
  );
}
