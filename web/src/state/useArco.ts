/**
 * Máquina del arco A -> B -> C.
 *
 * El backend en modo determinista termina en poco más de un segundo, así que
 * si el arco siguiera los eventos al milisegundo los tres estados pasarían en
 * un parpadeo y se perdería justo lo que hay que contar. Cada etapa se sostiene
 * un mínimo antes de ceder a la siguiente.
 *
 * Los datos y el orden son del backend; aquí solo se decide cuándo revelarlos.
 *
 * Con las flechas del teclado se puede recorrer el arco a mano una vez que la
 * corrida terminó, para explicar cada salto sin prisa.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Etapa } from "./runReducer";

export const PERMANENCIA_MS = 2500;

export interface UsarArco {
  etapa: Etapa;
  manual: boolean;
  ir: (e: Etapa) => void;
  siguiente: () => void;
  anterior: () => void;
  soltar: () => void;
}

export function useArco(objetivo: Etapa, habilitado: boolean): UsarArco {
  const [etapa, setEtapa] = useState<Etapa>(0);
  const [manual, setManual] = useState(false);
  const ultimoCambio = useRef<number>(0);
  const temporizador = useRef<number | undefined>(undefined);

  // Avance automático hacia el objetivo, respetando la permanencia mínima.
  useEffect(() => {
    if (manual || etapa >= objetivo) return;

    const transcurrido = Date.now() - ultimoCambio.current;
    const espera = Math.max(0, PERMANENCIA_MS - transcurrido);

    temporizador.current = window.setTimeout(() => {
      ultimoCambio.current = Date.now();
      setEtapa((actual) => (actual < objetivo ? ((actual + 1) as Etapa) : actual));
    }, espera);

    return () => window.clearTimeout(temporizador.current);
  }, [objetivo, etapa, manual]);

  const ir = useCallback((e: Etapa) => {
    window.clearTimeout(temporizador.current);
    setManual(true);
    ultimoCambio.current = Date.now();
    setEtapa(e);
  }, []);

  const siguiente = useCallback(() => {
    setManual(true);
    setEtapa((e) => (e < 2 ? ((e + 1) as Etapa) : e));
  }, []);

  const anterior = useCallback(() => {
    setManual(true);
    setEtapa((e) => (e > 0 ? ((e - 1) as Etapa) : e));
  }, []);

  const soltar = useCallback(() => {
    setManual(false);
    ultimoCambio.current = 0;
  }, []);

  // Reinicio al empezar una corrida nueva.
  useEffect(() => {
    if (objetivo === 0) {
      setEtapa(0);
      setManual(false);
      ultimoCambio.current = 0;
    }
  }, [objetivo]);

  // Flechas para recorrer el arco durante la presentación.
  useEffect(() => {
    if (!habilitado) return;

    const alPulsar = (e: KeyboardEvent) => {
      const activo = document.activeElement;
      if (activo instanceof HTMLInputElement || activo instanceof HTMLTextAreaElement) return;

      if (e.key === "ArrowRight") {
        e.preventDefault();
        siguiente();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        anterior();
      }
    };

    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, [habilitado, siguiente, anterior]);

  return { etapa, manual, ir, siguiente, anterior, soltar };
}
