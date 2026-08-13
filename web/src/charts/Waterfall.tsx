import { useId, useState } from "react";
import { monto } from "../lib/format";
import { MARCA, barraColgante, barraVertical, corto, escala, techo, ticks } from "./ejes";

/**
 * Cascada del arco A → B → C.
 *
 * Es el gráfico estándar para descomponer un cambio, y se lee sin que nadie lo
 * explique: dos totales, los saltos entre medias, y el total final.
 *
 * Los saltos se calculan RESTANDO los totales, nunca reutilizando otra métrica
 * parecida. El salto A→B mide 135,679.29 (la diferencia real entre las dos
 * vistas), no los 137,200.41 que suman las facturas de ISIS. Si la cascada no
 * cuadra, miente.
 *
 * Color por polaridad: sube en terracota, baja en azul pizarra, totales en la
 * rampa ámbar. Validado con el script; ΔE 19.4 en deuteranopía. Y como además
 * la dirección la lleva la posición del bloque y la etiqueta el signo, el dato
 * sigue leyéndose en escala de grises.
 */

export interface PasoCascada {
  clave: string;
  rotulo: string;
  /** Valor acumulado tras este paso. */
  total: number;
  /** Texto corto de qué lo movió. Solo en los saltos. */
  causa?: string;
}

interface Props {
  pasos: PasoCascada[];
  /** Índice hasta el que se ha revelado el arco. */
  hasta: number;
  alto?: number;
  onIr?: (i: number) => void;
}

const ALTO = 285;
const MARGEN = { arriba: 30, abajo: 42, izq: 58, der: 16 };

/** Ancho del viewBox. Se elige cercano al ancho real de render para que una
 *  unidad SVG sea casi un píxel: así el tope de 24px de grosor de barra que fija
 *  el método se cumple de verdad y no queda multiplicado por la escala. */
const ANCHO = 1180;

export function Waterfall({ pasos, hasta, alto = ALTO, onIr }: Props) {
  const id = useId();
  const [encima, setEncima] = useState<number | null>(null);

  if (pasos.length < 2) return null;

  // Cada columna es o un total (arranca en cero) o un salto (flota entre el
  // total anterior y el nuevo).
  const columnas = pasos.flatMap((p, i) => {
    const previo = pasos[i - 1];
    if (!previo) return [{ tipo: "total" as const, paso: p, desde: 0, hasta: p.total, indice: i }];
    const delta = p.total - previo.total;
    return [
      {
        tipo: "salto" as const,
        paso: p,
        desde: Math.min(previo.total, p.total),
        hasta: Math.max(previo.total, p.total),
        delta,
        indice: i,
      },
      { tipo: "total" as const, paso: p, desde: 0, hasta: p.total, indice: i },
    ];
  });

  const maximo = techo(Math.max(...pasos.map((p) => p.total)));
  const anchoTotal = ANCHO;
  const areaX = anchoTotal - MARGEN.izq - MARGEN.der;
  const areaY = alto - MARGEN.arriba - MARGEN.abajo;
  const y = escala(0, maximo, alto - MARGEN.abajo, MARGEN.arriba);

  const paso = areaX / columnas.length;
  // Marca fina: el sobrante del hueco es aire, no relleno.
  const ancho = Math.min(MARCA.barraMax, paso * 0.42);

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${anchoTotal} ${alto}`}
        className="w-full"
        role="img"
        aria-labelledby={`${id}-t`}
        style={{ overflow: "visible" }}
      >
        <title id={`${id}-t`}>
          Cascada de la cartera vencida: {pasos.map((p) => `${p.rotulo} ${monto(p.total)}`).join(", ")}
        </title>

        {/* Rejilla: filete sólido, un paso por encima de la superficie. */}
        {ticks(maximo).map((t) => (
          <g key={t}>
            <line
              x1={MARGEN.izq}
              x2={anchoTotal - MARGEN.der}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--color-rejilla)"
              strokeWidth={1}
            />
            <text
              x={MARGEN.izq - 8}
              y={y(t) + 3}
              textAnchor="end"
              className="cifra"
              fontSize={9.5}
              fill="var(--color-tinta-3)"
              fontFamily="var(--font-mono)"
            >
              {corto(t)}
            </text>
          </g>
        ))}

        {columnas.map((c, i) => {
          const x = MARGEN.izq + paso * i + (paso - ancho) / 2;
          const visible = c.indice <= hasta;
          const activo = encima === i;

          const yAlto = y(c.hasta);
          const yBajo = y(c.desde);
          const h = Math.max(2, yBajo - yAlto);

          const esSalto = c.tipo === "salto";
          const sube = esSalto && (c.delta ?? 0) > 0;

          const color = esSalto
            ? sube
              ? "var(--color-sube)"
              : "var(--color-baja)"
            : c.indice === hasta
              ? "var(--color-rampa-2)"
              : "var(--color-rampa-4)";

          // El extremo redondeado va siempre en el lado del dato: arriba si
          // crece desde la base, abajo si el bloque cuelga.
          const d = esSalto && !sube
            ? barraColgante(x, yAlto, ancho, h)
            : barraVertical(x, yAlto, ancho, h);

          return (
            <g
              key={`${c.paso.clave}-${c.tipo}`}
              onMouseEnter={() => setEncima(i)}
              onMouseLeave={() => setEncima(null)}
              onClick={() => onIr?.(c.indice)}
              style={{ cursor: onIr ? "pointer" : "default" }}
            >
              {/* Zona de contacto generosa, no solo la barra. */}
              <rect
                x={MARGEN.izq + paso * i}
                y={MARGEN.arriba}
                width={paso}
                height={areaY}
                fill="transparent"
              />
              <path
                d={d}
                fill={color}
                opacity={visible ? (activo ? 1 : 0.92) : 0.14}
                style={{ transition: "opacity .35s var(--ease-suave)" }}
              />

              {/* Etiqueta directa, solo en totales y saltos. Nunca en todo. */}
              {visible && (
                <text
                  x={x + ancho / 2}
                  y={yAlto - 7}
                  textAnchor="middle"
                  className="cifra"
                  fontSize={esSalto ? 10 : 11}
                  fontFamily="var(--font-mono)"
                  fill={esSalto ? "var(--color-tinta-2)" : "var(--color-tinta)"}
                >
                  {esSalto
                    ? `${sube ? "+" : "−"}${corto(Math.abs(c.delta ?? 0))}`
                    : monto(c.hasta)}
                </text>
              )}
            </g>
          );
        })}

        {/* Conectores entre el techo de un total y el arranque del siguiente. */}
        {columnas.map((c, i) => {
          const sig = columnas[i + 1];
          if (c.tipo !== "total" || !sig || sig.indice > hasta) return null;
          const x1 = MARGEN.izq + paso * i + (paso + ancho) / 2;
          const x2 = MARGEN.izq + paso * (i + 1) + (paso - ancho) / 2;
          return (
            <line
              key={`c-${i}`}
              x1={x1}
              x2={x2}
              y1={y(c.hasta)}
              y2={y(c.hasta)}
              // Sólido y algo más claro que el eje: en una cascada el conector
              // es lo que deja seguir el hilo de un total al siguiente, así que
              // tiene que verse. Nunca discontinuo.
              stroke="var(--color-atenuado)"
              strokeWidth={1}
            />
          );
        })}

        {/* Línea base sólida. */}
        <line
          x1={MARGEN.izq}
          x2={anchoTotal - MARGEN.der}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--color-eje)"
          strokeWidth={1}
        />

        {/* Rótulos del eje. El texto usa tinta, nunca el color del dato. */}
        {columnas.map((c, i) => {
          const x = MARGEN.izq + paso * i + paso / 2;
          const visible = c.indice <= hasta;
          const texto = c.tipo === "total" ? c.paso.rotulo : (c.paso.causa ?? "");
          if (!texto) return null;
          return (
            <text
              key={`r-${i}`}
              x={x}
              y={alto - MARGEN.abajo + 15}
              textAnchor="middle"
              fontSize={c.tipo === "total" ? 10.5 : 9.5}
              fill={
                c.tipo === "total" && c.indice === hasta
                  ? "var(--color-tinta)"
                  : "var(--color-tinta-3)"
              }
              opacity={visible ? 1 : 0.3}
              style={{ transition: "opacity .35s var(--ease-suave)" }}
            >
              {texto}
            </text>
          );
        })}
      </svg>
    </figure>
  );
}
