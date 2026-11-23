import { useCallback, useEffect, useState, type FormEvent } from 'react'
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

function filaIndicadores(periodo: Periodo, etiqueta: string) {
  const mediana = periodo.mediana_primera_respuesta_min
  const tasa = periodo.tasa_visitas_pct
  return (
    <tr>
      <th scope="row">
        {etiqueta}
        <small>{fechaCorta.format(new Date(periodo.desde))} – {fechaCorta.format(new Date(periodo.hasta))}</small>
      </th>
      <td>{numero.format(periodo.recibidas)}</td>
      <td>{numero.format(periodo.sin_respuesta)}</td>
      <td>{mediana == null ? '—' : `${numero.format(mediana)} min`}</td>
      <td>{numero.format(periodo.visitas_agendadas)}</td>
      <td>{tasa == null ? '—' : `${numero.format(tasa)} %`}</td>
    </tr>
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

  return (
    <main className="panel-leads">
      <header className="cabecera-leads">
        <div>
          <a className="enlace-panel" href="#/">Volver al buscador</a>
          <h1>Panel de leads</h1>
          <p>{ejecutivo.nombre}</p>
        </div>
        <button className="contactar" onClick={() => cerrarSesion()}>Cerrar sesión</button>
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
          {indicadores && (
            <section className="indicadores-leads" aria-labelledby="indicadores-leads">
              <h2 id="indicadores-leads">Indicadores por período</h2>
              <div className="tabla-indicadores">
                <table aria-labelledby="indicadores-leads">
                  <thead>
                    <tr>
                      <th scope="col">Período</th>
                      <th scope="col">Recibidas</th>
                      <th scope="col">Sin respuesta</th>
                      <th scope="col">Mediana primera respuesta</th>
                      <th scope="col">Visitas agendadas</th>
                      <th scope="col">Tasa de visitas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filaIndicadores(indicadores.periodo, 'Seleccionado')}
                    {filaIndicadores(indicadores.anterior, 'Anterior')}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          <section className="solicitudes-leads" aria-labelledby="solicitudes-leads">
            <h2 id="solicitudes-leads">Solicitudes de contacto</h2>
            <p className="total">
              {datos.total === 0
                ? 'No hay solicitudes para los filtros seleccionados.'
                : `Mostrando ${pagina * LEADS_POR_PAGINA + 1} a ${pagina * LEADS_POR_PAGINA + datos.resultados.length} de ${datos.total}`}
            </p>
            {datos.resultados.map(lead => (
              <FichaLead key={lead.id} lead={lead} ejecutivos={ejecutivos}
                token={token} alGuardar={alGuardar} mensajeError={mensajeError} />
            ))}
            {datos.total > LEADS_POR_PAGINA && (
              <nav aria-label="Páginas de solicitudes" className="paginacion-leads">
                <button className="contactar" disabled={!pagina} onClick={() => cambiarPagina(pagina - 1)}>Anterior</button>
                <button className="contactar" disabled={(pagina + 1) * LEADS_POR_PAGINA >= datos.total}
                  onClick={() => cambiarPagina(pagina + 1)}>Siguiente</button>
              </nav>
            )}
          </section>
        </>
      )}
    </main>
  )
}
