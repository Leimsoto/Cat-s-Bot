import asyncio
import json
import logging
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import httpx
from fastapi import FastAPI, HTTPException

from api.deps import get_bot, get_db, require_guild_admin
from api.routes.channels import ChannelConfigUpdate, get_all_channel_configs, router, update_channel_config
from cogs.channels import Channels, ClearAllConfirmView
from database.manager import DatabaseManager
from tests.test_snowflake_api_serialization import make_db


class AutoReactionsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = make_db()
        self.guild = SimpleNamespace(id=100, me=SimpleNamespace(id=777), emojis=[])
        self.permissions = discord.Permissions(view_channel=True, read_message_history=True, add_reactions=True)
        self.channels = {
            ident: SimpleNamespace(id=ident, guild=self.guild, type=discord.ChannelType.text,
                                   permissions_for=lambda _member: self.permissions)
            for ident in (200, 201)
        }
        self.guild.get_channel = self.channels.get
        self.guild.fetch_channel = AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "missing"))
        self.bot = SimpleNamespace(db=self.db, get_guild=lambda ident: self.guild if ident == 100 else None,
                                   loop=asyncio.get_running_loop(), get_emoji=lambda _ident: None,
                                   fetch_application_emojis=AsyncMock(return_value=[]))
        self.cog = Channels(self.bot)

    async def asyncTearDown(self):
        self.db._sqlite_conn.close()

    async def save(self, channel_id, **values):
        return await update_channel_config(100, str(channel_id), ChannelConfigUpdate(**values), self.db, {}, self.bot)

    def message(self, channel_id=200, **values):
        defaults = dict(guild=self.guild, channel=self.channels[channel_id], author=SimpleNamespace(bot=False),
                        webhook_id=None, attachments=[], add_reaction=AsyncMock())
        defaults.update(values)
        return SimpleNamespace(**defaults)

    async def test_independent_channels_disable_preserves_legacy_and_other_settings(self):
        self.db.set_channel_config(200, 100, slowmode=9)
        await self.save(200, auto_react=json.dumps(["👍", "🔥"]))
        await self.save(201, auto_react=json.dumps(["❤️"]))
        await self.save(200, auto_react_enabled=False)
        disabled = self.message()
        await self.cog.on_message(disabled)
        disabled.add_reaction.assert_not_awaited()
        await self.save(200, auto_react_enabled=True)
        first, second = self.message(), self.message(201)
        await self.cog.on_message(first)
        await self.cog.on_message(second)
        self.assertEqual([call.args[0] for call in first.add_reaction.await_args_list], ["👍", "🔥"])
        second.add_reaction.assert_awaited_once_with("❤️")
        self.assertEqual(self.db.get_channel_config(200)["slowmode"], 9)
        response = await get_all_channel_configs(100, self.db, {})
        self.assertEqual({row["channel_id"] for row in response["channels"]}, {"200", "201"})
        self.assertEqual((await get_all_channel_configs(101, self.db, {}))["channels"], [])
        await self.save(200, auto_react="[]")
        self.assertEqual(self.db.get_channel_config(200)["slowmode"], 9)

    async def test_invalid_or_foreign_channel_and_emoji_never_write(self):
        for ident, emoji in ((999, "✅"), (200, "hello"), (200, "👍 🔥"), (200, "<:bad:123>"), (200, "👍🔥")):
            with self.subTest(ident=ident, emoji=emoji):
                with self.assertRaises(HTTPException):
                    await self.save(ident, auto_react=json.dumps([emoji]))
                self.assertEqual(self.db.get_all_channel_configs(100), [])
        self.channels[200].guild = SimpleNamespace(id=101)
        with self.assertRaises(HTTPException):
            await self.save(200, auto_react=json.dumps(["✅"]))
        self.assertEqual(self.db.get_all_channel_configs(100), [])

    async def test_permissions_are_required_only_when_enabling(self):
        await self.save(200, auto_react=json.dumps(["✅"]))
        self.permissions.add_reactions = False
        await self.save(200, auto_react_enabled=False)
        with self.assertRaises(HTTPException):
            await self.save(200, auto_react_enabled=True)
        self.assertFalse(self.db.get_channel_config(200)["auto_react_enabled"])

    async def test_deleted_channel_can_be_paused_and_removed_without_bot(self):
        self.db.set_channel_config(200, 100, auto_react=json.dumps(["✅", "🔥"]), slowmode=9)
        del self.channels[200]
        for fields in ({"auto_react_enabled": False}, {"auto_react": "[]", "auto_react_enabled": False}):
            await update_channel_config(100, "200", ChannelConfigUpdate(**fields), self.db, {}, None)
            self.assertEqual(self.db.get_channel_config(200)["slowmode"], 9)
        with self.assertRaises(HTTPException):
            await update_channel_config(101, "200", ChannelConfigUpdate(auto_react="[]", auto_react_enabled=False), self.db, {}, None)

    async def test_runtime_skips_bots_webhooks_dm_unconfigured_and_does_not_write(self):
        self.db.set_channel_config(200, 100, auto_react=json.dumps(["✅"]))
        before = self.db._sqlite_conn.total_changes
        for message in (self.message(author=SimpleNamespace(bot=True)), self.message(webhook_id=9),
                        self.message(guild=None), self.message(201)):
            await self.cog.on_message(message)
            message.add_reaction.assert_not_awaited()
        await self.cog.on_message(self.message())
        self.assertEqual(self.db._sqlite_conn.total_changes, before)

    async def test_runtime_discord_failures_and_bad_legacy_data_are_contained(self):
        self.db.set_channel_config(200, 100, auto_react=json.dumps(["✅"]))
        for error in (discord.Forbidden, discord.NotFound, discord.HTTPException):
            message = self.message()
            message.add_reaction.side_effect = error(SimpleNamespace(status=403, reason="error"), "error")
            await self.cog.on_message(message)
        self.db.set_channel_config(200, 100, auto_react=json.dumps([None]))
        await self.cog.on_message(self.message())

    async def test_custom_application_emoji_uses_existing_picker_format(self):
        emoji = SimpleNamespace(id=123456789012345678, name="cat", animated=False)
        self.bot.fetch_application_emojis.return_value = [emoji]
        await self.save(200, auto_react=json.dumps(["<:cat:123456789012345678>"]))
        message = self.message()
        await self.cog.on_message(message)
        message.add_reaction.assert_awaited_once_with("<:cat:123456789012345678>")

    async def test_valid_unicode_sequences_and_external_custom_remain_supported(self):
        for emoji in ("Ⓜ️", "🅰️", "🅿️", "🆎", "🈁", "👨‍👩‍👧‍👦", "👍🏽", "🇪🇸", "1️⃣"):
            with self.subTest(emoji=emoji):
                await self.save(200, auto_react=json.dumps([emoji]))
        external = SimpleNamespace(id=123456789012345678, guild=SimpleNamespace(id=101), is_usable=lambda: True)
        self.bot.get_emoji = lambda _ident: external
        with self.assertRaises(HTTPException):
            await self.save(200, auto_react=json.dumps(["<:cat:123456789012345678>"]))
        self.permissions.use_external_emojis = True
        await self.save(200, auto_react=json.dumps(["<:cat:123456789012345678>"]))

    async def test_explicit_thread_does_not_inherit_parent_reactions(self):
        self.db.set_channel_config(200, 100, auto_react=json.dumps(["✅"]))
        thread = SimpleNamespace(id=300, parent_id=200)
        message = self.message(channel=thread)
        await self.cog.on_message(message)
        message.add_reaction.assert_not_awaited()
        self.db.set_channel_config(300, 100, auto_react=json.dumps(["🔥"]))
        await self.cog.on_message(message)
        message.add_reaction.assert_awaited_once_with("🔥")

    async def test_clearall_clone_preserves_paused_reactions(self):
        self.db.set_channel_config(200, 100, auto_react=json.dumps(["✅", "🔥"]), auto_react_enabled=0)
        class FakeTextChannel:
            id = 200
            clone = AsyncMock(return_value=SimpleNamespace(id=201, send=AsyncMock()))
            delete = AsyncMock()
        interaction = SimpleNamespace(channel=FakeTextChannel(), guild_id=100,
                                      user=SimpleNamespace(mention="<@42>"), client=self.bot,
                                      response=SimpleNamespace(edit_message=AsyncMock()))
        with patch("cogs.channels.discord.TextChannel", FakeTextChannel), patch("cogs._managed_messages.send_managed", AsyncMock()):
            view = ClearAllConfirmView(42)
            await view.confirm.callback(interaction)
        clone = self.db.get_channel_config(201)
        self.assertEqual(json.loads(clone["auto_react"]), ["✅", "🔥"])
        self.assertFalse(clone["auto_react_enabled"])

    def test_additive_migration_preserves_old_rows_and_is_idempotent(self):
        db = DatabaseManager.__new__(DatabaseManager)
        db.db_type = "sqlite"
        db._sqlite_lock = threading.Lock()
        db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
        db._sqlite_conn.row_factory = sqlite3.Row
        try:
            db._sqlite_conn.execute("CREATE TABLE channel_config (channel_id INTEGER PRIMARY KEY, guild_id INTEGER, auto_react TEXT, slowmode INTEGER)")
            db._sqlite_conn.execute("INSERT INTO channel_config VALUES (200, 100, ?, 9)", (json.dumps(["✅", "🔥"]),))
            with patch.object(logging.getLogger("Database"), "disabled", True):
                db._init_schema()
                db._init_schema()
            old = db.get_channel_config(200)
            self.assertEqual(json.loads(old["auto_react"]), ["✅", "🔥"])
            self.assertTrue(old["auto_react_enabled"])
            self.assertEqual(old["slowmode"], 9)
            self.assertFalse(db.get_channel_config(201)["auto_react"])
            db.set_channel_config(200, 101, auto_react="[]")
            self.assertEqual(json.loads(db.get_channel_config(200)["auto_react"]), ["✅", "🔥"])
        finally:
            db._sqlite_conn.close()

    def test_all_routes_require_guild_admin(self):
        self.assertTrue(all(any(dep.call is require_guild_admin for dep in route.dependant.dependencies)
                            for route in router.routes))

    async def test_http_contract_and_authorization_reject_before_write(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_bot] = lambda: self.bot
        app.dependency_overrides[require_guild_admin] = lambda: {"user_id": 42}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put("/api/guild/100/channels/200", json={"auto_react": '["✅"]', "auto_react_enabled": True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["channel"]["channel_id"], "200")
            invalid = await client.put("/api/guild/100/channels/200", json={"auto_react_enabled": "false"})
            self.assertEqual(invalid.status_code, 422)
            for ident in ("-1", "0", "9223372036854775808"):
                invalid = await client.put(f"/api/guild/100/channels/{ident}", json={"auto_react": "[]"})
                self.assertEqual(invalid.status_code, 400)
            def denied():
                raise HTTPException(403, "denied")
            app.dependency_overrides[require_guild_admin] = denied
            forbidden = await client.put("/api/guild/100/channels/200", json={"auto_react": "[]"})
            self.assertEqual(forbidden.status_code, 403)
            self.assertEqual(json.loads(self.db.get_channel_config(200)["auto_react"]), ["✅"])


if __name__ == "__main__":
    unittest.main()
