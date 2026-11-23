import { useEffect, useRef, useState, type FormEvent } from 'react'
import { enviarContacto, type AtributoAviso, type Aviso } from './api'

const pesos = (v: string | number | boolean | null) =>
  v != null && v !== false
    ? `$${Number(v).toLocaleString('es-CL', { maximumFractionDigits: 0 })}`
    : 'Sin precio'

const superficie = (a: Aviso) => {
  const m = a.m2_total ?? a.m2_util
  return m ? `${Number(m).toLocaleString('es-CL')} m²` : null
}

const PORTALES: Record<string, string> = {
  chilepropiedades: 'Chilepropiedades',
  toctoc: 'TocToc',
  yapo: 'Yapo',
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
function Contacto({ aviso, busquedaId, abiertoInicial }: {
  aviso: Aviso
  busquedaId: number | null
  abiertoInicial: boolean
}) {
  const [abierto, setAbierto] = useState(abiertoInicial)
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
      {error && <p className="error" role="alert">{error}</p>}
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

function PrecioAviso({ aviso }: { aviso: Aviso }) {
  return (
    <p className="aviso-precio">
      <strong>{pesos(aviso.precio_clp)}</strong>
      {aviso.gastos_comunes_clp != null && <span>+ {pesos(aviso.gastos_comunes_clp)} GC</span>}
    </p>
  )
}

function DatosAviso({ aviso }: { aviso: Aviso }) {
  const area = superficie(aviso)
  if (aviso.dormitorios == null && aviso.banos == null && !area) return null
  return (
    <ul className="datos" aria-label="Datos de la propiedad">
      {aviso.dormitorios != null && <li>{aviso.dormitorios} {aviso.dormitorios === 1 ? 'dormitorio' : 'dormitorios'}</li>}
      {aviso.banos != null && <li>{aviso.banos} {aviso.banos === 1 ? 'baño' : 'baños'}</li>}
      {area && <li>{area}</li>}
    </ul>
  )
}

function Descripcion({ aviso }: { aviso: Aviso }) {
  return aviso.extracto && (
    <p className="extracto">
      {aviso.extracto}
      {aviso.extracto.length >= 280 && '…'}
    </p>
  )
}

export function TarjetaAviso({ aviso, pedidos, abrir }: {
  aviso: Aviso
  pedidos: number
  abrir: (contactar: boolean) => void
}) {
  const portal = PORTALES[aviso.portal] ?? aviso.portal
  const coincidencias = aviso.coincidencias?.length ?? 0
  return (
    <li className="tarjeta-aviso">
      <div className="aviso-cabecera">
        <span className="aviso-comuna">{aviso.comuna ?? 'Sin comuna informada'}</span>
        <a className="aviso-portal" href={aviso.url} target="_blank" rel="noopener noreferrer"
          aria-label={`Ver aviso original de ${aviso.titulo} en ${portal}`}>
          {portal} <span aria-hidden="true">↗</span>
        </a>
      </div>
      <h3>{aviso.titulo}</h3>
      <PrecioAviso aviso={aviso} />
      <DatosAviso aviso={aviso} />
      {pedidos > 0 && (
        <p className={coincidencias ? 'calce' : 'calce sin-calce'}>
          {coincidencias
            ? `Cumple ${coincidencias} de ${pedidos} ${pedidos === 1 ? 'preferencia' : 'preferencias'}`
            : 'El aviso no menciona lo que pediste'}
        </p>
      )}
      <Etiquetas aviso={aviso} />
      <Descripcion aviso={aviso} />
      <div className="acciones">
        <button className="boton-texto" onClick={() => abrir(true)} aria-label="Quiero que me contacten">
          Contactar
        </button>
        <button className="secundario" onClick={() => abrir(false)} aria-label={`Ver ficha de ${aviso.titulo}`}>
          Ver ficha <span aria-hidden="true">→</span>
        </button>
      </div>
    </li>
  )
}

export function DetalleAviso({ aviso, busquedaId, contacto, cerrar }: {
  aviso: Aviso
  busquedaId: number | null
  contacto: boolean
  cerrar: () => void
}) {
  const dialogo = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const elemento = dialogo.current
    if (elemento && !elemento.open) elemento.showModal()
  }, [])

  return (
    <dialog ref={dialogo} className="detalle-aviso" aria-labelledby="titulo-detalle" onClose={cerrar}>
      <header className="detalle-cabecera">
        <span>Ficha del aviso</span>
        <button className="boton-cerrar" aria-label="Cerrar ficha" onClick={() => dialogo.current?.close()} autoFocus>×</button>
      </header>
      <div className="detalle-contenido">
        {aviso.comuna && <p className="aviso-comuna">{aviso.comuna}</p>}
        <h2 id="titulo-detalle">{aviso.titulo}</h2>
        <PrecioAviso aviso={aviso} />
        <DatosAviso aviso={aviso} />
        <Etiquetas aviso={aviso} />
        {aviso.extracto && (
          <section className="detalle-extracto">
            <h3>Descripción</h3>
            <Descripcion aviso={aviso} />
          </section>
        )}
        <a className="enlace-original" href={aviso.url} target="_blank" rel="noopener noreferrer">
          Ver aviso original en {PORTALES[aviso.portal] ?? aviso.portal} <span aria-hidden="true">↗</span>
        </a>
        <Contacto aviso={aviso} busquedaId={busquedaId} abiertoInicial={contacto} />
      </div>
    </dialog>
  )
}
