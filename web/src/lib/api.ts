/**
 * Cliente del backend de SON-IA.
 *
 * Rutas relativas a /api: Vite las proxea al backend, así que no hay CORS de
 * por medio ni el problema de `credentials` con Access-Control-Allow-Origin: *.
 */

import { leerStream, parsearDatos } from "./sse";
import type {
  EstadoDatos,
  EventoRun,
  Kpis,
  PeticionChat,
  PeticionRun,
  PlanCierre,
  RespuestaChat,
  RespuestaResultados,
  Salud,
  TablaId,
} from "./types";

const BASE = "/api";

export class ErrorApi extends Error {
  constructor(
    mensaje: string,
    readonly status?: number,
  ) {
    super(mensaje);
    this.name = "ErrorApi";
  }
}

async function pedir<T>(ruta: string, init?: RequestInit): Promise<T> {
  let respuesta: Response;
  try {
    respuesta = await fetch(`${BASE}${ruta}`, {
      ...init,
      credentials: "omit",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ErrorApi("No hay conexión con el backend.");
  }

  if (!respuesta.ok) {
    let detalle = `HTTP ${respuesta.status}`;
    try {
      const j = (await respuesta.json()) as { detail?: string };
      if (j?.detail) detalle = j.detail;
    } catch {
      /* cuerpo no-JSON */
    }
    throw new ErrorApi(detalle, respuesta.status);
  }

  // El backend serializa con allow_nan=False en los endpoints JSON, así que
  // aquí un NaN daría 500 y no llegaríamos hasta acá. Aun así se parsea a
  // través del saneador por simetría con el stream.
  const texto = await respuesta.text();
  const datos = parsearDatos<T>(texto);
  if (datos === null) throw new ErrorApi("El backend devolvió algo que no es JSON.");
  return datos;
}

export const getSalud = () => pedir<Salud>("/");

export const getKpis = (fechaCorte?: string) =>
  pedir<Kpis>(`/kpis${fechaCorte ? `?fecha_corte=${encodeURIComponent(fechaCorte)}` : ""}`);

export const getPlan = () => pedir<PlanCierre>("/plan");

/** Detalle fila a fila de la última corrida. Vacío si aún no se corrió nada. */
export const getResultados = () => pedir<RespuestaResultados>("/resultados");

// --------------------------------------------------------------------------
// Datasets
// --------------------------------------------------------------------------

/**
 * Rechazo de un dataset, con el detalle por archivo.
 *
 * El backend no contesta "error al cargar": dice qué archivo y qué le falta.
 * Ese detalle llega en `detail.problemas` y es lo único que permite que el
 * panel señale la fila del CSV que hay que corregir, en vez de un aviso suelto.
 */
export class ErrorDataset extends ErrorApi {
  constructor(
    mensaje: string,
    readonly motivo: "esquema" | "estructura",
    readonly problemas: Record<string, string[]>,
    status?: number,
  ) {
    super(mensaje, status);
    this.name = "ErrorDataset";
  }
}

/**
 * Pide que el cierre en curso pare.
 *
 * No corta el stream: el backend marca la corrida y sale en su siguiente punto
 * de control, y entonces llega el evento `cancelado` seguido de `fin`. Cortar
 * aquí por nuestra cuenta dejaría el hilo del servidor trabajando y el candado
 * tomado, así que el reintento daría 409 durante un minuto.
 */
export const detenerCierre = () =>
  pedir<{ ts: string; detenido: boolean; motivo?: string }>("/run/detener", {
    method: "POST",
  });

export const getEstadoDatos = () => pedir<EstadoDatos>("/datos/estado");

export const restaurarDemo = () =>
  pedir<EstadoDatos>("/datos/restaurar", { method: "POST" });

/** Sube los 6 CSV. Las claves son las tablas, no los nombres de archivo. */
export async function cargarDatos(
  archivos: Record<TablaId, File>,
  fechaCorte?: string,
): Promise<EstadoDatos> {
  const cuerpo = new FormData();
  for (const [clave, archivo] of Object.entries(archivos)) cuerpo.append(clave, archivo);
  if (fechaCorte) cuerpo.append("fecha_corte", fechaCorte);

  let respuesta: Response;
  try {
    // Sin Content-Type a mano: el navegador tiene que poner el boundary del
    // multipart, y fijarlo aquí rompe el parseo en el servidor.
    respuesta = await fetch(`${BASE}/datos/cargar`, {
      method: "POST",
      body: cuerpo,
      credentials: "omit",
    });
  } catch {
    throw new ErrorApi("No hay conexión con el backend.");
  }

  if (!respuesta.ok) {
    let detalle: unknown;
    try {
      detalle = ((await respuesta.json()) as { detail?: unknown }).detail;
    } catch {
      /* cuerpo no-JSON */
    }
    if (detalle && typeof detalle === "object" && "problemas" in detalle) {
      const d = detalle as { motivo: "esquema" | "estructura"; problemas: Record<string, string[]> };
      throw new ErrorDataset(
        d.motivo === "esquema"
          ? "Los archivos no tienen el esquema esperado."
          : "Los archivos cargan, pero el contenido no es consistente.",
        d.motivo,
        d.problemas,
        respuesta.status,
      );
    }
    throw new ErrorApi(
      typeof detalle === "string" ? detalle : `HTTP ${respuesta.status}`,
      respuesta.status,
    );
  }

  const datos = parsearDatos<EstadoDatos>(await respuesta.text());
  if (datos === null) throw new ErrorApi("El backend devolvió algo que no es JSON.");
  return datos;
}

export const postChat = (cuerpo: PeticionChat, senal?: AbortSignal) =>
  pedir<RespuestaChat>("/chat", {
    method: "POST",
    body: JSON.stringify(cuerpo),
    ...(senal ? { signal: senal } : {}),
  });

// --------------------------------------------------------------------------
// Stream del cierre
// --------------------------------------------------------------------------

export interface OpcionesCierre {
  peticion?: PeticionRun;
  senal?: AbortSignal;
  onEvento: (evento: EventoRun) => void;
}

/**
 * Corre el cierre y entrega los eventos según llegan.
 *
 * Termina cuando el servidor manda `fin`, que es el ÚNICO evento terminal:
 * `corrida_fin` llega antes de `reporte_final`, y `error` tampoco cierra el
 * stream. `ping` se descarta aquí mismo.
 */
export async function correrCierre({
  peticion = {},
  senal,
  onEvento,
}: OpcionesCierre): Promise<void> {
  await leerStream(`${BASE}/run`, peticion, {
    senal,
    onFrame: ({ evento, datos }) => {
      if (evento === "ping") return;

      const cuerpo = parsearDatos<Record<string, unknown>>(datos);
      if (cuerpo === null) {
        // Frame ilegible incluso tras sanear. Se descarta y el stream sigue:
        // perder un evento es mucho mejor que perder la corrida.
        console.warn("[sse] frame descartado", evento, datos.slice(0, 200));
        return;
      }

      // `fin` y `ping` no traen `tipo` dentro del JSON: manda el nombre del
      // evento SSE.
      const tipo = (cuerpo.tipo as string | undefined) ?? evento;
      onEvento({ ...cuerpo, tipo } as EventoRun);
    },
  });
}
