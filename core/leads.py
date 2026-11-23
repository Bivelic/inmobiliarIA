"""Solicitudes de contacto con un ejecutivo de Aurora (EDT 4.5.3, RF-07).

- Se guardan en la tabla `lead` (la única con datos personales), solo con consentimiento
  expreso (RN-06, Ley 21.719), asociadas al aviso y a la búsqueda que las originó (RF-07.03).
- Cada una se avisa por correo a la casilla comercial de Aurora (RF-07.04) con Resend.
  Si el correo falla o no está configurado, la solicitud igual queda guardada.
"""

import html
import logging
import re

import httpx
import psycopg
from pydantic import BaseModel, Field, field_validator

from core.config import leads_correo_destino, leads_correo_remitente, resend_api_key

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")  # mismo patrón que la tabla lead
_TELEFONO = re.compile(r"^\+?[\d\s()-]{8,20}$")


class SolicitudContacto(BaseModel):
    publicacion_id: int
    busqueda_id: int | None = None
    nombre: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=200)
    telefono: str | None = Field(default=None, max_length=20)
    mensaje: str | None = Field(default=None, max_length=1000)
    consentimiento: bool

    @field_validator("nombre", "mensaje", "telefono", mode="before")
    @classmethod
    def _limpiar(cls, v):
        return v.strip() or None if isinstance(v, str) else v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("correo inválido")
        return v

    @field_validator("telefono")
    @classmethod
    def _telefono(cls, v: str | None) -> str | None:
        if v and not _TELEFONO.match(v):
            raise ValueError("teléfono inválido")
        return v

    @field_validator("consentimiento")
    @classmethod
    def _consentimiento(cls, v: bool) -> bool:
        if not v:
            raise ValueError("se requiere el consentimiento para usar tus datos (Ley 21.719)")
        return v


def guardar_lead(conn: psycopg.Connection, s: SolicitudContacto) -> dict | None:
    """Guarda la solicitud. Devuelve el lead con los datos del aviso (None si no existe)."""
    aviso = conn.execute(
        """
        SELECT p.id, p.titulo, p.url, po.nombre AS portal, p.precio_clp, c.nombre AS comuna
        FROM publicacion p JOIN portal po ON po.id = p.portal_id
        LEFT JOIN comuna c ON c.id = p.comuna_id
        WHERE p.id = %s
        """,
        (s.publicacion_id,),
    ).fetchone()
    if aviso is None:
        return None
    busqueda = None
    if s.busqueda_id is not None:
        busqueda = conn.execute(
            "SELECT id, texto FROM busqueda WHERE id = %s", (s.busqueda_id,)
        ).fetchone()
    fila = conn.execute(
        """
        INSERT INTO lead (publicacion_id, busqueda_id, nombre, email, telefono, mensaje,
                          consentimiento)
        VALUES (%s, %s, %s, %s, %s, %s, true)
        RETURNING id, creado_en
        """,
        (aviso["id"], busqueda["id"] if busqueda else None, s.nombre, s.email, s.telefono,
         s.mensaje),
    ).fetchone()
    return {
        "id": fila["id"],
        "creado_en": fila["creado_en"],
        "aviso": aviso,
        "busqueda": busqueda["texto"] if busqueda else None,
        "solicitud": s,
    }


def correo_html(lead: dict) -> tuple[str, str]:
    """Asunto y cuerpo del aviso a Aurora. Todo dato del usuario va escapado."""
    s: SolicitudContacto = lead["solicitud"]
    a = lead["aviso"]
    e = html.escape
    precio = f"${a['precio_clp']:,.0f}".replace(",", ".") if a["precio_clp"] else "Sin precio"
    filas = [
        ("Nombre", e(s.nombre)),
        ("Correo", f'<a href="mailto:{e(s.email)}">{e(s.email)}</a>'),
        ("Teléfono", e(s.telefono or "—")),
        ("Mensaje", e(s.mensaje or "—").replace("\n", "<br>")),
        ("Aviso", f'<a href="{e(a["url"])}">{e(a["titulo"])}</a> ({e(a["portal"])})'),
        ("Precio · comuna", f"{precio} · {e(a['comuna'] or 's/i')}"),
        ("Búsqueda", e(lead["busqueda"] or "(sin texto)")),
        ("Fecha", lead["creado_en"].strftime("%d/%m/%Y %H:%M")),
    ]
    cuerpo = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;color:#5b6475">{k}</td><td>{v}</td></tr>'
        for k, v in filas
    )
    asunto = f"Nuevo lead #{lead['id']}: {s.nombre} · {a['titulo'][:60]}"
    return asunto, (
        '<div style="font-family:Arial,sans-serif;font-size:14px">'
        "<p>Llegó una nueva solicitud de contacto desde InmobiliarIA.</p>"
        f"<table>{cuerpo}</table>"
        '<p style="color:#8a93a3;font-size:12px">La persona aceptó que Aurora Propiedades use '
        "estos datos solo para responder esta solicitud (Ley 21.719).</p></div>"
    )


def notificar(lead: dict, http: httpx.Client | None = None) -> bool:
    """Envía el correo a Aurora. Nunca lanza: devuelve True si Resend lo aceptó."""
    clave, destino = resend_api_key(), leads_correo_destino()
    if not clave or not destino:
        log.warning("Correo de leads sin configurar (RESEND_API_KEY / LEADS_CORREO_DESTINO)")
        return False
    asunto, cuerpo = correo_html(lead)
    cliente = http or httpx.Client(timeout=10)
    try:
        r = cliente.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {clave}"},
            json={
                "from": leads_correo_remitente(),
                "to": [destino],
                "reply_to": lead["solicitud"].email,
                "subject": asunto,
                "html": cuerpo,
            },
        )
    except httpx.HTTPError as e:
        log.error("No se pudo enviar el correo del lead %s: %s", lead["id"], e)
        return False
    if r.status_code >= 400:
        log.error("Resend rechazó el correo del lead %s: %s %s", lead["id"], r.status_code,
                  r.text[:300])
        return False
    return True


def resumen_leads(conn: psycopg.Connection, desde, hasta) -> dict:
    """Solicitudes y búsquedas en un período: tasa de contactos por búsqueda (RF-07.05)."""
    fila = conn.execute(
        """
        SELECT
          (SELECT count(*) FROM lead WHERE creado_en >= %(d)s AND creado_en < %(h)s) AS leads,
          (SELECT count(*) FROM busqueda
            WHERE creada_en >= %(d)s AND creada_en < %(h)s AND NOT es_validacion
              AND texto <> '') AS busquedas
        """,
        {"d": desde, "h": hasta},
    ).fetchone()
    tasa = round(fila["leads"] / fila["busquedas"], 4) if fila["busquedas"] else None
    return {"desde": desde, "hasta": hasta, "leads": fila["leads"],
            "busquedas": fila["busquedas"], "tasa_contacto": tasa}
