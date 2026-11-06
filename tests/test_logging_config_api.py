import logging
import json
import sqlite3
import threading
import unittest

from api.routes.guild import get_logging_config, patch_logging_config
from database.manager import DatabaseManager


class _Request:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class _Channel:
    def __init__(self, channel_id: int):
        self.id = channel_id

    async def send(self, **kwargs):
        return None


class _Guild:
    def __init__(self, guild_id: int, real_channel_id: int):
        self.id = guild_id
        self.channels = [_Channel(real_channel_id)]

    def get_channel(self, channel_id: int):
        for channel in self.channels:
            if channel.id == channel_id:
                return channel
        return None


class _Bot:
    def __init__(self, guild):
        self._guild = guild

    def get_guild(self, guild_id: int):
        return self._guild if self._guild.id == guild_id else None


class LoggingConfigApiTest(unittest.IsolatedAsyncioTestCase):
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

    async def test_logging_channel_id_is_string_safe_and_repaired(self):
        guild_id = 123
        rounded_id = 1497055416062972000
        real_id = 1497055416062971949
        bot = _Bot(_Guild(guild_id, real_id))

        result = await patch_logging_config(
            guild_id,
            _Request({
                "serverlog_channel": str(rounded_id),
                "serverlog_enabled": 1,
                "log_events": "{}",
            }),
            self.db,
            bot,
            {"user_id": 42},
        )

        self.assertEqual(result["config"]["serverlog_channel"], str(real_id))
        self.assertEqual(self.db.get_server_config(guild_id)["serverlog_channel"], real_id)

        loaded = await get_logging_config(guild_id, self.db, {"user_id": 42})
        self.assertEqual(loaded["serverlog_channel"], str(real_id))

    async def test_channel_update_flag_roundtrips_preserving_other_events_and_guild_isolation(self):
        events = {"channel_update": True, "channel_updates": True, "channel_create": False, "message_delete": True,
                  "role_change": False, "role_changes": True, "nickname_changes": True, "audit_events": True}
        bot = _Bot(_Guild(123, 900))
        for enabled in (True, False):
            events["channel_update"] = enabled
            await patch_logging_config(123, _Request({"log_events": json.dumps(events)}), self.db, bot, {"user_id": 42})
            loaded = await get_logging_config(123, self.db, {"user_id": 42})
            self.assertEqual(json.loads(loaded["log_events"]), events)
            self.assertIsNone(self.db.get_server_config(124)["log_events"])


if __name__ == "__main__":
    unittest.main()
