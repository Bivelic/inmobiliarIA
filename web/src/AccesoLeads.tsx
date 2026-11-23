import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { consultarSesion, ErrorLeads, iniciarSesion, type Sesion } from './leadsApi'
import PanelLeads from './PanelLeads'
import santiago from './assets/santiago-departamentos.webp'
import './leads.css'

const CLAVE_SESION = 'inmobiliaria.sesionEjecutivo'

export default function AccesoLeads() {
  const [sesion, setSesion] = useState<Sesion | null>(null)
  const [comprobando, setComprobando] = useState(() => Boolean(sessionStorage.getItem(CLAVE_SESION)))
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState('')
  const cerrarSesion = useCallback((mensaje = '') => {
    sessionStorage.removeItem(CLAVE_SESION)
    setSesion(null)
    setError(mensaje)
  }, [])

  useEffect(() => {
    const token = sessionStorage.getItem(CLAVE_SESION)
    if (!token) return
    const controller = new AbortController()
    consultarSesion(token, controller.signal)
      .then(ejecutivo => {
        if (!controller.signal.aborted) setSesion({ token, ejecutivo })
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return
        cerrarSesion(e instanceof ErrorLeads && e.status === 401
          ? 'Tu sesión venció. Vuelve a ingresar.'
          : 'No se pudo recuperar la sesión. Puedes volver a ingresar.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setComprobando(false)
      })
    return () => controller.abort()
  }, [cerrarSesion])

  function ingresar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault()
    const form = new FormData(evento.currentTarget)
    setEnviando(true)
    setError('')
    iniciarSesion(String(form.get('email')).trim(), String(form.get('password')))
      .then(nueva => {
        sessionStorage.setItem(CLAVE_SESION, nueva.token)
        setSesion(nueva)
      })
      .catch((e: unknown) => setError(e instanceof ErrorLeads
        ? e.message
        : 'No se pudo conectar con el servidor. Intenta de nuevo.'))
      .finally(() => setEnviando(false))
  }

  if (sesion) return <PanelLeads sesion={sesion} cerrarSesion={cerrarSesion} />

  return (
    <main className="acceso-leads">
      <img className="acceso-imagen" src={santiago} alt="" />
      <section className="acceso-tarjeta">
        <h1>Acceso ejecutivos</h1>
        <p>Ingresa con tu cuenta de Aurora Propiedades.</p>
        {comprobando ? <p role="status">Comprobando sesión…</p> : (
          <form onSubmit={ingresar} className="formulario-acceso">
            <label>Correo
              <input type="email" name="email" autoComplete="username" required maxLength={200} />
            </label>
            <label>Contraseña
              <input type="password" name="password" autoComplete="current-password" required maxLength={256} />
            </label>
            {error && <p role="alert" className="error">{error}</p>}
            <button className="buscar" disabled={enviando}>
              {enviando ? 'Ingresando…' : 'Iniciar sesión'}
            </button>
          </form>
        )}
      </section>
    </main>
  )
}
