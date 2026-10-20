// Página mínima para la Entrega 2: listado con filtros simples y enlace al aviso original.
// Es la base sobre la que se construye la interfaz final (H4).
import { useEffect, useState } from 'react'
import { buscarAvisos, listarComunas, type Aviso, type Comuna, type Filtros } from './api'

const pesos = (v: string | null) =>
  v ? `$${Number(v).toLocaleString('es-CL', { maximumFractionDigits: 0 })}` : 'Sin precio'

export default function App() {
  const [filtros, setFiltros] = useState<Filtros>({})
  const [comunas, setComunas] = useState<Comuna[]>([])
  const [avisos, setAvisos] = useState<Aviso[]>([])
  const [total, setTotal] = useState(0)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listarComunas().then(setComunas).catch(() => setComunas([]))
  }, [])

  useEffect(() => {
    setCargando(true)
    setError(null)
    buscarAvisos(filtros)
      .then((r) => {
        setAvisos(r.resultados)
        setTotal(r.total)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setCargando(false))
  }, [filtros])

  const cambiar = (campo: keyof Filtros) => (e: { target: { value: string } }) =>
    setFiltros((f) => ({ ...f, [campo]: e.target.value || undefined }))

  return (
    <main>
      <header>
        <h1>InmobiliarIA</h1>
        <p>Departamentos en arriendo de Chilepropiedades, Yapo y Economicos en un solo lugar.</p>
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
      </section>

      {error && <p className="error">No se pudo cargar: {error}</p>}
      <p className="total">{cargando ? 'Cargando…' : `${total} ${total === 1 ? 'aviso' : 'avisos'}`}</p>

      <ul className="avisos">
        {avisos.map((a) => (
          <li key={a.id}>
            <h2>{a.titulo}</h2>
            <p className="datos">
              <strong>{pesos(a.precio_clp)}</strong>
              {a.gastos_comunes_clp && ` + ${pesos(a.gastos_comunes_clp)} GC`} · {a.comuna ?? 'Comuna s/i'}
              {a.dormitorios != null && ` · ${a.dormitorios}D`}
              {a.banos != null && `/${a.banos}B`}
              {a.m2_total && ` · ${Number(a.m2_total)} m²`}
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
    </main>
  )
}
