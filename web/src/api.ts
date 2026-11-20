// Cliente de la API. La URL viene de VITE_API_URL (archivo web/.env.local o variable en Vercel).
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// La API puede mandar los montos como número o como texto: siempre se leen con Number().
type Monto = string | number | null

export type AtributoAviso = {
  codigo: string
  nombre: string
  tipo: 'booleano' | 'numero' | 'texto'
  valor: boolean | number | string
}

export type Aviso = {
  id: number
  portal: string
  url: string
  titulo: string
  extracto: string | null
  precio_clp: Monto
  precio_uf: Monto
  gastos_comunes_clp: Monto
  comuna: string | null
  dormitorios: number | null
  banos: number | null
  m2_total: Monto
  m2_util: Monto
  puntaje?: number
  coincidencias?: string[] // atributos pedidos que este aviso cumple
  atributos?: AtributoAviso[] // detectados por la IA en la descripción
}

export type Interpretacion = {
  interpretado: boolean | null // null = no se escribió texto
  desde_cache: boolean
  aviso: string | null // ej. "se buscó por palabras" si la IA no respondió
  resumen: string[] // lo que se entendió, listo para mostrar
  criterios: { atributos: Record<string, unknown> }
}

export type RespuestaBusqueda = {
  busqueda_id: number | null
  total: number
  duracion_ms: number
  interpretacion: Interpretacion
  resultados: Aviso[]
}

export type Comuna = { slug: string; nombre: string; avisos: number }

export type Orden = 'relevancia' | 'recientes' | 'precio_asc' | 'precio_desc'

export type Filtros = {
  q?: string // búsqueda escrita en lenguaje natural
  comuna?: string
  precio_max?: string
  dormitorios_min?: string
  orden?: Orden
}

export const POR_PAGINA = 30

// Identificador anónimo de esta pestaña: agrupa las búsquedas de una sesión (sin datos personales).
const SESION = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : undefined

async function get<T>(ruta: string, params: Record<string, string | undefined> = {}): Promise<T> {
  const url = new URL(ruta, API_URL)
  for (const [k, v] of Object.entries(params)) if (v) url.searchParams.set(k, v)
  const r = await fetch(url)
  if (!r.ok) throw new Error(`Error ${r.status} al consultar ${ruta}`)
  return r.json() as Promise<T>
}

/** `desde` = avisos ya mostrados; `busquedaId` = el de la primera página (para "Cargar más"). */
export const buscarAvisos = (f: Filtros, desde = 0, busquedaId?: number | null) =>
  get<RespuestaBusqueda>('/buscar', {
    ...f,
    q: f.q?.trim() || undefined,
    limite: String(POR_PAGINA),
    desde: String(desde),
    sesion: SESION,
    busqueda_id: busquedaId ? String(busquedaId) : undefined,
  })

export const listarComunas = () => get<Comuna[]>('/comunas')

// --- Solicitud de contacto con un ejecutivo de Aurora (RF-07) ---
export type DatosContacto = {
  publicacion_id: number
  busqueda_id: number | null // la búsqueda que llevó a este aviso (RF-07.03)
  nombre: string
  email: string
  telefono?: string
  mensaje?: string
  consentimiento: boolean
}

export async function enviarContacto(datos: DatosContacto): Promise<{ id: number }> {
  const r = await fetch(new URL('/leads', API_URL), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  })
  if (!r.ok) {
    let detalle = `Error ${r.status} al enviar la solicitud`
    try {
      const cuerpo = await r.json()
      if (Array.isArray(cuerpo.detail)) {
        // Errores de validación de la API: se muestran en palabras simples
        detalle = cuerpo.detail
          .map((e: { msg: string }) => e.msg.replace(/^Value error, /, ''))
          .join('. ')
      } else if (typeof cuerpo.detail === 'string') {
        detalle = cuerpo.detail
      }
    } catch {
      // respuesta sin JSON: se deja el mensaje general
    }
    throw new Error(detalle)
  }
  return r.json()
}
