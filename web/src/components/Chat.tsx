import { useEffect, useRef, useState } from "react";
import { postChat } from "../lib/api";
import { TITULOS, destacadosDe } from "../lib/destacados";
import { hora, num } from "../lib/format";
import type { RespuestaChat } from "../lib/types";

/**
 * Consulta en lenguaje natural.
 *
 * Lo que hay que dejar ver: el modelo elige la herramienta y redacta, pero no
 * calcula. Cuando `redaccion_descartada` llega en true, el guardarraíl rechazó
 * la redacción por citar una cifra que ninguna herramienta produjo, y la
 * interfaz lo dice en vez de disimularlo.
 *
 * La respuesta NO se pinta como un párrafo suelto. El texto que devuelve el
 * backend está escrito para que lo lea un modelo: empieza por un titular en
 * mayúsculas y mete todas las cifras en prosa. Aquí se separa el titular, se
 * suben las métricas a la cabecera y el cuerpo se limita a un ancho legible.
 */

/** Groq limita por tokens por minuto y la redacción puede tardar. Pasado este
 *  tiempo se repite sin LLM: misma cifra, en centésimas de segundo. */
const ESPERA_LLM_MS = 15000;

const SUGERIDAS = [
  { texto: "¿Cuánto tenemos por cobrar a más de 90 días?", pista: "cartera por tramo" },
  { texto: "¿Qué cuentas activas no se están facturando?", pista: "fuga de ingresos" },
  { texto: "¿A quién le cobro primero?", pista: "mesa de recupero" },
  {
    texto: "Proyéctame la cartera vencida a diciembre con 10% de mora",
    pista: "aquí el guardarraíl no inventa",
    trampa: true,
  },
];

interface Turno {
  id: number;
  pregunta: string;
  respuesta?: RespuestaChat;
  error?: string;
  sinLlm?: boolean;
}

export function Chat({ modoSeguro }: { modoSeguro: boolean }) {
  const [turnos, setTurnos] = useState<Turno[]>([]);
  const [texto, setTexto] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [verSugeridas, setVerSugeridas] = useState(false);
  const contador = useRef(0);
  const fin = useRef<HTMLDivElement>(null);
  const campo = useRef<HTMLInputElement>(null);

  useEffect(() => {
    campo.current?.focus();
  }, []);

  async function preguntar(mensaje: string) {
    const limpio = mensaje.trim();
    if (!limpio || ocupado) return;

    const id = ++contador.current;
    setTurnos((t) => [...t, { id, pregunta: limpio }]);
    setTexto("");
    setVerSugeridas(false);
    setOcupado(true);
    requestAnimationFrame(() => fin.current?.scrollIntoView({ behavior: "smooth" }));

    const actualizar = (cambio: Partial<Turno>) =>
      setTurnos((t) => t.map((x) => (x.id === id ? { ...x, ...cambio } : x)));

    try {
      if (!modoSeguro) {
        const control = new AbortController();
        const reloj = window.setTimeout(() => control.abort(), ESPERA_LLM_MS);
        try {
          actualizar({ respuesta: await postChat({ mensaje: limpio }, control.signal) });
          return;
        } catch {
          /* abajo se repite sin LLM */
        } finally {
          window.clearTimeout(reloj);
        }
      }
      const respuesta = await postChat({ mensaje: limpio, usar_llm: false });
      actualizar({ respuesta, sinLlm: !modoSeguro });
    } catch (e) {
      actualizar({ error: e instanceof Error ? e.message : "No se pudo consultar." });
    } finally {
      setOcupado(false);
      requestAnimationFrame(() => fin.current?.scrollIntoView({ behavior: "smooth" }));
    }
  }

  const vacio = turnos.length === 0;

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="filete-b flex items-baseline gap-3 px-6 py-2.5">
        <h2 className="rotulo">Consulta</h2>
        <span className="text-[10.5px] text-[var(--color-tinta-3)]">
          el modelo elige la herramienta y redacta; las cifras las calcula Python
        </span>
        {!vacio && (
          <button
            onClick={() => setVerSugeridas((v) => !v)}
            className="ml-auto text-[10.5px] text-[var(--color-tinta-3)] transition-colors hover:text-[var(--color-tinta)]"
          >
            {verSugeridas ? "ocultar sugeridas" : "ver sugeridas"}
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6">
        {vacio ? (
          <div className="mx-auto flex h-full max-w-4xl flex-col justify-center py-6">
            <h3 className="font-[family-name:var(--font-display)] text-[clamp(1.35rem,2.4vw,1.9rem)] font-medium leading-tight tracking-[-0.02em] text-[var(--color-tinta)]">
              ¿Qué quieres saber de la cartera?
            </h3>
            <p className="mt-2 max-w-[54ch] text-[12.5px] leading-relaxed text-[var(--color-tinta-2)]">
              Escríbelo como se lo dirías a alguien del equipo. El modelo decide qué
              herramienta usar; el número lo calcula Python y queda registrado.
            </p>

            <div className="rotulo mb-2 mt-7 text-[9.5px]">Prueba con una de estas</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {SUGERIDAS.map((s) => (
                <Sugerida key={s.texto} {...s} onClick={() => preguntar(s.texto)} />
              ))}
            </div>
            {/* Dirige la atención al guardarraíl sin que haga falta narrarlo. */}
            <p className="mt-3 text-[10.5px] text-[var(--color-tinta-3)]">
              La cuarta pide algo que los datos no soportan. Fíjate en qué contesta.
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-4xl py-4">
            {verSugeridas && (
              <div className="anim-entra mb-4 grid gap-2 sm:grid-cols-2">
                {SUGERIDAS.map((s) => (
                  <Sugerida key={s.texto} {...s} onClick={() => preguntar(s.texto)} />
                ))}
              </div>
            )}
            <div className="space-y-5">
              {turnos.map((t) => (
                <TurnoChat key={t.id} turno={t} />
              ))}
            </div>
            <div ref={fin} className="h-2" />
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          preguntar(texto);
        }}
        className="filete-t px-6 py-3"
      >
        <div
          className="mx-auto flex max-w-4xl items-center gap-3 border px-3.5 py-2.5 transition-colors duration-200 focus-within:border-[var(--color-rampa-2)]/50"
          style={{ borderColor: "var(--filete-fuerte)", background: "var(--color-superficie)" }}
        >
          <span className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-tinta-3)]">
            &gt;
          </span>
          <input
            ref={campo}
            type="text"
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            disabled={ocupado}
            placeholder={ocupado ? "consultando…" : "Pregunta sobre la cartera"}
            className="min-w-0 flex-1 bg-transparent text-[13px] text-[var(--color-tinta)] placeholder:text-[var(--color-tinta-3)] focus:outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={ocupado || !texto.trim()}
            className="shrink-0 border border-[var(--color-rampa-2)]/40 px-2.5 py-1 text-[11px] text-[var(--color-rampa-2)] transition-colors duration-200 hover:bg-[var(--color-rampa-2)]/12 disabled:border-[var(--filete)] disabled:text-[var(--color-tinta-3)]"
          >
            Preguntar
          </button>
        </div>
      </form>
    </section>
  );
}

function Sugerida({
  texto,
  pista,
  trampa,
  onClick,
}: {
  texto: string;
  pista: string;
  trampa?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="group border px-3.5 py-2.5 text-left transition-colors duration-200 hover:bg-[var(--color-superficie-2)]"
      style={{ borderColor: trampa ? "rgb(217 122 52 / .32)" : "var(--filete)" }}
    >
      <div className="text-[12.5px] text-[var(--color-tinta-2)] transition-colors group-hover:text-[var(--color-tinta)]">
        {texto}
      </div>
      <div
        className="mt-0.5 text-[10px]"
        style={{ color: trampa ? "var(--color-cobre)" : "var(--color-tinta-3)" }}
      >
        {pista}
      </div>
    </button>
  );
}

// --------------------------------------------------------------------------

function TurnoChat({ turno }: { turno: Turno }) {
  const [verTrazas, setVerTrazas] = useState(false);
  const r = turno.respuesta;
  const cifras = r ? destacadosDe(r.tool, r.metricas) : [];
  const separado = separarTitular(r?.respuesta ?? "");
  // Si redactó el LLM no hay titular dentro del texto: se repone el de la
  // herramienta para que todas las respuestas tengan la misma forma.
  const titulo = separado.titulo || (r ? (TITULOS[r.tool] ?? "") : "");
  const cuerpo = separado.cuerpo;

  return (
    <div className="anim-entra">
      <p className="flex items-baseline gap-2 text-[13px] text-[var(--color-tinta)]">
        <span className="shrink-0 font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-tinta-3)]">
          &gt;
        </span>
        {turno.pregunta}
      </p>

      {turno.error && (
        <p className="mt-2 border-l-2 border-[var(--color-terracota)] pl-3 text-[12.5px] text-[var(--color-terracota)]">
          {turno.error}
        </p>
      )}

      {!r && !turno.error && (
        <p className="anim-late mt-2 pl-4 text-[12px] text-[var(--color-tinta-3)]">
          buscando en los datos…
        </p>
      )}

      {r && (
        <div className="mt-2.5 border-l-2 border-[var(--color-rampa-4)] pl-4">
          {titulo && (
            <h3 className="text-[11px] font-medium uppercase tracking-[0.1em] text-[var(--color-rampa-2)]">
              {titulo}
            </h3>
          )}

          {/* Las cifras suben a la cabecera en vez de quedarse dentro del párrafo. */}
          {cifras.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-x-8 gap-y-2">
              {cifras.map((c) => (
                <div key={c.rotulo}>
                  <div className="text-[8.5px] uppercase tracking-[0.07em] text-[var(--color-tinta-3)]">
                    {c.rotulo}
                  </div>
                  <div className="font-[family-name:var(--font-display)] text-[19px] font-medium leading-tight text-[var(--color-tinta)]">
                    {c.texto}
                    {c.unidad && (
                      <span className="ml-1 text-[10px] font-normal text-[var(--color-tinta-3)]">
                        {c.unidad}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Ancho acotado: a 1900 px una línea de texto son 200 caracteres y
              nadie la lee. Lo cómodo son 65-75. */}
          <p className="mt-2.5 max-w-[68ch] text-[12.5px] leading-relaxed text-[var(--color-tinta-2)]">
            {cuerpo}
          </p>

          {/* El argumento entero del proyecto cabe en estos bloques, así que no
              pueden ir al mismo peso que "15 filas". */}
          {r.redaccion_descartada && <Guardarrail tipo="cifra" />}
          {r.supuesto_ignorado && (
            <Guardarrail tipo="supuesto" supuesto={r.supuesto_ignorado} />
          )}

          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <Procedencia r={r} sinLlm={turno.sinLlm} />
            {r.trazas.length > 0 && (
              <button
                onClick={() => setVerTrazas((v) => !v)}
                className="text-[10px] text-[var(--color-tinta-3)] transition-colors hover:text-[var(--color-tinta)]"
              >
                {verTrazas ? "ocultar cálculo" : "cómo se calculó"}
              </button>
            )}
            <span className="ml-auto font-[family-name:var(--font-mono)] text-[9.5px] text-[var(--color-tinta-3)]">
              {hora(r.ts)}
            </span>
          </div>

          {verTrazas && (
            <div className="anim-entra mt-2 border-l border-[var(--filete-fuerte)] pl-3">
              {r.trazas.map((t, i) => (
                <div
                  key={i}
                  className="flex gap-2 font-[family-name:var(--font-mono)] text-[10.5px] leading-relaxed text-[var(--color-tinta-2)]"
                >
                  <span className="shrink-0 text-[var(--color-tinta-3)]">{i + 1}</span>
                  <span className="min-w-0 break-words">{t}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Los dos guardarraíles, cuando saltan.
 *
 * `redaccion_descartada`: el LLM citó una cifra que ninguna herramienta
 * produjo, el backend tiró su redacción entera y devolvió el resultado
 * determinista.
 *
 * `supuesto_ignorado`: la pregunta traía un supuesto ("10% de mora") que
 * ninguna herramienta recibe. Este hace falta porque el primero valida cifras,
 * no premisas, y por esa rendija cabe una respuesta con tres números correctos
 * atribuidos a un escenario que nadie calculó.
 */
function Guardarrail({ tipo, supuesto }: { tipo: "cifra" | "supuesto"; supuesto?: string }) {
  return (
    <div
      className="anim-entra mt-3 max-w-[68ch] border-l-2 px-3 py-2"
      style={{
        borderLeftColor: "var(--color-cobre)",
        background: "rgb(217 122 52 / .07)",
      }}
    >
      <div className="rotulo text-[9.5px] text-[var(--color-cobre)]">
        {tipo === "cifra" ? "Redacción descartada" : "Supuesto no aplicado"}
      </div>
      <p className="mt-1 text-[12px] leading-relaxed text-[var(--color-tinta-2)]">
        {tipo === "cifra" ? (
          <>
            El modelo citó una cifra que ninguna herramienta calculó. Se descartó su
            redacción entera; lo que se lee arriba es el resultado de la herramienta,
            sin retocar.
          </>
        ) : (
          <>
            La pregunta pide{" "}
            <span className="text-[var(--color-tinta)]">«{supuesto}»</span> y ninguna
            herramienta recibe ese parámetro. Aquí el modelo no redacta: arriba está el
            resultado de la herramienta tal cual, sin ese supuesto aplicado. Simularlo
            pediría un modelo de escenarios que este sistema no tiene.
          </>
        )}
      </p>
    </div>
  );
}

function Procedencia({ r, sinLlm }: { r: RespuestaChat; sinLlm?: boolean }) {
  const chip = (texto: string, color: string, borde?: string) => (
    <span
      className="border px-1.5 py-px font-[family-name:var(--font-mono)] text-[9.5px]"
      style={{ color, borderColor: borde ?? "var(--filete)" }}
    >
      {texto}
    </span>
  );

  return (
    <span className="flex flex-wrap items-center gap-2">
      {chip(r.tool, "var(--color-tinta-3)")}
      {r.filas_detalle > 0 &&
        chip(`${num(r.filas_detalle)} filas`, "var(--color-tinta-3)")}
      {/* El caso de redacción descartada ya lo cuenta su propio bloque. */}
      {r.redaccion_descartada ? (
        <span className="text-[10px] text-[var(--color-tinta-3)]">
          cifra directa de la herramienta
        </span>
      ) : r.redactado_por_llm ? (
        <span className="text-[10px] text-[var(--color-tinta-3)]">
          redactado sobre cifras verificadas
        </span>
      ) : (
        <span className="text-[10px] text-[var(--color-tinta-3)]">
          {sinLlm ? "el LLM tardó, respuesta directa" : "cifra directa de la herramienta"}
        </span>
      )}
    </span>
  );
}

/**
 * Separa el titular en mayúsculas del cuerpo.
 *
 * Los resúmenes del backend empiezan siempre igual: "FUGA DE INGRESOS. 422 de
 * 1,571 cuentas…", "MESA DE ACELERACIÓN DE RECUPERO al 2026-08-12. 284…".
 * Ese titular es un rótulo, no una frase, y como parte del párrafo estorba.
 */
function separarTitular(texto: string): { titulo: string; cuerpo: string } {
  const m = texto.match(/^([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ0-9\s↔/·-]{6,}?)(?=\s[a-z(—·]|[.,])/);
  if (!m) return { titulo: "", cuerpo: texto };
  // El separador se limpia de los dos lados. El punto medio está DENTRO de la
  // clase de caracteres porque hay titulares que lo llevan de verdad
  // ("CONCILIACIÓN PAGO ↔ FACTURA"), así que puede quedar colgando al final.
  const titulo = (m[1] ?? "").trim().replace(/[.,·\-/]+$/, "").trim();
  const cuerpo = texto.slice(m[0].length).replace(/^[.,\s—·]+/, "");
  return titulo.split(/\s+/).length >= 2 ? { titulo, cuerpo } : { titulo: "", cuerpo: texto };
}
