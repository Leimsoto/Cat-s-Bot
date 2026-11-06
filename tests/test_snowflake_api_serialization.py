import json
import asyncio
import logging
import sqlite3
import threading
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.routes.autoroles import ReactionPanelBody, list_reaction_panels, upsert_reaction_panel
from api.routes.guild import get_ia_config, patch_ia_config
from api.routes.voice_gen import VoiceGenConfigUpdate, get_voice_gen_config, patch_voice_gen_config
from database.manager import DatabaseManager


def make_db():
    db = DatabaseManager.__new__(DatabaseManager)
    db.db_type = "sqlite"
    db._sqlite_lock = threading.Lock()
    db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
    db._sqlite_conn.row_factory = sqlite3.Row
    db._sqlite_conn.execute("PRAGMA foreign_keys = ON")
    db._sqlite_conn.execute("PRAGMA journal_mode = WAL")
    db_logger = logging.getLogger("Database")
    previous_disabled = db_logger.disabled
    db_logger.disabled = True
    try:
        db._init_schema()
    finally:
        db_logger.disabled = previous_disabled
    return db


class SnowflakeApiSerializationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = make_db()

    async def asyncTearDown(self):
        self.db._sqlite_conn.close()

    async def test_autorole_reaction_ids_are_string_safe(self):
        guild_id = 123
        channel_id = 1497055415400136681
        message_id = 1497055416062971949
        role_id = 1523702726393860373

        class _Role:
            def __init__(self, ident, name, position):
                self.id = ident
                self.name = name
                self.position = position
                self.managed = False

        class _Message:
            def __init__(self):
                self.reactions = []

            async def add_reaction(self, emoji):
                self.reactions.append(emoji)

        class _Channel:
            def __init__(self, message):
                self.message = message

            async def fetch_message(self, ident):
                self.last_message_id = ident
                return self.message

        managed_role = _Role(role_id, "Miembro", 5)
        default_role = _Role(guild_id, "@everyone", 0)
        bot_top_role = _Role(999, "Bot", 10)
        bot_member = type("BotMember", (), {"top_role": bot_top_role})()
        message = _Message()
        channel = _Channel(message)

        class _Guild:
            def __init__(self):
                self.me = bot_member
                self.default_role = default_role

            def get_channel(self, ident):
                return channel if ident == channel_id else None

            def get_role(self, ident):
                return managed_role if ident == role_id else None

            def get_member(self, _ident):
                return bot_member

        guild = _Guild()
        bot = type(
            "Bot",
            (),
            {
                "user": type("User", (), {"id": 999})(),
                "get_guild": lambda self, ident: guild if ident == guild_id else None,
            },
        )()
        bot.loop = asyncio.get_running_loop()

        result = await upsert_reaction_panel(
            guild_id,
            ReactionPanelBody(
                message_id=str(message_id),
                channel_id=str(channel_id),
                # El frontend envía el JSON crudo para que Python conserve el entero exacto.
                mapping_data='{"👍": %d}' % role_id,
            ),
            self.db,
            bot,
            {"user_id": 42},
        )

        self.assertEqual(result["message_id"], str(message_id))
        self.assertEqual(result["channel_id"], str(channel_id))
        stored = self.db.get_autorole(message_id)
        self.assertEqual(json.loads(stored["mapping_data"])["👍"], role_id)
        self.assertEqual(message.reactions, ["👍"])

        listed = await list_reaction_panels(guild_id, self.db, {"user_id": 42})
        panel = listed["panels"][0]
        self.assertEqual(panel["message_id"], str(message_id))
        self.assertEqual(panel["channel_id"], str(channel_id))
        self.assertEqual(json.loads(panel["mapping_data"])["👍"], str(role_id))

    async def test_voice_gen_config_ids_are_string_safe(self):
        guild_id = 123
        generator_id = 1497055415400136681
        category_id = 1497055415400136702
        panel_id = 1497055416062971949
        panel_message_id = 1497055416062972001

        result = await patch_voice_gen_config(
            guild_id,
            VoiceGenConfigUpdate(
                generator_channel_id=str(generator_id),
                category_id=str(category_id),
                panel_channel_id=str(panel_id),
            ),
            self.db,
            {"user_id": 42},
        )

        self.assertEqual(result["config"]["generator_channel_id"], str(generator_id))
        self.assertEqual(result["config"]["category_id"], str(category_id))
        self.assertEqual(result["config"]["panel_channel_id"], str(panel_id))

        self.db.set_voice_gen_config(
            guild_id,
            panel_message_channel_id=panel_id,
            panel_message_id=panel_message_id,
        )

        loaded = await get_voice_gen_config(guild_id, self.db, {"user_id": 42})
        self.assertEqual(loaded["config"]["generator_channel_id"], str(generator_id))
        self.assertEqual(loaded["config"]["panel_message_channel_id"], str(panel_id))
        self.assertEqual(loaded["config"]["panel_message_id"], str(panel_message_id))

        self.db.create_voice_gen_channel(generator_id, guild_id, 42)
        self.db.update_voice_gen_channel_panel(generator_id, panel_id, panel_message_id)
        active = self.db.get_voice_gen_channel(generator_id)
        self.assertEqual(active["panel_channel_id"], panel_id)
        self.assertEqual(active["panel_message_id"], panel_message_id)

    async def test_ia_config_ids_are_string_safe(self):
        guild_id = 123
        channel_id = 1497055415400136681
        role_id = 1523702726393860373

        with patch("api.routes.guild._validate_privileged_role_updates", new=AsyncMock(return_value={"ai_role_id": role_id})):
            result = await patch_ia_config(
                guild_id,
                {
                    "ai_enabled": "0",
                    "ai_response_mode": " MENTIONS ",
                    "ai_channel_id": str(channel_id),
                    "ai_role_id": str(role_id),
                    "ai_imagine_enabled": 1,
                },
                request=None,
                db=self.db,
                bot=None,
                user={"user_id": 42},
            )

        self.assertEqual(result["ai_enabled"], 0)
        self.assertEqual(result["ai_response_mode"], "mentions")
        self.assertEqual(result["ai_channel_id"], str(channel_id))
        self.assertEqual(result["ai_role_id"], str(role_id))
        loaded = await get_ia_config(guild_id, self.db, {"user_id": 42})
        self.assertEqual(loaded["ai_enabled"], 0)
        self.assertEqual(loaded["ai_response_mode"], "mentions")
        self.assertEqual(loaded["ai_channel_id"], str(channel_id))
        self.assertEqual(loaded["ai_role_id"], str(role_id))

    async def test_ia_config_rejects_invalid_enabled_and_response_mode(self):
        cases = (
            ({"ai_enabled": 2}, "ai_enabled"),
            ({"ai_response_mode": "sometimes"}, "ai_response_mode"),
        )

        for payload, field in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(HTTPException) as raised:
                    await patch_ia_config(
                        123,
                        payload,
                        request=None,
                        db=self.db,
                        bot=None,
                        user={"user_id": 42},
                    )
                self.assertEqual(getattr(raised.exception, "status_code", None), 400)
                self.assertIn(field, str(getattr(raised.exception, "detail", "")))

    async def test_ai_config_migration_adds_controls_without_losing_rows(self):
        db = DatabaseManager.__new__(DatabaseManager)
        db.db_type = "sqlite"
        db._sqlite_lock = threading.Lock()
        db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
        db._sqlite_conn.row_factory = sqlite3.Row
        try:
            db._sqlite_conn.execute(
                "CREATE TABLE ai_config ("
                "guild_id INTEGER PRIMARY KEY, "
                "ai_channel_id INTEGER, "
                "ai_imagine_enabled INTEGER DEFAULT 1)"
            )
            db._sqlite_conn.execute(
                "INSERT INTO ai_config (guild_id, ai_channel_id) VALUES (?, ?)",
                (123, 456),
            )
            db._sqlite_conn.commit()

            db._migrate_ai_config()

            columns = {
                row["name"]
                for row in db._sqlite_conn.execute("PRAGMA table_info(ai_config)")
            }
            self.assertIn("ai_enabled", columns)
            self.assertIn("ai_response_mode", columns)
            config = db.get_ai_config(123)
            self.assertEqual(config["ai_channel_id"], 456)
            self.assertEqual(config["ai_enabled"], 1)
            self.assertEqual(config["ai_response_mode"], "all")
        finally:
            db._sqlite_conn.close()


if __name__ == "__main__":
    unittest.main()
