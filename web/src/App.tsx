import { useEffect, useState } from 'react'
import { buscarAvisos, listarComunas, type Aviso, type Comuna, type Filtros, type Orden } from './api'

const pesos = (v: string | null) =>
  v ? `$${Number(v).toLocaleString('es-CL', { maximumFractionDigits: 0 })}` : 'Sin precio'

const superficie = (a: Aviso) => {
  const m2 = a.m2_total ?? a.m2_util
  return m2 ? ` · ${Number(m2).toLocaleString('es-CL')} m²` : ''
}

export default function App() {
  const [filtros, setFiltros] = useState<Filtros>({ orden: 'recientes' })
  const [comunas, setComunas] = useState<Comuna[]>([])
  const [avisos, setAvisos] = useState<Aviso[]>([])
  const [total, setTotal] = useState(0)
  const [cargando, setCargando] = useState(false)
  const [cargandoMas, setCargandoMas] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listarComunas().then(setComunas).catch(() => setComunas([]))
  }, [])

  useEffect(() => {
    let vigente = true 
    setCargando(true)
    setError(null)
    buscarAvisos(filtros)
      .then((r) => {
        if (!vigente) return
        setAvisos(r.resultados)
        setTotal(r.total)
      })
      .catch((e: Error) => vigente && setError(e.message))
      .finally(() => vigente && setCargando(false))
    return () => {
      vigente = false
    }
  }, [filtros])

  const cargarMas = () => {
    setCargandoMas(true)
    buscarAvisos(filtros, avisos.length)
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

  const cambiar = (campo: keyof Filtros) => (e: { target: { value: string } }) =>
    setFiltros((f) => ({ ...f, [campo]: e.target.value || undefined }))

  const quedan = total - avisos.length

  return (
    <main>
      <header>
        <h1>InmobiliarIA</h1>
        <p>Departamentos en arriendo de varios portales inmobiliarios en un solo lugar.</p>
      </header>

      <section className="filtros">
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
            <option value="recientes">Más recientes</option>
            <option value="precio_asc">Precio: menor a mayor</option>
            <option value="precio_desc">Precio: mayor a menor</option>
          </select>
        </label>
      </section>

      {error && <p className="error">No se pudo cargar: {error}</p>}
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
              {a.gastos_comunes_clp && ` + ${pesos(a.gastos_comunes_clp)} GC`} · {a.comuna ?? 'Comuna s/i'}
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
            <a href={a.url} target="_blank" rel="noopener noreferrer">
              Ver aviso original en {a.portal}
            </a>
          </li>
        ))}
      </ul>

      {!cargando && quedan > 0 && (
        <button className="cargar-mas" onClick={cargarMas} disabled={cargandoMas}>
          {cargandoMas ? 'Cargando…' : `Cargar más (quedan ${quedan})`}
        </button>
      )}
    </main>
  )
}
