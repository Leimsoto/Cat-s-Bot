import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from fastapi import HTTPException

from api.routes.autoroles import ReactionPanelBody, list_reaction_panels, upsert_reaction_panel
from cogs.autoroles import AutoRoles
from tests.test_snowflake_api_serialization import make_db


class AutoroleCustomEmojiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = make_db()
        self.guild = SimpleNamespace(id=10, channels=[])
        self.role_id = 1397395667118194730
        self.emoji = discord.PartialEmoji(name="coraverde2", id=1403084927637000363)
        self.guild.emojis = [self.emoji]
        self.role = discord.Role(guild=self.guild, state=None, data={"id": str(self.role_id), "name": "Verde", "permissions": "0", "position": 1})
        top = discord.Role(guild=self.guild, state=None, data={"id": "999", "name": "Bot", "permissions": "8", "position": 10})
        self.guild.default_role = discord.Role(guild=self.guild, state=None, data={"id": "10", "name": "everyone", "permissions": "0", "position": 0})
        self.guild.me = SimpleNamespace(top_role=top, guild=self.guild)
        self.guild.get_role = lambda ident: self.role if ident == self.role_id else None
        self.member = SimpleNamespace(id=42, bot=False, add_roles=AsyncMock(), remove_roles=AsyncMock())
        self.guild.get_member = lambda _ident: self.member
        self.message = SimpleNamespace(add_reaction=AsyncMock())
        self.channel = SimpleNamespace(id=30, guild=self.guild, fetch_message=AsyncMock(return_value=self.message))
        self.guild.get_channel = lambda ident: self.channel if ident == 30 else None
        self.bot = SimpleNamespace(db=self.db, user=SimpleNamespace(id=999), loop=asyncio.get_running_loop(),
                                   emojis=[self.emoji], get_guild=lambda ident: self.guild if ident == 10 else None,
                                   fetch_application_emojis=AsyncMock(return_value=[]))

    async def asyncTearDown(self):
        self.db._sqlite_conn.close()

    async def save(self, mapping):
        return await upsert_reaction_panel(10, ReactionPanelBody(message_id="1420078388546244609", channel_id="30", mapping_data=mapping),
                                           self.db, self.bot, {})

    async def test_id_name_mention_and_unicode_roundtrip_preserve_role_snowflake(self):
        for key in (str(self.emoji.id), ":coraverde2:", "coraverde2", str(self.emoji), "✅"):
            with self.subTest(key=key):
                await self.save('{"%s": %d}' % (key, self.role_id))
                expected = "✅" if key == "✅" else str(self.emoji)
                self.assertEqual(self.message.add_reaction.await_args.args[0], expected)
                stored = self.db.get_autorole(1420078388546244609)
                self.assertEqual(json.loads(stored["mapping_data"]), {expected: self.role_id})
                listed = await list_reaction_panels(10, self.db, {})
                self.assertEqual(json.loads(listed["panels"][0]["mapping_data"]), {expected: str(self.role_id)})

    async def test_unknown_ambiguous_and_conflicting_aliases_fail_before_any_reaction_or_write(self):
        for mapping in ('{"999999999999999999": 1397395667118194730}', '{":missing:": 1397395667118194730}',
                        '{":coraverde2:": 1397395667118194730, "1403084927637000363": 1397395667118194730}'):
            with self.subTest(mapping=mapping):
                with self.assertRaises(HTTPException) as error:
                    await self.save(mapping)
                self.assertEqual(error.exception.status_code, 400)
                self.assertTrue(error.exception.detail)
                self.message.add_reaction.assert_not_awaited()
                self.assertIsNone(self.db.get_autorole(1420078388546244609))
        self.guild.emojis.append(discord.PartialEmoji(name="coraverde2", id=1403084927637000364))
        with self.assertRaises(HTTPException) as error:
            await self.save('{":coraverde2:": 1397395667118194730}')
        self.assertIn("ID", error.exception.detail)

    async def test_animated_application_emoji_and_multiple_formats_share_exact_identity(self):
        app = discord.Emoji(guild=SimpleNamespace(id=0), state=SimpleNamespace(_get_guild=lambda _ident: None),
                            data={"name": "99corarosa", "id": "1403084927637000365", "animated": True})
        self.assertFalse(app.is_usable())  # Esta comprobación de guild no aplica a emojis de aplicación.
        self.bot.fetch_application_emojis.return_value = [app]
        await self.save('{":99corarosa:": 1397395667118194730}')
        self.message.add_reaction.assert_awaited_once_with(str(app))

    async def test_discord_unknown_emoji_and_missing_permissions_return_actionable_400(self):
        for error in (discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), {"code": 10014, "message": "Unknown Emoji"}),
                      discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing permissions")):
            with self.subTest(error=type(error).__name__):
                self.message.add_reaction.side_effect = error
                with self.assertRaises(HTTPException) as failure:
                    await self.save('{":coraverde2:": 1397395667118194730}')
                self.assertEqual(failure.exception.status_code, 400)
                self.assertNotIn("Unknown Emoji", failure.exception.detail)
                self.assertIsNone(self.db.get_autorole(1420078388546244609))

    async def test_slash_uses_same_normalization_and_keeps_role_safety(self):
        cog = AutoRoles(self.bot)
        interaction = SimpleNamespace(channel=self.channel, guild=self.guild, guild_id=10,
                                      response=SimpleNamespace(send_message=AsyncMock()))
        await AutoRoles.autorolereact_setup.callback(cog, interaction, "1420078388546244609", str(self.emoji.id), self.role)
        self.message.add_reaction.assert_awaited_once_with(str(self.emoji))
        self.assertEqual(json.loads(self.db.get_autorole(1420078388546244609)["mapping_data"]), {str(self.emoji): self.role_id})
        self.message.add_reaction.reset_mock()
        self.db.set_server_config(10, mod_role_id=self.role_id)
        await AutoRoles.autorolereact_setup.callback(cog, interaction, "1420078388546244609", str(self.emoji.id), self.role)
        self.message.add_reaction.assert_not_awaited()

    async def test_raw_add_remove_match_custom_id_after_rename_and_keep_other_ids_separate(self):
        await self.save('{"<:coraverde2:1403084927637000363>": 1397395667118194730}')
        cog = AutoRoles(self.bot)
        payload = SimpleNamespace(message_id=1420078388546244609, channel_id=30, guild_id=10, user_id=42,
                                  emoji=discord.PartialEmoji(name="renamed", id=self.emoji.id))
        await cog.on_raw_reaction_add(payload)
        await cog.on_raw_reaction_remove(payload)
        self.member.add_roles.assert_awaited_once_with(self.role, reason="AutoRole Reaction")
        self.member.remove_roles.assert_awaited_once_with(self.role, reason="AutoRole Reaction")
        self.member.add_roles.reset_mock()
        payload.emoji = discord.PartialEmoji(name="coraverde2", id=self.emoji.id + 1)
        await cog.on_raw_reaction_add(payload)
        self.member.add_roles.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
