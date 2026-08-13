import { useEffect } from "react";

/**
 * Las cuatro vistas.
 *
 * En una presentación solo se ve una pantalla, y antes esto era una columna con
 * scroll de cinco secciones apiladas. Cada vista se diseña para llenar la
 * pantalla y leerse de lejos; se cambia con las teclas 1 a 4 o con las pestañas.
 */

export const VISTAS = [
  { id: "cierre", tecla: "1", rotulo: "Cierre" },
  { id: "hallazgos", tecla: "2", rotulo: "Hallazgos" },
  { id: "traza", tecla: "3", rotulo: "Trazabilidad" },
  { id: "consulta", tecla: "4", rotulo: "Consulta" },
] as const;

export type VistaId = (typeof VISTAS)[number]["id"];

interface Props {
  activa: VistaId;
  onCambiar: (v: VistaId) => void;
  /** Marca discreta por vista, p. ej. el número de líneas de traza. */
  contadores?: Partial<Record<VistaId, string>>;
}

export function Pestanas({ activa, onCambiar, contadores }: Props) {
  useEffect(() => {
    const alPulsar = (e: KeyboardEvent) => {
      const foco = document.activeElement;
      if (foco instanceof HTMLInputElement || foco instanceof HTMLTextAreaElement) return;
      const v = VISTAS.find((x) => x.tecla === e.key);
      if (!v) return;
      e.preventDefault();
      onCambiar(v.id);
    };
    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, [onCambiar]);

  return (
    <nav className="flex items-stretch" role="tablist">
      {VISTAS.map((v) => {
        const sel = v.id === activa;
        return (
          <button
            key={v.id}
            role="tab"
            aria-selected={sel}
            onClick={() => onCambiar(v.id)}
            className="group relative flex items-baseline gap-1.5 px-3.5 py-2 text-[12px] transition-colors duration-200"
            style={{ color: sel ? "var(--color-tinta)" : "var(--color-tinta-3)" }}
          >
            <span className="font-[family-name:var(--font-mono)] text-[9.5px] opacity-70">
              {v.tecla}
            </span>
            {v.rotulo}
            {contadores?.[v.id] && (
              <span className="cifra font-[family-name:var(--font-mono)] text-[9.5px] text-[var(--color-tinta-3)]">
                {contadores[v.id]}
              </span>
            )}
            <span
              className="absolute inset-x-2.5 bottom-0 h-[2px] transition-colors duration-200"
              style={{ background: sel ? "var(--color-rampa-2)" : "transparent" }}
            />
          </button>
        );
      })}
    </nav>
  );
}
