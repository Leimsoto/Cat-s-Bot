"""
Paquete `api`.
Backend FastAPI para el panel web del bot.
Exporta `iniciar_api()` para arrancarlo en un hilo daemon desde main.py.
"""


def iniciar_api(*args, **kwargs):
    """Importa FastAPI/uvicorn solo cuando realmente se arranca la API.

    Esto mantiene compatible ``from api import iniciar_api`` en ``main.py`` y evita
    que herramientas de descubrimiento de tests importen dependencias web pesadas
    cuando solo necesitan cargar el paquete ``api``.
    """
    from .app import iniciar_api as _iniciar_api

    return _iniciar_api(*args, **kwargs)

__all__ = ["iniciar_api"]
