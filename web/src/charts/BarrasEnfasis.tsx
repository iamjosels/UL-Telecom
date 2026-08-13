import { useId, useState } from "react";
import { monto } from "../lib/format";
import { MARCA, barraHorizontal, escala } from "./ejes";

/**
 * Barras horizontales con énfasis: uno manda, el resto es contexto.
 *
 * Es la forma correcta cuando la historia es "este de aquí", no "compara estos
 * ocho". Un dato en ámbar, los demás en gris; sin paleta categórica, así que no
 * hay nada que pueda fallar en daltonismo.
 *
 * La cola se pliega a propósito. La cartera está tan concentrada que el mayor
 * deudor vale unas cuarenta veces la mediana: con quince barras lineales, de la
 * cuarta en adelante no se ve nada. Plegando el resto en una sola barra, esa
 * barra pasa a ser la segunda más alta y de paso cuenta lo que hay que contar:
 * la cola larga junta pesa menos que dos clientes.
 */

export interface FilaBarra {
  clave: string;
  rotulo: string;
  valor: number;
  nota?: string;
}

interface Props {
  filas: FilaBarra[];
  /** Cuántas se muestran sueltas antes de plegar el resto. */
  visibles?: number;
  /** Total de la población, para calcular la cola. */
  total?: number;
  /** Cuántos elementos hay en total, para rotular la cola. */
  poblacion?: number;
  formato?: (v: number) => string;
  /** Ancho del viewBox. Debe ir cerca del ancho real de render: si el SVG se
   *  escala mucho, el texto del gráfico acaba al doble del de la interfaz. */
  ancho?: number;
}

export function BarrasEnfasis({
  filas,
  visibles = 6,
  total,
  poblacion,
  formato = monto,
  ancho = 980,
}: Props) {
  const id = useId();
  const [encima, setEncima] = useState<string | null>(null);

  if (!filas.length) return null;

  const cabeza = filas.slice(0, visibles);
  const sumaCabeza = cabeza.reduce((a, f) => a + f.valor, 0);
  const cola = total !== undefined ? Math.max(0, total - sumaCabeza) : 0;
  const restantes = poblacion !== undefined ? poblacion - cabeza.length : 0;

  const puestos: Array<FilaBarra & { esCola?: boolean }> =
    cola > 0
      ? [
          ...cabeza,
          {
            clave: "__cola",
            rotulo: restantes > 0 ? `otros ${restantes}` : "resto",
            valor: cola,
            esCola: true,
          },
        ]
      : cabeza;

  const maximo = Math.max(...puestos.map((f) => f.valor));
  const anchoRotulo = 150;
  const anchoCifra = 96;
  const altoFila = 21;
  const alto = puestos.length * altoFila + 6;
  const x = escala(0, maximo, anchoRotulo, ancho - anchoCifra);
  const grosor = 12;

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${ancho} ${alto}`}
        className="w-full"
        role="img"
        aria-labelledby={`${id}-t`}
      >
        <title id={`${id}-t`}>
          {puestos.map((f) => `${f.rotulo} ${formato(f.valor)}`).join(", ")}
        </title>

        {puestos.map((f, i) => {
          const y = i * altoFila + 4;
          const w = Math.max(2, x(f.valor) - anchoRotulo);
          const activo = encima === f.clave;
          // Solo el primero lleva el acento. Lo demás es contexto.
          const color = f.esCola
            ? "var(--color-atenuado)"
            : i === 0
              ? "var(--color-rampa-2)"
              : "var(--color-rampa-5)";

          return (
            <g
              key={f.clave}
              onMouseEnter={() => setEncima(f.clave)}
              onMouseLeave={() => setEncima(null)}
            >
              <rect x={0} y={y - 2} width={ancho} height={altoFila} fill="transparent" />

              <text
                x={anchoRotulo - 8}
                y={y + grosor / 2 + 3}
                textAnchor="end"
                className="cifra"
                fontSize={9.5}
                fontFamily="var(--font-mono)"
                fill={f.esCola ? "var(--color-tinta-3)" : "var(--color-tinta-2)"}
              >
                {f.rotulo}
              </text>

              <path
                d={barraHorizontal(anchoRotulo, y, w, grosor, MARCA.radio)}
                fill={color}
                opacity={activo ? 1 : f.esCola ? 0.75 : 0.95}
              />

              <text
                x={ancho - anchoCifra + 8}
                y={y + grosor / 2 + 3}
                className="cifra"
                fontSize={9.5}
                fontFamily="var(--font-mono)"
                fill={i === 0 ? "var(--color-tinta)" : "var(--color-tinta-2)"}
              >
                {formato(f.valor)}
              </text>
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
