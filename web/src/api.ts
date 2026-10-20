// Cliente mínimo de la API. La URL viene de VITE_API_URL (archivo web/.env.local).
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Aviso = {
  id: number
  portal: string
  url: string
  titulo: string
  extracto: string | null
  precio_clp: string | null
  precio_uf: string | null
  gastos_comunes_clp: string | null
  comuna: string | null
  dormitorios: number | null
  banos: number | null
  m2_total: string | null
}

export type Comuna = { slug: string; nombre: string; avisos: number }

export type Filtros = { comuna?: string; precio_max?: string; dormitorios_min?: string }

async function get<T>(ruta: string, params: Record<string, string | undefined> = {}): Promise<T> {
  const url = new URL(ruta, API_URL)
  for (const [k, v] of Object.entries(params)) if (v) url.searchParams.set(k, v)
  const r = await fetch(url)
  if (!r.ok) throw new Error(`Error ${r.status} al consultar ${ruta}`)
  return r.json() as Promise<T>
}

export const buscarAvisos = (f: Filtros) =>
  get<{ total: number; resultados: Aviso[] }>('/publicaciones', { ...f, limite: '50' })

export const listarComunas = () => get<Comuna[]>('/comunas')
