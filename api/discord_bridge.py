"""Puente seguro entre el event loop de FastAPI y el de discord.py.

Uvicorn se ejecuta en un hilo independiente. Las corutinas que usan objetos de
discord.py (y su sesión aiohttp) deben ejecutarse en ``bot.loop``; esperarlas
directamente desde una ruta FastAPI produce errores de afinidad de event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Optional, TypeVar


T = TypeVar("T")


class DiscordBridgeUnavailable(RuntimeError):
    """El bot o su event loop no están disponibles."""


class DiscordBridgeTimeout(TimeoutError):
    """La operación no terminó dentro del tiempo permitido."""


async def run_on_bot_loop(
    bot: Any,
    operation: Callable[[], Awaitable[T]],
    *,
    timeout: Optional[float] = 15.0,
    complete_on_cancel: bool = False,
) -> T:
    """Ejecuta ``operation`` en ``bot.loop`` sin bloquear el loop de FastAPI.

    Se recibe una factoría, no una corutina ya creada, para no dejar corutinas
    sin esperar si el loop del bot no está disponible.
    """

    if complete_on_cancel and timeout is not None:
        raise ValueError(
            "complete_on_cancel requiere timeout=None para ofrecer un resultado definitivo"
        )
    if bot is None:
        raise DiscordBridgeUnavailable("Bot no disponible")
    bot_loop = getattr(bot, "loop", None)
    is_closed = getattr(bot_loop, "is_closed", None)
    is_running = getattr(bot_loop, "is_running", None)
    if (
        bot_loop is None
        or not callable(is_closed)
        or not callable(is_running)
        or is_closed()
        or not is_running()
    ):
        raise DiscordBridgeUnavailable("Event loop del bot no disponible")

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    async def await_local_task(task: "asyncio.Task[T]") -> T:
        awaited = asyncio.shield(task) if complete_on_cancel else task
        try:
            if timeout is None:
                return await awaited
            return await asyncio.wait_for(awaited, timeout=timeout)
        except asyncio.CancelledError:
            if complete_on_cancel:
                try:
                    await asyncio.shield(task)
                except BaseException:
                    pass
            else:
                task.cancel()
            raise
        except asyncio.TimeoutError as exc:
            if complete_on_cancel:
                return await asyncio.shield(task)
            raise DiscordBridgeTimeout(
                f"Discord no respondió antes de {timeout:g}s"
            ) from exc

    if current_loop is bot_loop:
        return await await_local_task(asyncio.create_task(operation()))

    async def invoke_on_bot_loop() -> T:
        # La factoría también se invoca dentro del loop de Discord. Esto es
        # importante para operaciones que consultan estado ligado al loop
        # antes de devolver su awaitable.
        return await operation()

    bridge_coro = invoke_on_bot_loop()
    try:
        future = asyncio.run_coroutine_threadsafe(bridge_coro, bot_loop)
    except Exception:
        bridge_coro.close()
        raise
    wrapped = asyncio.wrap_future(future)
    awaited = asyncio.shield(wrapped) if complete_on_cancel else wrapped
    try:
        if timeout is None:
            return await awaited
        return await asyncio.wait_for(awaited, timeout=timeout)
    except asyncio.CancelledError:
        if complete_on_cancel:
            try:
                await asyncio.shield(wrapped)
            except BaseException:
                pass
        else:
            future.cancel()
        raise
    except asyncio.TimeoutError as exc:
        if complete_on_cancel:
            return await asyncio.shield(wrapped)
        future.cancel()
        raise DiscordBridgeTimeout(
            f"Discord no respondió antes de {timeout:g}s"
        ) from exc
