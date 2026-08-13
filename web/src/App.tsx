import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { AgenteColumna } from "./components/AgenteColumna";
import { AuditLog } from "./components/AuditLog";
import { Chat } from "./components/Chat";
import { GuionPitch } from "./components/GuionPitch";
import { HeroCartera } from "./components/HeroCartera";
import { KpiBand } from "./components/KpiBand";
import { Masthead } from "./components/Masthead";
import { PanelDatos } from "./components/PanelDatos";
import { SupervisorPanel } from "./components/SupervisorPanel";
import { Pestanas, type VistaId } from "./components/Vistas";
import { TablaAnomalias, VistaHallazgos } from "./components/VistaHallazgos";

import {
  correrCierre,
  detenerCierre,
  ErrorApi,
  getEstadoDatos,
  getKpis,
  getPlan,
  getResultados,
  getSalud,
} from "./lib/api";
import type { DetalleTools, EstadoDatos, Kpis } from "./lib/types";
import { agentesDe, estadoInicial, reducer } from "./state/runReducer";
import { useArco } from "./state/useArco";

export default function App() {
  const [estado, despachar] = useReducer(reducer, estadoInicial);
  const [kpis, setKpis] = useState<Kpis | undefined>();
  const [detalle, setDetalle] = useState<DetalleTools | undefined>();
  const [salud, setSalud] = useState<{ ok: boolean; llm: boolean }>({ ok: false, llm: false });
  const [cargando, setCargando] = useState(true);
  const [modoSeguro, setModoSeguro] = useState(false);
  const [nota, setNota] = useState<string | undefined>();
  const [guion, setGuion] = useState(false);
  const [vista, setVista] = useState<VistaId>("cierre");
  const [estadoDatos, setEstadoDatos] = useState<EstadoDatos | undefined>();
  const [panelDatos, setPanelDatos] = useState(false);
  const [deteniendo, setDeteniendo] = useState(false);
  const abortar = useRef<AbortController | null>(null);
  /** El usuario pidió parar. Evita que la cadena de reserva relance el cierre. */
  const pidioParar = useRef(false);

  const corriendo = estado.fase === "corriendo";
  const arco = useArco(estado.etapa, true);
  const agentes = useMemo(() => agentesDe(estado), [estado]);

  // --- carga inicial -------------------------------------------------------
  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const [s, k, p] = await Promise.all([getSalud(), getKpis(), getPlan()]);
        if (!vivo) return;
        setSalud({ ok: true, llm: s.llm_configurado });
        setKpis(k);
        despachar({ tipo: "plan", pasos: p.pasos });
        // Qué dataset hay cargado. No bloquea el arranque: si falla, el
        // masthead se comporta como si fuera el de ejemplo.
        getEstadoDatos()
          .then((d) => vivo && setEstadoDatos(d))
          .catch(() => undefined);
        if (!s.llm_configurado) setModoSeguro(true);
        // Puede haber una corrida previa viva en memoria del backend.
        getResultados()
          .then((r) => vivo && setDetalle(r.tools))
          .catch(() => undefined);
      } catch (e) {
        if (!vivo) return;
        setSalud({ ok: false, llm: false });
        setNota(
          e instanceof ErrorApi && e.status
            ? `El backend respondió ${e.status}. ${e.message}`
            : "No hay conexión con el backend. Levántalo con uvicorn api.main:app --port 8000",
        );
      } finally {
        if (vivo) setCargando(false);
      }
    })();
    return () => {
      vivo = false;
    };
  }, []);

  useEffect(() => () => abortar.current?.abort(), []);

  /**
   * Cambió el dataset: todo lo derivado del anterior deja de valer.
   *
   * Los hallazgos y el detalle de la corrida previa son cifras del corte que
   * ya no está cargado. Dejarlos a la vista mientras la portada muestra otras
   * es peor que no mostrar nada, así que se descartan y se vuelve al cierre.
   */
  const alCambiarDatos = useCallback(async (nuevo: EstadoDatos) => {
    setEstadoDatos(nuevo);
    setDetalle(undefined);
    setNota(undefined);
    despachar({ tipo: "reinicia" });
    setVista("cierre");
    try {
      setKpis(await getKpis());
      const p = await getPlan();
      despachar({ tipo: "plan", pasos: p.pasos });
    } catch (e) {
      setNota(
        e instanceof ErrorApi
          ? `Los datos se cargaron pero no pude recalcular la portada. ${e.message}`
          : "Los datos se cargaron pero no pude recalcular la portada.",
      );
    }
  }, []);

  // G abre y cierra el guión. Se ignora si el foco está en un campo de texto.
  useEffect(() => {
    const alPulsar = (e: KeyboardEvent) => {
      if (e.key !== "g" && e.key !== "G") return;
      const foco = document.activeElement;
      if (foco instanceof HTMLInputElement || foco instanceof HTMLTextAreaElement) return;
      e.preventDefault();
      setGuion((v) => !v);
    };
    window.addEventListener("keydown", alPulsar);
    return () => window.removeEventListener("keydown", alPulsar);
  }, []);

  // --- cierre del ciclo ----------------------------------------------------
  const cerrarCiclo = useCallback(async () => {
    if (corriendo) return;

    setNota(undefined);
    setVista("cierre");
    setDeteniendo(false);
    pidioParar.current = false;
    arco.soltar();
    despachar({ tipo: "arranca" });

    const controlador = new AbortController();
    abortar.current = controlador;

    const lanzar = (deterministico: boolean) =>
      correrCierre({
        peticion: { deterministico },
        senal: controlador.signal,
        onEvento: (evento) => despachar({ tipo: "evento", evento }),
      });

    try {
      await lanzar(modoSeguro);
    } catch (e) {
      if (controlador.signal.aborted) return;

      if (e instanceof Error && "status" in e && (e as { status?: number }).status === 409) {
        despachar({ tipo: "falla", mensaje: "Ya hay un cierre corriendo. Espera a que termine." });
        return;
      }

      // Se pidió parar: repetir sin LLM sería justo lo contrario de lo pedido.
      if (pidioParar.current) return;

      if (!modoSeguro) {
        setNota("El camino con agentes falló. Repitiendo sin LLM, con las mismas cifras.");
        try {
          despachar({ tipo: "arranca" });
          await lanzar(true);
          return;
        } catch {
          /* cae al nivel 3 */
        }
      }

      try {
        const k = await getKpis();
        setKpis(k);
        despachar({
          tipo: "falla",
          mensaje: "No se pudo correr el cierre. Se muestran las últimas cifras.",
        });
      } catch {
        despachar({
          tipo: "falla",
          mensaje: e instanceof Error ? e.message : "No se pudo correr el cierre.",
        });
      }
    } finally {
      abortar.current = null;
      setDeteniendo(false);
    }
  }, [corriendo, modoSeguro, arco]);

  /**
   * Detener el cierre en curso.
   *
   * No se corta el stream por nuestro lado: se le pide al backend que pare y se
   * espera su evento `cancelado`. Cortar aquí dejaría el hilo del servidor
   * trabajando con el candado tomado, y el siguiente intento devolvería 409
   * durante un minuto largo. La parada llega en el siguiente paso o llamada al
   * modelo, que en la práctica son unos segundos.
   */
  const detener = useCallback(async () => {
    if (!corriendo || deteniendo) return;
    setDeteniendo(true);
    pidioParar.current = true;
    try {
      await detenerCierre();
    } catch {
      // Si ni la petición de parada llega, el backend no está. Ahí sí se corta
      // por nuestro lado: es preferible devolverle el control al usuario.
      abortar.current?.abort();
      despachar({ tipo: "falla", mensaje: "Se perdió la conexión con el backend." });
      setDeteniendo(false);
    }
  }, [corriendo, deteniendo]);

  // Al terminar se refrescan KPIs y detalle, que es lo que alimenta los gráficos.
  useEffect(() => {
    if (estado.fase !== "terminado") return;
    getKpis().then(setKpis).catch(() => undefined);
    getResultados().then((r) => setDetalle(r.tools)).catch(() => undefined);
  }, [estado.fase]);

  const avisos = [
    ...(estado.error ? [{ texto: humanizar(estado.error), grave: true }] : []),
    ...(nota ? [{ texto: nota, grave: false }] : []),
    ...estado.avisos.map((a) => ({ texto: humanizar(a), grave: false })),
  ];

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[var(--color-fondo)]">
      <Masthead
        fechaCorte={kpis?.fecha_corte}
        conectado={salud.ok}
        llmConfigurado={salud.llm}
        corriendo={corriendo}
        modo={estado.modo}
        modoSeguro={modoSeguro}
        datosDemo={estadoDatos?.es_demo ?? true}
        deteniendo={deteniendo}
        detenido={estado.fase === "detenido"}
        onModoSeguro={setModoSeguro}
        onCerrarCiclo={cerrarCiclo}
        onDetener={detener}
        onAbrirDatos={() => setPanelDatos(true)}
      />

      {panelDatos && (
        <PanelDatos
          estado={estadoDatos}
          corriendo={corriendo}
          onCerrar={() => setPanelDatos(false)}
          onCambiado={alCambiarDatos}
        />
      )}

      <div className="filete-b flex items-center px-4">
        <Pestanas
          activa={vista}
          onCambiar={setVista}
          contadores={{
            traza: estado.audit.length ? String(estado.audit.length) : undefined,
          }}
        />
      </div>

      <KpiBand kpis={kpis} cargando={cargando} />

      {avisos.length > 0 && (
        <div className="filete-b">
          {avisos.map((a, i) => (
            <p
              key={`${a.texto}-${i}`}
              className="anim-entra px-6 py-1.5 text-[11.5px]"
              style={{
                color: a.grave ? "var(--color-terracota)" : "var(--color-arena)",
                background: a.grave ? "rgb(196 85 61 / .07)" : "transparent",
              }}
            >
              {a.texto}
            </p>
          ))}
        </div>
      )}

      <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {vista === "cierre" && (
          // overflow-y-auto es la red de seguridad: en pantallas bajas el héroe
          // llega a su altura mínima y la vista pasa a desplazarse, en vez de
          // desbordar por debajo y pintarse encima del panel de agentes.
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <div
              className="flex flex-1 shrink-0 items-center"
              style={{ minHeight: "min(44vh, 360px)" }}
            >
              <HeroCartera
                reconciliacion={kpis?.reconciliacion}
                carteraC={estado.carteraC}
                etapa={arco.etapa}
                manual={arco.manual}
                onIr={arco.ir}
                corriendo={corriendo}
              />
            </div>
            <div className="filete-t grid shrink-0 grid-cols-1 gap-px bg-[var(--filete)] lg:grid-cols-3">
              {agentes.map((a) => (
                <AgenteColumna key={a.clave} agente={a} corriendo={corriendo} />
              ))}
            </div>
          </div>
        )}

        {vista === "hallazgos" && (
          <>
            <SupervisorPanel
              alertas={estado.alertas}
              narrativa={estado.narrativa}
              kpis={kpis}
              modo={estado.modo}
              corriendo={corriendo}
              mensajes={estado.mensajes}
            />
            <VistaHallazgos
              kpis={kpis}
              alertas={estado.alertas}
              pasos={estado.pasos}
              detalle={detalle}
            />
          </>
        )}

        {vista === "traza" && (
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-px overflow-hidden bg-[var(--filete)] xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <div className="flex min-h-0 flex-col bg-[var(--color-fondo)]">
              <AuditLog
                lineas={estado.audit}
                archivo={estado.archivoAuditoria}
                toolsOk={estado.toolsOk}
                toolsError={estado.toolsError}
              />
            </div>
            <section className="flex min-h-0 flex-col overflow-y-auto bg-[var(--color-fondo)] px-5 py-4">
              <div className="mb-3 flex flex-wrap items-baseline gap-2">
                <h3 className="rotulo">Anomalías detectadas</h3>
                <span className="text-[10px] text-[var(--color-tinta-3)]">
                  registros y monto no correlacionan
                </span>
              </div>
              {detalle?.detectar_anomalias?.data?.length ? (
                <TablaAnomalias filas={detalle.detectar_anomalias.data} />
              ) : (
                <p className="text-[11px] text-[var(--color-tinta-3)]">
                  Se rellena al cerrar el ciclo.
                </p>
              )}
            </section>
          </div>
        )}

        {vista === "consulta" && <Chat modoSeguro={modoSeguro} />}
      </main>

      <GuionPitch kpis={kpis} abierto={guion} onCerrar={() => setGuion(false)} />
    </div>
  );
}

/**
 * El backend reenvía el error tal cual se lo dio LiteLLM, que es un volcado de
 * varias líneas con el JSON de Groq dentro. Eso no puede aparecer en pantalla
 * durante una presentación: se traduce a una frase.
 */
function humanizar(mensaje: string): string {
  if (/rate.?limit/i.test(mensaje)) {
    return "Groq agotó su cuota por minuto. El cierre se completó sin LLM, con las mismas cifras.";
  }
  if (/invalid.?api.?key|authentication/i.test(mensaje)) {
    return "La clave de Groq no es válida. El cierre se completó sin LLM, con las mismas cifras.";
  }
  if (/timeout|excedió/i.test(mensaje)) {
    return "Los agentes tardaron más de la cuenta. El cierre se completó sin LLM, con las mismas cifras.";
  }
  const limpio = mensaje.split(/[\n{]/)[0]?.trim() ?? mensaje;
  return limpio.length > 160 ? `${limpio.slice(0, 157)}…` : limpio;
}
