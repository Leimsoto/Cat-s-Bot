import asyncio
import copy
import logging
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from fastapi import HTTPException
from pydantic import ValidationError

from api.routes.channel_settings import (
    ChannelSettings, PermissionUpdate, SettingsBatch, delete_channel_settings,
    get_channel_settings, get_native_permissions, patch_native_permissions,
    put_channel_settings,
)
from database.manager import DatabaseManager


class _Channel:
    def __init__(self, guild, channel_id, store):
        self.guild, self.id, self.store = guild, channel_id, store
        self.type = SimpleNamespace(value=0)
        self.send = AsyncMock()
        self._overwrites = []
        for (kind, target_id), value in store.items():
            allow, deny = value.pair()
            self._overwrites.append(SimpleNamespace(
                id=target_id, type=0 if kind == "role" else 1,
                allow=allow.value, deny=deny.value,
                is_role=lambda kind=kind: kind == "role", is_member=lambda kind=kind: kind == "member",
            ))

    def permissions_for(self, member):
        return discord.abc.GuildChannel.permissions_for(self, member)

    def overwrites_for(self, target):
        return discord.abc.GuildChannel.overwrites_for(self, target)

    async def set_permissions(self, target, *, overwrite, reason):
        await asyncio.sleep(0)
        kind = "role" if isinstance(target, discord.Role) else "member"
        if overwrite is None:
            self.store.pop((kind, target.id), None)
        else:
            self.store[kind, target.id] = copy.copy(overwrite)


class ChannelSettingsApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DatabaseManager.__new__(DatabaseManager)
        self.db.db_type = "sqlite"
        self.db._sqlite_lock = threading.Lock()
        self.db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.db._sqlite_conn.row_factory = sqlite3.Row
        with patch.object(logging.getLogger("Database"), "disabled", True):
            self.db._init_schema()
        self.guild = SimpleNamespace(id=100, owner_id=999)
        everybody = discord.Permissions(view_channel=True, send_messages=True, attach_files=True, embed_links=True, read_message_history=True)
        manager = discord.Permissions(manage_roles=True, manage_channels=True)
        self.roles = {
            role_id: discord.Role(guild=self.guild, state=None, data={
                "id": str(role_id), "name": str(role_id), "position": position,
                "permissions": str(permissions.value), "managed": False,
            })
            for role_id, position, permissions in ((100, 0, everybody), (50, 1, discord.Permissions.none()),
                                                   (60, 2, discord.Permissions.none()), (80, 8, manager),
                                                   (90, 10, discord.Permissions(administrator=True)))
        }
        self.guild.default_role = self.roles[100]
        self.guild.get_role = lambda role_id: self.roles.get(role_id)
        self.actor = self.member(42, [80])
        self.bot_member = self.member(777, [90])
        self.target_member = self.member(43, [50])
        self.members = {42: self.actor, 777: self.bot_member, 43: self.target_member}
        self.guild.get_member = lambda user_id: self.members.get(user_id)

        async def fetch_member(user_id):
            if user_id not in self.members:
                raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "unknown member")
            return self.members[user_id]

        self.guild.fetch_member = AsyncMock(side_effect=fetch_member)
        self.store = {("role", 50): discord.PermissionOverwrite(send_messages=False, manage_messages=True)}
        self.guild.fetch_channel = AsyncMock(side_effect=lambda channel_id: _Channel(self.guild, channel_id, self.store))
        self.guild.fetch_channels = AsyncMock(side_effect=lambda: [_Channel(self.guild, 200, self.store), _Channel(self.guild, 201, {})])
        self.guild.fetch_roles = AsyncMock(side_effect=lambda: list(self.roles.values()))
        self.bot = SimpleNamespace(get_guild=lambda guild_id: self.guild if guild_id == 100 else None,
                                   fetch_guild=AsyncMock(return_value=self.guild), user=SimpleNamespace(id=777),
                                   loop=asyncio.get_running_loop())
        self.user = {"user_id": 42}

    def member(self, member_id, roles):
        return SimpleNamespace(id=member_id, guild=self.guild, _roles=discord.utils.SnowflakeList(roles),
                               is_timed_out=lambda: False, display_name=f"Member {member_id}")

    async def asyncTearDown(self):
        self.db._sqlite_conn.close()

    async def save(self, config=None, channel_ids=None):
        body = SettingsBatch(channel_ids=channel_ids or ["200", "201"], config=config or {})
        return await put_channel_settings(100, body, self.db, self.bot, self.user)

    async def native(self, **permissions):
        body = PermissionUpdate(target_type="role", target_id="50", permissions=permissions)
        return await patch_native_permissions(100, 200, body, self.bot, self.user)

    async def test_batch_persistence_inherits_by_default_and_reports_legacy(self):
        self.db.set_config(100, message_role_enabled=1, message_role_id=50)
        self.db.set_channel_config(200, 100, media_only=1)
        response = await self.save({"restrictions": {"block_links": True}})
        self.assertEqual(response["global_role"]["role_id"], "50")
        self.assertEqual(response["thread_inheritance"], "parent")
        self.assertEqual(len(response["channels"]), 2)
        self.assertTrue(response["channels"][0]["legacy"]["media_only"])
        self.assertEqual(response["channels"][0]["config"]["role"]["mode"], "inherit")
        self.assertTrue(self.db.get_channel_settings(100, 201)["restrictions"]["block_links"])
        self.assertIsNone(self.db.get_channel_settings(101, 201))
        await delete_channel_settings(101, 200, self.db, self.user)
        self.assertIsNotNone(self.db.get_channel_settings(100, 200))
        await delete_channel_settings(100, 200, self.db, self.user)
        self.assertIsNone(self.db.get_channel_settings(100, 200))

    async def test_entire_batch_validated_before_any_config_write(self):
        for channels, config in ((["200", "999"], {}), (["200"], {"role": {"mode": "additional", "role_ids": ["999"]}}),
                                  (["200"], {"whitelist": {"role_ids": ["100"]}}), (["200"], {"whitelist": {"user_ids": ["999"]}})):
            with self.subTest(channels=channels, config=config):
                with self.assertRaises(HTTPException):
                    await self.save(config, channels)
                self.assertEqual(self.db.list_channel_settings(100), [])

    async def test_disable_and_role_off_accept_inactive_deleted_references(self):
        config = ChannelSettings(role={"mode": "additional", "role_ids": ["50"]}).model_dump()
        await self.save(config)
        del self.roles[50]
        config["enabled"] = False
        await self.save(config)
        config["enabled"] = True
        config["role"]["mode"] = "off"
        await self.save(config)
        config["role"]["mode"] = "additional"
        with self.assertRaises(HTTPException):
            await self.save(config)

    async def test_native_patch_preserves_unrelated_bits_and_null_inherits(self):
        response = await self.native(attach_files=False)
        value = self.store["role", 50]
        self.assertFalse(value.send_messages)
        self.assertTrue(value.manage_messages)
        self.assertFalse(value.attach_files)
        self.assertEqual(response["overwrite"]["target_id"], "50")
        await self.native(attach_files=None)
        self.assertIsNone(self.store["role", 50].attach_files)
        self.assertFalse(self.store["role", 50].send_messages)
        read = await get_native_permissions(100, 200, self.bot, self.user)
        self.assertTrue(read["can_manage"])
        self.assertIn("attach_files", read["available_permissions"])

    async def test_native_concurrent_patches_are_serialized_before_fetch(self):
        await asyncio.gather(self.native(attach_files=False), self.native(embed_links=False))
        value = self.store["role", 50]
        self.assertFalse(value.attach_files)
        self.assertFalse(value.embed_links)
        self.assertTrue(value.manage_messages)

    async def test_native_checks_fresh_authority_hierarchy_and_granted_permissions(self):
        self.actor._roles = discord.utils.SnowflakeList([50])
        with self.assertRaises(HTTPException) as failure:
            await self.native(attach_files=False)
        self.assertEqual(failure.exception.status_code, 403)
        self.actor._roles = discord.utils.SnowflakeList([80])
        with self.assertRaises(HTTPException):
            await patch_native_permissions(100, 200, PermissionUpdate(target_type="role", target_id="90", permissions={"attach_files": False}), self.bot, self.user)
        # El actor conserva gestión, pero el canal le deniega adjuntar archivos.
        self.store["member", 42] = discord.PermissionOverwrite(attach_files=False)
        with self.assertRaises(HTTPException):
            await self.native(attach_files=True)
        self.assertIsNone(self.store["role", 50].attach_files)

    async def test_batch_rolls_back_if_insert_fails_midway(self):
        original = ChannelSettings().model_dump()
        self.db.set_channel_settings_batch(100, [200], original)
        self.db._sqlite_conn.execute("CREATE TRIGGER deny_channel_201 BEFORE INSERT ON channel_settings WHEN NEW.channel_id = 201 BEGIN SELECT RAISE(ABORT, 'blocked'); END")
        updated = ChannelSettings(restrictions={"block_links": True}).model_dump()
        with patch.object(logging.getLogger("Database"), "disabled", True):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.set_channel_settings_batch(100, [200, 201], updated)
        self.assertEqual(self.db.get_channel_settings(100, 200), original)
        self.assertIsNone(self.db.get_channel_settings(100, 201))

    def test_models_reject_external_invalid_and_unsafe_input(self):
        invalid = [dict(enabled="false"), dict(role={"mode": "unknown"}), dict(role={"mode": "override"}),
                   dict(whitelist={"user_ids": [42]}), dict(schedule={"timezone": "Bad/Zone"}),
                   dict(schedule={"enabled": True}), dict(schedule={"windows": [{"days": [True], "start": "10:00", "end": "11:00"}]}),
                   dict(schedule={"windows": [{"days": [1], "start": "11:00", "end": "11:00"}]}),
                   dict(restrictions={"notice": "😀" * 988}), dict(triggers=[dict(id="t", name="n", condition="contains_text", delete=True)])]
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValidationError):
                ChannelSettings(**config)
        with self.assertRaises(ValidationError):
            PermissionUpdate(target_type="role", target_id="50", permissions={"administrator": True})


if __name__ == "__main__":
    unittest.main()
