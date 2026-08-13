import { useEffect, useRef, useState } from "react";
import { hora, ms, num } from "../lib/format";
import { abreviar, type LineaAudit } from "../state/runReducer";

/**
 * Trazabilidad.
 *
 * Esto es la prueba del "0% de alucinaciones", y para que lo sea hay que poder
 * abrir cualquier línea y ver de dónde sale la cifra: con qué argumentos se
 * llamó la herramienta y qué pasos dio el cálculo hasta el resultado.
 *
 * El linaje lo escribe el backend en `trazas`, del estilo
 * "facturas 3364 -> saldo>0.01 -> 476". Es lo que permite a alguien seguir un
 * número sin leer el código.
 */

interface Props {
  lineas: LineaAudit[];
  archivo?: string;
  toolsOk?: number;
  toolsError?: number;
}

export function AuditLog({ lineas, archivo, toolsOk, toolsError }: Props) {
  const [abierta, setAbierta] = useState<string | null>(null);
  const fin = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!abierta) fin.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [lineas.length, abierta]);

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="filete-b flex items-baseline gap-3 px-4 py-3">
        <h2 className="rotulo">Trazabilidad</h2>
        <span className="text-[10.5px] text-[var(--color-tinta-3)]">
          abre una línea y verás de dónde sale
        </span>
        {toolsOk !== undefined && (
          <span className="ml-auto font-[family-name:var(--font-mono)] text-[10.5px] text-[var(--color-tinta-3)]">
            {toolsOk} ok{toolsError ? ` · ${toolsError} error` : ""}
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
        {lineas.length === 0 ? (
          <div className="flex h-full flex-col justify-center gap-2 pb-6">
            <p className="max-w-[38ch] text-[11.5px] leading-relaxed text-[var(--color-tinta-3)]">
              Cada herramienta que se ejecute queda registrada aquí con su agente,
              sus argumentos y su duración.
            </p>
            <p className="max-w-[38ch] text-[11.5px] leading-relaxed text-[var(--color-tinta-3)]/70">
              Es la prueba de que las cifras las calcula Python y no el modelo.
            </p>
          </div>
        ) : (
          <div className="font-[family-name:var(--font-mono)] text-[11px]">
            {lineas.map((l) => (
              <Fila
                key={l.clave}
                linea={l}
                abierta={abierta === l.clave}
                onToggle={() => setAbierta(abierta === l.clave ? null : l.clave)}
              />
            ))}
            <div ref={fin} />
          </div>
        )}
      </div>

      {archivo && (
        <div className="filete-t px-4 py-2">
          <p className="truncate font-[family-name:var(--font-mono)] text-[10px] text-[var(--color-tinta-3)]">
            {archivo.split(/[\\/]/).pop()}
          </p>
        </div>
      )}
    </section>
  );
}

function Fila({
  linea,
  abierta,
  onToggle,
}: {
  linea: LineaAudit;
  abierta: boolean;
  onToggle: () => void;
}) {
  const hayDetalle = Boolean(linea.trazas?.length || linea.inputs || linea.error);

  const color = linea.enCurso
    ? "var(--color-ambar)"
    : linea.ok
      ? "var(--color-tinta-2)"
      : "var(--color-terracota)";

  return (
    <div className="anim-entra">
      <button
        type="button"
        onClick={hayDetalle ? onToggle : undefined}
        disabled={!hayDetalle}
        className="flex w-full items-baseline gap-2 py-[3px] text-left leading-[1.7] transition-colors duration-150 hover:bg-[var(--color-superficie-2)]/60 disabled:cursor-default disabled:hover:bg-transparent"
      >
        <span className="shrink-0 text-[var(--color-tinta-3)]">{hora(linea.ts)}</span>
        <span className="w-[34px] shrink-0" style={{ color: colorAgente(linea.agente) }}>
          {abreviar(linea.agente)}
        </span>
        <span className="truncate" style={{ color }}>
          {linea.etiqueta || linea.tool}
        </span>
        <span className="ml-auto shrink-0 text-[var(--color-tinta-3)]">
          {linea.enCurso ? "···" : ms(linea.duracionMs)}
        </span>
        {hayDetalle && (
          <span
            className="w-[9px] shrink-0 text-center text-[9px] text-[var(--color-tinta-3)] transition-transform duration-200"
            style={{ transform: abierta ? "rotate(90deg)" : "none" }}
          >
            ▸
          </span>
        )}
      </button>

      {abierta && hayDetalle && (
        <div className="anim-entra mb-2 ml-[54px] border-l border-[var(--filete-fuerte)] pl-3">
          <p className="mt-1 text-[10px] text-[var(--color-tinta-3)]">{linea.tool}</p>

          {linea.inputs && Object.keys(linea.inputs).length > 0 && (
            <Bloque titulo="Argumentos">
              {Object.entries(linea.inputs).map(([k, v]) => (
                <div key={k} className="text-[10.5px] text-[var(--color-tinta-2)]">
                  {k}
                  <span className="text-[var(--color-tinta-3)]"> = </span>
                  <span className="text-[var(--color-arena)]">{formatearValor(v)}</span>
                </div>
              ))}
            </Bloque>
          )}

          {linea.trazas && linea.trazas.length > 0 && (
            <Bloque titulo="Cómo se calculó">
              {linea.trazas.map((t, i) => (
                <div key={i} className="flex gap-1.5 text-[10.5px] text-[var(--color-tinta-2)]">
                  <span className="shrink-0 text-[var(--color-tinta-3)]">{i + 1}</span>
                  <span className="min-w-0 break-words">{t}</span>
                </div>
              ))}
            </Bloque>
          )}

          {linea.filasDetalle !== undefined && linea.filasDetalle > 0 && (
            <p className="mt-2 text-[10px] text-[var(--color-tinta-3)]">
              {num(linea.filasDetalle)} filas de detalle en el registro
            </p>
          )}

          {linea.error && (
            <Bloque titulo="Error">
              <p className="break-words text-[10.5px] text-[var(--color-terracota)]">
                {linea.error}
              </p>
            </Bloque>
          )}
        </div>
      )}
    </div>
  );
}

function Bloque({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div className="mt-2">
      <div className="rotulo mb-1 text-[9.5px]">{titulo}</div>
      <div className="space-y-[2px]">{children}</div>
    </div>
  );
}

function formatearValor(v: unknown): string {
  if (v === null || v === undefined) return "sin filtro";
  if (typeof v === "boolean") return v ? "sí" : "no";
  return String(v);
}

function colorAgente(agente: string): string {
  switch (agente) {
    case "AGENTE_FACTURACION":
      return "var(--color-arena)";
    case "AGENTE_COBRANZAS":
      return "var(--color-cobre)";
    case "AGENTE_BI":
      return "var(--color-musgo)";
    default:
      return "var(--color-tinta-3)";
  }
}
