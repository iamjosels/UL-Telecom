import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorDataset, cargarDatos, restaurarDemo } from "../lib/api";
import { fechaCorta, num } from "../lib/format";
import type { EstadoDatos, TablaId } from "../lib/types";

/**
 * Carga de un corte propio.
 *
 * El sistema arrancaba clavado a `data/`, con seis nombres de archivo fijos.
 * Aquí se sustituye el dataset entero y todo el dashboard se recalcula sobre
 * el nuevo.
 *
 * Dos decisiones que se ven en la interfaz:
 *
 *  - El emparejado archivo -> tabla lo propone el nombre pero lo decide el
 *    usuario. Un CSV renombrado tiene que seguir funcionando, así que cada
 *    ranura se puede reasignar a mano.
 *  - Los rechazos se pintan EN la ranura del archivo culpable, no como un
 *    aviso suelto arriba. El backend contesta qué archivo y qué columna falta;
 *    tirar ese detalle sería quedarse con "error al cargar".
 */

interface Props {
  estado?: EstadoDatos;
  corriendo: boolean;
  onCerrar: () => void;
  onCambiado: (estado: EstadoDatos) => void;
}

const TABLAS: { id: TablaId; nombre: string; pista: string }[] = [
  { id: "clientes", nombre: "Clientes", pista: "maestro y estado SUNAT" },
  { id: "planta_fija", nombre: "Planta fija", pista: "servicios y altas" },
  { id: "planta_movil", nombre: "Planta móvil", pista: "líneas y permanencia" },
  { id: "pagos", nombre: "Pagos", pista: "recaudo y factura afectada" },
  { id: "facturas", nombre: "Facturas", pista: "emisión, vencimiento e importes" },
  { id: "notas_credito", nombre: "Notas de crédito", pista: "rebajas sobre factura" },
];

/** Adivina a qué tabla pertenece un archivo por su nombre. Es una propuesta:
 *  la ranura se puede cambiar después, así que fallar aquí no bloquea nada. */
function adivinarTabla(nombre: string): TablaId | null {
  const n = nombre.toLowerCase();
  if (n.includes("nota")) return "notas_credito";
  if (n.includes("factura")) return "facturas";
  if (n.includes("pago")) return "pagos";
  if (n.includes("client")) return "clientes";
  if (n.includes("fija")) return "planta_fija";
  if (n.includes("movil") || n.includes("móvil")) return "planta_movil";
  return null;
}

export function PanelDatos({ estado, corriendo, onCerrar, onCambiado }: Props) {
  const [archivos, setArchivos] = useState<Partial<Record<TablaId, File>>>({});
  const [corte, setCorte] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [problemas, setProblemas] = useState<Record<string, string[]>>({});
  const [aviso, setAviso] = useState<string | undefined>();
  const [sobre, setSobre] = useState(false);
  const cerrarRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cerrarRef.current?.focus();
    const alPulsar = (e: KeyboardEvent) => e.key === "Escape" && onCerrar();
    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, [onCerrar]);

  const asignar = useCallback((lista: FileList | File[]) => {
    setAviso(undefined);
    setProblemas({});
    setArchivos((previos) => {
      const siguiente = { ...previos };
      const sueltos: string[] = [];
      for (const f of Array.from(lista)) {
        const tabla = adivinarTabla(f.name);
        if (tabla) siguiente[tabla] = f;
        else sueltos.push(f.name);
      }
      if (sueltos.length) {
        setAviso(
          `No supe a qué tabla va ${sueltos.join(", ")}. Asígnalo desde su fila.`,
        );
      }
      return siguiente;
    });
  }, []);

  const completos = TABLAS.every((t) => archivos[t.id]);

  async function enviar() {
    if (!completos || enviando) return;
    setEnviando(true);
    setProblemas({});
    setAviso(undefined);
    try {
      const nuevo = await cargarDatos(
        archivos as Record<TablaId, File>,
        corte.trim() || undefined,
      );
      onCambiado(nuevo);
      setArchivos({});
      setCorte("");
    } catch (e) {
      if (e instanceof ErrorDataset) {
        setProblemas(e.problemas);
        setAviso(e.message);
      } else {
        setAviso(e instanceof Error ? e.message : "No se pudo cargar el dataset.");
      }
    } finally {
      setEnviando(false);
    }
  }

  async function volverAlDemo() {
    setEnviando(true);
    setAviso(undefined);
    setProblemas({});
    try {
      onCambiado(await restaurarDemo());
      setArchivos({});
      setCorte("");
    } catch (e) {
      setAviso(e instanceof Error ? e.message : "No se pudo restaurar.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[var(--color-fondo)]/88 px-6 py-10"
      onMouseDown={(e) => e.target === e.currentTarget && onCerrar()}
    >
      <section
        role="dialog"
        aria-label="Datos del cierre"
        className="anim-entra w-full max-w-3xl border bg-[var(--color-superficie)]"
        style={{ borderColor: "var(--filete-fuerte)" }}
      >
        <header className="filete-b flex items-baseline gap-3 px-5 py-3">
          <h2 className="rotulo">Datos del cierre</h2>
          <span className="text-[10.5px] text-[var(--color-tinta-3)]">
            todo el tablero se recalcula sobre lo que cargues aquí
          </span>
          <button
            ref={cerrarRef}
            onClick={onCerrar}
            className="ml-auto text-[11px] text-[var(--color-tinta-3)] transition-colors hover:text-[var(--color-tinta)]"
          >
            cerrar
          </button>
        </header>

        {estado && <Cargado estado={estado} />}

        <div className="px-5 py-4">
          <div className="rotulo mb-2 text-[9.5px]">Cargar otro corte</div>

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setSobre(true);
            }}
            onDragLeave={() => setSobre(false)}
            onDrop={(e) => {
              e.preventDefault();
              setSobre(false);
              asignar(e.dataTransfer.files);
            }}
            className="border border-dashed px-4 py-5 text-center transition-colors duration-200"
            style={{
              borderColor: sobre ? "var(--color-rampa-2)" : "var(--filete-fuerte)",
              background: sobre ? "rgb(232 161 60 / .06)" : "transparent",
            }}
          >
            <p className="text-[12.5px] text-[var(--color-tinta-2)]">
              Arrastra aquí los seis CSV del corte
            </p>
            <p className="mt-1 text-[10.5px] text-[var(--color-tinta-3)]">
              se reparten solos por el nombre; si alguno cae mal, se cambia abajo
            </p>
          </div>

          <div className="mt-3 divide-y" style={{ borderColor: "var(--filete)" }}>
            {TABLAS.map((t) => (
              <Ranura
                key={t.id}
                tabla={t}
                archivo={archivos[t.id]}
                esperado={estado?.archivos[t.id]}
                problemas={problemas[estado?.archivos[t.id] ?? ""] ?? []}
                onElegir={(f) => setArchivos((p) => ({ ...p, [t.id]: f }))}
                onQuitar={() =>
                  setArchivos((p) => {
                    const s = { ...p };
                    delete s[t.id];
                    return s;
                  })
                }
              />
            ))}
          </div>

          {/* El corte es una decisión de negocio, no un dato: si no lo fijas,
              el cargador lo deriva de las fechas del propio dataset. */}
          <label className="mt-4 flex flex-wrap items-center gap-3">
            <span className="text-[11.5px] text-[var(--color-tinta-2)]">Fecha de corte</span>
            <input
              type="date"
              value={corte}
              onChange={(e) => setCorte(e.target.value)}
              className="border bg-transparent px-2 py-1 font-[family-name:var(--font-mono)] text-[11.5px] text-[var(--color-tinta)] focus:outline-none focus:border-[var(--color-rampa-2)]/50"
              style={{ borderColor: "var(--filete-fuerte)", colorScheme: "dark" }}
            />
            <span className="text-[10.5px] text-[var(--color-tinta-3)]">
              en blanco, se deriva de las fechas del dataset
            </span>
          </label>

          {aviso && (
            <p
              className="anim-entra mt-3 border-l-2 py-2 pl-3 text-[12px] leading-relaxed"
              style={{
                borderLeftColor: "var(--color-terracota)",
                background: "rgb(196 85 61 / .07)",
                color: "var(--color-tinta-2)",
              }}
            >
              {aviso}
            </p>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              onClick={enviar}
              disabled={!completos || enviando || corriendo}
              className="border border-[var(--color-ambar)]/45 bg-[var(--color-ambar)]/10 px-4 py-1.5 text-[12.5px] font-medium text-[var(--color-ambar)] transition-colors duration-200 hover:bg-[var(--color-ambar)]/18 disabled:cursor-not-allowed disabled:border-[var(--filete)] disabled:bg-transparent disabled:text-[var(--color-tinta-3)]"
            >
              {enviando ? "Validando…" : "Cargar y recalcular"}
            </button>

            {estado && !estado.es_demo && (
              <button
                onClick={volverAlDemo}
                disabled={enviando || corriendo}
                className="text-[11.5px] text-[var(--color-tinta-3)] transition-colors hover:text-[var(--color-tinta)] disabled:opacity-45"
              >
                volver al dataset de ejemplo
              </button>
            )}

            {corriendo && (
              <span className="text-[11px] text-[var(--color-cobre)]">
                hay un cierre en curso; espera a que termine
              </span>
            )}

            {!completos && !corriendo && (
              <span className="text-[11px] text-[var(--color-tinta-3)]">
                faltan {TABLAS.filter((t) => !archivos[t.id]).length} de 6
              </span>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

/** Qué hay cargado ahora mismo. */
function Cargado({ estado }: { estado: EstadoDatos }) {
  return (
    <div className="filete-b px-5 py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="rotulo text-[9.5px]">Cargado</span>
        <span className="text-[12.5px] text-[var(--color-tinta)]">
          {estado.es_demo ? "Dataset de ejemplo del reto" : "Corte cargado por ti"}
        </span>
        <span className="font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-tinta-2)]">
          corte {fechaCorta(estado.fecha_corte)}
        </span>
        <span className="text-[10.5px] text-[var(--color-tinta-3)]">
          {estado.corte_procedencia}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1">
        {TABLAS.map((t) => (
          <span key={t.id} className="text-[10.5px] text-[var(--color-tinta-3)]">
            {t.nombre}{" "}
            <span className="cifra font-[family-name:var(--font-mono)] text-[var(--color-tinta-2)]">
              {num(estado.filas[t.id] ?? 0)}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

function Ranura({
  tabla,
  archivo,
  esperado,
  problemas,
  onElegir,
  onQuitar,
}: {
  tabla: { id: TablaId; nombre: string; pista: string };
  archivo?: File;
  esperado?: string;
  problemas: string[];
  onElegir: (f: File) => void;
  onQuitar: () => void;
}) {
  const malo = problemas.length > 0;

  return (
    <div className="py-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          className="size-[5px] shrink-0"
          style={{
            background: malo
              ? "var(--color-terracota)"
              : archivo
                ? "var(--color-musgo)"
                : "var(--color-superficie-3)",
          }}
        />
        <span className="min-w-[7.5rem] text-[12px] text-[var(--color-tinta-2)]">
          {tabla.nombre}
        </span>

        {archivo ? (
          <span className="min-w-0 flex-1 truncate font-[family-name:var(--font-mono)] text-[10.5px] text-[var(--color-tinta)]">
            {archivo.name}
          </span>
        ) : (
          <span className="min-w-0 flex-1 truncate text-[10.5px] text-[var(--color-tinta-3)]">
            {tabla.pista}
            {esperado && ` · se espera ${esperado}`}
          </span>
        )}

        <label className="shrink-0 cursor-pointer text-[10.5px] text-[var(--color-tinta-3)] transition-colors hover:text-[var(--color-tinta)]">
          {archivo ? "cambiar" : "elegir"}
          <input
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onElegir(f);
              e.target.value = "";
            }}
          />
        </label>
        {archivo && (
          <button
            onClick={onQuitar}
            className="shrink-0 text-[10.5px] text-[var(--color-tinta-3)] transition-colors hover:text-[var(--color-terracota)]"
          >
            quitar
          </button>
        )}
      </div>

      {malo && (
        <ul className="anim-entra mt-1 pl-[13px]">
          {problemas.map((p) => (
            <li key={p} className="text-[10.5px] text-[var(--color-terracota)]">
              {p}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
