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

  // El modo manual deja de mandar en cuanto la corrida avanza.
  //
  // Antes, tocar una barra de la cascada o una flecha ponía `manual` y
  // congelaba el avance automático hasta el siguiente cierre. Si eso pasaba a
  // mitad de corrida el arco se quedaba plantado en la etapa que tocaste,
  // aunque los agentes siguieran desbloqueando etapas detrás. El resultado que
  // se ve es un héroe que no se mueve, o que aparece de golpe en C al final.
  //
  // La regla ahora es que explorar a mano no puede romper la reproducción: si
  // llega una etapa nueva del backend, manda el backend.
  const objetivoPrevio = useRef<Etapa>(objetivo);
  useEffect(() => {
    if (objetivo > objetivoPrevio.current) setManual(false);
    objetivoPrevio.current = objetivo;
  }, [objetivo]);

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

  // `Date.now()` y no 0, que era el bug del reveal.
  //
  // Con 0, el primer `transcurrido` valía "ahora menos 1970", muchísimo más que
  // la permanencia, así que la espera salía 0 y el arco saltaba de A a B en
  // cuanto llegaba el primer evento. La etapa A no se veía nunca: el héroe
  // parecía aparecer directamente en B. Arrancar el reloj aquí le da a A sus
  // 2.5 s, que es el punto de partida de toda la historia.
  const soltar = useCallback(() => {
    setManual(false);
    ultimoCambio.current = Date.now();
  }, []);

  // Reinicio al empezar una corrida nueva.
  useEffect(() => {
    if (objetivo === 0) {
      setEtapa(0);
      setManual(false);
      ultimoCambio.current = Date.now();
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
