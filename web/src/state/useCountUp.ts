/**
 * Interpola el número héroe entre dos valores.
 *
 * Salida suavizada (easeOutExpo): arranca rápido y frena al final, que es lo
 * que hace que un contador se lea como una cifra que se asienta y no como un
 * marcador de gasolinera.
 */

import { useEffect, useRef, useState } from "react";

const DURACION_MS = 900;

const easeOutExpo = (t: number): number => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t));

function prefiereQuieto(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

export function useCountUp(objetivo: number, duracion = DURACION_MS): number {
  const [valor, setValor] = useState(objetivo);
  const desde = useRef(objetivo);
  const frame = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!Number.isFinite(objetivo)) return;

    if (prefiereQuieto()) {
      desde.current = objetivo;
      setValor(objetivo);
      return;
    }

    const origen = desde.current;
    if (origen === objetivo) return;

    const inicio = performance.now();

    const paso = (ahora: number) => {
      const t = Math.min(1, (ahora - inicio) / duracion);
      const v = origen + (objetivo - origen) * easeOutExpo(t);
      setValor(v);
      if (t < 1) {
        frame.current = requestAnimationFrame(paso);
      } else {
        desde.current = objetivo;
        setValor(objetivo);
      }
    };

    frame.current = requestAnimationFrame(paso);
    return () => {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current);
      desde.current = objetivo;
    };
  }, [objetivo, duracion]);

  return valor;
}
