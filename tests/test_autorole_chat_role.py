import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs._role_safety import safe_for_automatic_assignment, self_service_forbidden_role_ids
from cogs.autoroles import AutoRoles
from tests.test_snowflake_api_serialization import make_db


class AutoroleChatRoleTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = make_db()
        self.db.set_ai_config(10, ai_role_id=50)
        self.guild = SimpleNamespace(id=10, channels=[])
        self.roles = {ident: self.role(ident, position=position) for ident, position in ((10, 0), (50, 1), (99, 10))}
        self.guild.default_role = self.roles[10]
        self.guild.get_role = self.roles.get
        self.bot_member = SimpleNamespace(id=999, guild=self.guild, top_role=self.roles[99])
        self.guild.me = self.bot_member
        self.member = SimpleNamespace(id=42, bot=False, add_roles=AsyncMock(), remove_roles=AsyncMock())
        self.guild.get_member = lambda ident: self.bot_member if ident == 999 else None
        self.guild.fetch_member = AsyncMock(return_value=self.member)
        self.bot = SimpleNamespace(user=SimpleNamespace(id=999), db=self.db,
                                   get_guild=lambda ident: self.guild if ident == 10 else None)
        self.cog = AutoRoles(self.bot)
        self.db.set_autorole(20, 10, 30, '{"✅": 50}')
        self.payload = SimpleNamespace(message_id=20, guild_id=10, channel_id=30, user_id=42,
                                       emoji=discord.PartialEmoji(name="✅"))

    def role(self, ident, *, position=1, permissions=0, managed=False):
        return discord.Role(guild=self.guild, state=None, data={"id": str(ident), "name": str(ident),
                            "permissions": str(permissions), "position": position, "managed": managed})

    async def asyncTearDown(self):
        self.db._sqlite_conn.close()

    async def test_chat_access_role_is_added_and_removed_on_new_reactions(self):
        await self.cog.on_raw_reaction_add(self.payload)
        self.member.add_roles.assert_awaited_once_with(self.roles[50], reason="AutoRole Reaction")
        await self.cog.on_raw_reaction_remove(self.payload)
        self.member.remove_roles.assert_awaited_once_with(self.roles[50], reason="AutoRole Reaction")
        self.assertEqual(self.guild.fetch_member.await_count, 2)

    async def test_real_privileged_and_containment_roles_stay_blocked_for_add_and_remove(self):
        self.db.set_server_config(10, mod_role_id=60, staff_role_id=61, embed_role_id=62,
                                  channels_role_id=63, users_role_id=64, anti_alt_role_id=65)
        self.db.set_config(10, staff_role_id=66, mute_role_id=67)
        self.db.set_ticket_config(10, allowed_roles='[68]', immune_roles='[69]')
        self.db._execute("INSERT INTO ticket_categories (guild_id,name,staff_role_id) VALUES (?,?,?)", (10, "Staff", 70))
        forbidden = self_service_forbidden_role_ids(self.db, 10)
        self.assertEqual(forbidden, set(range(60, 71)))
        for ident in forbidden:
            self.roles[ident] = self.role(ident)
            self.db.set_autorole(20, 10, 30, '{"✅": %d}' % ident)
            await self.cog.on_raw_reaction_add(self.payload)
            await self.cog.on_raw_reaction_remove(self.payload)
        self.db.set_server_config(10, mod_role_id=50)
        self.db.set_autorole(20, 10, 30, '{"✅": 50}')
        await self.cog.on_raw_reaction_add(self.payload)
        await self.cog.on_raw_reaction_remove(self.payload)
        self.member.add_roles.assert_not_awaited()
        self.member.remove_roles.assert_not_awaited()

    def test_chat_role_still_requires_discord_safety_hierarchy_and_verified_config(self):
        forbidden = self_service_forbidden_role_ids(self.db, 10)
        self.assertTrue(safe_for_automatic_assignment(self.roles[50], self.bot_member, forbidden_role_ids=forbidden))
        for role in (self.role(50, permissions=discord.Permissions(manage_roles=True).value),
                     self.role(50, managed=True), self.role(50, position=11), self.roles[10]):
            self.assertFalse(safe_for_automatic_assignment(role, self.bot_member, forbidden_role_ids=forbidden))
        self.assertFalse(safe_for_automatic_assignment(self.roles[50], self.bot_member, forbidden_role_ids=None))
        self.guild.channels = [SimpleNamespace(permissions_for=lambda _role: discord.Permissions(manage_messages=True))]
        self.assertFalse(safe_for_automatic_assignment(self.roles[50], self.bot_member, forbidden_role_ids=forbidden))


if __name__ == "__main__":
    unittest.main()
