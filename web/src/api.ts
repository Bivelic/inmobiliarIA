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
  m2_util: string | null
}

export type Comuna = { slug: string; nombre: string; avisos: number }

export type Orden = 'recientes' | 'precio_asc' | 'precio_desc'

export type Filtros = {
  comuna?: string
  precio_max?: string
  dormitorios_min?: string
  orden?: Orden
}

export const POR_PAGINA = 30

async function get<T>(ruta: string, params: Record<string, string | undefined> = {}): Promise<T> {
  const url = new URL(ruta, API_URL)
  for (const [k, v] of Object.entries(params)) if (v) url.searchParams.set(k, v)
  const r = await fetch(url)
  if (!r.ok) throw new Error(`Error ${r.status} al consultar ${ruta}`)
  return r.json() as Promise<T>
}

export const buscarAvisos = (f: Filtros, desde = 0) =>
  get<{ total: number; resultados: Aviso[] }>('/publicaciones', {
    ...f,
    limite: String(POR_PAGINA),
    desde: String(desde),
  })

export const listarComunas = () => get<Comuna[]>('/comunas')
