import asyncio
import logging
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from api.routes.radio import RadioConfigUpdate, patch_radio_config
from cogs.radio import Radio
from database.manager import DatabaseManager


class RadioConfigApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DatabaseManager.__new__(DatabaseManager)
        self.db.db_type = "sqlite"
        self.db._sqlite_lock = threading.Lock()
        self.db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.db._sqlite_conn.row_factory = sqlite3.Row
        self.db._sqlite_conn.execute("PRAGMA foreign_keys = ON")
        self.db._sqlite_conn.execute("PRAGMA journal_mode = WAL")
        db_logger = logging.getLogger("Database")
        previous_disabled = db_logger.disabled
        db_logger.disabled = True
        try:
            self.db._init_schema()
        finally:
            db_logger.disabled = previous_disabled

    async def asyncTearDown(self):
        self.db._sqlite_conn.close()

    async def test_patch_radio_returns_persisted_config(self):
        body = RadioConfigUpdate(
            enabled=1,
            channel_id="123456789012345678",
            stream_url="https://example.com/radio.mp3",
            station_name="Smoke Radio",
            volume=42,
            auto_reconnect=1,
            pause_on_empty=0,
        )

        result = await patch_radio_config(
            123,
            body,
            SimpleNamespace(),
            self.db,
            None,
            {"user_id": 42},
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["radio_config"]["enabled"], 1)
        self.assertEqual(result["radio_config"]["channel_id"], "123456789012345678")
        self.assertEqual(result["radio_config"]["stream_url"], "https://example.com/radio.mp3")
        self.assertEqual(self.db.get_lofi_config(123)["channel_id"], 123456789012345678)
        self.assertEqual(self.db.get_lofi_config(123)["station_name"], "Smoke Radio")

    async def test_patch_radio_forces_active_stream_restart(self):
        class FakeRadioCog:
            def __init__(self):
                self.calls = []

            async def restart_guild(self, guild_id):
                self.calls.append((guild_id, "restart"))

        fake_radio = FakeRadioCog()
        fake_bot = SimpleNamespace(cogs={"Radio": fake_radio}, loop=asyncio.get_running_loop())

        result = await patch_radio_config(
            123,
            RadioConfigUpdate(stream_url="https://example.com/new.mp3", station_name="New Radio"),
            SimpleNamespace(),
            self.db,
            fake_bot,
            {"user_id": 42},
        )

        self.assertEqual(fake_radio.calls, [(123, "restart")])
        self.assertEqual(result["radio_restart"], {"triggered": True, "completed": True})

    async def test_radio_channel_id_coercion_accepts_string_snowflakes(self):
        self.assertEqual(Radio._coerce_channel_id("123456789012345678"), 123456789012345678)
        self.assertIsNone(Radio._coerce_channel_id(""))
        self.assertIsNone(Radio._coerce_channel_id("not-a-channel"))

    async def test_voice_status_text_is_short_and_clean(self):
        self.assertEqual(Radio._voice_status_text("  My   Station  "), "🎶 My Station")
        self.assertLessEqual(len(Radio._voice_status_text("x" * 500)), 120)

    async def test_radio_start_schema_exposes_optional_voice_channel(self):
        command = next(cmd for cmd in Radio.radio_group.commands if cmd.name == "start")

        self.assertEqual(len(command.parameters), 1)
        self.assertEqual(command.parameters[0].name, "canal")
        self.assertFalse(command.parameters[0].required)
        self.assertEqual(command.parameters[0].type, discord.AppCommandOptionType.channel)
        self.assertEqual(command.parameters[0].channel_types, [discord.ChannelType.voice])

    def _radio_start_fixture(
        self,
        *,
        configured_channel_id=None,
        member_channel=None,
        connected_channel=None,
    ):
        class FakeDB:
            def __init__(self):
                self.config = {
                    "guild_id": 123,
                    "enabled": 0,
                    "channel_id": configured_channel_id,
                    "station_name": "Smoke Radio",
                }
                self.updates = []

            def get_lofi_config(self, guild_id):
                assert guild_id == 123
                return dict(self.config)

            def set_lofi_config(self, guild_id, **kwargs):
                assert guild_id == 123
                self.updates.append(kwargs)
                self.config.update(kwargs)

        class FakeVoiceClient:
            def __init__(self, channel):
                self.channel = channel

            def is_connected(self):
                return True

        guild = SimpleNamespace(id=123, name="Guild", voice_client=None)
        guild.get_channel = lambda channel_id: None
        if connected_channel is not None:
            guild.voice_client = FakeVoiceClient(connected_channel)

        interaction = SimpleNamespace(
            guild=guild,
            guild_id=guild.id,
            user=SimpleNamespace(voice=SimpleNamespace(channel=member_channel)),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        cog = Radio.__new__(Radio)
        cog.bot = SimpleNamespace(voice_clients=[])
        cog.db = FakeDB()
        cog._is_voice_channel = lambda channel: bool(getattr(channel, "is_voice", False))
        cog._resolve_voice_channel = AsyncMock(return_value=None)
        cog._check_and_connect_guild = AsyncMock()
        return cog, interaction

    @staticmethod
    def _fake_voice_channel(channel_id: int):
        return SimpleNamespace(
            id=channel_id,
            mention=f"<#{channel_id}>",
            is_voice=True,
        )

    async def test_radio_start_activates_explicit_channel_immediately(self):
        channel = self._fake_voice_channel(456)
        cog, interaction = self._radio_start_fixture(connected_channel=channel)

        await Radio.radio_start.callback(cog, interaction, canal=channel)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        self.assertEqual(cog.db.updates, [{"channel_id": 456, "enabled": 1}])
        cog._check_and_connect_guild.assert_awaited_once_with(interaction.guild)
        response = interaction.followup.send.await_args.args[0]
        self.assertIn("Radio activada", response)
        self.assertIn("Smoke Radio", response)

    async def test_radio_start_does_not_reread_db_after_connecting(self):
        channel = self._fake_voice_channel(456)
        cog, interaction = self._radio_start_fixture(connected_channel=channel)
        original_get = cog.db.get_lofi_config
        read_count = 0

        def get_once(guild_id):
            nonlocal read_count
            read_count += 1
            if read_count > 1:
                raise RuntimeError("La segunda lectura no debe ocurrir")
            return original_get(guild_id)

        cog.db.get_lofi_config = get_once

        await Radio.radio_start.callback(cog, interaction, canal=channel)

        self.assertEqual(read_count, 1)
        response = interaction.followup.send.await_args.args[0]
        self.assertIn("Radio activada", response)

    async def test_radio_start_prefers_callers_current_voice_channel(self):
        current = self._fake_voice_channel(789)
        cog, interaction = self._radio_start_fixture(
            configured_channel_id=456,
            member_channel=current,
            connected_channel=current,
        )

        await Radio.radio_start.callback(cog, interaction, canal=None)

        self.assertEqual(cog.db.updates, [{"channel_id": 789, "enabled": 1}])
        cog._resolve_voice_channel.assert_not_awaited()

    async def test_radio_start_falls_back_to_saved_channel(self):
        configured = self._fake_voice_channel(456)
        cog, interaction = self._radio_start_fixture(
            configured_channel_id=configured.id,
            connected_channel=configured,
        )
        cog._resolve_voice_channel.return_value = configured

        await Radio.radio_start.callback(cog, interaction, canal=None)

        cog._resolve_voice_channel.assert_awaited_once_with(interaction.guild, configured.id)
        self.assertEqual(cog.db.updates, [{"channel_id": configured.id, "enabled": 1}])

    async def test_radio_start_requires_a_resolvable_channel(self):
        cog, interaction = self._radio_start_fixture()

        await Radio.radio_start.callback(cog, interaction, canal=None)

        self.assertEqual(cog.db.updates, [])
        cog._check_and_connect_guild.assert_not_awaited()
        response = interaction.followup.send.await_args.args[0]
        self.assertIn("Indica un canal", response)

    async def test_radio_start_reports_unconfirmed_connection_without_rollback(self):
        channel = self._fake_voice_channel(456)
        cog, interaction = self._radio_start_fixture()

        await Radio.radio_start.callback(cog, interaction, canal=channel)

        self.assertEqual(cog.db.updates, [{"channel_id": 456, "enabled": 1}])
        response = interaction.followup.send.await_args.args[0]
        self.assertIn("quedó activada", response)
        self.assertIn("Conectar", response)

    async def test_radio_start_handles_connection_exception_after_persisting(self):
        channel = self._fake_voice_channel(456)
        cog, interaction = self._radio_start_fixture()
        cog._check_and_connect_guild.side_effect = RuntimeError("Discord unavailable")

        await Radio.radio_start.callback(cog, interaction, canal=channel)

        self.assertEqual(cog.db.updates, [{"channel_id": 456, "enabled": 1}])
        response = interaction.followup.send.await_args.args[0]
        self.assertIn("quedó activada", response)
        self.assertNotIn("Discord unavailable", response)

    async def test_radio_reuses_cached_voice_client_when_guild_voice_client_is_missing(self):
        class FakeDB:
            def get_lofi_config(self, guild_id):
                return {
                    "enabled": 1,
                    "channel_id": 1497055415400136701,
                    "stream_url": "https://example.com/radio.mp3",
                    "station_name": "Cached VC Radio",
                    "volume": 100,
                }

        class FakeChannel:
            is_voice = True

            def __init__(self, channel_id, guild):
                self.id = channel_id
                self.guild = guild
                self.name = "Radio"
                self.connect_calls = 0

            async def connect(self, reconnect=True):
                self.connect_calls += 1
                raise AssertionError("No debe llamar connect() si ya existe voice client en bot.voice_clients")

        class FakeVoiceClient:
            def __init__(self, guild, channel):
                self.guild = guild
                self.channel = channel
                self.moved_to = []

            def is_connected(self):
                return True

            def is_playing(self):
                return False

            async def move_to(self, channel):
                self.moved_to.append(channel.id)
                self.channel = channel

        class FakeGuild:
            def __init__(self):
                self.id = 123
                self.name = "Guild"
                self.voice_client = None
                self.channels = []

            def get_channel(self, channel_id):
                return next((ch for ch in self.channels if ch.id == channel_id), None)

        guild = FakeGuild()
        stale_channel = FakeChannel(111, guild)
        target_channel = FakeChannel(1497055415400136701, guild)
        guild.channels = [stale_channel, target_channel]
        voice_client = FakeVoiceClient(guild, stale_channel)

        cog = Radio.__new__(Radio)
        cog.bot = SimpleNamespace(voice_clients=[voice_client])
        cog.db = FakeDB()
        cog._playback_wait = 0
        cog._restart_in_progress = set()
        cog._guild_locks = {}
        cog._is_voice_channel = lambda ch: getattr(ch, "is_voice", False)
        cog._set_voice_channel_status = AsyncMock()
        starts = []
        cog.start_playing = lambda vc, channel, cfg: starts.append((vc, channel.id, cfg["station_name"]))

        await cog._check_and_connect_guild(guild)

        self.assertEqual(target_channel.connect_calls, 0)
        self.assertEqual(voice_client.moved_to, [target_channel.id])
        self.assertEqual(starts, [(voice_client, target_channel.id, "Cached VC Radio")])


if __name__ == "__main__":
    unittest.main()
