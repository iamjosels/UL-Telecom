import { ms, num } from "../lib/format";
import type { PasoCorrida, ResumenAgente } from "../state/runReducer";

/**
 * Las tres filas de agentes.
 *
 * Se arman desde GET /plan y se marcan con los eventos tool_inicio/tool_fin.
 * No se usa `paso_inicio`: el backend solo lo emite en el camino determinista,
 * así que en una corrida con agentes puede no llegar nunca.
 *
 * El agente que está actuando se enciende con el filete izquierdo en ámbar y
 * subiendo el texto de secundario a principal. Sin parpadeos.
 */

interface Props {
  agentes: ResumenAgente[];
  corriendo: boolean;
}

export function AgentTrack({ agentes, corriendo }: Props) {
  return (
    <section className="filete-t px-6 py-5">
      <h2 className="rotulo mb-4">Agentes</h2>
      <div className="space-y-px">
        {agentes.map((a) => (
          <FilaAgente key={a.clave} agente={a} corriendo={corriendo} />
        ))}
      </div>
    </section>
  );
}

function FilaAgente({ agente, corriendo }: { agente: ResumenAgente; corriendo: boolean }) {
  const completo = agente.total > 0 && agente.hechos === agente.total;
  const conError = agente.pasos.some((p) => p.estado === "error");

  const colorFilete = agente.activo
    ? "var(--color-ambar)"
    : conError
      ? "var(--color-terracota)"
      : completo
        ? "var(--color-musgo)"
        : "var(--filete-fuerte)";

  return (
    <div
      className="border-l-2 bg-[var(--color-superficie)]/40 py-3 pl-4 pr-3 transition-colors duration-300"
      style={{ borderLeftColor: colorFilete }}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3
          className="text-[13px] font-medium transition-colors duration-300"
          style={{
            color: agente.activo || completo ? "var(--color-tinta)" : "var(--color-tinta-2)",
          }}
        >
          {agente.nombre}
        </h3>

        <span className="cifra font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-tinta-3)]">
          {agente.hechos}/{agente.total}
        </span>

        <span className="ml-auto text-[11px]">
          {agente.activo ? (
            <span className="anim-late text-[var(--color-ambar)]">
              {etiquetaEnCurso(agente)}
            </span>
          ) : completo ? (
            <span className="text-[var(--color-musgo)]">listo</span>
          ) : corriendo ? (
            <span className="text-[var(--color-tinta-3)]">en espera</span>
          ) : null}
        </span>
      </div>

      <ul className="mt-2.5 space-y-1.5">
        {agente.pasos.map((p) => (
          <FilaPaso key={p.id} paso={p} />
        ))}
      </ul>
    </div>
  );
}

function etiquetaEnCurso(a: ResumenAgente): string {
  const nombre = a.nombre.split(" ")[0];
  return `${nombre} ${a.toolActual ? `ejecutando ${a.toolActual}` : "trabajando"}…`;
}

function FilaPaso({ paso }: { paso: PasoCorrida }) {
  const color =
    paso.estado === "ok"
      ? "var(--color-musgo)"
      : paso.estado === "error"
        ? "var(--color-terracota)"
        : paso.estado === "corriendo"
          ? "var(--color-ambar)"
          : "var(--color-superficie-3)";

  return (
    <li className="flex items-start gap-2.5">
      <span
        className={`mt-[6px] size-[5px] shrink-0 ${paso.estado === "corriendo" ? "anim-late" : ""}`}
        style={{ background: color }}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span
            className="truncate text-[12px]"
            style={{
              color:
                paso.estado === "pendiente"
                  ? "var(--color-tinta-3)"
                  : "var(--color-tinta-2)",
            }}
          >
            {paso.titulo}
          </span>

          {/* Momento del ciclo de facturación, cuando el paso pertenece a uno.
              Es lo que ancla cada herramienta a la ficha del reto. */}
          {paso.momento && (
            <span
              className="shrink-0 border border-[var(--filete-fuerte)] px-1 font-[family-name:var(--font-mono)] text-[9px] text-[var(--color-tinta-3)]"
              title={`Momento ${paso.momento}`}
            >
              M{paso.momento.charAt(0)}
            </span>
          )}

          <span className="ml-auto flex shrink-0 items-baseline gap-2">
            {paso.filasDetalle !== undefined && paso.filasDetalle > 0 && (
              <span className="cifra font-[family-name:var(--font-mono)] text-[10px] text-[var(--color-tinta-3)]">
                {num(paso.filasDetalle)} filas
              </span>
            )}
            {paso.duracionMs !== undefined && (
              <span className="cifra font-[family-name:var(--font-mono)] text-[10px] text-[var(--color-tinta-3)]">
                {ms(paso.duracionMs)}
              </span>
            )}
          </span>
        </div>

        {/* Una sola línea: el detalle completo vive en la trazabilidad. Con dos
            líneas el panel crecía ~400 px durante la corrida y empujaba el
            resto de la pantalla justo mientras el jurado está mirando. */}
        {paso.estado !== "pendiente" && paso.resumen && (
          <p className="anim-entra mt-0.5 truncate text-[11px] text-[var(--color-tinta-3)]">
            {paso.resumen}
          </p>
        )}
      </div>
    </li>
  );
}
