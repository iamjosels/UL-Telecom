import { monto } from "../lib/format";
import type { AlertaCompleta, Kpis, Modo } from "../lib/types";

/**
 * La conclusión del supervisor.
 *
 * Dos bloques con orígenes distintos, y conviene que se distingan:
 *
 *  - El consolidado sale de las alertas y las métricas, que son deterministas.
 *    Siempre está, también en modo seguro.
 *  - La lectura ejecutiva la redacta el LLM sobre esas mismas cifras. Solo
 *    aparece cuando corrieron los agentes.
 *
 * Separarlos es el argumento entero del proyecto: las cifras no dependen del
 * modelo, la prosa sí.
 */

interface Props {
  alertas: AlertaCompleta[];
  narrativa?: string;
  kpis?: Kpis;
  modo?: Modo;
  corriendo: boolean;
  mensajes: { agente: string; texto: string }[];
}

export function SupervisorPanel({
  alertas,
  narrativa,
  kpis,
  modo,
  corriendo,
  mensajes,
}: Props) {
  const hayCorrida = alertas.length > 0 || Boolean(narrativa);
  const ultimoMensaje = mensajes.at(-1);

  if (!hayCorrida && !corriendo) {
    return (
      <section className="supervisor filete-t px-6 py-5">
        <h2 className="rotulo">Supervisor</h2>
        <p className="mt-2 max-w-lg text-[12.5px] text-[var(--color-tinta-3)]">
          Cuando termine el cierre, aquí queda el diagnóstico consolidado y las
          acciones con su responsable.
        </p>
      </section>
    );
  }

  return (
    <section className="supervisor filete-t px-6 py-5">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="rotulo">Supervisor</h2>
        {corriendo && ultimoMensaje ? (
          <span className="anim-late text-[11px] text-[var(--color-ambar)]">
            {ultimoMensaje.texto.slice(0, 70)}
          </span>
        ) : hayCorrida ? (
          <span className="text-[11px] text-[var(--color-tinta-3)]">
            consolidó {alertas.length} hallazgos de los tres agentes
          </span>
        ) : null}
      </div>

      {hayCorrida && (
        <div className="mt-4 grid gap-x-8 gap-y-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Diagnostico alertas={alertas} kpis={kpis} />
          {narrativa ? (
            <Lectura narrativa={narrativa} />
          ) : (
            <Acciones alertas={alertas} nota={notaSinLlm(modo)} />
          )}
          {/* Con narrativa, las acciones bajan a una fila propia a lo ancho. */}
          {narrativa && (
            <div className="lg:col-span-2">
              <Acciones alertas={alertas} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

const notaSinLlm = (modo?: Modo) =>
  modo === "deterministico"
    ? "El cierre corrió sin LLM. Las cifras son exactamente las mismas."
    : "El supervisor no llegó a redactar. Nada de esto depende de eso.";

/** Diagnóstico y lo más caro. Todo determinista. */
function Diagnostico({ alertas, kpis }: { alertas: AlertaCompleta[]; kpis?: Kpis }) {
  const conImpacto = alertas.filter((a) => a.impacto_pen > 0).slice(0, 3);
  const r = kpis?.reconciliacion;

  return (
    <div>
      <div className="rotulo mb-2 text-[9.5px]">Consolidado · sin LLM</div>

      {r && (
        <p className="mb-3.5 text-[12.5px] leading-relaxed text-[var(--color-tinta-2)]">
          Los hallazgos más caros comparten causa: dos sistemas de facturación
          que no cruzan entre sí.{" "}
          <span className="text-[var(--color-tinta)]">{r.facturas_ocultas} facturas</span>{" "}
          no aparecen en el reporte por el formato de fecha, y{" "}
          <span className="text-[var(--color-tinta)]">{r.pagos_recuperados} pagos</span>{" "}
          no se aplicaron por un cero de menos en el correlativo.
        </p>
      )}

      {conImpacto.length > 0 && (
        <>
          <div className="rotulo mb-1.5 text-[9.5px]">Lo más urgente</div>
          {conImpacto.map((a) => (
            <div key={a.titulo} className="flex items-baseline gap-3 py-[3px]">
              <span className="min-w-0 flex-1 truncate text-[12px] text-[var(--color-tinta-2)]">
                {a.titulo}
              </span>
              <span className="cifra shrink-0 font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-tinta)]">
                S/{monto(a.impacto_pen)}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function Acciones({ alertas, nota }: { alertas: AlertaCompleta[]; nota?: string }) {
  const acciones = alertas.filter((a) => a.accion).slice(0, 4);
  if (!acciones.length) return null;

  return (
    <div>
      <div className="rotulo mb-1.5 text-[9.5px]">Acciones</div>
      <ol className="space-y-1">
        {acciones.map((a, i) => (
          <li key={a.titulo} className="flex items-baseline gap-2 text-[12px]">
            <span className="shrink-0 font-[family-name:var(--font-mono)] text-[10px] text-[var(--color-tinta-3)]">
              {i + 1}
            </span>
            <span className="min-w-0 flex-1 text-[var(--color-tinta-2)]">{a.accion}</span>
            {a.responsable && (
              <span className="shrink-0 text-[10.5px] text-[var(--color-cobre)]">
                {a.responsable}
              </span>
            )}
          </li>
        ))}
      </ol>
      {nota && <p className="mt-3 text-[11px] text-[var(--color-tinta-3)]">{nota}</p>}
    </div>
  );
}

/** Bloque del LLM. Solo prosa: cada cifra que cita ya estaba calculada. */
function Lectura({ narrativa }: { narrativa: string }) {
  return (
    <div>
      <div className="rotulo mb-2 text-[9.5px]">
        Lectura ejecutiva · redactada por el modelo
      </div>
      <div className="space-y-1.5">
        {parsear(narrativa).map((b, i) => (
          <Linea key={i} bloque={b} />
        ))}
      </div>
      <p className="mt-3 text-[10.5px] text-[var(--color-tinta-3)]">
        El modelo redacta sobre las cifras ya calculadas. No las recalcula.
      </p>
    </div>
  );
}

// --------------------------------------------------------------------------
// Parser mínimo del markdown que devuelve el supervisor
// --------------------------------------------------------------------------

type BloqueTexto =
  | { tipo: "titulo"; texto: string; resto: string }
  | { tipo: "item"; texto: string }
  | { tipo: "parrafo"; texto: string };

/**
 * El supervisor devuelve markdown sencillo y siempre con la misma forma:
 * rótulos en `**NEGRITA**:`, listas con `- ` o `* `, a veces numeradas, y
 * bloques separados por línea en blanco. No hace falta una librería para esto.
 */
function parsear(texto: string): BloqueTexto[] {
  const bloques: BloqueTexto[] = [];

  for (const bruto of texto.split("\n")) {
    const linea = bruto.trim();
    if (!linea) continue;

    const titulo = linea.match(/^\*\*(.+?)\*\*:?\s*(.*)$/);
    if (titulo) {
      bloques.push({
        tipo: "titulo",
        texto: titulo[1] ?? "",
        resto: (titulo[2] ?? "").trim(),
      });
      continue;
    }

    const item = linea.match(/^[-*•]\s+(.*)$/) ?? linea.match(/^\d+[.)]\s+(.*)$/);
    if (item) {
      bloques.push({ tipo: "item", texto: limpiar(item[1] ?? "") });
      continue;
    }

    bloques.push({ tipo: "parrafo", texto: limpiar(linea) });
  }

  return bloques;
}

const limpiar = (s: string) => s.replace(/\*\*(.+?)\*\*/g, "$1").trim();

function Linea({ bloque }: { bloque: BloqueTexto }) {
  if (bloque.tipo === "titulo") {
    return (
      <div className="pt-1.5 first:pt-0">
        <span className="rotulo text-[9.5px] text-[var(--color-cobre)]">{bloque.texto}</span>
        {bloque.resto && (
          <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--color-tinta-2)]">
            {limpiar(bloque.resto)}
          </p>
        )}
      </div>
    );
  }

  if (bloque.tipo === "item") {
    return (
      <div className="flex gap-2 text-[12px] leading-relaxed text-[var(--color-tinta-2)]">
        <span className="shrink-0 text-[var(--color-tinta-3)]">·</span>
        <span className="min-w-0">{bloque.texto}</span>
      </div>
    );
  }

  return (
    <p className="text-[12px] leading-relaxed text-[var(--color-tinta-2)]">{bloque.texto}</p>
  );
}
