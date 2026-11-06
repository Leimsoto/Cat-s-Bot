"""Validated custom endpoint configuration shared by the API and moderation worker."""
from urllib.parse import urlsplit
import asyncio
import ipaddress
import os
import socket

DEFAULT_LLM_CONFIG = {
    "enabled": False, "rules_text": "", "context_messages": 10,
    "context_mode": "user", "endpoint_url": "", "model": "",
    "api_type": "chat_completions",
    "context_window_tokens": 262144,
    "chat_reasoning_effort": "none", "web_reasoning_effort": "none",
    "supports_images": False, "api_key": "", "insecure_http_confirmed_url": "", "private_endpoint_confirmed_url": "",
}
REASONING_EFFORTS = frozenset({"none", "auto", "low", "medium", "high", "max"})
ENDPOINT_CONFIG_FIELDS = frozenset({"endpoint_url", "model", "api_type", "supports_images", "api_key",
    "insecure_http_confirmed_url", "private_endpoint_confirmed_url", "context_window_tokens",
    "chat_reasoning_effort", "web_reasoning_effort"})
PRIVATE_ENDPOINT_NETWORKS = tuple(ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
PRIVATE_ENDPOINT_PATHS = {"", "/v1", "/v1/chat/completions", "/v1/responses"}


def completion_output_tokens(cfg, *, task="chat", deep=False):
    effort = cfg.get(f"{task}_reasoning_effort", "none")
    tokens = 1000 if effort == "none" else (16384 if effort in {"high", "max"} else 8192)
    return max(tokens, 16384) if deep else tokens


def allowed_endpoint_hosts():
    return {value.strip().lower() for value in os.getenv("CATBOT_LLM_ALLOWED_HOSTS", "").split(",") if value.strip()}


class EndpointConfirmationRequired(ValueError):
    def __init__(self, endpoint_url, required_confirmations):
        self.endpoint_url = endpoint_url
        self.required_confirmations = required_confirmations
        self.code = "private_confirmation_required" if "private" in required_confirmations else "http_confirmation_required"
        messages = []
        if "http" in required_confirmations:
            messages.append("el tráfico y la clave HTTP se enviarán sin cifrar")
        if "private" in required_confirmations:
            messages.append("el endpoint privado dará acceso a este servicio de la red del bot")
        super().__init__("Confirma esta URL: " + "; ".join(messages) + ".")


class HTTPConfirmationRequired(EndpointConfirmationRequired):
    pass


class PrivateEndpointConfirmationRequired(EndpointConfirmationRequired):
    pass


def endpoint_address_allowed(value, *, private=False):
    address = ipaddress.ip_address(value)
    # AWS IMDS also has a ULA endpoint, outside the link-local ranges.
    if address == ipaddress.ip_address("fd00:ec2::254"):
        return False
    if address.is_loopback:
        return private
    if address.is_link_local or address.is_unspecified or address.is_multicast or address.is_reserved:
        return False
    return address.is_global or private and any(address in network for network in PRIVATE_ENDPOINT_NETWORKS)


def parse_endpoint_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(char in value for char in "\r\n\t"):
        raise ValueError("llm.endpoint_url inválido (máximo 2048)")
    try:
        url = urlsplit(value.strip())
        port = url.port
    except ValueError as exc:
        raise ValueError("llm.endpoint_url inválido") from exc
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment or port == 0:
        raise ValueError("llm.endpoint_url requiere HTTP(S) sin credenciales, query ni fragmento")
    return url


async def resolve_endpoint_addresses(endpoint_url):
    url = parse_endpoint_url(endpoint_url)
    try:
        return [str(ipaddress.ip_address(url.hostname))]
    except ValueError:
        pass
    try:
        records = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
            url.hostname, url.port or (443 if url.scheme == "https" else 80), type=socket.SOCK_STREAM), timeout=2)
    except (OSError, asyncio.TimeoutError):
        raise ValueError("No se pudo resolver el endpoint. Revisa el nombre o inténtalo de nuevo; no se ha guardado.") from None
    if not records:
        raise ValueError("No se pudo resolver el endpoint; no se ha guardado.")
    return sorted({record[4][0] for record in records})


def validate_llm_config(value, current=None, *, resolved_addresses=None):
    if not isinstance(value, dict):
        raise ValueError("llm debe ser un objeto")
    allowed = set(DEFAULT_LLM_CONFIG) | {"api_key_configured", "api_key_clear"}
    if set(value) - allowed:
        raise ValueError("Campo LLM desconocido")
    cfg = {**DEFAULT_LLM_CONFIG, **(current or {}), **value}
    cfg.pop("api_key_configured", None)
    clear_key = cfg.pop("api_key_clear", False)
    if type(clear_key) is not bool:
        raise ValueError("llm.api_key_clear debe ser booleano")
    if clear_key and value.get("api_key") not in (None, ""):
        raise ValueError("No puedes reemplazar y borrar la API key a la vez")
    if clear_key:
        cfg["api_key"] = ""
    elif value.get("api_key") in (None, ""):
        cfg["api_key"] = (current or {}).get("api_key") or ""
    for field in ("enabled", "supports_images"):
        if not isinstance(cfg[field], bool):
            raise ValueError(f"llm.{field} debe ser booleano")
    count = cfg["context_messages"]
    if type(count) is not int or not 0 <= count <= 50:
        raise ValueError("llm.context_messages debe estar entre 0 y 50")
    if not isinstance(cfg["context_mode"], str) or cfg["context_mode"] not in {"user", "channel"}:
        raise ValueError("llm.context_mode debe ser user o channel")
    if not isinstance(cfg["api_type"], str) or cfg["api_type"] not in {"chat_completions", "responses"}:
        raise ValueError("llm.api_type debe ser chat_completions o responses")
    if type(cfg["context_window_tokens"]) is not int or not 4096 <= cfg["context_window_tokens"] <= 1048576:
        raise ValueError("llm.context_window_tokens debe ser un entero entre 4096 y 1048576")
    for field in ("chat_reasoning_effort", "web_reasoning_effort"):
        if not isinstance(cfg[field], str) or cfg[field] not in REASONING_EFFORTS:
            raise ValueError(f"llm.{field} debe ser none, auto, low, medium, high o max")
    for field, limit in (("rules_text", 12000), ("model", 200), ("endpoint_url", 2048), ("insecure_http_confirmed_url", 2048), ("private_endpoint_confirmed_url", 2048)):
        if not isinstance(cfg[field], str) or len(cfg[field]) > limit:
            raise ValueError(f"llm.{field} inválido (máximo {limit})")
        cfg[field] = cfg[field].strip()
    for field in ("insecure_http_confirmed_url", "private_endpoint_confirmed_url"):
        if cfg[field] != cfg["endpoint_url"]:
            cfg[field] = ""
    if cfg["api_key"] is None:
        cfg["api_key"] = ""
    if not isinstance(cfg["api_key"], str) or len(cfg["api_key"]) > 4096 or any(c in cfg["api_key"] for c in "\r\n"):
        raise ValueError("llm.api_key inválida")
    if cfg["endpoint_url"]:
        url = parse_endpoint_url(cfg["endpoint_url"])
        opposite = "/v1/chat/completions" if cfg["api_type"] == "responses" else "/v1/responses"
        if url.path.rstrip("/") == opposite:
            raise ValueError("La ruta del endpoint no corresponde al tipo de API seleccionado; usa la base /v1 o la ruta de esa API.")
        if url.hostname.lower() not in allowed_endpoint_hosts():
            try:
                address = ipaddress.ip_address(url.hostname)
            except ValueError:
                address = None
            addresses = [str(address)] if address is not None else resolved_addresses
            needs_private = False
            if addresses is not None:
                if not addresses or any(not endpoint_address_allowed(address, private=True) for address in addresses):
                    raise ValueError("El endpoint no puede usar direcciones de metadatos, link-local, reservadas, multicast ni sin especificar.")
                needs_private = any(not endpoint_address_allowed(address) for address in addresses)
                if not needs_private:
                    cfg["private_endpoint_confirmed_url"] = ""
            if (needs_private or cfg["private_endpoint_confirmed_url"]) and url.path.rstrip("/") not in PRIVATE_ENDPOINT_PATHS:
                raise ValueError("Un endpoint privado solo admite la base, /v1, /v1/chat/completions o /v1/responses.")
            missing = []
            if url.scheme == "http" and cfg["insecure_http_confirmed_url"] != cfg["endpoint_url"]:
                missing.append("http")
            if needs_private and cfg["private_endpoint_confirmed_url"] != cfg["endpoint_url"]:
                missing.append("private")
            if missing:
                error = PrivateEndpointConfirmationRequired if "private" in missing else HTTPConfirmationRequired
                raise error(cfg["endpoint_url"], missing)
        if url.scheme == "https":
            cfg["insecure_http_confirmed_url"] = ""
    if cfg["enabled"] and not all(cfg[f] for f in ("rules_text", "endpoint_url", "model")):
        raise ValueError("Para activar LLM, configura reglas, endpoint y modelo")
    return cfg


def public_automod_config(config):
    result = {**config, "rules": dict(config.get("rules") or {})}
    llm = {**DEFAULT_LLM_CONFIG, **(result["rules"].get("llm") or {})}
    llm["api_key_configured"] = bool(llm.pop("api_key", ""))
    result["rules"]["llm"] = llm
    return result
