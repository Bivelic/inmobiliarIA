import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  actualizarLead,
  consultarIndicadores,
  ErrorLeads,
  ESTADOS,
  LEADS_POR_PAGINA,
  listarEjecutivos,
  listarLeads,
  type Ejecutivo,
  type Estado,
  type FiltrosLeads,
  type Indicadores,
  type Lead,
  type LeadCambio,
  type PaginaLeads,
  type Periodo,
  type Sesion,
} from './leadsApi'

const SIN_FILTROS: FiltrosLeads = { estado: '', asignacion: '', desde: '', hasta: '' }
const fechaHora = new Intl.DateTimeFormat('es-CL', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Santiago',
})
const fechaCorta = new Intl.DateTimeFormat('es-CL', { dateStyle: 'medium', timeZone: 'UTC' })
const numero = new Intl.NumberFormat('es-CL', { maximumFractionDigits: 1 })
const opcionesEstado = Object.entries(ESTADOS).map(([valor, texto]) =>
  <option key={valor} value={valor}>{texto}</option>,
)

const intervalo = (periodo: Periodo) =>
  `${fechaCorta.format(new Date(periodo.desde))} al ${fechaCorta.format(new Date(periodo.hasta))}`

const metricas = [
  { titulo: 'Solicitudes recibidas', campo: 'recibidas' },
  { titulo: 'Sin respuesta', campo: 'sin_respuesta' },
  { titulo: 'Primera respuesta (mediana)', campo: 'mediana_primera_respuesta_min', unidad: ' min' },
  { titulo: 'Visitas agendadas', campo: 'visitas_agendadas' },
  { titulo: 'Tasa de visitas', campo: 'tasa_visitas_pct', unidad: ' %' },
] as const

const valorIndicador = (valor: number | null, unidad = '') =>
  valor == null ? '—' : numero.format(valor) + unidad

const iniciales = (nombre: string) =>
  nombre.trim().split(/\s+/).slice(0, 2).map(palabra => palabra[0]).join('').toLocaleUpperCase('es-CL')

function ResumenIndicadores({ periodo, anterior }: Indicadores) {
  return (
    <section className="indicadores-leads" aria-labelledby="indicadores-leads">
      <div className="cabecera-seccion">
        <h2 id="indicadores-leads">Indicadores por período</h2>
        <p className="nota">Actual · {intervalo(periodo)}<br />Anterior · {intervalo(anterior)}</p>
      </div>
      <dl className="metricas-leads">
        {metricas.map(metrica => {
          const unidad = 'unidad' in metrica ? metrica.unidad : ''
          return (
            <div className="metrica-leads" key={metrica.campo}>
              <dt>{metrica.titulo}</dt>
              <dd>{valorIndicador(periodo[metrica.campo], unidad)}</dd>
              <dd className="metrica-anterior">Anterior {valorIndicador(anterior[metrica.campo], unidad)}</dd>
            </div>
          )
        })}
      </dl>
    </section>
  )
}

function leadUrl(valor: string | null) {
  if (!valor) return null
  try {
    const url = new URL(valor)
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null
  } catch {
    return null
  }
}

function FichaLead({ lead, ejecutivos, token, alGuardar, mensajeError }: {
  lead: Lead
  ejecutivos: Ejecutivo[]
  token: string
  alGuardar: (lead: Lead) => void
  mensajeError: (e: unknown) => string
}) {
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState('')
  const [estado, setEstado] = useState<Estado>(lead.estado)
  const [asignado, setAsignado] = useState(lead.ejecutivo_id == null ? '' : String(lead.ejecutivo_id))
  const url = leadUrl(lead.publicacion_url)
  const asignadoInactivo = lead.ejecutivo_id != null && !ejecutivos.some(e => e.id === lead.ejecutivo_id)
  const ejecutivoId = asignado ? Number(asignado) : null
  const hayCambios = estado !== lead.estado || ejecutivoId !== lead.ejecutivo_id

  function guardar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    if (!hayCambios) return
    const cambio: LeadCambio = {}
    if (estado !== lead.estado) cambio.estado = estado
    if (ejecutivoId !== lead.ejecutivo_id) cambio.ejecutivo_id = ejecutivoId
    setGuardando(true)
    setError('')
    actualizarLead(token, lead.id, cambio)
      .then(alGuardar)
      .catch((e: unknown) => setError(mensajeError(e)))
      .finally(() => setGuardando(false))
  }

  return (
    <article className="ficha-lead" aria-labelledby={`lead-${lead.id}`}>
      <div className="ficha-lead-cabecera">
        <div>
          <h3 id={`lead-${lead.id}`}>{lead.nombre}</h3>
          <p className="nota">#{lead.id} · {fechaHora.format(new Date(lead.creado_en))}</p>
        </div>
        <span className={`estado-lead estado-${lead.estado}`}>{ESTADOS[lead.estado]}</span>
      </div>
      <dl className="datos-lead">
        <div><dt>Correo</dt><dd>{lead.email}</dd></div>
        <div><dt>Teléfono</dt><dd>{lead.telefono || '—'}</dd></div>
        <div>
          <dt>Propiedad</dt>
          <dd>
            {url ? <a href={url} target="_blank" rel="noopener noreferrer">
              {lead.publicacion_titulo || 'Ver aviso original'}
            </a> : lead.publicacion_titulo || '—'}
            {lead.portal && <small>{lead.portal}</small>}
          </dd>
        </div>
      </dl>
      {lead.mensaje && <p className="mensaje-lead">{lead.mensaje}</p>}
      {(lead.primera_respuesta_en || lead.visita_agendada_en) && (
        <p className="nota">
          {lead.primera_respuesta_en && <>Primera respuesta {fechaHora.format(new Date(lead.primera_respuesta_en))}</>}
          {lead.primera_respuesta_en && lead.visita_agendada_en && ' · '}
          {lead.visita_agendada_en && <>Visita registrada {fechaHora.format(new Date(lead.visita_agendada_en))}</>}
        </p>
      )}
      <form className="controles-leads cambio-lead" onSubmit={guardar}>
        <label>Estado
          <select aria-label="Estado" value={estado} onChange={e => setEstado(e.target.value as Estado)} disabled={guardando}>
            {opcionesEstado}
          </select>
        </label>
        <label>Ejecutivo responsable
          <select aria-label="Ejecutivo responsable" value={asignado} onChange={e => setAsignado(e.target.value)} disabled={guardando}>
            <option value="">Sin asignar</option>
            {asignadoInactivo && (
              <option value={lead.ejecutivo_id!} disabled>{lead.ejecutivo_nombre || 'Ejecutivo inactivo'}</option>
            )}
            {ejecutivos.map(e => <option key={e.id} value={e.id}>{e.nombre}</option>)}
          </select>
        </label>
        <button className="buscar" disabled={guardando || !hayCambios}>
          {guardando ? 'Guardando…' : 'Guardar cambios'}
        </button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
    </article>
  )
}

export default function PanelLeads({ sesion, cerrarSesion }: {
  sesion: Sesion
  cerrarSesion: (mensaje?: string) => void
}) {
  const { token, ejecutivo } = sesion
  const [ejecutivos, setEjecutivos] = useState<Ejecutivo[]>([])
  const [filtros, setFiltros] = useState(SIN_FILTROS)
  const [pagina, setPagina] = useState(0)
  const [datos, setDatos] = useState<PaginaLeads | null>(null)
  const [indicadores, setIndicadores] = useState<Indicadores | null>(null)
  const [cargando, setCargando] = useState(true)
  const [mensaje, setMensaje] = useState('')
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [seleccion, setSeleccion] = useState<number | null>(null)
  const [visitados, setVisitados] = useState<number[]>([])
  const detalle = useRef<HTMLDivElement>(null)
  const seleccionado = datos?.resultados.find(lead => lead.id === seleccion) ?? datos?.resultados[0]

  const mensajeError = useCallback((e: unknown) => {
    if (e instanceof ErrorLeads) {
      if (e.status === 401) cerrarSesion('Tu sesión venció. Vuelve a ingresar.')
      return e.message
    }
    return 'No se pudo conectar con el servidor. Intenta de nuevo.'
  }, [cerrarSesion])

  useEffect(() => {
    const controller = new AbortController()
    let corrigiendoPagina = false
    Promise.all([
      listarLeads(token, filtros, pagina, controller.signal),
      listarEjecutivos(token, controller.signal),
      consultarIndicadores(token, filtros.desde, filtros.hasta, controller.signal),
    ])
      .then(([leads, equipo, metricas]) => {
        if (controller.signal.aborted) return
        if (pagina > 0 && leads.resultados.length === 0) {
          corrigiendoPagina = true
          setPagina(Math.max(0, Math.ceil(leads.total / LEADS_POR_PAGINA) - 1))
          return
        }
        setDatos(leads)
        setEjecutivos(equipo)
        setIndicadores(metricas)
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return
        setDatos(null)
        setIndicadores(null)
        setError(mensajeError(e))
      })
      .finally(() => {
        if (!controller.signal.aborted && !corrigiendoPagina) setCargando(false)
      })
    return () => controller.abort()
  }, [token, filtros, pagina, revision, mensajeError])

  function filtrar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    const form = new FormData(evento.currentTarget)
    const desde = String(form.get('desde'))
    const hasta = String(form.get('hasta'))
    if (desde && hasta && desde > hasta) {
      setError('La fecha inicial debe ser anterior a la fecha final.')
      return
    }
    setMensaje('')
    prepararCarga()
    setPagina(0)
    setFiltros({ estado: String(form.get('estado')), asignacion: String(form.get('asignacion')), desde, hasta })
  }

  function alGuardar(lead: Lead) {
    setMensaje(`Cambios guardados en la solicitud #${lead.id}.`)
    recargar()
  }

  function prepararCarga() {
    setCargando(true)
    setError('')
    setVisitados([])
  }

  function recargar() {
    prepararCarga()
    setRevision(actual => actual + 1)
  }

  function cambiarPagina(siguiente: number) {
    prepararCarga()
    setMensaje('')
    setPagina(siguiente)
  }

  function abrirLead(id: number) {
    if (seleccionado) setVisitados(previos => previos.includes(seleccionado.id) ? previos : [...previos, seleccionado.id])
    setSeleccion(id)
    setMensaje('')
    if (window.matchMedia('(max-width: 720px)').matches) {
      detalle.current?.focus({ preventScroll: true })
      detalle.current?.scrollIntoView({ block: 'start' })
    }
  }

  return (
    <main className="panel-leads">
      <header className="cabecera-leads">
        <div>
          <h1>Panel de leads</h1>
          <p>Revisa las solicitudes de contacto y gestiona su seguimiento.</p>
        </div>
        <div className="cuenta-leads">
          <span className="avatar-lead" aria-hidden="true">{iniciales(ejecutivo.nombre)}</span>
          <strong>{ejecutivo.nombre}</strong>
          <button className="secundario" onClick={() => cerrarSesion()}>Cerrar sesión</button>
        </div>
      </header>

      <form className="controles-leads filtro-leads" onSubmit={filtrar}>
        <label>Estado de las solicitudes
          <select name="estado" aria-label="Estado de las solicitudes">
            <option value="">Todos</option>
            {opcionesEstado}
          </select>
        </label>
        <label>Asignación
          <select name="asignacion" aria-label="Asignación">
            <option value="">Todos</option>
            <option value="sin_asignar">Sin asignar</option>
            {ejecutivos.map(e => (
              <option key={e.id} value={e.id}>{e.nombre}{e.id === ejecutivo.id && ' (yo)'}</option>
            ))}
          </select>
        </label>
        <label>Desde<input name="desde" type="date" /></label>
        <label>Hasta<input name="hasta" type="date" /></label>
        <button className="buscar" disabled={cargando}>Aplicar filtros</button>
      </form>

      {error && (
        <div className="error" role="alert">
          <p>{error}</p>
          {!datos && <button className="contactar" onClick={recargar}>Reintentar</button>}
        </div>
      )}
      {mensaje && <p className="contacto-ok" role="status">{mensaje}</p>}
      {cargando ? <p role="status">Cargando solicitudes…</p> : datos && (
        <>
          {indicadores && <ResumenIndicadores {...indicadores} />}
          <section className="solicitudes-leads" aria-labelledby="solicitudes-leads">
            <div className="solicitudes-cabecera">
              <h2 id="solicitudes-leads">Solicitudes de contacto</h2>
              <p className="nota">
                {datos.total === 0 ? '0 solicitudes' : `${pagina * LEADS_POR_PAGINA + 1}–${pagina * LEADS_POR_PAGINA + datos.resultados.length} de ${datos.total}`}
              </p>
            </div>
            {seleccionado ? (
              <div className="bandeja-leads">
                <div className="navegacion-leads">
                  <ul className="lista-leads" aria-label="Solicitudes">
                    {datos.resultados.map(lead => (
                      <li key={lead.id}>
                        <button type="button" aria-pressed={lead.id === seleccionado.id}
                          aria-controls="detalle-solicitud" onClick={() => abrirLead(lead.id)}>
                          <span className="avatar-lead" aria-hidden="true">{iniciales(lead.nombre)}</span>
                          <span className="resumen-lead">
                            <strong>{lead.nombre}</strong>
                            <span>{lead.publicacion_titulo || 'Solicitud de contacto'}</span>
                            <small className={`estado-lead estado-${lead.estado}`}>{ESTADOS[lead.estado]}</small>
                          </span>
                          <span className="flecha-lead" aria-hidden="true">›</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {datos.total > LEADS_POR_PAGINA && (
                    <nav aria-label="Páginas de solicitudes" className="paginacion-leads">
                      <button className="secundario" disabled={!pagina} onClick={() => cambiarPagina(pagina - 1)}>Anterior</button>
                      <button className="secundario" disabled={(pagina + 1) * LEADS_POR_PAGINA >= datos.total}
                        onClick={() => cambiarPagina(pagina + 1)}>Siguiente</button>
                    </nav>
                  )}
                </div>
                <div className="area-detalle-lead" id="detalle-solicitud" ref={detalle} tabIndex={-1}>
                  {datos.resultados.filter(lead => lead.id === seleccionado.id || visitados.includes(lead.id)).map(lead => (
                    <div key={lead.id} hidden={lead.id !== seleccionado.id}>
                      <FichaLead lead={lead} ejecutivos={ejecutivos}
                        token={token} alGuardar={alGuardar} mensajeError={mensajeError} />
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="leads-vacio">No hay solicitudes para los filtros seleccionados.</p>
            )}
          </section>
        </>
      )}
    </main>
  )
}
