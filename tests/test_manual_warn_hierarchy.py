import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from discord import app_commands

from cogs.moderation import Moderation
from main import BotCommandTree
from tests.test_managed_messages import make_db


class ManualWarnHierarchyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = make_db()
        self.guild = SimpleNamespace(id=100, name="Servidor sintético", owner_id=1, channels=[])
        self.roles = {}
        for role_id, name, position, permissions in (
            (100, "@everyone", 0, 0), (1470, "Manager", 147, 8),
            (1460, "Bot", 146, 8), (1450, "Admin", 145, 8),
            (1440, "Muted", 144, 0),
        ):
            self.roles[role_id] = self.role(role_id, name, position, permissions)
        self.guild.default_role = self.roles[100]
        self.guild.get_role = self.roles.get
        self.members = {}
        self.actor = self.member(10, 1470)
        self.target = self.member(20, 1450)
        self.bot_member = self.member(999, 1460, bot=True)
        self.guild.get_member = self.members.get
        self.guild.fetch_member = AsyncMock(side_effect=self.members.get)
        self.guild.fetch_roles = AsyncMock(side_effect=lambda: list(self.roles.values()))
        self.guild.ban = AsyncMock()
        self.guild.kick = AsyncMock()
        response = SimpleNamespace(done=False)
        async def acknowledge(*args, **kwargs):
            response.done = True
        response.send_message = AsyncMock(side_effect=acknowledge)
        response.defer = AsyncMock(side_effect=acknowledge)
        response.is_done = lambda: response.done
        self.interaction = SimpleNamespace(guild=self.guild, guild_id=100, user=self.actor,
            response=response, followup=SimpleNamespace(send=AsyncMock()), channel_id=30,
            type=discord.InteractionType.application_command, extras={})
        self.cog = Moderation.__new__(Moderation)
        self.cog.db = self.db
        self.cog.bot = SimpleNamespace(db=self.db, user=self.bot_member,
            fetch_guild=AsyncMock(return_value=self.guild), catbot_voice=None)
        self.cog._send_log = AsyncMock(return_value=True)
        self.cog._dm = AsyncMock()

    def tearDown(self):
        self.db._sqlite_conn.close()

    def role(self, role_id, name, position, permissions):
        return discord.Role(guild=self.guild, state=Mock(), data={"id": str(role_id),
            "name": name, "position": position, "permissions": str(permissions), "managed": False})

    def member(self, user_id, role_id, *, bot=False):
        state = Mock()
        state.http = SimpleNamespace(add_role=AsyncMock())
        state.store_user = lambda data: discord.User(state=state, data=data)
        member = discord.Member(guild=self.guild, state=state, data={
            "user": {"id": str(user_id), "username": f"usuario{user_id}", "discriminator": "0", "avatar": None, "bot": bot},
            "roles": [str(role_id)], "flags": 0,
        })
        self.members[user_id] = member
        return member

    async def warn(self, target=None):
        await self.invoke(self.cog.warn, usuario=target or self.target, razon="Motivo concreto")

    async def invoke(self, command, **arguments):
        self.interaction.response.done = False
        namespace = app_commands.Namespace.__new__(app_commands.Namespace)
        namespace.__dict__.update(arguments)
        self.interaction.command, self.interaction.namespace = command, namespace
        if await BotCommandTree.interaction_check(None, self.interaction):
            await command._invoke_with_namespace(self.interaction, namespace)

    async def test_registered_ban_dispatches_transforms_acknowledges_and_persists_case(self):
        ban_reason = ""
        async def ban(member, **kwargs):
            nonlocal ban_reason
            self.assertTrue(self.interaction.response.done)
            ban_reason = kwargs["reason"]
        self.guild.ban.side_effect = ban
        self.guild.fetch_ban = AsyncMock(side_effect=lambda target: SimpleNamespace(reason=ban_reason))
        await self.invoke(self.cog.ban, usuario=self.target, razon="Motivo concreto")
        self.guild.ban.assert_awaited_once()
        self.interaction.response.defer.assert_awaited_once()
        self.interaction.followup.send.assert_awaited_once()
        self.assertEqual([(row["action_type"], row["status"]) for row in self.db.list_cases(100)], [("BAN", "active")])

    async def test_registered_kick_dispatches_transforms_acknowledges_and_persists_case(self):
        async def kick(member, **kwargs):
            self.assertTrue(self.interaction.response.done)
        self.guild.kick.side_effect = kick
        await self.invoke(self.cog.kick, usuario=self.target, razon="Motivo concreto")
        self.guild.kick.assert_awaited_once()
        self.interaction.response.defer.assert_awaited_once()
        self.interaction.followup.send.assert_awaited_once()
        self.assertEqual([row["action_type"] for row in self.db.list_cases(100)], ["KICK"])

    async def test_manager_and_bot_above_lower_administrator_can_record_manual_warn(self):
        self.assertEqual((self.actor.top_role.position, self.bot_member.top_role.position, self.target.top_role.position), (147, 146, 145))
        self.assertTrue(self.actor.guild_permissions.administrator)
        self.assertTrue(self.target.guild_permissions.administrator)
        await self.warn()
        cases = self.db.list_cases(100)
        self.assertEqual([(case["action_type"], case["target_id"]) for case in cases], [("WARN", 20)])
        self.assertEqual(self.db.get_user(20, 100)["warns"], 1)
        self.assertEqual(self.guild.fetch_roles.await_count, 2)
        self.guild.ban.assert_not_awaited()

    async def test_equal_higher_owner_self_and_bot_still_cannot_be_warned(self):
        targets = [self.member(21, 1470), self.member(22, 1460), self.member(1, 1450), self.actor, self.bot_member]
        self.roles[1480] = self.role(1480, "CoOwner", 148, 8)
        targets.append(self.member(23, 1480))
        for target in targets:
            with self.subTest(target=target.id):
                await self.warn(target)
        self.assertEqual(self.db.list_cases(100), [])
        self.interaction.response.defer.assert_not_awaited()

    async def test_role_named_admin_without_flag_uses_hierarchy_and_required_actor_permission(self):
        self.roles[1450] = self.role(1450, "Admin", 145, 0)
        self.roles[1470] = self.role(1470, "Staff", 147, discord.Permissions(moderate_members=True).value)
        self.assertFalse(self.actor.guild_permissions.administrator)
        self.assertFalse(self.target.guild_permissions.administrator)
        self.assertIsNone(self.cog._can_moderate(self.actor, self.target))
        await self.warn()
        self.assertEqual(self.db.get_user(20, 100)["warns"], 1)

    async def test_manager_role_name_does_not_grant_moderation_permission(self):
        self.roles[1470] = self.role(1470, "Manager", 147, 0)
        await self.warn()
        self.assertEqual(self.db.list_cases(100), [])
        self.guild.fetch_roles.assert_not_awaited()

    async def test_fresh_actor_permission_revocation_and_target_or_bot_role_change_block_persistence(self):
        for changed in ("actor_permission", "target_higher", "bot_lower"):
            with self.subTest(changed=changed):
                live = dict(self.roles)
                if changed == "actor_permission":
                    live[1470] = self.role(1470, "Manager", 147, 0)
                elif changed == "target_higher":
                    live[1450] = self.role(1450, "Admin", 148, 8)
                else:
                    live[1460] = self.role(1460, "Bot", 144, 8)
                self.guild.fetch_roles.side_effect = lambda: list(live.values())
                await self.warn()
                self.assertEqual(self.db.list_cases(100), [])
        self.assertEqual(self.interaction.response.defer.await_count, 3)

    async def test_shared_guards_allow_lower_admin_and_timeout_explains_discord_limit(self):
        self.assertIsNone(self.cog._can_moderate(self.actor, self.target))
        for permission in ("ban_members", "kick_members", "manage_roles", "moderate_members"):
            _, _, error = await self.cog._fresh_moderation_context(self.interaction, permission, target_id=20)
            self.assertIsNone(error)
        self.assertIn("Discord", self.cog._can_moderate(self.actor, self.target, action_type="TIMEOUT"))
        _, _, error = await self.cog._fresh_moderation_context(
            self.interaction, "moderate_members", target_id=20, action_type="TIMEOUT")
        self.assertIn("Discord", error)

    async def test_warn_thresholds_do_not_turn_allowed_admin_warning_into_ban_kick_or_mute(self):
        for action in ("BAN", "KICK", "MUTE"):
            self.db.set_config(100, mute_role_id=1440,
                warn_ban_enabled=int(action == "BAN"), warn_ban_threshold=1,
                warn_kick_enabled=int(action == "KICK"), warn_kick_threshold=1,
                warn_mute_enabled=int(action == "MUTE"), warn_mute_threshold=1)
            with self.subTest(action=action):
                await self.warn()
                self.assertTrue(self.db.list_cases(100))
                self.assertEqual({row["action_type"] for row in self.db.list_cases(100)}, {"WARN"})
                self.assertEqual(self.db.get_pending_moderation_actions(100), [])
        self.assertEqual(self.db.get_user(20, 100)["warns"], 3)
        self.guild.ban.assert_not_awaited()
        self.guild.kick.assert_not_awaited()
        self.target._state.http.add_role.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
