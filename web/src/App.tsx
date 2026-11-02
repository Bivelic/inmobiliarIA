import { useEffect, useState, type FormEvent } from 'react'
import {
  buscarAvisos,
  listarComunas,
  type Aviso,
  type Comuna,
  type Filtros,
  type Orden,
} from './api'

// Filtros que se editan en el formulario y solo se aplican al apretar "Buscar".
type Borrador = Omit<Filtros, 'orden'>

const pesos = (v: string | null) =>
  v ? `$${Number(v).toLocaleString('es-CL', { maximumFractionDigits: 0 })}` : 'Sin precio'

const superficie = (a: Aviso) => {
  const m = a.m2_total ?? a.m2_util
  return m ? ` · ${Number(m).toLocaleString('es-CL')} m²` : ''
}

export default function App() {
  const [filtros, setFiltros] = useState<Filtros>({ orden: 'recientes' })
  const [borrador, setBorrador] = useState<Borrador>({})
  const [comunas, setComunas] = useState<Comuna[]>([])
  const [avisos, setAvisos] = useState<Aviso[]>([])
  const [total, setTotal] = useState(0)
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

  // Carga más resultados utilizando los filtros aplicados.
  const cargarMas = () => {
    setCargandoMas(true)

    buscarAvisos(filtros, avisos.length)
      .then((r) => {
        setAvisos((actuales) => {
          const vistos = new Set(actuales.map((a) => a.id))
          return [
            ...actuales,
            ...r.resultados.filter((a) => !vistos.has(a.id)),
          ]
        })
        setTotal(r.total)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargandoMas(false))
  }

  // Escribir en el formulario solo actualiza el borrador.
  const cambiar = (campo: keyof Borrador) =>
    (evento: { target: { value: string } }) =>
      setBorrador((previo) => ({
        ...previo,
        [campo]: evento.target.value || undefined,
      }))

  // Aplica los filtros y vuelve a mostrar los resultados.
  const buscar = (evento: FormEvent) => {
    evento.preventDefault()
    setMostrarResultados(true)
    setFiltros((previo) => ({ ...previo, ...borrador }))
  }

  const quedan = total - avisos.length

  return (
    <main>
      <header>
        <h1>InmobiliarIA</h1>
        <p>
          Departamentos en arriendo de varios portales inmobiliarios en un solo lugar.
        </p>
      </header>

      <form className="filtros" onSubmit={buscar}>
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
          <input
            type="number"
            min={0}
            step={50000}
            onChange={cambiar('precio_max')}
          />
        </label>

        <label>
          Dormitorios mínimos
          <input
            type="number"
            min={0}
            max={10}
            onChange={cambiar('dormitorios_min')}
          />
        </label>

        <label>
          Ordenar por
          <select
            value={filtros.orden}
            onChange={(e) =>
              setFiltros((f) => ({
                ...f,
                orden: e.target.value as Orden,
              }))
            }
          >
            <option value="recientes">Más recientes</option>
            <option value="precio_asc">Precio: menor a mayor</option>
            <option value="precio_desc">Precio: mayor a menor</option>
          </select>
        </label>

        <button type="submit" className="buscar" disabled={cargando}>
          {cargando ? 'Buscando…' : 'Buscar'}
        </button>
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

          <p className="total">
            {cargando
              ? 'Cargando…'
              : `Mostrando ${avisos.length} de ${total} ${
                  total === 1 ? 'aviso' : 'avisos'
                }`}
          </p>

          <ul className="avisos">
            {avisos.map((a) => (
              <li key={a.id}>
                <h2>{a.titulo}</h2>

                <p className="datos">
                  <strong>{pesos(a.precio_clp)}</strong>
                  {a.gastos_comunes_clp &&
                    ` + ${pesos(a.gastos_comunes_clp)} GC`}
                  {' · '}
                  {a.comuna ?? 'Comuna s/i'}
                  {a.dormitorios != null && ` · ${a.dormitorios}D`}
                  {a.banos != null && `/${a.banos}B`}
                  {superficie(a)}
                </p>

                {a.extracto && (
                  <p className="extracto">
                    {a.extracto}
                    {a.extracto.length >= 280 && '…'}
                  </p>
                )}

                <a
                  href={a.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Ver aviso original en {a.portal}
                </a>
              </li>
            ))}
          </ul>

          {!cargando && quedan > 0 && (
            <button
              className="cargar-mas"
              onClick={cargarMas}
              disabled={cargandoMas}
            >
              {cargandoMas
                ? 'Cargando…'
                : `Cargar más (quedan ${quedan})`}
            </button>
          )}
        </>
      )}
    </main>
  )
}