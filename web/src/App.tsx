import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { buscarAvisos, listarComunas, type Aviso, type Comuna, type Filtros, type Interpretacion, type Orden } from './api'
import AccesoLeads from './AccesoLeads'
import { DetalleAviso, TarjetaAviso } from './Avisos'
import santiago from './assets/santiago-departamentos.webp'

type Borrador = Omit<Filtros, 'orden'>
const INICIO: Filtros = { orden: 'relevancia' }
const numero = new Intl.NumberFormat('es-CL')
const EJEMPLOS = [
  { titulo: 'Mascotas en Ñuñoa', texto: 'Depto en Ñuñoa que acepte perros' },
  { titulo: 'Amoblado cerca del metro', texto: 'Amoblado cerca del metro hasta 600 mil' },
  { titulo: 'Estacionamiento en Providencia', texto: '2 dormitorios con estacionamiento en Providencia' },
  { titulo: 'Piscina en Las Condes', texto: 'Con piscina y gimnasio en Las Condes' },
]

function Buscador() {
  const [filtros, setFiltros] = useState<Filtros>(INICIO)
  const [borrador, setBorrador] = useState<Borrador>({})
  const [comunas, setComunas] = useState<Comuna[]>([])
  const [avisos, setAvisos] = useState<Aviso[]>([])
  const [total, setTotal] = useState(0)
  const [interpretacion, setInterpretacion] = useState<Interpretacion | null>(null)
  const [busquedaId, setBusquedaId] = useState<number | null>(null)
  const [cargando, setCargando] = useState(true)
  const [cargandoMas, setCargandoMas] = useState(false)
  const [mostrarResultados, setMostrarResultados] = useState(true)
  const [filtrosMovil, setFiltrosMovil] = useState(false)
  const [seleccion, setSeleccion] = useState<{ aviso: Aviso; contacto: boolean } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const version = useRef(0)
  const alternarFiltros = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    let vigente = true
    listarComunas().then(datos => { if (vigente) setComunas(datos) }).catch(() => {})
    return () => { vigente = false }
  }, [])

  useEffect(() => {
    let vigente = true
    buscarAvisos(filtros)
      .then(r => {
        if (!vigente) return
        setAvisos(r.resultados)
        setTotal(r.total)
        setInterpretacion(r.interpretacion)
        setBusquedaId(r.busqueda_id)
      })
      .catch((e: Error) => { if (vigente) setError(e.message) })
      .finally(() => { if (vigente) setCargando(false) })
    return () => { vigente = false }
  }, [filtros])

  function aplicar(nuevos: Filtros) {
    version.current += 1
    setCargando(true)
    setCargandoMas(false)
    setAvisos([])
    setTotal(0)
    setInterpretacion(null)
    setBusquedaId(null)
    setError(null)
    setMostrarResultados(true)
    setFiltros({ ...nuevos })
  }

  function cargarMas() {
    const actual = version.current
    setCargandoMas(true)
    setError(null)
    buscarAvisos(filtros, avisos.length, busquedaId)
      .then(r => {
        if (actual !== version.current) return
        setAvisos(vistos => {
          const ids = new Set(vistos.map(a => a.id))
          return [...vistos, ...r.resultados.filter(a => !ids.has(a.id))]
        })
        setTotal(r.total)
      })
      .catch((e: Error) => { if (actual === version.current) setError(e.message) })
      .finally(() => { if (actual === version.current) setCargandoMas(false) })
  }

  const cambiar = (campo: keyof Borrador) => (evento: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setBorrador(previo => ({ ...previo, [campo]: evento.target.value || undefined }))

  function buscar(evento: FormEvent) {
    evento.preventDefault()
    if (filtrosMovil) alternarFiltros.current?.focus()
    setFiltrosMovil(false)
    aplicar({ ...filtros, ...borrador })
  }

  function usarEjemplo(texto: string) {
    setBorrador(previo => ({ ...previo, q: texto }))
    aplicar({ ...filtros, ...borrador, q: texto })
  }

  function reiniciar() {
    setBorrador({})
    aplicar(INICIO)
  }

  const quedan = total - avisos.length
  const pedidos = Object.keys(interpretacion?.criterios.atributos ?? {}).length
  const hayTexto = Boolean(filtros.q?.trim())
  const filtrosActivos = [filtros.comuna, filtros.precio_max, filtros.dormitorios_min].filter(Boolean).length
  const hayFiltros = Boolean(borrador.q || borrador.comuna || borrador.precio_max || borrador.dormitorios_min || filtros.orden !== INICIO.orden)

  return (
    <main className="pagina-buscador">
      <section className="hero-buscador" aria-labelledby="titulo-buscador">
        <div className="hero-texto">
          <p className="hero-region"><span aria-hidden="true" />Arriendos en Santiago</p>
          <h1 id="titulo-buscador">Encuentra tu<br className="hero-salto" /> próximo departamento</h1>
          <p className="hero-descripcion">Busca con tus palabras y compara avisos de distintos portales.</p>
          <form id="form-busqueda" className="buscador" onSubmit={buscar}>
            <label className="solo-lectura" htmlFor="q">¿Qué estás buscando?</label>
            <div className="fila-busqueda">
              <span className="lupa" aria-hidden="true" />
              <input id="q" type="search" value={borrador.q ?? ''} onChange={cambiar('q')}
                maxLength={300} placeholder="Ej. Depto en Ñuñoa" />
              <button type="submit" className="buscar" disabled={cargando}>
                {cargando ? 'Buscando…' : 'Buscar'} <span aria-hidden="true">→</span>
              </button>
            </div>
          </form>
        </div>
        <div className="hero-foto"><img src={santiago} alt="" fetchPriority="high" /></div>
      </section>

      <div className="ejemplos" aria-label="Ideas de búsqueda">
        <span>Prueba</span>
        {EJEMPLOS.map(({ titulo, texto }) => (
          <button key={texto} type="button" title={texto} onClick={() => usarEjemplo(texto)}>{titulo}</button>
        ))}
      </div>

      <div className="catalogo">
        <aside className={`filtros-catalogo${filtrosMovil ? ' filtros-abiertos' : ''}`}>
          <button ref={alternarFiltros} className="secundario alternar-filtros" type="button" aria-expanded={filtrosMovil}
            aria-controls="filtros-busqueda" onClick={() => setFiltrosMovil(abiertos => !abiertos)}>
            Filtros{filtrosActivos > 0 && ` (${filtrosActivos})`} <span aria-hidden="true">{filtrosMovil ? '−' : '+'}</span>
          </button>
          <div className="filtros" id="filtros-busqueda">
            <div className="filtros-cabecera">
              <h2>Filtros</h2>
              {hayFiltros && <button type="button" className="boton-texto" onClick={reiniciar}>Limpiar búsqueda</button>}
            </div>
            <label>Comuna
              <select aria-label="Comuna" form="form-busqueda" onChange={cambiar('comuna')} value={borrador.comuna ?? ''}>
                <option value="">Todas las comunas</option>
                {comunas.map(c => <option key={c.slug} value={c.slug}>{c.nombre} ({c.avisos})</option>)}
              </select>
            </label>
            <label>Precio máximo (CLP)
              <input type="number" form="form-busqueda" min={0} step={50000} placeholder="Sin máximo"
                value={borrador.precio_max ?? ''} onChange={cambiar('precio_max')} />
            </label>
            <label>Dormitorios mínimos
              <input type="number" form="form-busqueda" min={0} max={10} placeholder="Sin mínimo"
                value={borrador.dormitorios_min ?? ''} onChange={cambiar('dormitorios_min')} />
            </label>
            <button type="submit" className="buscar" form="form-busqueda" disabled={cargando}>Aplicar filtros</button>
            <p className="nota">Los filtros tienen prioridad sobre el texto.</p>
          </div>
        </aside>

        <section className="resultados" aria-labelledby="titulo-resultados" aria-busy={cargando}>
          <div className="cabecera-resultados">
            <div>
              <h2 id="titulo-resultados">Departamentos</h2>
              <p className="total" role="status">
                {cargando ? 'Cargando avisos…' : error && !avisos.length ? 'Avisos no disponibles'
                  : `Mostrando ${numero.format(avisos.length)} de ${numero.format(total)} ${total === 1 ? 'aviso' : 'avisos'}`}
              </p>
            </div>
            <div className="controles-resultados">
              <label className="solo-lectura" htmlFor="orden">Ordenar por</label>
              <select id="orden" value={filtros.orden} onChange={e => aplicar({ ...filtros, orden: e.target.value as Orden })}>
                <option value="relevancia">Más relevantes</option>
                <option value="recientes">Más recientes</option>
                <option value="precio_asc">Precio: menor a mayor</option>
                <option value="precio_desc">Precio: mayor a menor</option>
              </select>
              {(avisos.length > 0 || cargando || error) && (
                <button type="button" className="secundario" aria-expanded={mostrarResultados} aria-controls="lista-resultados"
                  onClick={() => setMostrarResultados(previo => !previo)}>
                  {mostrarResultados ? 'Ocultar resultados' : 'Mostrar resultados'}
                </button>
              )}
            </div>
          </div>
          <div id="lista-resultados" hidden={!mostrarResultados}>
            {error && (
              <div className="error" role="alert">
                <p>No se pudo cargar: {error}</p>
                {!avisos.length && <button type="button" className="secundario" onClick={() => aplicar(filtros)}>Reintentar</button>}
              </div>
            )}
            {!cargando && hayTexto && interpretacion && (
              <section className="entendido" aria-live="polite">
                {interpretacion.resumen.length > 0 ? (
                  <>
                    <span>Buscamos</span>
                    <ul>{interpretacion.resumen.map(parte => <li key={parte}>{parte}</li>)}</ul>
                  </>
                ) : <span>No reconocimos criterios en el texto.</span>}
                {interpretacion.aviso && <p className="nota">{interpretacion.aviso}</p>}
              </section>
            )}
            {cargando && (
              <div className="esqueleto-avisos" aria-hidden="true">
                {[0, 1].map(n => <div key={n}><i /><i /><i /></div>)}
              </div>
            )}
            {!cargando && !error && !avisos.length && (
              <div className="resultados-vacios">
                <h3>No encontramos avisos</h3>
                <p>Prueba cambiando la comuna, el precio o los dormitorios.</p>
                {hayFiltros && <button type="button" className="secundario" onClick={reiniciar}>Ver todos los avisos</button>}
              </div>
            )}
            {avisos.length > 0 && (
              <ul className="avisos">
                {avisos.map(aviso => (
                  <TarjetaAviso key={aviso.id} aviso={aviso} pedidos={pedidos}
                    abrir={contacto => setSeleccion({ aviso, contacto })} />
                ))}
              </ul>
            )}
            {!cargando && quedan > 0 && (
              <button className="cargar-mas" onClick={cargarMas} disabled={cargandoMas}>
                {cargandoMas ? 'Cargando…' : `Cargar más (quedan ${numero.format(quedan)})`}
              </button>
            )}
          </div>
        </section>
      </div>
      {seleccion && (<DetalleAviso aviso={seleccion.aviso} contacto={seleccion.contacto}
        busquedaId={busquedaId} cerrar={() => setSeleccion(null)} />)}
    </main>
  )
}

export default function App() {
  const [ruta, setRuta] = useState(window.location.hash)
  useEffect(() => {
    const navegar = () => {
      setRuta(window.location.hash)
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', navegar)
    return () => window.removeEventListener('hashchange', navegar)
  }, [])
  const panel = ruta === '#/leads'
  return (
    <>
      <header className="barra-sitio">
        <nav className="barra-interior" aria-label="Navegación principal">
          <a className="marca" href="#/" aria-label="InmobiliarIA inicio">
            <span className="marca-icono" aria-hidden="true"><i /></span>
            <span>Inmobiliar<span className="marca-ia">IA</span></span>
          </a>
          <a className="enlace-panel" href={panel ? '#/' : '#/leads'}>
            {panel ? 'Volver al buscador' : 'Acceso ejecutivos'} <span aria-hidden="true">↗</span>
          </a>
        </nav>
      </header>
      {panel ? <AccesoLeads /> : <Buscador />}
    </>
  )
}
