"""Autenticación de ejecutivos: hash de contraseñas con scrypt (solo librería estándar) y tokens JWT."""

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt  # PyJWT

from core.config import jwt_horas, jwt_secret

_N, _R, _P = 2**14, 8, 1  # costo de scrypt (usa ~16 MB de memoria por verificación)


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode()


def hashear_password(password: str) -> str:
    sal = os.urandom(16)
    derivada = hashlib.scrypt(password.encode(), salt=sal, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${_b64(sal)}${_b64(derivada)}"


def verificar_password(password: str, almacenado: str) -> bool:
    try:
        _, n, r, p, sal, esperado = almacenado.split("$")
        derivada = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p)
        )
        return hmac.compare_digest(derivada, base64.b64decode(esperado))
    except (ValueError, TypeError):
        return False


# Se compara contra este hash cuando el correo no existe, para que responder tarde lo mismo
HASH_FALSO = hashear_password("no-es-la-contrasena-de-nadie")


def crear_token(ejecutivo_id: int) -> str:
    ahora = datetime.now(timezone.utc)
    carga = {"sub": str(ejecutivo_id), "iat": ahora, "exp": ahora + timedelta(hours=jwt_horas())}
    return jwt.encode(carga, jwt_secret(), algorithm="HS256")


def leer_token(token: str) -> int | None:
    """Devuelve el id del ejecutivo, o None si el token es inválido o venció."""
    try:
        carga = jwt.decode(token, jwt_secret(), algorithms=["HS256"])
        return int(carga["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
