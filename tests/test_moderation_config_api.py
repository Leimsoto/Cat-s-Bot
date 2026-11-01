import asyncio
import logging
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from api.routes.guild import get_moderation_config, patch_moderation_config
from database.manager import DatabaseManager


class ModerationConfigApiTest(unittest.IsolatedAsyncioTestCase):
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

    async def test_dashboard_moderation_config_is_what_cogs_read(self):
        guild = SimpleNamespace(id=123, owner_id=42)
        roles = [
            discord.Role(guild=guild, state=None, data={
                "id": str(role_id), "name": name, "position": position,
                "permissions": "0", "managed": False,
            })
            for role_id, name, position in ((123, "@everyone", 0), (222, "Staff", 1),
                                             (333, "Mod", 2), (4444, "Bot", 10))
        ]
        member = SimpleNamespace(id=777, guild=guild, _roles=[4444])
        guild.fetch_member = AsyncMock(return_value=member)
        guild.fetch_roles = AsyncMock(return_value=roles)
        bot = SimpleNamespace(get_guild=lambda _id: guild, user=SimpleNamespace(id=777),
                              fetch_guild=AsyncMock(return_value=guild), loop=asyncio.get_running_loop())
        result = await patch_moderation_config(
            123,
            {
                "mute_role_id": "111",
                "staff_role_id": "222",
                "mod_role_id": "333",
                "modlog_channel": "444",
                "modlog_enabled": 1,
            },
            request=None,
            db=self.db,
            bot=bot,
            user={"user_id": 42, "is_master_admin": True},
        )

        self.assertEqual(result["config"]["mute_role_id"], "111")
        self.assertEqual(result["config"]["staff_role_id"], "222")
        self.assertEqual(result["config"]["mod_role_id"], "333")
        self.assertEqual(result["config"]["modlog_channel"], "444")

        guild_cfg = self.db.get_config(123)
        server_cfg = self.db.get_server_config(123)
        self.assertEqual(guild_cfg["mute_role_id"], 111)
        self.assertEqual(guild_cfg["staff_role_id"], 222)
        self.assertEqual(server_cfg["staff_role_id"], 222)
        self.assertEqual(server_cfg["mod_role_id"], 333)

        loaded = await get_moderation_config(123, self.db, {"user_id": 42})
        self.assertEqual(loaded["mute_role_id"], "111")
        self.assertEqual(loaded["staff_role_id"], "222")


if __name__ == "__main__":
    unittest.main()
