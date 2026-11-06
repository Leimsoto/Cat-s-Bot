"""Chat-only deny rules; no Discord, provider or persistent database connections."""
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from fastapi import HTTPException

from api.routes.guild import get_ia_config, patch_ia_config
from cogs.ia import IA, types
from database.manager import DatabaseManager
from tests import test_conversation_memory as conversation_fixtures
from tests.test_ia_runtime import _Bot, _Message


class GeminiChatAccessTest(unittest.IsolatedAsyncioTestCase):
    def cog(self, **config):
        cog = IA(_Bot(**config))
        cog._get_client_for_guild = lambda _: object()
        cog._get_system_prompt = lambda _: "Prompt"
        cog._build_user_parts = AsyncMock(return_value=[types.Part.from_text(text="Pregunta")])
        cog._send_reply = AsyncMock()
        cog._generate_with_retries = AsyncMock(return_value=SimpleNamespace(text="Respuesta"))
        return cog

    async def test_bots_and_webhooks_stop_before_strata_dispatch_or_gemini_queue(self):
        for provider in ("strata", "gemini"):
            for automated in ("bot", "webhook"):
                with self.subTest(provider=provider, automated=automated):
                    cog = self.cog(ai_provider=provider)
                    cog.conversation.listen = AsyncMock()
                    message = _Message()
                    message.author.bot = automated == "bot"
                    message.webhook_id = 123 if automated == "webhook" else None
                    await cog.on_message(message)
                    cog.conversation.listen.assert_not_awaited()
                    cog._build_user_parts.assert_not_awaited()
                    self.assertTrue(cog._queue.empty())
                    self.assertEqual(message.channel.sent, [])

    async def test_queued_automated_job_never_reaches_provider_or_conversation(self):
        for conversation in (False, True):
            with self.subTest(conversation=conversation):
                cog = self.cog()
                cog.conversation.process = AsyncMock()
                message = _Message()
                message.author.bot = True
                await cog._process_job({"message": message, "conversation": conversation, "ctx_id": "10_20_30",
                    "config": None, "is_ai_channel": True, "user_parts": [types.Part.from_text(text="Pregunta")]})
                cog.conversation.process.assert_not_awaited()
                cog._generate_with_retries.assert_not_awaited()
                self.assertEqual(message.channel.sent, [])

    async def test_restricted_role_wins_over_allowed_role_admin_and_primary_channel(self):
        cog = self.cog(ai_role_id=77, ai_restricted_role_ids=["88"])
        message = _Message()
        message.author.roles = [SimpleNamespace(id=77), SimpleNamespace(id=88, permissions=discord.Permissions(administrator=True))]
        message.mentions = [cog.bot.user]
        await cog.on_message(message)
        cog._build_user_parts.assert_not_awaited()
        self.assertTrue(cog._queue.empty())
        self.assertEqual(message.channel.sent, [])

    async def test_restriction_added_during_generation_blocks_reply_and_error_silently(self):
        for change in ("config", "cached_role", "error"):
            with self.subTest(change=change):
                cog = self.cog(ai_restricted_role_ids=["88"] if change == "cached_role" else [])
                message = _Message()
                current = SimpleNamespace(id=message.author.id, bot=False, roles=[])
                message.guild.get_member = lambda _: current
                if change != "cached_role":
                    message.author.roles = [SimpleNamespace(id=88)]
                    current.roles = message.author.roles
                async def generate(**kwargs):
                    if change == "cached_role":
                        current.roles = [SimpleNamespace(id=88)]
                    else:
                        cog.db.config["ai_restricted_role_ids"] = ["88"]
                    if change == "error":
                        raise RuntimeError("provider fixture failure")
                    return SimpleNamespace(text="No debe enviarse")
                cog._generate_with_retries.side_effect = generate
                await cog.on_message(message)
                await cog._process_job(cog._queue.get_nowait())
                cog._send_reply.assert_not_awaited()
                self.assertEqual(message.channel.sent, [])
                self.assertFalse(any(turn.role == "model" for turn in cog._chat_histories.get("10_20_30", [])))


class StrataChatAccessTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = conversation_fixtures.ConversationRuntimeTest()
        await self.fixture.asyncSetUp()

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()

    async def test_restricted_admin_is_silent_and_allowed_human_still_queues(self):
        f = self.fixture
        admin = discord.Role(guild=f.guild, state=None, data={"id": "44", "name": "Admin", "permissions": "8", "position": 1})
        f.guild._roles[44] = admin
        f.guild.fetch_roles.return_value = [f.role, admin]
        f.members[30]._roles = discord.utils.SnowflakeList([10, 44])
        f.db.set_ai_config(10, ai_role_id=10, ai_restricted_role_ids=["44"])
        restricted = f.message(ping=True)
        await f.engine.listen(restricted)
        self.assertTrue(f.cog._queue.empty())
        self.assertEqual(f.db.get_ai_chat_turns(10, 20), [])
        restricted.reply.assert_not_awaited()
        allowed = f.message(101, user_id=31, ping=True)
        await f.engine.listen(allowed)
        self.assertEqual(f.cog._queue.qsize(), 1)

    async def test_restricted_role_added_after_queue_prevents_llm_and_reply(self):
        f = self.fixture
        f.db.set_ai_config(10, ai_restricted_role_ids=["44"])
        message = f.message(ping=True)
        await f.engine.listen(message)
        role = discord.Role(guild=f.guild, state=None, data={"id": "44", "name": "Blocked", "permissions": "8", "position": 1})
        f.guild._roles[44] = role
        f.guild.fetch_roles.return_value = [f.role, role]
        f.members[30]._roles = discord.utils.SnowflakeList([10, 44])
        with patch("cogs._conversation.request_completion", new=AsyncMock()) as provider:
            await f.engine.process(f.cog._queue.get_nowait())
        provider.assert_not_awaited()
        message.reply.assert_not_awaited()


class ChatAccessConfigTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = conversation_fixtures.database()

    async def asyncTearDown(self):
        self.db._sqlite_conn.close()

    async def test_api_default_exact_ids_roundtrip_and_legacy_update_preserves_denylist(self):
        self.assertEqual((await get_ia_config(10, self.db, {}))["ai_restricted_role_ids"], [])
        role_id = "1523702726393860373"
        result = await patch_ia_config(10, {"ai_restricted_role_ids": [role_id, role_id]}, None, self.db, None, {})
        self.assertEqual(result["ai_restricted_role_ids"], [role_id])
        await patch_ia_config(10, {"ai_response_mode": "mentions"}, None, self.db, None, {})
        self.assertEqual(self.db.get_ai_config(10)["ai_restricted_role_ids"], [role_id])
        await patch_ia_config(10, {"ai_restricted_role_ids": []}, None, self.db, None, {})
        self.assertEqual(self.db.get_ai_config(10)["ai_restricted_role_ids"], [])

    async def test_invalid_role_lists_are_rejected_without_changing_config(self):
        for value in (None, "[]", {}, True, [True], [1.5], [0], [-1], [""], ["x"], [2**64], ["١"]):
            with self.subTest(value=value):
                with self.assertRaises(HTTPException) as caught:
                    await patch_ia_config(10, {"ai_restricted_role_ids": value}, None, self.db, None, {})
                self.assertEqual(caught.exception.status_code, 400)

    async def test_additive_migration_preserves_old_config(self):
        db = DatabaseManager.__new__(DatabaseManager)
        db.db_type = "sqlite"
        db._sqlite_lock = threading.Lock()
        db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
        db._sqlite_conn.row_factory = sqlite3.Row
        try:
            db._sqlite_conn.execute("CREATE TABLE ai_config (guild_id INTEGER PRIMARY KEY, ai_channel_id INTEGER)")
            db._sqlite_conn.execute("INSERT INTO ai_config VALUES (10, 20)")
            db._sqlite_conn.commit()
            db._migrate_ai_config()
            self.assertEqual(db.get_ai_config(10)["ai_channel_id"], 20)
            self.assertEqual(db.get_ai_config(10)["ai_restricted_role_ids"], [])
        finally:
            db._sqlite_conn.close()


if __name__ == "__main__":
    unittest.main()
