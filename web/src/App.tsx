import { useEffect, useState, type FormEvent } from 'react'
import {
  buscarAvisos,
  enviarContacto,
  listarComunas,
  type AtributoAviso,
  type Aviso,
  type Comuna,
  type Filtros,
  type Interpretacion,
  type Orden,
} from './api'

// Lo que se edita en el formulario y solo se aplica al apretar "Buscar".
type Borrador = Omit<Filtros, 'orden'>

// Búsquedas de ejemplo: muestran qué se puede escribir (y sirven para la demo).
const EJEMPLOS = [
  'Depto en Ñuñoa que acepte perros',
  'Amoblado cerca del metro hasta 600 mil',
  '2 dormitorios con estacionamiento en Providencia',
  'Con piscina y gimnasio en Las Condes',
]

const pesos = (v: string | number | boolean | null) =>
  v != null && v !== false
    ? `$${Number(v).toLocaleString('es-CL', { maximumFractionDigits: 0 })}`
    : 'Sin precio'

const superficie = (a: Aviso) => {
  const m = a.m2_total ?? a.m2_util
  return m ? ` · ${Number(m).toLocaleString('es-CL')} m²` : ''
}

// Texto de la etiqueta de un atributo detectado por la IA (RF-06.08).
const etiqueta = (a: AtributoAviso) => {
  if (a.tipo === 'booleano') return a.nombre
  if (a.codigo === 'estacion_metro') return `Metro ${a.valor}`
  if (a.codigo.endsWith('_clp')) return `${a.nombre.replace(/\s*\(CLP\)/, '')} ${pesos(a.valor)}`
  if (a.codigo === 'orientacion') return `Orientación ${a.valor}`
  return `${a.nombre}: ${a.valor}`
}

function Etiquetas({ aviso }: { aviso: Aviso }) {
  const atributos = aviso.atributos ?? []
  if (atributos.length === 0) return null
  const calzan = new Set(aviso.coincidencias ?? [])
  // Primero las que calzan con lo pedido, después el resto.
  const ordenados = [...atributos].sort(
    (a, b) => Number(calzan.has(b.codigo)) - Number(calzan.has(a.codigo)),
  )
  return (
    <ul className="etiquetas" aria-label="Características detectadas en la descripción">
      {ordenados.map((a) => {
        const no = a.valor === false
        const clase = ['etiqueta', calzan.has(a.codigo) ? 'coincide' : '', no ? 'no' : '']
          .filter(Boolean)
          .join(' ')
        return (
          <li key={a.codigo} className={clase} title={no ? `No: ${a.nombre}` : undefined}>
            {calzan.has(a.codigo) && '✓ '}
            {no && '✕ '}
            {etiqueta(a)}
          </li>
        )
      })}
    </ul>
  )
}

// Botón "Quiero que me contacten" y su formulario, dentro de cada aviso (RF-07.01 y 07.02).
function Contacto({ aviso, busquedaId }: { aviso: Aviso; busquedaId: number | null }) {
  const [abierto, setAbierto] = useState(false)
  const [nombre, setNombre] = useState('')
  const [email, setEmail] = useState('')
  const [telefono, setTelefono] = useState('')
  const [mensaje, setMensaje] = useState('Hola, me interesa este departamento.')
  const [consentimiento, setConsentimiento] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [enviado, setEnviado] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (enviado) {
    return (
      <p className="contacto-ok" role="status">
        ¡Listo, {nombre.split(' ')[0]}! Un ejecutivo de Aurora Propiedades te contactará pronto.
      </p>
    )
  }

  if (!abierto) {
    return (
      <button type="button" className="contactar" onClick={() => setAbierto(true)}>
        Quiero que me contacten
      </button>
    )
  }

  const enviar = (evento: FormEvent) => {
    evento.preventDefault()
    setEnviando(true)
    setError(null)
    enviarContacto({
      publicacion_id: aviso.id,
      busqueda_id: busquedaId,
      nombre,
      email,
      telefono: telefono || undefined,
      mensaje: mensaje || undefined,
      consentimiento,
    })
      .then(() => setEnviado(true))
      .catch((e: Error) => setError(e.message))
      .finally(() => setEnviando(false))
  }

  const id = (campo: string) => `contacto-${aviso.id}-${campo}`
  return (
    <form className="contacto" onSubmit={enviar}>
      <p className="contacto-titulo">Un ejecutivo de Aurora Propiedades te contactará por este aviso.</p>
      <div className="contacto-campos">
        <label htmlFor={id('nombre')}>
          Nombre
          <input id={id('nombre')} required minLength={2} maxLength={100} value={nombre}
            onChange={(e) => setNombre(e.target.value)} autoComplete="name" />
        </label>
        <label htmlFor={id('email')}>
          Correo
          <input id={id('email')} type="email" required maxLength={200} value={email}
            onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </label>
        <label htmlFor={id('telefono')}>
          Teléfono (opcional)
          <input id={id('telefono')} type="tel" maxLength={20} value={telefono}
            onChange={(e) => setTelefono(e.target.value)} autoComplete="tel"
            placeholder="+56 9 1234 5678" />
        </label>
      </div>
      <label htmlFor={id('mensaje')} className="contacto-mensaje">
        Mensaje (opcional)
        <textarea id={id('mensaje')} rows={2} maxLength={1000} value={mensaje}
          onChange={(e) => setMensaje(e.target.value)} />
      </label>
      <label className="consentimiento">
        <input type="checkbox" checked={consentimiento}
          onChange={(e) => setConsentimiento(e.target.checked)} />
        Acepto que Aurora Propiedades use estos datos solo para contactarme por este aviso. No se
        comparten con terceros (Ley 21.719).
      </label>
      {error && <p className="error">{error}</p>}
      <div className="contacto-botones">
        <button type="submit" className="buscar" disabled={!consentimiento || enviando}>
          {enviando ? 'Enviando…' : 'Enviar solicitud'}
        </button>
        <button type="button" className="cancelar" onClick={() => setAbierto(false)}>
          Cancelar
        </button>
      </div>
    </form>
  )
}

export default function App() {
  const [filtros, setFiltros] = useState<Filtros>({ orden: 'relevancia' })
  const [borrador, setBorrador] = useState<Borrador>({})
  const [comunas, setComunas] = useState<Comuna[]>([])
  const [avisos, setAvisos] = useState<Aviso[]>([])
  const [total, setTotal] = useState(0)
  const [interpretacion, setInterpretacion] = useState<Interpretacion | null>(null)
  const [busquedaId, setBusquedaId] = useState<number | null>(null)
  const [cargando, setCargando] = useState(false)
  const [cargandoMas, setCargandoMas] = useState(false)
  const [mostrarResultados, setMostrarResultados] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listarComunas()
      .then(setComunas)
      .catch(() => setComunas([]))
  }, [])

  // Ejecuta la búsqueda cada vez que cambian los filtros aplicados.
  useEffect(() => {
    let vigente = true

    setCargando(true)
    setError(null)
    setAvisos([])
    setTotal(0)

    buscarAvisos(filtros)
      .then((r) => {
        if (!vigente) return
        setAvisos(r.resultados)
        setTotal(r.total)
        setInterpretacion(r.interpretacion)
        setBusquedaId(r.busqueda_id)
      })
      .catch((e: Error) => {
        if (vigente) setError(e.message)
      })
      .finally(() => {
        if (vigente) setCargando(false)
      })

    return () => {
      vigente = false
    }
  }, [filtros])

  // Carga más resultados de la misma búsqueda.
  const cargarMas = () => {
    setCargandoMas(true)

    buscarAvisos(filtros, avisos.length, busquedaId)
      .then((r) => {
        setAvisos((actuales) => {
          const vistos = new Set(actuales.map((a) => a.id))
          return [...actuales, ...r.resultados.filter((a) => !vistos.has(a.id))]
        })
        setTotal(r.total)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargandoMas(false))
  }

  // Escribir en el formulario solo actualiza el borrador.
  const cambiar = (campo: keyof Borrador) => (evento: { target: { value: string } }) =>
    setBorrador((previo) => ({ ...previo, [campo]: evento.target.value || undefined }))

  // Aplica el texto y los filtros, y vuelve a mostrar los resultados.
  const buscar = (evento: FormEvent) => {
    evento.preventDefault()
    setMostrarResultados(true)
    setFiltros((previo) => ({ ...previo, ...borrador }))
  }

  // Un ejemplo se escribe en la caja y se busca de inmediato.
  const usarEjemplo = (texto: string) => {
    setBorrador((previo) => ({ ...previo, q: texto }))
    setMostrarResultados(true)
    setFiltros((previo) => ({ ...previo, ...borrador, q: texto }))
  }

  const quedan = total - avisos.length
  const pedidos = Object.keys(interpretacion?.criterios.atributos ?? {}).length
  const hayTexto = Boolean(filtros.q?.trim())

  return (
    <main>
      <header>
        <h1>InmobiliarIA</h1>
        <p>
          Departamentos en arriendo de varios portales inmobiliarios en un solo lugar. Escribe lo
          que buscas con tus palabras.
        </p>
      </header>

      <form className="buscador" onSubmit={buscar}>
        <label className="campo-texto" htmlFor="q">
          ¿Qué estás buscando?
        </label>
        <div className="fila-busqueda">
          <input
            id="q"
            type="search"
            value={borrador.q ?? ''}
            onChange={cambiar('q')}
            maxLength={300}
            placeholder="Ej: depto en Ñuñoa que acepte perros, cerca del metro, hasta 600 mil"
          />
          <button type="submit" className="buscar" disabled={cargando}>
            {cargando ? 'Buscando…' : 'Buscar'}
          </button>
        </div>

        <div className="ejemplos">
          <span>Prueba:</span>
          {EJEMPLOS.map((texto) => (
            <button key={texto} type="button" onClick={() => usarEjemplo(texto)}>
              {texto}
            </button>
          ))}
        </div>

        <div className="filtros">
          <label>
            Comuna
            <select onChange={cambiar('comuna')} defaultValue="">
              <option value="">Todas</option>
              {comunas.map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.nombre} ({c.avisos})
                </option>
              ))}
            </select>
          </label>

          <label>
            Precio máximo (CLP)
            <input type="number" min={0} step={50000} onChange={cambiar('precio_max')} />
          </label>

          <label>
            Dormitorios mínimos
            <input type="number" min={0} max={10} onChange={cambiar('dormitorios_min')} />
          </label>

          <label>
            Ordenar por
            <select
              value={filtros.orden}
              onChange={(e) => setFiltros((f) => ({ ...f, orden: e.target.value as Orden }))}
            >
              <option value="relevancia">Más relevantes</option>
              <option value="recientes">Más recientes</option>
              <option value="precio_asc">Precio: menor a mayor</option>
              <option value="precio_desc">Precio: mayor a menor</option>
            </select>
          </label>
        </div>
        <p className="nota">Los filtros de arriba mandan sobre lo que escribas en el texto.</p>
      </form>

      {/* Controles de visualización de resultados */}
      {(avisos.length > 0 || cargando || error) && (
        <button
          type="button"
          className="cargar-mas"
          onClick={() => setMostrarResultados((previo) => !previo)}
        >
          {mostrarResultados ? 'Ocultar resultados' : 'Mostrar resultados'}
        </button>
      )}

      {/* Resultados */}
      {mostrarResultados && (
        <>
          {error && <p className="error">No se pudo cargar: {error}</p>}

          {/* Lo que se entendió de la búsqueda (RNF-04) */}
          {!cargando && hayTexto && interpretacion && (
            <section className="entendido" aria-live="polite">
              {interpretacion.resumen.length > 0 ? (
                <>
                  <span>Buscamos:</span>
                  <ul>
                    {interpretacion.resumen.map((parte) => (
                      <li key={parte}>{parte}</li>
                    ))}
                  </ul>
                </>
              ) : (
                <span>No reconocimos criterios en el texto; te mostramos lo más parecido.</span>
              )}
              {interpretacion.aviso && <p className="nota">{interpretacion.aviso}</p>}
            </section>
          )}

          <p className="total">
            {cargando
              ? 'Cargando…'
              : `Mostrando ${avisos.length} de ${total} ${total === 1 ? 'aviso' : 'avisos'}`}
          </p>

          <ul className="avisos">
            {avisos.map((a) => (
              <li key={a.id}>
                <h2>{a.titulo}</h2>

                <p className="datos">
                  <strong>{pesos(a.precio_clp)}</strong>
                  {a.gastos_comunes_clp != null && ` + ${pesos(a.gastos_comunes_clp)} GC`}
                  {' · '}
                  {a.comuna ?? 'Comuna s/i'}
                  {a.dormitorios != null && ` · ${a.dormitorios}D`}
                  {a.banos != null && `/${a.banos}B`}
                  {superficie(a)}
                </p>

                {pedidos > 0 && (
                  <p className={a.coincidencias?.length ? 'calce' : 'calce sin-calce'}>
                    {a.coincidencias?.length
                      ? `Cumple ${a.coincidencias.length} de ${pedidos} ${
                          pedidos === 1 ? 'preferencia' : 'preferencias'
                        }`
                      : 'El aviso no menciona lo que pediste'}
                  </p>
                )}

                <Etiquetas aviso={a} />

                {a.extracto && (
                  <p className="extracto">
                    {a.extracto}
                    {a.extracto.length >= 280 && '…'}
                  </p>
                )}

                <div className="acciones">
                  <a href={a.url} target="_blank" rel="noopener noreferrer">
                    Ver aviso original en {a.portal}
                  </a>
                </div>
                <Contacto aviso={a} busquedaId={busquedaId} />
              </li>
            ))}
          </ul>

          {!cargando && quedan > 0 && (
            <button className="cargar-mas" onClick={cargarMas} disabled={cargandoMas}>
              {cargandoMas ? 'Cargando…' : `Cargar más (quedan ${quedan})`}
            </button>
          )}
        </>
      )}
    </main>
  )
}
