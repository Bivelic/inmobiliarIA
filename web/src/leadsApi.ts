import { API_URL } from './api'

export const ESTADOS = {
  nuevo: 'Nuevo',
  contactado: 'Contactado',
  visita_agendada: 'Visita agendada',
  cerrado: 'Cerrado',
  descartado: 'Descartado',
}

export type Estado = keyof typeof ESTADOS
export type Ejecutivo = { id: number; nombre: string }
export type Sesion = { token: string; ejecutivo: Ejecutivo }

export type Lead = {
  id: number
  nombre: string
  email: string
  telefono: string | null
  mensaje: string | null
  estado: Estado
  ejecutivo_id: number | null
  ejecutivo_nombre: string | null
  creado_en: string
  primera_respuesta_en: string | null
  visita_agendada_en: string | null
  publicacion_titulo: string | null
  publicacion_url: string | null
  portal: string | null
}

export type LeadCambio = { estado?: Estado; ejecutivo_id?: number | null }

export type Periodo = {
  desde: string
  hasta: string
  recibidas: number
  sin_respuesta: number
  con_respuesta: number
  mediana_primera_respuesta_min: number | null
  promedio_primera_respuesta_min: number | null
  visitas_agendadas: number
  tasa_visitas_pct: number | null
}

export type Indicadores = { periodo: Periodo; anterior: Periodo }
export type PaginaLeads = { total: number; resultados: Lead[] }
export type FiltrosLeads = { estado: string; asignacion: string; desde: string; hasta: string }
export const LEADS_POR_PAGINA = 30

export class ErrorLeads extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function solicitar<T>(ruta: string, init: RequestInit, token?: string): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const respuesta = await fetch(new URL(ruta, API_URL), { ...init, headers, cache: 'no-store' })
  if (!respuesta.ok) {
    const datos = await respuesta.json().catch(() => null)
    const mensaje = typeof datos?.detail === 'string'
      ? datos.detail
      : `No se pudo completar la solicitud (HTTP ${respuesta.status}).`
    throw new ErrorLeads(respuesta.status, mensaje)
  }
  return respuesta.json() as Promise<T>
}

export const iniciarSesion = (email: string, password: string) =>
  solicitar<Sesion>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })

export const consultarSesion = (token: string, signal: AbortSignal) =>
  solicitar<Ejecutivo>('/auth/yo', { signal }, token)

export const listarEjecutivos = (token: string, signal: AbortSignal) =>
  solicitar<Ejecutivo[]>('/ejecutivos', { signal }, token)

export function listarLeads(token: string, filtros: FiltrosLeads, pagina: number, signal: AbortSignal) {
  const p = new URLSearchParams({
    limite: String(LEADS_POR_PAGINA),
    salto: String(pagina * LEADS_POR_PAGINA),
  })
  if (filtros.estado) p.set('estado', filtros.estado)
  if (filtros.asignacion === 'sin_asignar') p.set('sin_asignar', 'true')
  else if (filtros.asignacion) p.set('ejecutivo_id', filtros.asignacion)
  if (filtros.desde) p.set('fecha_desde', filtros.desde)
  if (filtros.hasta) p.set('fecha_hasta', filtros.hasta)
  return solicitar<PaginaLeads>(`/leads?${p}`, { signal }, token)
}

export function consultarIndicadores(token: string, desde: string, hasta: string, signal: AbortSignal) {
  const p = new URLSearchParams()
  if (desde) p.set('desde', desde)
  if (hasta) p.set('hasta', hasta)
  return solicitar<Indicadores>(`/leads/indicadores?${p}`, { signal }, token)
}

export const actualizarLead = (token: string, id: number, cambio: LeadCambio) =>
  solicitar<Lead>(`/leads/${id}`, { method: 'PATCH', body: JSON.stringify(cambio) }, token)
