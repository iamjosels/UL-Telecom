/**
 * Lector de Server-Sent Events sobre fetch + ReadableStream.
 *
 * No se puede usar EventSource: es GET y no admite cuerpo, y /run es POST.
 *
 * Tres cosas que este parser tiene que hacer bien o el demo se cae:
 *
 *  1. Tolerar chunks partidos. La red corta donde quiere, incluso a mitad de
 *     una línea. Se acumula en un buffer y solo se procesan bloques completos
 *     terminados en línea en blanco.
 *
 *  2. Sanear NaN. El backend serializa los eventos con allow_nan=True, así que
 *     una métrica NaN viaja como el token desnudo `NaN` y JSON.parse revienta
 *     con SyntaxError. Hay rutas reales que lo producen (medianas sobre series
 *     vacías, porcentajes con denominador cero). Un frame malo no puede tumbar
 *     la conexión entera.
 *
 *  3. Despachar por el nombre del evento, no por el `tipo` del cuerpo: `fin` y
 *     `ping` no llevan `tipo` dentro del JSON.
 */

export interface FrameSSE {
  evento: string;
  datos: string;
}

/** `NaN`, `Infinity` y `-Infinity` sueltos no son JSON válido. */
const NO_JSON = /(?<![\w."])(-?Infinity|NaN)(?![\w"])/g;

export function parsearDatos<T>(datos: string): T | null {
  try {
    return JSON.parse(datos) as T;
  } catch {
    try {
      return JSON.parse(datos.replace(NO_JSON, "null")) as T;
    } catch {
      return null;
    }
  }
}

function extraerFrame(bloque: string): FrameSSE | null {
  let evento = "message";
  const datos: string[] = [];

  for (const linea of bloque.split(/\r?\n/)) {
    if (!linea || linea.startsWith(":")) continue; // comentario o keep-alive
    const sep = linea.indexOf(":");
    const campo = sep === -1 ? linea : linea.slice(0, sep);
    // El espacio tras los dos puntos es opcional en el protocolo.
    let valor = sep === -1 ? "" : linea.slice(sep + 1);
    if (valor.startsWith(" ")) valor = valor.slice(1);

    if (campo === "event") evento = valor;
    else if (campo === "data") datos.push(valor);
  }

  if (!datos.length) return null;
  return { evento, datos: datos.join("\n") };
}

export interface OpcionesStream {
  senal?: AbortSignal;
  /** Se llama por cada frame recibido, ya separado en evento y datos. */
  onFrame: (frame: FrameSSE) => void;
}

/**
 * Abre el stream y bombea frames hasta que el servidor cierre.
 * Lanza si la respuesta no es 2xx, para que el llamador decida el fallback.
 */
export async function leerStream(
  url: string,
  cuerpo: unknown,
  { senal, onFrame }: OpcionesStream,
): Promise<void> {
  const respuesta = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(cuerpo),
    // El backend responde Access-Control-Allow-Origin: * sin credenciales.
    credentials: "omit",
    signal: senal,
  });

  if (!respuesta.ok) {
    let detalle = "";
    try {
      const j = (await respuesta.json()) as { detail?: string };
      detalle = j?.detail ?? "";
    } catch {
      /* cuerpo no-JSON, da igual */
    }
    const err = new Error(detalle || `HTTP ${respuesta.status}`) as Error & {
      status?: number;
    };
    err.status = respuesta.status;
    throw err;
  }

  if (!respuesta.body) throw new Error("La respuesta no trae cuerpo legible.");

  const lector = respuesta.body.getReader();
  const decodificador = new TextDecoder("utf-8");
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await lector.read();
      if (done) break;

      buffer += decodificador.decode(value, { stream: true });

      // Los bloques se separan por línea en blanco. Lo que quede tras el
      // último separador es un frame incompleto: se guarda para la vuelta
      // siguiente.
      let corte: number;
      while ((corte = buscarSeparador(buffer)) !== -1) {
        const bloque = buffer.slice(0, corte.valueOf());
        buffer = buffer.slice(corte + longitudSeparador(buffer, corte));
        const frame = extraerFrame(bloque);
        if (frame) onFrame(frame);
      }
    }

    // Último frame si el servidor cerró sin la línea en blanco final.
    const resto = extraerFrame(buffer);
    if (resto) onFrame(resto);
  } finally {
    try {
      lector.releaseLock();
    } catch {
      /* ya liberado */
    }
  }
}

function buscarSeparador(buffer: string): number {
  const a = buffer.indexOf("\n\n");
  const b = buffer.indexOf("\r\n\r\n");
  if (a === -1) return b;
  if (b === -1) return a;
  return Math.min(a, b);
}

function longitudSeparador(buffer: string, corte: number): number {
  return buffer.startsWith("\r\n\r\n", corte) ? 4 : 2;
}
