import { fechaCorta } from "../lib/format";
import type { Modo } from "../lib/types";

interface Props {
  fechaCorte?: string;
  conectado: boolean;
  llmConfigurado: boolean;
  corriendo: boolean;
  modo?: Modo;
  modoSeguro: boolean;
  /** false cuando el corte cargado no es el dataset de ejemplo. */
  datosDemo?: boolean;
  /** Ya se pidió parar y aún no llegó el evento de cancelación. */
  deteniendo: boolean;
  /** El último cierre paró porque se pidió, no porque terminara. */
  detenido?: boolean;
  onModoSeguro: (v: boolean) => void;
  onCerrarCiclo: (sinLlm?: boolean) => void;
  onDetener: () => void;
  onAbrirDatos: () => void;
}

// "hibrido" era "agentes + relleno": nombre interno del mecanismo de reserva,
// no algo que le diga nada a quien mira. Para el usuario el cierre corrió con
// agentes, y si alguno no llegó, el aviso ya lo cuenta aparte.
const TEXTO_MODO: Record<Modo, string> = {
  deterministico: "sin LLM",
  crew: "agentes",
  hibrido: "agentes",
};

export function Masthead({
  fechaCorte,
  conectado,
  llmConfigurado,
  corriendo,
  modo,
  modoSeguro,
  datosDemo = true,
  deteniendo,
  detenido = false,
  onModoSeguro,
  onCerrarCiclo,
  onDetener,
  onAbrirDatos,
}: Props) {
  return (
    <header className="filete-b flex flex-wrap items-center gap-x-6 gap-y-3 px-6 py-3">
      <div className="flex items-baseline gap-3">
        <span className="font-[family-name:var(--font-display)] text-[15px] font-bold tracking-[-0.02em] text-[var(--color-tinta)]">
          SON<span className="text-[var(--color-ambar)]">·</span>IA
        </span>
        <span className="rotulo hidden sm:inline">Ciclo del ingreso B2B</span>
        {/* La pista de teclado del guión de pitch vivía aquí. Es una nota para
            quien presenta, no información de producto: en pantalla delata el
            andamiaje. La tecla G sigue funcionando igual, sin anunciarse. */}
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-2">
        <Estado
          conectado={conectado}
          corriendo={corriendo}
          detenido={detenido}
          modo={modo}
          llm={llmConfigurado}
        />

        {/* El corte es también la puerta a los datos: es lo que identifica al
            dataset cargado, así que es donde se va a buscar para cambiarlo. */}
        <button
          onClick={onAbrirDatos}
          title="Ver o cambiar el dataset del cierre"
          className="group flex items-baseline gap-2 border border-transparent px-1.5 py-0.5 transition-colors duration-200 hover:border-[var(--filete-fuerte)]"
        >
          {fechaCorte && (
            <span className="font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-tinta-3)] transition-colors group-hover:text-[var(--color-tinta-2)]">
              corte {fechaCorta(fechaCorte)}
            </span>
          )}
          <span
            className="text-[10.5px]"
            style={{ color: datosDemo ? "var(--color-tinta-3)" : "var(--color-cobre)" }}
          >
            {datosDemo ? "datos" : "datos propios"}
          </span>
        </button>

        <Interruptor
          activo={modoSeguro}
          disabled={corriendo}
          onChange={onModoSeguro}
          etiqueta="Modo seguro"
          titulo="Corre el cierre sin LLM. Mismas cifras, un segundo, sin depender de la red."
        />

        {/* Mientras corre, el par se lee como un solo control: qué está
            pasando a la izquierda y cómo pararlo a la derecha. */}
        <div className="flex items-center gap-2">
          <button
            // Envuelto a propósito: `onClick={onCerrarCiclo}` le pasaría el
            // MouseEvent como primer argumento, y ese objeto es truthy, así que
            // el cierre se forzaría siempre a determinista sin que se note.
            onClick={() => onCerrarCiclo()}
            disabled={corriendo || !conectado}
            className="group relative overflow-hidden border border-[var(--color-ambar)]/45 bg-[var(--color-ambar)]/10 px-4 py-1.5 text-[13px] font-medium text-[var(--color-ambar)] transition-colors duration-200 hover:bg-[var(--color-ambar)]/18 disabled:cursor-not-allowed disabled:border-[var(--filete)] disabled:bg-transparent disabled:text-[var(--color-tinta-3)]"
          >
            {corriendo ? "Cerrando…" : "Cerrar ciclo del mes"}
          </button>

          {corriendo && (
            <button
              onClick={onDetener}
              disabled={deteniendo}
              title="El cierre para en el siguiente paso o llamada al modelo, no al instante."
              className="anim-entra border px-3 py-1.5 text-[13px] transition-colors duration-200 disabled:cursor-not-allowed"
              style={{
                borderColor: deteniendo ? "var(--filete)" : "rgb(196 85 61 / .45)",
                color: deteniendo ? "var(--color-tinta-3)" : "var(--color-terracota)",
              }}
            >
              {deteniendo ? "Deteniendo…" : "Detener"}
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

function Estado({
  conectado,
  corriendo,
  detenido,
  modo,
  llm,
}: {
  conectado: boolean;
  corriendo: boolean;
  detenido: boolean;
  modo?: Modo;
  llm: boolean;
}) {
  // Detenido va en arena, no en terracota: no es un fallo. Pero tampoco puede
  // decir "listo", que se leería como que el cierre cuadró.
  const color = !conectado
    ? "var(--color-terracota)"
    : corriendo
      ? "var(--color-ambar)"
      : detenido
        ? "var(--color-arena)"
        : "var(--color-musgo)";

  const texto = !conectado
    ? "backend caído"
    : corriendo
      ? modo
        ? `en curso · ${TEXTO_MODO[modo]}`
        : "en curso"
      : detenido
        ? "detenido · incompleto"
        : modo
          ? `listo · ${TEXTO_MODO[modo]}`
          : llm
            ? "listo"
            : "listo · sin LLM";

  return (
    <span className="flex items-center gap-2">
      <span
        className={`size-[6px] rounded-full ${corriendo ? "anim-late" : ""}`}
        style={{ background: color }}
      />
      <span className="text-[12px] text-[var(--color-tinta-2)]">{texto}</span>
    </span>
  );
}

function Interruptor({
  activo,
  disabled,
  onChange,
  etiqueta,
  titulo,
}: {
  activo: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
  etiqueta: string;
  titulo: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={activo}
      title={titulo}
      disabled={disabled}
      onClick={() => onChange(!activo)}
      className="flex items-center gap-2 text-[12px] text-[var(--color-tinta-2)] transition-colors hover:text-[var(--color-tinta)] disabled:cursor-not-allowed disabled:opacity-45"
    >
      <span
        className="relative h-[14px] w-[26px] border transition-colors duration-200"
        style={{
          borderColor: activo ? "var(--color-ambar)" : "var(--filete-fuerte)",
          background: activo ? "rgb(232 161 60 / .16)" : "transparent",
        }}
      >
        <span
          className="absolute top-[2px] size-[8px] transition-all duration-200"
          style={{
            left: activo ? "14px" : "2px",
            background: activo ? "var(--color-ambar)" : "var(--color-tinta-3)",
          }}
        />
      </span>
      {etiqueta}
    </button>
  );
}
