import asyncio
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from api.routes.channel_settings import ChannelSettings
from cogs._channel_policy import local_actions, policy_active
from main import BotES


class ChannelSettingsRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.global_cfg = {"message_role_enabled": 1, "message_role_id": 50, "message_role_notice": "Global"}
        self.policy = ChannelSettings().model_dump()
        self.db = SimpleNamespace(get_config=lambda _id: self.global_cfg, get_channel_settings=Mock(side_effect=lambda _g, _c: self.policy))
        with patch("main.DatabaseManager", return_value=self.db):
            self.bot = BotES()
        await self.bot._async_setup_hook()
        self.bot.process_commands = AsyncMock()
        self.listener = AsyncMock()
        self.bot.add_listener(self.listener, "on_message")
        self.member = SimpleNamespace(id=42, bot=False, roles=[])
        self.staff = SimpleNamespace(id=300, send=AsyncMock())
        self.guild = SimpleNamespace(id=100, get_member=lambda _id: self.member, get_channel=lambda _id: self.staff)
        self.channel = SimpleNamespace(id=200, send=AsyncMock())
        self.tasks = []
        schedule = self.bot._schedule_event

        def record(*args, **kwargs):
            task = schedule(*args, **kwargs)
            self.tasks.append(task)
            return task

        self.bot._schedule_event = record

    async def asyncTearDown(self):
        await self.drain()
        await self.bot.close()

    def message(self, **kwargs):
        values = dict(id=600, guild=self.guild, channel=self.channel, author=self.member,
                      webhook_id=None, is_system=lambda: False, content="hello", attachments=[], embeds=[],
                      jump_url="https://discord.com/channels/100/200/600", delete=AsyncMock())
        values.update(kwargs)
        return SimpleNamespace(**values)

    async def drain(self):
        while self.tasks:
            tasks, self.tasks = self.tasks, []
            await asyncio.gather(*tasks)

    async def check(self, message):
        return await self.bot._check_message_role(message, self.global_cfg, self.policy)

    async def test_global_inherit_and_whitelist_does_not_bypass_global(self):
        self.policy["whitelist"]["user_ids"] = ["42"]
        blocked = self.message()
        self.assertFalse(await self.check(blocked))
        blocked.delete.assert_awaited_once()
        self.member.roles = [SimpleNamespace(id=50)]
        self.policy["restrictions"]["media_only"] = True
        self.assertTrue(await self.check(self.message()))

    async def test_additional_override_and_explicit_off(self):
        self.policy["role"].update(mode="additional", role_ids=["60"])
        self.member.roles = [SimpleNamespace(id=60)]
        self.assertFalse(await self.check(self.message()))
        self.member.roles.append(SimpleNamespace(id=50))
        self.assertTrue(await self.check(self.message()))
        self.policy["role"]["mode"] = "override"
        self.member.roles = [SimpleNamespace(id=60)]
        self.assertTrue(await self.check(self.message()))
        self.policy["role"]["mode"] = "off"
        self.member.roles = []
        self.assertTrue(await self.check(self.message()))

    async def test_local_content_whitelist_only_bypasses_local(self):
        self.member.roles = [SimpleNamespace(id=50)]
        self.policy["restrictions"].update(media_only=True, block_links=True, blocked_words=["malo"])
        media = SimpleNamespace(content_type="image/png", filename="photo.png")
        self.assertTrue(await self.check(self.message(attachments=[media])))
        for message in (self.message(), self.message(content="https://example.org", attachments=[media]), self.message(content="MALO", attachments=[media])):
            self.assertFalse(await self.check(message))
        self.policy["whitelist"]["role_ids"] = ["50"]
        self.assertTrue(await self.check(self.message(content="malo https://example.org")))

    async def test_trigger_actions_edits_deduplicate_and_suppress_dispatch(self):
        self.member.roles = [SimpleNamespace(id=50)]
        self.policy["staff_channel_id"] = "300"
        self.policy["triggers"] = [dict(id="links", name="Enlaces", condition="has_link", values=[], delete=True, response="Sin enlaces @everyone", notify_staff=True)]
        message = self.message(content="https://example.org")
        self.bot.dispatch("raw_message_edit", SimpleNamespace(message=message))
        self.bot.dispatch("message_edit", self.message(), message)
        await self.drain()
        message.delete.assert_awaited_once()
        self.channel.send.assert_awaited_once()
        self.staff.send.assert_awaited_once()
        self.assertEqual(self.staff.send.await_args.kwargs["allowed_mentions"].to_dict()["parse"], [])
        self.bot.dispatch("message", self.message(content="https://example.net"))
        await self.drain()
        self.channel.send.assert_awaited_once()
        self.listener.assert_not_awaited()
        self.bot.process_commands.assert_not_awaited()

    async def test_non_deleting_trigger_continues_listeners_and_bounds_responses(self):
        self.member.roles = [SimpleNamespace(id=50)]
        trigger = dict(id="one", name="Uno", condition="any_message", values=[], delete=False, response="Hola", notify_staff=False)
        self.policy["triggers"] = [trigger, {**trigger, "id": "two"}]
        message = self.message()
        self.bot.dispatch("message", message)
        await self.drain()
        self.listener.assert_awaited_once_with(message)
        self.channel.send.assert_awaited_once()
        message.delete.assert_not_awaited()

    async def test_disabled_and_outside_schedule_restore_global_and_threads_inherit(self):
        self.policy["role"]["mode"] = "off"
        self.policy["enabled"] = False
        message = self.message()
        self.bot.dispatch("message", message)
        await self.drain()
        message.delete.assert_awaited_once()
        self.policy["enabled"] = True
        self.policy["schedule"] = {"enabled": True, "timezone": "UTC", "windows": [{"days": [0], "start": "01:00", "end": "02:00"}]}
        with patch("main.policy_active", return_value=False):
            outside = self.message(id=601)
            self.bot.dispatch("message", outside)
            await self.drain()
        outside.delete.assert_awaited_once()
        thread = Mock(spec=discord.Thread)
        thread.id = 201
        thread.parent_id = 200
        self.policy["schedule"]["enabled"] = False
        self.bot.dispatch("message", self.message(channel=thread))
        await self.drain()
        self.db.get_channel_settings.assert_called_with(100, 200)

    async def test_discord_errors_do_not_release_rejected_messages(self):
        self.member.roles = [SimpleNamespace(id=50)]
        self.policy["restrictions"]["media_only"] = True
        response = SimpleNamespace(status=403, reason="Forbidden")
        message = self.message(delete=AsyncMock(side_effect=discord.Forbidden(response, "cannot delete")))
        self.bot.dispatch("message", message)
        await self.drain()
        self.listener.assert_not_awaited()
        self.bot.process_commands.assert_not_awaited()

    async def test_uncached_thread_resolves_parent_policy_before_dispatch(self):
        self.global_cfg["message_role_enabled"] = 0
        self.policy["restrictions"]["block_links"] = True
        partial = Mock(spec=discord.PartialMessageable)
        partial.id = 201
        thread = Mock(spec=discord.Thread)
        thread.id = 201
        thread.parent_id = 200
        self.guild.fetch_channel = AsyncMock(return_value=thread)
        message = self.message(channel=partial, content="https://example.org")
        self.bot.dispatch("message", message)
        await self.drain()
        self.guild.fetch_channel.assert_awaited_once_with(201)
        self.db.get_channel_settings.assert_called_with(100, 200)
        message.delete.assert_awaited_once()
        self.listener.assert_not_awaited()


class ChannelScheduleTest(unittest.TestCase):
    def test_overnight_window_uses_previous_start_day_and_end_is_exclusive(self):
        config = ChannelSettings(schedule={"enabled": True, "timezone": "UTC", "windows": [{"days": [0], "start": "22:00", "end": "06:00"}]}).model_dump()
        def active(iso):
            return policy_active(config, datetime.fromisoformat(iso))
        self.assertTrue(active("2026-10-05T22:00:00+00:00"))
        self.assertTrue(active("2026-10-06T05:59:00+00:00"))
        self.assertFalse(active("2026-10-06T06:00:00+00:00"))
        self.assertFalse(active("2026-10-07T02:00:00+00:00"))

    def test_dst_repeated_hour_uses_local_wall_time(self):
        config = ChannelSettings(schedule={"enabled": True, "timezone": "Europe/Lisbon", "windows": [{"days": [6], "start": "01:00", "end": "02:00"}]}).model_dump()
        self.assertTrue(policy_active(config, datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)))
        self.assertTrue(policy_active(config, datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)))
        self.assertFalse(policy_active(config, datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc)))

    def test_trigger_conditions_are_literal_and_do_not_run_regex(self):
        config = ChannelSettings(triggers=[dict(id="literal", name="Literal", condition="contains_text", values=["(a+)+$"], response="Texto"),
                                          dict(id="rolecheck", name="Rol", condition="missing_role", values=["90"], delete=True)]).model_dump()
        member = SimpleNamespace(id=42, roles=[SimpleNamespace(id=90)])
        message = SimpleNamespace(content="aaaaa", attachments=[], embeds=[])
        self.assertEqual(local_actions(message, member, config), [])
        message.content = "Texto (A+)+$ literal"
        self.assertEqual(local_actions(message, member, config)[0]["id"], "literal")

    def test_forwarded_snapshots_are_checked_but_reply_reference_is_not(self):
        config = ChannelSettings(restrictions={"block_links": True, "media_only": True, "blocked_words": ["prohibido"]}).model_dump()
        member = SimpleNamespace(id=42, roles=[])
        image = SimpleNamespace(content_type="image/png", filename="photo.png")
        source = SimpleNamespace(content="PROHIBIDO https://example.org", attachments=[image], embeds=[])
        message = SimpleNamespace(content="", attachments=[], embeds=[], message_snapshots=[source])
        self.assertEqual(local_actions(message, member, config)[0]["id"], "content")
        source.content = "foto"
        self.assertEqual(local_actions(message, member, config), [])
        message.message_snapshots = []
        message.referenced_message = source
        self.assertEqual(local_actions(message, member, config)[0]["id"], "content")


if __name__ == "__main__":
    unittest.main()
