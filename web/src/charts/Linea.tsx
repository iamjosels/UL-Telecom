import { useId, useState } from "react";
import { MARCA, escala, ruta } from "./ejes";

/**
 * Curva empírica de cobro.
 *
 * Una sola serie, así que no lleva leyenda: el título ya dice qué se pinta.
 * Etiqueta directa solo en los dos puntos que importan (el KPI de 30 días y el
 * final), nunca una cifra sobre cada punto.
 *
 * Eje X lineal en días de verdad, aunque los puntos estén en 0/7/15/30/60/90/180
 * y se agolpen a la izquierda. Repartirlos a distancia igual haría creer que el
 * cobro avanza a ritmo constante, y la historia es justo la contraria: casi todo
 * entra en el primer mes y después la curva se aplana.
 */

export interface PuntoLinea {
  x: number;
  y: number;
}

interface Props {
  puntos: PuntoLinea[];
  /** Valores de x que llevan etiqueta directa. */
  destacar?: number[];
  formatoY?: (v: number) => string;
  formatoX?: (v: number) => string;
  alto?: number;
  maxY?: number;
}

const MARGEN = { arriba: 18, abajo: 26, izq: 38, der: 40 };

export function Linea({
  puntos,
  destacar = [],
  formatoY = (v) => `${v.toFixed(0)}%`,
  formatoX = (v) => `${v}d`,
  alto = 150,
  maxY = 100,
}: Props) {
  const id = useId();
  const [encima, setEncima] = useState<number | null>(null);

  if (puntos.length < 2) return null;

  const ancho = 540;
  const maxX = Math.max(...puntos.map((p) => p.x));
  const x = escala(0, maxX, MARGEN.izq, ancho - MARGEN.der);
  const y = escala(0, maxY, alto - MARGEN.abajo, MARGEN.arriba);

  const coords = puntos.map((p) => ({ x: x(p.x), y: y(p.y), dato: p }));

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${ancho} ${alto}`}
        className="w-full"
        role="img"
        aria-labelledby={`${id}-t`}
        style={{ overflow: "visible" }}
      >
        <title id={`${id}-t`}>
          Curva de cobro: {puntos.map((p) => `${formatoX(p.x)} ${formatoY(p.y)}`).join(", ")}
        </title>

        {[0, 50, 100].map((t) => (
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
              {formatoY(t)}
            </text>
          </g>
        ))}

        {/* Sin relleno de área: esta curva sube al 99% y se queda plana, así que
            el área bajo la línea ocupa casi todo el panel y se lee como un
            bloque, no como un lavado. La línea sola cuenta lo mismo. */}
        <path
          d={ruta(coords)}
          fill="none"
          stroke="var(--color-rampa-2)"
          strokeWidth={MARCA.linea}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {coords.map((c, i) => {
          const marcado = destacar.includes(c.dato.x);
          const activo = encima === i;
          if (!marcado && !activo && i !== coords.length - 1) {
            return (
              <circle
                key={i}
                cx={c.x}
                cy={c.y}
                r={2.5}
                fill="var(--color-rampa-2)"
                opacity={0.55}
                onMouseEnter={() => setEncima(i)}
                onMouseLeave={() => setEncima(null)}
              />
            );
          }
          return (
            <g key={i} onMouseEnter={() => setEncima(i)} onMouseLeave={() => setEncima(null)}>
              {/* Anillo del color de la superficie, para que el marcador se lea
                  cuando cae encima de la línea. */}
              <circle
                cx={c.x}
                cy={c.y}
                r={MARCA.marcador + MARCA.anillo / 2}
                fill="var(--color-superficie)"
              />
              <circle cx={c.x} cy={c.y} r={MARCA.marcador} fill="var(--color-rampa-2)" />
              <text
                x={c.x + (i === coords.length - 1 ? 9 : 0)}
                y={c.y - (i === coords.length - 1 ? 0 : 11)}
                textAnchor={i === coords.length - 1 ? "start" : "middle"}
                dominantBaseline={i === coords.length - 1 ? "middle" : "auto"}
                className="cifra"
                fontSize={10}
                fontFamily="var(--font-mono)"
                fill="var(--color-tinta)"
              >
                {formatoY(c.dato.y)}
              </text>
            </g>
          );
        })}

        {/* Zonas de contacto anchas: un punto de 9px es imposible de acertar. */}
        {coords.map((c, i) => (
          <rect
            key={`hit-${i}`}
            x={c.x - 14}
            y={MARGEN.arriba}
            width={28}
            height={alto - MARGEN.arriba - MARGEN.abajo}
            fill="transparent"
            onMouseEnter={() => setEncima(i)}
            onMouseLeave={() => setEncima(null)}
          />
        ))}

        <line
          x1={MARGEN.izq}
          x2={ancho - MARGEN.der}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--color-eje)"
          strokeWidth={1}
        />

        {puntos
          .filter((p) => destacar.includes(p.x) || p.x === 0 || p.x === maxX)
          .map((p) => (
            <text
              key={p.x}
              x={x(p.x)}
              y={alto - MARGEN.abajo + 13}
              textAnchor="middle"
              className="cifra"
              fontSize={9}
              fontFamily="var(--font-mono)"
              fill="var(--color-tinta-3)"
            >
              {formatoX(p.x)}
            </text>
          ))}
      </svg>
    </figure>
  );
}
