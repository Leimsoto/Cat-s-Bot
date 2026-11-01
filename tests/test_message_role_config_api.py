import logging
import sqlite3
import threading
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from api.routes.guild import get_moderation_config, patch_moderation_config
from database.manager import DatabaseManager


ROLE_ID = 123456789012345678


class MessageRoleConfigApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = DatabaseManager.__new__(DatabaseManager)
        self.db.db_type = "sqlite"
        self.db._sqlite_lock = threading.Lock()
        self.db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.db._sqlite_conn.row_factory = sqlite3.Row
        with unittest.mock.patch.object(logging.getLogger("Database"), "disabled", True):
            self.db._init_schema()
        self.role = SimpleNamespace(id=ROLE_ID, managed=True)
        self.guild = SimpleNamespace(id=100, get_role=lambda role_id: self.role if role_id == ROLE_ID else None)
        self.bot = SimpleNamespace(get_guild=lambda _id: self.guild)

    async def asyncTearDown(self):
        self.db._sqlite_conn.close()

    async def save(self, **body):
        return await patch_moderation_config(100, body, request=None, db=self.db,
                                             bot=self.bot, user={"user_id": 42})

    async def test_disabled_default_persistence_and_string_id(self):
        initial = await get_moderation_config(100, self.db, {})
        self.assertEqual(initial["message_role_enabled"], 0)
        self.assertIsNone(initial["message_role_id"])
        response = await self.save(message_role_enabled=1, message_role_id=str(ROLE_ID), message_role_notice="Consigue tu rol.")
        self.assertEqual(response["config"]["message_role_id"], str(ROLE_ID))
        self.assertEqual(self.db.get_config(100)["message_role_id"], ROLE_ID)
        self.assertEqual(self.db.get_config(101)["message_role_enabled"], 0)
        loaded = await get_moderation_config(100, self.db, {})
        self.assertEqual(loaded["message_role_notice"], "Consigue tu rol.")
        # Una actualización parcial conserva el rol y la activación.
        await self.save(message_role_notice="Texto nuevo")
        self.assertEqual(self.db.get_config(100)["message_role_enabled"], 1)
        await self.save(message_role_enabled=0, message_role_id=None, message_role_notice="")
        self.assertEqual(self.db.get_config(100)["message_role_enabled"], 0)

    async def test_invalid_gate_input_does_not_persist_other_fields(self):
        invalid = [dict(message_role_enabled=1),
                   dict(message_role_id="100"), dict(message_role_id="999"),
                   dict(message_role_id=True), dict(message_role_id="1.5"),
                   dict(message_role_enabled="false"), dict(message_role_enabled=2),
                   dict(message_role_notice=None), dict(message_role_notice="x" * 1976),
                   dict(message_role_notice="😀" * 988), dict(message_role_notice="\ud800"),
                   dict(message_role_enabled=1, message_role_id=str(ROLE_ID), message_role_notice="  \n ")]
        for body in invalid:
            with self.subTest(body=body):
                with self.assertRaises(HTTPException) as result:
                    await self.save(warn_mute_threshold=99, **body)
                self.assertEqual(result.exception.status_code, 400)
                self.assertEqual(self.db.get_config(100)["warn_mute_threshold"], 3)

    async def test_notice_limit_reserves_author_mention_and_role_is_not_privileged_assignment(self):
        # No comprobaciones de asignación/hierarquía: incluso rol gestionado válido.
        await self.save(message_role_enabled=True, message_role_id=str(ROLE_ID), message_role_notice="😀" * 987 + "a")
        notice = self.db.get_config(100)["message_role_notice"]
        full_message = f"<@18446744073709551615> {notice}"
        self.assertLessEqual(len(full_message.encode("utf-16-le")) // 2, 2000)

    async def test_existing_sqlite_schema_is_migrated_idempotently(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE guild_config (guild_id INTEGER PRIMARY KEY, staff_role_id INTEGER)")
        conn.execute("INSERT INTO guild_config VALUES (100, 42)")
        old_db = DatabaseManager.__new__(DatabaseManager)
        old_db.db_type = "sqlite"
        old_db._sqlite_lock = threading.Lock()
        old_db._sqlite_conn = conn
        try:
            with unittest.mock.patch.object(logging.getLogger("Database"), "disabled", True):
                old_db._init_schema()
                old_db._init_schema()
            cfg = old_db.get_config(100)
            self.assertEqual(cfg["staff_role_id"], 42)
            self.assertEqual(cfg["message_role_enabled"], 0)
            old_db.set_config(100, message_role_id=ROLE_ID)
            self.assertEqual(old_db.get_config(100)["message_role_id"], ROLE_ID)
        finally:
            conn.close()

    async def test_can_disable_after_configured_role_has_been_deleted(self):
        saved = await self.save(message_role_enabled=1, message_role_id=str(ROLE_ID))
        self.guild.get_role = lambda _id: None
        cfg = saved["config"]
        cfg["message_role_enabled"] = 0
        # Dashboard envía la configuración completa, conservando el antiguo ID.
        response = await self.save(**cfg)
        self.assertEqual(response["config"]["message_role_enabled"], 0)
        with self.assertRaises(HTTPException):
            await self.save(message_role_enabled=1)


if __name__ == "__main__":
    unittest.main()
