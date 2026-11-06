import inspect
import logging
import os
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from api.deps import (
    get_current_user_from_request,
    require_guild_admin,
    require_master_admin,
)
from api.routes.ai_keys import (
    assign_guild_key,
    get_guild_key,
    unassign_guild_key,
)
from api.routes.embeds import SendEmbedBody, send_embed_to_channel
from api.routes.guild import patch_ia_config, update_guild_config_legacy
from database.manager import DatabaseManager


class _Permissions:
    def __init__(self, **values):
        self.administrator = values.get("administrator", False)
        self.manage_guild = values.get("manage_guild", False)
        self.view_channel = values.get("view_channel", False)
        self.send_messages = values.get("send_messages", False)
        self.embed_links = values.get("embed_links", False)
        self.manage_webhooks = values.get("manage_webhooks", False)


class _Member:
    def __init__(self, permissions=None):
        self.guild_permissions = permissions or _Permissions()


class _Channel:
    def __init__(self, channel_id, permissions=None):
        self.id = channel_id
        self._permissions = permissions or _Permissions()

    def permissions_for(self, _member):
        return self._permissions


class _Guild:
    def __init__(self, guild_id=123, member=None, channels=()):
        self.id = guild_id
        self.owner_id = 999
        self.me = object()
        self._member = member
        self._channels = {channel.id: channel for channel in channels}

    def get_member(self, user_id):
        return self._member if user_id == 42 else None

    def get_channel(self, channel_id):
        return self._channels.get(channel_id)


class _Bot:
    def __init__(self, guild=None):
        self.guild = guild

    def get_guild(self, guild_id):
        return self.guild if self.guild and self.guild.id == guild_id else None


class _Request:
    def __init__(self, method="GET", bot=None):
        self.method = method
        self.headers = {}
        self.cookies = {}
        self.url = SimpleNamespace(path="/test")
        self.app = SimpleNamespace(state=SimpleNamespace(bot=bot))


class ApiAuthenticationRegressionTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_auth_secrets_fails_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                await get_current_user_from_request(_Request())
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_mutation_rechecks_stale_positive_jwt_live(self):
        guild = _Guild(member=_Member(_Permissions()))
        request = _Request(method="POST", bot=_Bot(guild))
        stale_admin = {
            "user_id": 42,
            "guilds": [{"id": "123", "permissions": 0x8, "owner": False}],
        }

        with self.assertRaises(HTTPException) as ctx:
            await require_guild_admin(123, request, stale_admin)

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_read_can_use_snapshot_and_dev_flag_is_not_master(self):
        snapshot_admin = {
            "user_id": 42,
            "guilds": [{"id": "123", "permissions": 0x20, "owner": False}],
        }
        self.assertIs(
            await require_guild_admin(123, _Request(method="GET"), snapshot_admin),
            snapshot_admin,
        )
        with self.assertRaises(HTTPException) as ctx:
            await require_master_admin({"is_dev_mode": True})
        self.assertEqual(ctx.exception.status_code, 403)


class DatabaseTenantBoundaryRegressionTest(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager.__new__(DatabaseManager)
        self.db.db_type = "sqlite"
        self.db._sqlite_lock = threading.Lock()
        self.db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.db._sqlite_conn.row_factory = sqlite3.Row
        self.db._sqlite_conn.execute("PRAGMA foreign_keys = ON")
        db_logger = logging.getLogger("Database")
        previous_disabled = db_logger.disabled
        db_logger.disabled = True
        try:
            self.db._init_schema()
        finally:
            db_logger.disabled = previous_disabled

    def tearDown(self):
        self.db._sqlite_conn.close()

    def test_object_mutations_are_bound_to_the_route_guild(self):
        response_id = self.db.add_autoresponse(1, None, "hello", "world")
        self.db.update_autoresponse(response_id, 2, response="owned")
        self.assertEqual(self.db.get_autoresponses(1)[0]["response"], "world")
        self.db.remove_autoresponse(response_id, 2)
        self.assertEqual(len(self.db.get_autoresponses(1)), 1)

        self.db.save_embed(1, 10, "notice", "{}")
        embed_id = self.db.get_saved_embeds(1)[0]["id"]
        self.db.delete_saved_embed(embed_id, 2)
        self.assertEqual(len(self.db.get_saved_embeds(1)), 1)

        self.db.add_ticket_category(1, "Support", "x", "[]", "[]")
        category_id = self.db.get_ticket_categories(1)[0]["id"]
        self.db.update_ticket_category(category_id, 2, name="Owned")
        self.assertEqual(self.db.get_ticket_categories(1)[0]["name"], "Support")
        self.db.delete_ticket_category(category_id, 2)
        self.assertEqual(len(self.db.get_ticket_categories(1)), 1)

    def test_generic_config_identifiers_are_allowlisted(self):
        self.db.set_welcome_config(1, embed_data="one", enabled=1)
        self.db.set_welcome_config(2, embed_data="two", enabled=1)
        malicious = "embed_data = ? WHERE 1=1 OR ? IS NULL --"

        with self.assertRaises(ValueError):
            self.db.set_welcome_config(1, **{malicious: "owned"})
        with self.assertRaises(ValueError):
            self.db._upsert_config("welcome_config; DROP TABLE welcome_config", 1)

        self.assertEqual(self.db.get_welcome_config(1)["embed_data"], "one")
        self.assertEqual(self.db.get_welcome_config(2)["embed_data"], "two")


class ApiRouteAuthorizationRegressionTest(unittest.IsolatedAsyncioTestCase):
    async def test_ai_key_assignment_is_master_only(self):
        self.assertIs(
            inspect.signature(assign_guild_key).parameters["_user"].default.dependency,
            require_master_admin,
        )
        self.assertIs(
            inspect.signature(unassign_guild_key).parameters["_user"].default.dependency,
            require_master_admin,
        )
        self.assertIs(
            inspect.signature(get_guild_key).parameters["_user"].default.dependency,
            require_guild_admin,
        )

    async def test_ai_config_rejects_guild_id_rekey(self):
        with self.assertRaises(HTTPException) as ctx:
            await patch_ia_config(1, {"guild_id": 2}, object(), {})
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(HTTPException) as ctx:
            await update_guild_config_legacy(
                1,
                {"ai_config": {"guild_id": 2}},
                SimpleNamespace(set_ai_config=lambda *_args, **_kwargs: None),
                {},
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_embed_send_rejects_cross_guild_channel_and_missing_bot_perms(self):
        body = SendEmbedBody(channel_id="777", embed={"title": "test"})
        guild = _Guild(channels=())
        with mock.patch.dict(os.environ, {"TOKEN": "test-token"}):
            with self.assertRaises(HTTPException) as ctx:
                await send_embed_to_channel(123, body, object(), _Bot(guild), {})
        self.assertEqual(ctx.exception.status_code, 404)

        channel = _Channel(777, _Permissions(view_channel=True))
        guild = _Guild(channels=(channel,))
        with mock.patch.dict(os.environ, {"TOKEN": "test-token"}):
            with self.assertRaises(HTTPException) as ctx:
                await send_embed_to_channel(123, body, object(), _Bot(guild), {})
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
