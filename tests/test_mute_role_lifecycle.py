import json
import asyncio
import unittest
from copy import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from fastapi import HTTPException

from api.routes.moderation import update_appeal
from cogs._mute_roles import fresh_members, plan_role_mute, restore_roles
from cogs.moderation import Moderation
from tests.test_managed_messages import make_db


class MuteRoleLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db._sqlite_conn.close)
        self.state = SimpleNamespace(self_id=999, cache_guild_expressions=False,
            member_cache_flags=SimpleNamespace(joined=False, voice=False), http=SimpleNamespace())
        self.state.store_user = lambda data: discord.User(state=self.state, data=data)
        member_permissions = discord.Permissions(view_channel=True, send_messages=True,
            send_messages_in_threads=True, create_public_threads=True, create_private_threads=True)
        self.roles_data = [
            {"id": "100", "name": "@everyone", "position": 0, "permissions": str(member_permissions.value)},
            {"id": "200", "name": "Member", "position": 100, "permissions": "0"},
            {"id": "210", "name": "Staff", "position": 110, "permissions": "0"},
            {"id": "220", "name": "Admin", "position": 120, "permissions": "8"},
            {"id": "300", "name": "Muted", "position": 125, "permissions": "0"},
            {"id": "400", "name": "Bot", "position": 146, "permissions": "8"},
            {"id": "450", "name": "Manager", "position": 147, "permissions": "8"},
        ]
        self.guild = discord.Guild(state=self.state, data={"id": "100", "name": "Synthetic",
            "owner_id": "1", "roles": self.roles_data})
        allow, deny = Moderation._mute_overwrite().pair()
        self.channel_data = {"id": "500", "type": 0, "name": "synthetic", "position": 0,
            "permission_overwrites": [
                {"id": "300", "type": 0, "allow": str(allow.value), "deny": str(deny.value)},
                {"id": "210", "type": 0, "allow": str(discord.Permissions(send_messages=True).value), "deny": "0"},
            ]}
        self.guild._channels[500] = discord.TextChannel(state=self.state, guild=self.guild, data=self.channel_data)
        self.server_roles = {20: [200, 210, 220], 10: [450], 999: [400]}
        self.members = {}
        for user_id in self.server_roles:
            self.members[user_id] = discord.Member(state=self.state, guild=self.guild, data={
                "user": {"id": str(user_id), "username": "synthetic", "discriminator": "0", "avatar": None,
                         "bot": user_id == 999},
                "roles": [str(value) for value in self.server_roles[user_id]], "flags": 0,
                "joined_at": "2026-01-01T00:00:00+00:00",
            })
        self.guild._members = self.members
        self.events = []
        self.state.http.add_role = AsyncMock(side_effect=self.add_role)
        self.state.http.remove_role = AsyncMock(side_effect=self.remove_role)
        self.cog = Moderation.__new__(Moderation)
        self.cog.db = self.db
        self.cog.bot = SimpleNamespace(db=self.db, user=self.members[999], catbot_voice=None,
            get_guild=lambda _: self.guild, fetch_guild=AsyncMock(return_value=self.guild))
        self.cog._send_log, self.cog._dm = AsyncMock(return_value=True), AsyncMock()
        self.interaction = SimpleNamespace(guild=self.guild, guild_id=100, user=self.members[10], channel_id=500,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))
        self.db.set_config(100, mute_role_id=300)
        for name, replacement in (
            ("fetch_member", AsyncMock(side_effect=self.current_member)),
            ("fetch_roles", AsyncMock(side_effect=lambda: list(self.guild.roles))),
            ("fetch_channels", AsyncMock(side_effect=lambda: list(self.guild.channels))),
            ("audit_logs", self.audit_logs),
        ):
            active = patch.object(discord.Guild, name, replacement)
            active.start()
            self.addCleanup(active.stop)

    def current_member(self, user_id):
        member = copy(self.members[user_id])
        member._roles = discord.utils.SnowflakeList(self.server_roles[user_id])
        return member

    async def add_role(self, guild_id, user_id, role_id, *, reason):
        self.server_roles[user_id] = sorted(set(self.server_roles[user_id]) | {role_id})
        self.audit_event(role_id, reason, added=True)

    async def remove_role(self, guild_id, user_id, role_id, *, reason):
        self.server_roles[user_id].remove(role_id)
        self.audit_event(role_id, reason, added=False)

    def audit_event(self, role_id, reason, *, added):
        role = self.guild.get_role(role_id)
        self.events.insert(0, SimpleNamespace(id=len(self.events) + 1,
            target=discord.Object(id=20), user=discord.Object(id=999),
            before=SimpleNamespace(roles=[] if added else [role]),
            after=SimpleNamespace(roles=[role] if added else []), reason=reason))

    async def audit_logs(self, **kwargs):
        for event in self.events:
            yield event

    async def mute(self):
        await Moderation.mute.callback(self.cog, self.interaction, self.current_member(20), "5m", "Synthetic reason")
        return self.db.list_cases(100)[0]

    async def unmute(self):
        await Moderation.unmute.callback(self.cog, self.interaction, self.current_member(20), "Synthetic reason")

    async def test_admin_and_conflicting_staff_roles_are_restored_exactly_on_unmute(self):
        case = await self.mute()
        self.assertEqual(case["status"], "active")
        self.assertEqual(self.server_roles[20], [200, 300])
        self.assertEqual({role["id"] for role in json.loads(case["extra_data"])["suppressed_roles"]}, {210, 220})
        await self.unmute()
        self.assertEqual(self.server_roles[20], [200, 210, 220])
        self.assertEqual(self.db.get_case_by_id(100, case["id"])["status"], "revoked")
        self.assertEqual(self.db.get_pending_moderation_actions(100), [])

    async def test_normal_member_with_allow_role_can_be_muted_without_removing_unrelated_role(self):
        self.server_roles[20] = [200, 210]
        case = await self.mute()
        self.assertEqual(self.server_roles[20], [200, 300])
        self.assertEqual([role["id"] for role in json.loads(case["extra_data"])["suppressed_roles"]], [210])

    async def test_member_specific_allow_is_rejected_before_any_mutation_or_intent(self):
        self.channel_data["permission_overwrites"].append(
            {"id": "20", "type": 1, "allow": str(discord.Permissions(send_messages=True).value), "deny": "0"})
        self.guild._channels[500] = discord.TextChannel(state=self.state, guild=self.guild, data=self.channel_data)
        await Moderation.mute.callback(self.cog, self.interaction, self.current_member(20), "5m")
        self.state.http.add_role.assert_not_awaited()
        self.state.http.remove_role.assert_not_awaited()
        self.assertEqual(self.db.list_cases(100), [])

    async def test_partial_removal_failure_rolls_back_roles_and_mute(self):
        async def fail_second(guild_id, user_id, role_id, *, reason):
            if role_id == 220:
                raise discord.Forbidden(SimpleNamespace(status=403, reason="blocked"), "blocked")
            await self.remove_role(guild_id, user_id, role_id, reason=reason)
        self.state.http.remove_role.side_effect = fail_second
        case = await self.mute()
        self.assertEqual(self.server_roles[20], [200, 210, 220])
        self.assertEqual(case["status"], "failed")

    async def test_unmute_retry_when_muted_is_absent_restores_roles_before_closing_case(self):
        case = await self.mute()
        self.server_roles[20].remove(300)
        await self.unmute()
        self.assertEqual(self.server_roles[20], [200, 210, 220])
        self.assertEqual(self.db.get_case_by_id(100, case["id"])["status"], "revoked")

    async def test_expiry_restores_roles_and_closes_exact_case(self):
        case = await self.mute()
        self.events.clear()  # Simulate Discord no longer retaining the original audit events.
        class ExpiredClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(minutes=6)
        with patch("cogs.moderation.datetime", ExpiredClock):
            await Moderation._check_pending_moderation.coro(self.cog)
        self.assertEqual(self.server_roles[20], [200, 210, 220])
        self.assertEqual(self.db.get_case_by_id(100, case["id"])["status"], "expired")

    async def test_changed_deleted_managed_roles_membership_and_lower_actor_never_restore_privileges(self):
        case = await self.mute()
        original = self.guild._roles[220]
        scenarios = ("permissions", "deleted", "managed", "membership", "actor")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                role = copy(original)
                self.guild._roles[220] = role
                if scenario == "permissions":
                    role._permissions = discord.Permissions.all().value
                elif scenario == "deleted":
                    del self.guild._roles[220]
                elif scenario == "managed":
                    role.managed = True
                elif scenario == "membership":
                    self.members[20].joined_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
                else:
                    self.server_roles[10] = [210]
                with self.assertRaises(PermissionError):
                    await restore_roles(self.cog.bot, self.guild, 20, case, actor_id=10)
                self.assertNotIn(220, self.server_roles[20])
                self.members[20].joined_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
                self.server_roles[10] = [450]
        self.guild._roles[220] = original

    async def test_restoration_rechecks_actor_after_reading_audit(self):
        case = await self.mute()
        self.state.http.add_role.reset_mock()

        async def revoke_actor(_guild, **kwargs):
            async for entry in self.audit_logs(**kwargs):
                yield entry
            self.server_roles[10] = [200]

        with patch.object(discord.Guild, "audit_logs", revoke_actor):
            with self.assertRaises(PermissionError):
                await restore_roles(self.cog.bot, self.guild, 20, case, actor_id=10, db=self.db)
        self.state.http.add_role.assert_not_awaited()

    async def test_restoration_rechecks_role_grants_after_reading_audit(self):
        case = await self.mute()
        self.state.http.add_role.reset_mock()

        async def promote_role(_guild, **kwargs):
            async for entry in self.audit_logs(**kwargs):
                yield entry
            self.guild._roles[210]._permissions = discord.Permissions(administrator=True).value

        with patch.object(discord.Guild, "audit_logs", promote_role):
            with self.assertRaises(PermissionError):
                await restore_roles(self.cog.bot, self.guild, 20, case, actor_id=10, db=self.db)
        self.state.http.add_role.assert_not_awaited()

    async def test_restoration_rechecks_remaining_role_after_each_grant(self):
        case = await self.mute()
        self.state.http.add_role.reset_mock()

        async def promote_after_first_grant(guild_id, user_id, role_id, *, reason):
            await self.add_role(guild_id, user_id, role_id, reason=reason)
            if role_id == 210:
                self.guild._roles[220]._permissions = discord.Permissions.all().value

        self.state.http.add_role.side_effect = promote_after_first_grant
        with self.assertRaises(PermissionError):
            await restore_roles(self.cog.bot, self.guild, 20, case, actor_id=10, db=self.db)
        self.assertIn(210, self.server_roles[20])
        self.assertNotIn(220, self.server_roles[20])
        stored = json.loads(self.db.get_case_by_id(100, case["id"])["extra_data"])
        self.assertTrue(next(role for role in stored["suppressed_roles"] if role["id"] == 210)["restored"])

    async def test_forged_reason_from_another_audit_actor_cannot_restore_roles(self):
        case = await self.mute()
        for event in self.events:
            event.user = discord.Object(id=777)
        with self.assertRaises(PermissionError):
            await restore_roles(self.cog.bot, self.guild, 20, case)
        self.assertEqual(self.server_roles[20], [200, 300])

    async def test_durable_receipts_allow_long_mute_restoration_after_audit_retention(self):
        case = await self.mute()
        self.assertTrue(all(role.get("withdrawal_audit_id") for role in json.loads(case["extra_data"])["suppressed_roles"]))
        self.events.clear()
        await self.unmute()
        self.assertEqual(self.server_roles[20], [200, 210, 220])
        self.assertEqual(self.db.get_case_by_id(100, case["id"])["status"], "revoked")

    async def test_interrupted_restoration_retains_case_and_retry_finishes_remaining_roles(self):
        case = await self.mute()
        original = self.state.http.add_role.side_effect
        async def fail_admin(guild_id, user_id, role_id, *, reason):
            if role_id == 220:
                raise discord.Forbidden(SimpleNamespace(status=403, reason="blocked"), "blocked")
            await original(guild_id, user_id, role_id, reason=reason)
        self.state.http.add_role.side_effect = fail_admin
        await self.unmute()
        self.assertEqual(self.server_roles[20], [200, 210])
        self.assertEqual(self.db.get_case_by_id(100, case["id"])["status"], "active")
        self.state.http.add_role.side_effect = original
        await self.unmute()
        self.assertEqual(self.server_roles[20], [200, 210, 220])
        self.assertEqual(self.db.get_case_by_id(100, case["id"])["status"], "revoked")

    async def test_reconciliation_restores_withdrawals_when_applying_mute_effect_is_absent(self):
        case = await self.mute()
        self.db.update_case_by_id(100, case["id"], status="applying")
        self.server_roles[20].remove(300)
        self.cog.bot.wait_until_ready = AsyncMock()
        self.cog.bot.is_closed = lambda: False
        self.cog._ban_reconciliation_ready = asyncio.Event()
        with patch("cogs.moderation.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.cog._reconcile_applying_bans()
        self.assertEqual(self.server_roles[20], [200, 210, 220])
        self.assertEqual(self.db.get_case_by_id(100, case["id"])["status"], "failed")

    async def test_api_appeal_restores_roles_before_accepting_and_closing_exact_case(self):
        case = await self.mute()
        self.events.clear()
        appeal_id = self.db.create_appeal(100, 20, "MUTE", "Reason", "Review", case_id=case["id"])
        self.cog.bot.get_cog = lambda _: self.cog
        self.cog.bot.loop = asyncio.get_running_loop()
        result = await update_appeal(100, appeal_id, {"status": "ACCEPTED", "auto_remove": True},
            None, db=self.db, bot=self.cog.bot, user={"user_id": "10"})
        self.assertEqual(result["action_taken"], "unmuted")
        self.assertEqual(self.server_roles[20], [200, 210, 220])
        self.assertEqual(self.db.get_appeal(appeal_id)["status"], "ACCEPTED")
        self.assertEqual(self.db.get_case_by_id(100, case["id"])["status"], "revoked")

    async def test_api_appeal_keeps_case_and_releases_claim_when_restoration_is_unsafe(self):
        case = await self.mute()
        appeal_id = self.db.create_appeal(100, 20, "MUTE", "Reason", "Review", case_id=case["id"])
        self.cog.bot.get_cog = lambda _: self.cog
        self.cog.bot.loop = asyncio.get_running_loop()
        self.guild._roles[220]._permissions = discord.Permissions.all().value
        with self.assertRaises(HTTPException):
            await update_appeal(100, appeal_id, {"status": "ACCEPTED", "auto_remove": True},
                None, db=self.db, bot=self.cog.bot, user={"user_id": "10"})
        self.assertNotIn(220, self.server_roles[20])
        self.assertEqual(self.db.get_appeal(appeal_id)["status"], "PENDING")
        self.assertEqual(self.db.get_case_by_id(100, case["id"])["status"], "active")

    async def test_unmute_finds_original_case_after_more_than_fifty_later_actions(self):
        case = await self.mute()
        for number in range(51):
            self.db.log_action(100, 20, 10, "WARN", f"Later warning {number}")
        await self.unmute()
        self.assertEqual(self.server_roles[20], [200, 210, 220])
        self.assertEqual(self.db.get_case_by_id(100, case["id"])["status"], "revoked")

    async def test_withdrawing_chat_allow_cannot_open_a_channel_hidden_by_same_role(self):
        self.server_roles[20] = [200, 210]
        hidden = {**self.channel_data, "id": "501", "permission_overwrites": [
            {"id": "300", "type": 0, "allow": "0", "deny": str(Moderation._mute_overwrite().pair()[1].value)},
            {"id": "210", "type": 0, "allow": "0", "deny": str(discord.Permissions(view_channel=True).value)},
        ]}
        self.guild._channels[501] = discord.TextChannel(state=self.state, guild=self.guild, data=hidden)
        await Moderation.mute.callback(self.cog, self.interaction, self.current_member(20), "5m")
        self.state.http.add_role.assert_not_awaited()
        self.state.http.remove_role.assert_not_awaited()
        self.assertEqual(self.db.list_cases(100), [])
        self.assertEqual(self.server_roles[20], [200, 210])


if __name__ == "__main__":
    unittest.main()
