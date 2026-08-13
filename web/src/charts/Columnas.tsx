import { useId, useState } from "react";
import { monto } from "../lib/format";
import { MARCA, barraVertical, corto, escala, techo, ticks } from "./ejes";

/**
 * Columnas para escalas ORDENADAS (tramos de aging, ventanas de proyección).
 *
 * La rampa ámbar se usa aquí a propósito y solo aquí: los tramos tienen orden
 * natural (1-30 → 90+), así que un tono más oscuro significa "más viejo" y
 * aporta información. Sobre categorías sin orden esto sería un anti-patrón,
 * porque gastaría el color en repetir lo que ya dice la altura.
 *
 * Cada columna puede llevar una parte destacada dentro (la provisión sobre el
 * saldo), separada por un hueco de 2px del color de la superficie, nunca por un
 * borde dibujado.
 */

export interface Columna {
  clave: string;
  rotulo: string;
  valor: number;
  /** Parte del valor que se resalta dentro de la columna. */
  parte?: number;
  /** Segunda línea del rótulo, p. ej. el número de facturas. */
  nota?: string;
}

interface Props {
  columnas: Columna[];
  /** Rótulo de la parte resaltada, para la leyenda. */
  etiquetaParte?: string;
  etiquetaTotal?: string;
  alto?: number;
  formato?: (v: number) => string;
}

const MARGEN = { arriba: 22, abajo: 34, izq: 44, der: 8 };

export function Columnas({
  columnas,
  etiquetaParte,
  etiquetaTotal,
  alto = 170,
  formato = monto,
}: Props) {
  const id = useId();
  const [encima, setEncima] = useState<number | null>(null);

  if (!columnas.length) return null;

  const ancho = 540;
  const maximo = techo(Math.max(...columnas.map((c) => c.valor)));
  const y = escala(0, maximo, alto - MARGEN.abajo, MARGEN.arriba);
  const paso = (ancho - MARGEN.izq - MARGEN.der) / columnas.length;
  const w = Math.min(MARCA.barraMax, paso * 0.5);

  const hayParte = columnas.some((c) => (c.parte ?? 0) > 0);

  return (
    <figure className="m-0">
      {/* Leyenda: obligatoria en cuanto hay dos series. */}
      {hayParte && (etiquetaParte || etiquetaTotal) && (
        <figcaption className="mb-1.5 flex items-center gap-3 text-[10px] text-[var(--color-tinta-3)]">
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-[7px] w-[7px]"
              style={{ background: "var(--color-rampa-2)", opacity: 0.34 }}
            />
            {etiquetaTotal}
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-[7px] w-[7px]"
              style={{ background: "var(--color-rampa-4)" }}
            />
            {etiquetaParte}
          </span>
        </figcaption>
      )}

      <svg
        viewBox={`0 0 ${ancho} ${alto}`}
        className="w-full"
        role="img"
        aria-labelledby={`${id}-t`}
        style={{ overflow: "visible" }}
      >
        <title id={`${id}-t`}>
          {columnas.map((c) => `${c.rotulo} ${formato(c.valor)}`).join(", ")}
        </title>

        {ticks(maximo, 3).map((t) => (
          <g key={t}>
            <line
              x1={MARGEN.izq}
              x2={ancho - MARGEN.der}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--color-rejilla)"
              strokeWidth={1}
            />
            <text
              x={MARGEN.izq - 7}
              y={y(t) + 3}
              textAnchor="end"
              className="cifra"
              fontSize={9}
              fontFamily="var(--font-mono)"
              fill="var(--color-tinta-3)"
            >
              {corto(t)}
            </text>
          </g>
        ))}

        {columnas.map((c, i) => {
          const x = MARGEN.izq + paso * i + (paso - w) / 2;
          const yTop = y(c.valor);
          const h = Math.max(2, y(0) - yTop);
          const activo = encima === i;

          const parte = c.parte ?? 0;
          const hParte = parte > 0 ? Math.max(2, y(0) - y(parte)) : 0;
          // Hueco de superficie entre el total y la parte, no un borde.
          const hResto = Math.max(0, h - hParte - (hParte > 0 ? MARCA.hueco : 0));

          return (
            <g
              key={c.clave}
              onMouseEnter={() => setEncima(i)}
              onMouseLeave={() => setEncima(null)}
            >
              <rect
                x={MARGEN.izq + paso * i}
                y={MARGEN.arriba}
                width={paso}
                height={alto - MARGEN.arriba - MARGEN.abajo}
                fill="transparent"
              />

              {/* Parte no provisionada: mismo tono, en lavado. */}
              <path
                d={barraVertical(x, yTop, w, hResto)}
                fill="var(--color-rampa-2)"
                opacity={activo ? 0.46 : 0.34}
              />
              {/* Parte destacada, pegada a la base. */}
              {hParte > 0 && (
                <rect
                  x={x}
                  y={y(0) - hParte}
                  width={w}
                  height={hParte}
                  fill="var(--color-rampa-4)"
                  opacity={activo ? 1 : 0.92}
                />
              )}

              <text
                x={x + w / 2}
                y={yTop - 6}
                textAnchor="middle"
                className="cifra"
                fontSize={9.5}
                fontFamily="var(--font-mono)"
                fill="var(--color-tinta-2)"
              >
                {corto(c.valor)}
              </text>
            </g>
          );
        })}

        <line
          x1={MARGEN.izq}
          x2={ancho - MARGEN.der}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--color-eje)"
          strokeWidth={1}
        />

        {columnas.map((c, i) => (
          <g key={`r-${c.clave}`}>
            <text
              x={MARGEN.izq + paso * i + paso / 2}
              y={alto - MARGEN.abajo + 13}
              textAnchor="middle"
              className="cifra"
              fontSize={9.5}
              fontFamily="var(--font-mono)"
              fill="var(--color-tinta-2)"
            >
              {c.rotulo}
            </text>
            {c.nota && (
              <text
                x={MARGEN.izq + paso * i + paso / 2}
                y={alto - MARGEN.abajo + 24}
                textAnchor="middle"
                fontSize={8.5}
                fill="var(--color-tinta-3)"
              >
                {c.nota}
              </text>
            )}
          </g>
        ))}
      </svg>
    </figure>
  );
}
