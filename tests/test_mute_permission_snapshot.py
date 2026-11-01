import unittest
from copy import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from cogs.moderation import Moderation
from tests.test_managed_messages import make_db


class MutePermissionSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = SimpleNamespace(self_id=999, cache_guild_expressions=False,
            member_cache_flags=SimpleNamespace(joined=False, voice=False), http=SimpleNamespace(remove_role=AsyncMock()))
        self.state.store_user = lambda data: discord.User(state=self.state, data=data)
        permissions = discord.Permissions(view_channel=True, read_message_history=True, send_messages=True,
            send_messages_in_threads=True, create_public_threads=True, create_private_threads=True)
        self.roles_data = [
            {"id": "100", "name": "@everyone", "position": 0, "permissions": str(permissions.value)},
            {"id": "200", "name": "Tortuguita", "position": 124, "permissions": "0"},
            {"id": "300", "name": "Muted", "position": 125, "permissions": "0"},
            {"id": "400", "name": "Bot", "position": 146, "permissions": "8"},
        ]
        self.guild = discord.Guild(state=self.state, data={"id": "100", "owner_id": "1", "name": "Synthetic", "roles": self.roles_data})
        allow, deny = discord.PermissionOverwrite(send_messages=False, speak=False,
            send_messages_in_threads=False, create_public_threads=False, create_private_threads=False).pair()
        self.channel_data = {"id": "500", "type": 0, "name": "synthetic", "position": 0,
            "permission_overwrites": [{"id": "300", "type": 0, "allow": str(allow.value), "deny": str(deny.value)}]}
        self.fresh_channel = discord.TextChannel(state=self.state, guild=self.guild, data=self.channel_data)
        stale_channel = {**self.channel_data, "permission_overwrites": self.channel_data["permission_overwrites"] + [
            {"id": "200", "type": 0, "allow": str(discord.Permissions(send_messages=True).value), "deny": "0"}]}
        self.guild._channels[500] = discord.TextChannel(state=self.state, guild=self.guild, data=stale_channel)
        self.member = discord.Member(state=self.state, guild=self.guild, data={"user": {"id": "20", "username": "synthetic", "discriminator": "0", "avatar": None}, "roles": ["200", "300"], "flags": 0})
        self.bot_member = discord.Member(state=self.state, guild=self.guild, data={"user": {"id": "999", "username": "bot", "discriminator": "0", "avatar": None, "bot": True}, "roles": ["400"], "flags": 0})
        self.fresh_roles = [discord.Role(state=self.state, guild=self.guild, data=raw) for raw in self.roles_data]
        self.cog = Moderation.__new__(Moderation)
        self.cog.db = SimpleNamespace(get_config=lambda _: {}, get_server_config=lambda _: {})
        self.cog.bot = SimpleNamespace(user=self.bot_member, fetch_guild=AsyncMock(return_value=SimpleNamespace(id=100, owner_id=1)))
        self.members = {20: self.member, 999: self.bot_member}
        for name, fake in (
            ("fetch_member", AsyncMock(side_effect=self.members.get)),
            ("fetch_roles", AsyncMock(return_value=self.fresh_roles)),
            ("fetch_channels", AsyncMock(return_value=[self.fresh_channel])),
        ):
            active = patch.object(discord.Guild, name, fake)
            active.start()
            self.addCleanup(active.stop)

    async def test_stale_channel_allow_cannot_undo_a_mute_confirmed_by_fresh_overwrites(self):
        self.assertTrue(self.guild.get_channel(500).permissions_for(self.member).send_messages)
        result = await self.cog._confirm_effective_mute(self.guild, 20, self.guild.get_role(300))
        self.assertIsNotNone(result)
        self.state.http.remove_role.assert_not_awaited()
        self.assertFalse(result.guild.get_channel(500).permissions_for(result).send_messages)
        self.assertIsNot(result.guild, self.guild)
        self.assertIs(self.member.guild, self.guild)
        self.assertIs(self.fresh_channel.guild, self.guild)
        self.assertIs(self.bot_member.guild, self.guild)
        self.assertTrue(all(role.guild is self.guild for role in self.fresh_roles))
        self.assertTrue(self.guild.get_channel(500).permissions_for(self.member).send_messages)

    async def test_stale_role_permission_cannot_override_fresh_role_snapshot(self):
        self.guild._channels[500] = self.fresh_channel
        self.guild._roles[200] = discord.Role(state=self.state, guild=self.guild,
            data={**self.roles_data[1], "permissions": "8"})
        self.assertTrue(self.member.guild_permissions.administrator)
        result = await self.cog._confirm_effective_mute(self.guild, 20, self.guild.get_role(300))
        self.assertIsNotNone(result)
        self.assertFalse(result.guild_permissions.administrator)
        self.assertTrue(self.member.guild_permissions.administrator)
        self.state.http.remove_role.assert_not_awaited()

    async def test_actual_fresh_allow_still_reverts_the_ineffective_mute(self):
        self.fresh_channel = self.guild.get_channel(500)
        discord.Guild.fetch_channels.return_value = [self.fresh_channel]
        with self.assertLogs("Moderation", level="WARNING") as logged:
            result = await self.cog._confirm_effective_mute(self.guild, 20, self.guild.get_role(300))
        self.assertIsNone(result)
        self.state.http.remove_role.assert_awaited_once()
        self.assertIn("category=ineffective_permissions", logged.output[0])

    async def test_unavailable_fresh_channels_never_claim_success_or_remove_role(self):
        discord.Guild.fetch_channels.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="forbidden"), "blocked")
        result = await self.cog._confirm_effective_mute(self.guild, 20, self.guild.get_role(300))
        self.assertIsNone(result)
        self.state.http.remove_role.assert_not_awaited()

    async def test_incomplete_fresh_roles_cannot_confirm_permissions_from_cached_role(self):
        discord.Guild.fetch_roles.return_value = [role for role in self.fresh_roles if role.id != 200]
        result = await self.cog._confirm_effective_mute(self.guild, 20, self.guild.get_role(300))
        self.assertIsNone(result)
        self.state.http.remove_role.assert_not_awaited()

    async def test_manual_mute_activates_case_and_expiry_using_fresh_permissions_despite_stale_cache(self):
        self.cog.db = make_db()
        self.addCleanup(self.cog.db._sqlite_conn.close)
        self.cog.db.set_config(100, mute_role_id=300)
        manager = discord.Role(state=self.state, guild=self.guild,
            data={"id": "450", "name": "Manager", "position": 147, "permissions": "8"})
        self.guild._roles[450] = manager
        self.fresh_roles.append(manager)
        actor = discord.Member(state=self.state, guild=self.guild,
            data={"user": {"id": "10", "username": "manager", "discriminator": "0", "avatar": None}, "roles": ["450"], "flags": 0})
        self.member._roles = discord.utils.SnowflakeList([200])
        self.members[10] = actor
        self.guild._members = self.members
        server_roles = {20: [200], 10: [450], 999: [400]}
        def current_member(user_id):
            member = copy(self.members[user_id])
            member._roles = discord.utils.SnowflakeList(server_roles[user_id])
            return member
        discord.Guild.fetch_member.side_effect = current_member
        audit_reason = ""
        async def add_role(guild_id, user_id, role_id, *, reason):
            nonlocal audit_reason
            server_roles[user_id].append(role_id)
            audit_reason = reason
        self.state.http.add_role = AsyncMock(side_effect=add_role)
        async def audit_logs(guild, **kwargs):
            yield SimpleNamespace(id=1001, user=discord.Object(id=999), target=discord.Object(id=20), before=SimpleNamespace(roles=[]),
                after=SimpleNamespace(roles=[self.guild.get_role(300)]), reason=audit_reason)
        interaction = SimpleNamespace(guild=self.guild, guild_id=100, user=actor, channel_id=500,
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        self.cog._send_log, self.cog._dm = AsyncMock(return_value=True), AsyncMock()
        with patch.object(discord.Guild, "audit_logs", audit_logs):
            await Moderation.mute.callback(self.cog, interaction, self.member, "5m", "Motivo sintético")
        self.state.http.add_role.assert_awaited_once()
        self.state.http.remove_role.assert_not_awaited()
        self.assertEqual([(row["action_type"], row["status"]) for row in self.cog.db.list_cases(100)], [("MUTE", "active")])
        self.assertEqual([row["action_type"] for row in self.cog.db.get_pending_moderation_actions(100)], ["MUTE_EXPIRE"])
        self.assertTrue(self.guild.get_channel(500).permissions_for(self.member).send_messages)
        interaction.followup.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
