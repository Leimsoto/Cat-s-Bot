import asyncio
import threading
import unittest
from types import SimpleNamespace

from api.discord_bridge import DiscordBridgeTimeout, run_on_bot_loop
from api.routes.guild import send_ticket_panel


class DiscordBridgeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot_loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.bot_loop.run_forever, daemon=True)
        self.thread.start()
        self.bot = SimpleNamespace(loop=self.bot_loop)

    def tearDown(self):
        self.bot_loop.call_soon_threadsafe(self.bot_loop.stop)
        self.thread.join(timeout=2)
        self.bot_loop.close()

    async def test_operation_runs_on_bot_loop(self):
        async def operation():
            return asyncio.get_running_loop(), threading.get_ident()

        loop, thread_id = await run_on_bot_loop(self.bot, operation, timeout=1)

        self.assertIs(loop, self.bot_loop)
        self.assertEqual(thread_id, self.thread.ident)

    async def test_timeout_cancels_bot_operation(self):
        cancelled = threading.Event()

        async def operation():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with self.assertRaises(DiscordBridgeTimeout):
            await run_on_bot_loop(self.bot, operation, timeout=0.02)

        await asyncio.to_thread(cancelled.wait, 1)
        self.assertTrue(cancelled.is_set())

    async def test_ticket_panel_runs_on_discord_loop(self):
        guild = SimpleNamespace(id=123)

        class TicketsCog:
            def __init__(self):
                self.executed_loop = None

            async def send_panel_to_channel(self, received_guild, channel_id):
                self.executed_loop = asyncio.get_running_loop()
                self.received = (received_guild, channel_id)
                return True, "Panel enviado"

        cog = TicketsCog()
        bot = SimpleNamespace(
            loop=self.bot_loop,
            get_guild=lambda guild_id: guild if guild_id == 123 else None,
            get_cog=lambda name: cog if name == "Tickets" else None,
        )

        result = await send_ticket_panel(
            123,
            {"channel_id": "1497055416062971949"},
            bot,
            None,
            {"user_id": 42},
        )

        self.assertEqual(result, {"status": "ok", "message": "Panel enviado"})
        self.assertIs(cog.executed_loop, self.bot_loop)
        self.assertEqual(cog.received, (guild, 1497055416062971949))


if __name__ == "__main__":
    unittest.main()
