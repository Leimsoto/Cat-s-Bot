import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from cogs.automod import AutoMod
from cogs._llm_moderation import fingerprint
from tests import test_manual_warn_hierarchy as manual


class WarnEscalationTests(unittest.IsolatedAsyncioTestCase):
    role = manual.ManualWarnHierarchyTests.role
    member = manual.ManualWarnHierarchyTests.member

    def setUp(self):
        manual.ManualWarnHierarchyTests.setUp(self)
        self.roles[1450] = self.role(1450, "Member", 145, 0)
        self.cog.bot.get_cog = lambda name: self.cog if name == "Moderation" else None
        self.db.set_config(100, warn_mute_enabled=1, warn_mute_threshold=3,
            warn_mute_duration=3600, mute_role_id=1440,
            warn_kick_enabled=1, warn_kick_threshold=5,
            warn_ban_enabled=1, warn_ban_threshold=8)
        self.db.set_automod_config(100, enabled=1, rules={"banned_words": {
            "enabled": True, "words": ["prohibido"], "action": "warn"}})
        self.automod = AutoMod(self.cog.bot)
        self.automod._log_to_modlog = AsyncMock()
        self.automod.llm.notify_deleted = AsyncMock()
        self.message = SimpleNamespace(id=500, author=self.target, guild=self.guild,
            channel=SimpleNamespace(id=30), content="prohibido", delete=AsyncMock(),
            jump_url="https://discord.com/channels/100/30/500", attachments=[])
        self.message.channel.fetch_message = AsyncMock(return_value=self.message)

    def tearDown(self):
        self.db._sqlite_conn.close()

    async def auto_warn(self):
        await self.automod._execute_action(self.message, "banned_words", "warn", {})

    def llm_warn_config(self):
        self.db.set_automod_config(100, rules={"llm": {"enabled": True,
            "rules_text": "No insultar", "endpoint_url": "https://llm.example/v1",
            "model": "test"}})
        decision = {"action": "warn", "duration_seconds": None,
            "reason": "Incumple la regla", "rule": "No insultar"}
        version = fingerprint(self.message)
        self.automod.llm.versions[self.message.id] = version
        self.automod.llm.decisions[self.message.id] = (
            version, self.automod.llm.configured(100)[1], decision, version)
        return self.automod.llm.action_config(self.message, decision)

    async def test_automod_seventh_warn_uses_dashboard_kick_and_links_warn_case(self):
        self.db._upsert_user(20, 100, warns=6)
        await self.auto_warn()
        self.guild.kick.assert_awaited_once()
        cases = self.db.list_cases(100)
        self.assertEqual([(case["action_type"], case["status"]) for case in cases],
            [("AUTO_KICK", "active"), ("AUTO_WARN", "active")])
        self.assertEqual(cases[0]["parent_case_id"], cases[1]["id"])
        self.assertEqual(json.loads(cases[0]["extra_data"])["source"], "automod")

    async def test_llm_warns_use_kick_at_seven_and_ban_at_eight(self):
        config = self.llm_warn_config()
        self.db._upsert_user(20, 100, warns=6)
        await self.automod._execute_action(self.message, "llm", "warn", config)
        self.guild.kick.assert_awaited_once()
        self.guild.ban.assert_not_awaited()
        self.message.id += 1
        config = self.llm_warn_config()
        ban_reason = ""
        async def ban(member, **kwargs):
            nonlocal ban_reason
            ban_reason = kwargs["reason"]
        self.guild.ban.side_effect = ban
        self.guild.fetch_ban = AsyncMock(side_effect=lambda _: SimpleNamespace(reason=ban_reason))
        await self.automod._execute_action(self.message, "llm", "warn", config)
        self.guild.ban.assert_awaited_once()
        self.assertEqual(self.guild.kick.await_count, 1)
        cases = self.db.list_cases(100)
        self.assertEqual([(case["action_type"], case["status"]) for case in cases],
            [("AUTO_BAN", "active"), ("AUTO_WARN", "active"),
             ("AUTO_KICK", "active"), ("AUTO_WARN", "active")])
        self.assertEqual(cases[0]["parent_case_id"], cases[1]["id"])
        self.assertEqual(json.loads(cases[0]["extra_data"])["source"], "llm")
        self.assertEqual([row["action_taken"] for row in self.db.get_automod_log(100)],
            ["warn", "delete", "warn", "delete"])

    async def test_llm_warn_still_escalates_after_successful_message_deletion(self):
        self.db._upsert_user(20, 100, warns=6)
        config = self.llm_warn_config()
        self.db.set_automod_config(100, enabled=0)
        async def deleted():
            self.message.channel.fetch_message.side_effect = discord.NotFound(
                SimpleNamespace(status=404, reason="not found"), "deleted")
        self.message.delete.side_effect = deleted
        await self.automod._execute_action(self.message, "llm", "warn", config)
        self.guild.kick.assert_awaited_once()
        self.assertEqual(self.message.channel.fetch_message.await_count, 2)

    async def test_llm_failed_deletion_keeps_message_version_guard_for_consequence(self):
        self.db._upsert_user(20, 100, warns=6)
        config = self.llm_warn_config()
        async def failed_deletion():
            self.message.channel.fetch_message.side_effect = discord.NotFound(
                SimpleNamespace(status=404, reason="not found"), "deleted elsewhere")
            raise discord.Forbidden(SimpleNamespace(status=403, reason="forbidden"), "blocked")
        self.message.delete.side_effect = failed_deletion
        await self.automod._execute_action(self.message, "llm", "warn", config)
        self.guild.kick.assert_not_awaited()
        self.assertEqual(self.message.channel.fetch_message.await_count, 3)

    async def test_manual_warn_reuses_kick_and_requires_actor_kick_authority(self):
        self.db._upsert_user(20, 100, warns=6)
        self.roles[1470] = self.role(1470, "Moderator", 147,
            discord.Permissions(moderate_members=True).value)
        await self.cog.warn.callback(self.cog, self.interaction, self.target, "Motivo concreto")
        self.guild.kick.assert_not_awaited()
        self.assertEqual([row["action_type"] for row in self.db.list_cases(100)], ["WARN"])
        self.roles[1470] = self.role(1470, "Moderator", 147, 8)
        self.db.set_config(100, warn_ban_enabled=0)
        await self.cog.warn.callback(self.cog, self.interaction, self.target, "Motivo concreto")
        self.guild.kick.assert_awaited_once()

    async def test_disabled_actions_and_below_threshold_do_not_apply_a_consequence(self):
        await self.auto_warn()
        self.db._upsert_user(20, 100, warns=7)
        self.db.set_config(100, warn_mute_enabled=0, warn_kick_enabled=0, warn_ban_enabled=0)
        await self.auto_warn()
        self.guild.kick.assert_not_awaited()
        self.guild.ban.assert_not_awaited()
        self.assertEqual({case["action_type"] for case in self.db.list_cases(100)}, {"AUTO_WARN"})

    async def test_changed_dashboard_policy_is_rechecked_after_authorization(self):
        self.db._upsert_user(20, 100, warns=6)
        fresh = self.cog._fresh_moderation_context
        async def changed(*args, **kwargs):
            result = await fresh(*args, **kwargs)
            self.db.set_config(100, warn_kick_enabled=0, warn_mute_enabled=0)
            return result
        self.cog._fresh_moderation_context = changed
        await self.auto_warn()
        self.guild.kick.assert_not_awaited()
        self.assertEqual([row["action_type"] for row in self.db.list_cases(100)], ["AUTO_WARN"])

    async def test_changed_automod_exemption_is_rechecked_before_consequence(self):
        self.db._upsert_user(20, 100, warns=6)
        fresh = self.automod._fresh_policy_allows_action
        calls = 0
        async def changed(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 3:
                self.db.set_automod_config(100, rules={"ignored": {"channels": [30]}})
            return await fresh(*args, **kwargs)
        self.automod._fresh_policy_allows_action = changed
        await self.auto_warn()
        self.guild.kick.assert_not_awaited()
        self.assertEqual([row["action_type"] for row in self.db.list_cases(100)], ["AUTO_WARN"])

    async def test_missing_bot_permission_or_fresh_admin_protection_blocks_consequence(self):
        self.db._upsert_user(20, 100, warns=6)
        self.roles[1460] = self.role(1460, "Bot", 146, 0)
        await self.auto_warn()
        self.guild.kick.assert_not_awaited()
        self.roles[1460] = self.role(1460, "Bot", 146, 8)
        fresh = self.cog._fresh_moderation_context
        async def promoted(*args, **kwargs):
            self.roles[1450] = self.role(1450, "Admin", 145, 8)
            return await fresh(*args, **kwargs)
        self.cog._fresh_moderation_context = promoted
        self.db.set_config(100, warn_ban_enabled=0)
        await self.auto_warn()
        self.guild.kick.assert_not_awaited()
        self.guild.ban.assert_not_awaited()

    async def test_http_kick_failure_retains_warn_and_does_not_log_success(self):
        self.db._upsert_user(20, 100, warns=6)
        self.guild.kick.side_effect = discord.HTTPException(
            SimpleNamespace(status=500, reason="server error"), "unavailable")
        await self.auto_warn()
        self.assertEqual([row["action_type"] for row in self.db.list_cases(100)], ["AUTO_WARN"])
        self.assertEqual(self.automod._log_to_modlog.await_count, 1)
        embed = self.automod._log_to_modlog.await_args.args[1]
        self.assertIn("sin confirmar", embed.fields[-1].value)

    async def test_unconfirmed_ban_remains_applying_and_never_logs_success(self):
        self.db._upsert_user(20, 100, warns=7)
        self.guild.fetch_ban = AsyncMock(return_value=SimpleNamespace(reason="different ban"))
        with patch("cogs.moderation.asyncio.sleep", new=AsyncMock()):
            await self.auto_warn()
        self.assertEqual([(row["action_type"], row["status"]) for row in self.db.list_cases(100)],
            [("AUTO_BAN", "applying"), ("AUTO_WARN", "active")])
        self.assertEqual(self.automod._log_to_modlog.await_count, 1)

    async def test_forbidden_ban_marks_intent_failed(self):
        self.db._upsert_user(20, 100, warns=7)
        self.guild.ban.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason="forbidden"), "blocked")
        await self.auto_warn()
        self.assertEqual([(row["action_type"], row["status"]) for row in self.db.list_cases(100)],
            [("AUTO_BAN", "failed"), ("AUTO_WARN", "active")])
        self.assertEqual(self.automod._log_to_modlog.await_count, 1)

    async def test_concurrent_llm_delivery_counts_and_escalates_message_once(self):
        self.db._upsert_user(20, 100, warns=6)
        config = self.llm_warn_config()
        await asyncio.gather(*(self.automod._execute_action(self.message, "llm", "warn", config)
            for _ in range(2)))
        self.guild.kick.assert_awaited_once()
        self.assertEqual(self.db.get_user(20, 100)["warns"], 7)
        self.assertEqual([row["action_type"] for row in self.db.list_cases(100)], ["AUTO_KICK", "AUTO_WARN"])

    async def test_concurrent_distinct_warns_do_not_kick_an_absent_member_twice(self):
        self.db._upsert_user(20, 100, warns=4)
        async def fetch_member(user_id):
            if user_id not in self.members:
                raise discord.NotFound(SimpleNamespace(status=404, reason="not found"), "left")
            return self.members[user_id]
        self.guild.fetch_member.side_effect = fetch_member
        async def kicked(*args, **kwargs):
            self.members.pop(20)
        self.guild.kick.side_effect = kicked
        other = SimpleNamespace(**{**vars(self.message), "id": 501})
        await asyncio.gather(self.auto_warn(),
            self.automod._execute_action(other, "banned_words", "warn", {}))
        self.guild.kick.assert_awaited_once()
        self.assertEqual(sum(row["action_type"] == "AUTO_KICK"
            for row in self.db.list_cases(100)), 1)


if __name__ == "__main__":
    unittest.main()
