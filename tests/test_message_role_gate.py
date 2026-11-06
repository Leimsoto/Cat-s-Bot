import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from main import BotES


ROLE_ID = 123456789012345678


class MessageRoleGateTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = {"message_role_enabled": 1, "message_role_id": ROLE_ID,
                    "message_role_notice": "Consigue el rol. @everyone <@&123> <@456>"}
        self.db = SimpleNamespace(get_config=Mock(side_effect=lambda _guild_id: dict(self.cfg)))
        with patch("main.DatabaseManager", return_value=self.db):
            self.bot = BotES()
        await self.bot._async_setup_hook()
        self.bot.process_commands = AsyncMock()
        self.listener = AsyncMock()
        self.bot.add_listener(self.listener, "on_message")
        self.edit_listener = AsyncMock()
        self.raw_listener = AsyncMock()
        self.bot.add_listener(self.edit_listener, "on_message_edit")
        self.bot.add_listener(self.raw_listener, "on_raw_message_edit")
        self.tasks = []
        schedule = self.bot._schedule_event

        def record(*args, **kwargs):
            task = schedule(*args, **kwargs)
            self.tasks.append(task)
            return task

        self.bot._schedule_event = record
        self.author = SimpleNamespace(id=42, bot=False, roles=[], guild_permissions=SimpleNamespace(administrator=True))
        self.guild = SimpleNamespace(id=100, get_member=lambda _id: self.author, fetch_member=AsyncMock())
        self.channel = SimpleNamespace(id=200, send=AsyncMock(), fetch_message=AsyncMock())

    async def asyncTearDown(self):
        await self.drain()
        await self.bot.close()

    def message(self, **overrides):
        values = dict(id=300, guild=self.guild, author=self.author, channel=self.channel,
                      webhook_id=None, is_system=lambda: False, delete=AsyncMock())
        values.update(overrides)
        return SimpleNamespace(**values)

    async def drain(self):
        while self.tasks:
            tasks, self.tasks = self.tasks, []
            await asyncio.gather(*tasks)

    async def test_block_precedes_commands_cogs_and_wait_for_even_for_admin(self):
        waiter = asyncio.create_task(self.bot.wait_for("message"))
        await asyncio.sleep(0)
        message = self.message()
        self.bot.dispatch("message", message)
        await self.drain()
        message.delete.assert_awaited_once()
        self.listener.assert_not_awaited()
        self.bot.process_commands.assert_not_awaited()
        self.assertFalse(waiter.done())
        notice = self.channel.send.await_args
        self.assertTrue(notice.args[0].startswith("<@42> "))
        self.assertIn("@everyone", notice.args[0])
        mentions = notice.kwargs["allowed_mentions"].to_dict()
        self.assertEqual(mentions["users"], [42])
        self.assertEqual(mentions["parse"], [])
        self.author.roles.append(SimpleNamespace(id=ROLE_ID))
        allowed = self.message(id=301)
        self.bot.dispatch("message", allowed)
        await self.drain()
        self.assertIs(await waiter, allowed)
        self.listener.assert_awaited_once_with(allowed)
        self.bot.process_commands.assert_awaited_once_with(allowed)
        allowed.delete.assert_not_awaited()

    async def test_disabled_bot_webhook_dm_and_system_pass(self):
        excluded = [self.message(author=SimpleNamespace(id=9, bot=True)),
                    self.message(webhook_id=9), self.message(guild=None),
                    self.message(is_system=lambda: True)]
        for message in excluded:
            self.bot.dispatch("message", message)
            await self.drain()
            message.delete.assert_not_awaited()
        self.cfg["message_role_enabled"] = 0
        message = self.message()
        self.bot.dispatch("message", message)
        await self.drain()
        self.assertEqual(self.listener.await_count, 5)
        self.assertEqual(self.bot.process_commands.await_count, 5)
        message.delete.assert_not_awaited()

    async def test_cooldown_suppresses_only_notice_and_expires(self):
        with patch.object(asyncio.get_running_loop(), "call_later") as timer:
            first, second = self.message(), self.message(id=301)
            self.bot.dispatch("message", first)
            self.bot.dispatch("message", second)
            await self.drain()
        first.delete.assert_awaited_once()
        second.delete.assert_awaited_once()
        self.channel.send.assert_awaited_once()
        seconds, expire, key = timer.call_args.args
        self.assertEqual(seconds, 10)
        expire(key)
        self.bot.dispatch("message", self.message(id=302))
        await self.drain()
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_discord_failures_do_not_release_rejected_message(self):
        response = SimpleNamespace(status=403, reason="Forbidden")
        for failure in (discord.Forbidden(response, "no permission"),
                        discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "gone")):
            message = self.message(delete=AsyncMock(side_effect=failure))
            self.bot.dispatch("message", message)
            await self.drain()
        self.channel.send.side_effect = discord.HTTPException(response, "send failed")
        self.bot.dispatch("message", self.message())
        await self.drain()
        self.listener.assert_not_awaited()
        self.bot.process_commands.assert_not_awaited()

    async def test_raw_and_cached_edit_share_check_but_later_edits_are_checked(self):
        message = self.message()
        raw = SimpleNamespace(message=message, cached_message=self.message())
        self.bot.dispatch("raw_message_edit", raw)
        self.bot.dispatch("message_edit", raw.cached_message, message)
        await self.drain()
        message.delete.assert_awaited_once()
        self.raw_listener.assert_not_awaited()
        self.edit_listener.assert_not_awaited()
        self.assertEqual(self.bot._message_role_checks, {})
        self.author.roles.append(SimpleNamespace(id=ROLE_ID))
        # Mismo ID Discord, objeto distinto para la siguiente edición.
        edited = self.message()
        self.bot.dispatch("raw_message_edit", SimpleNamespace(message=edited))
        self.bot.dispatch("message_edit", message, edited)
        await self.drain()
        self.raw_listener.assert_awaited_once()
        self.edit_listener.assert_awaited_once_with(message, edited)

    async def test_incomplete_raw_payload_fetches_author_and_fails_closed(self):
        partial = self.message(author=None)
        resolved = self.message()
        self.channel.fetch_message.return_value = resolved
        self.bot.dispatch("raw_message_edit", SimpleNamespace(message=partial))
        await self.drain()
        resolved.delete.assert_awaited_once()
        self.raw_listener.assert_not_awaited()
        self.channel.fetch_message.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "no access")
        self.bot.dispatch("raw_message_edit", SimpleNamespace(message=self.message(author=None)))
        await self.drain()
        self.raw_listener.assert_not_awaited()

    async def test_notice_limit_does_not_expand_mentions_and_typing_is_unaffected(self):
        self.cfg["message_role_notice"] = "@here" * 395
        self.bot.dispatch("message", self.message())
        await self.drain()
        notice = self.channel.send.await_args
        self.assertLessEqual(len(notice.args[0].encode("utf-16-le")) // 2, 2000)
        self.assertEqual(notice.kwargs["allowed_mentions"].to_dict()["parse"], [])
        typing = AsyncMock()
        self.bot.add_listener(typing, "on_typing")
        self.bot.dispatch("typing", self.channel, self.author, None)
        await self.drain()
        typing.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
