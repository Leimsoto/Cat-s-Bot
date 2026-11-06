"""Política común para URLs de radio consumidas por el servidor."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urldefrag, urlsplit


MAX_RADIO_URL_LENGTH = 2048


class RadioURLPolicyError(ValueError):
    """La URL no es apta para una conexión saliente del bot."""


def validate_public_http_url(value: object) -> str:
    """Acepta únicamente HTTP(S) sin credenciales y con DNS totalmente público."""
    url = str(value or "").strip()
    if not url:
        raise RadioURLPolicyError("La URL de la radio está vacía.")
    if len(url) > MAX_RADIO_URL_LENGTH:
        raise RadioURLPolicyError("La URL de la radio es demasiado larga.")
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise RadioURLPolicyError("La URL de la radio contiene caracteres no permitidos.")

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise RadioURLPolicyError("La URL de la radio no es válida.") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise RadioURLPolicyError("La radio solo admite URLs HTTP o HTTPS.")
    if not parsed.hostname:
        raise RadioURLPolicyError("La URL de la radio debe incluir un host.")
    if parsed.username is not None or parsed.password is not None:
        raise RadioURLPolicyError("La URL de la radio no puede incluir credenciales.")
    if port is not None and port <= 0:
        raise RadioURLPolicyError("La URL de la radio usa un puerto no válido.")

    service_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        addresses = {
            item[4][0].split("%", 1)[0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                service_port,
                type=socket.SOCK_STREAM,
            )
        }
    except (OSError, UnicodeError) as exc:
        raise RadioURLPolicyError("No se pudo resolver el host de la radio.") from exc

    if not addresses:
        raise RadioURLPolicyError("El host de la radio no tiene direcciones utilizables.")
    try:
        if any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise RadioURLPolicyError(
                "La URL de la radio apunta a una red privada o no enrutable."
            )
    except ValueError as exc:
        raise RadioURLPolicyError("El host de la radio resolvió a una dirección inválida.") from exc

    return urldefrag(url).url


def redact_url_for_log(value: object) -> str:
    """Conserva solo esquema y host para no registrar rutas, tokens o consultas."""
    try:
        parsed = urlsplit(str(value or ""))
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return "<url-no-válida>"
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        return f"{parsed.scheme.lower()}://{host}{port}"
    except (TypeError, ValueError):
        return "<url-no-válida>"
