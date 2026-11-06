import logging
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cogs.levels import Levels
from database.manager import DatabaseManager


def make_db():
    db = DatabaseManager.__new__(DatabaseManager)
    db.db_type = "sqlite"
    db._sqlite_lock = threading.Lock()
    db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
    db._sqlite_conn.row_factory = sqlite3.Row
    db._sqlite_conn.execute("PRAGMA foreign_keys = ON")
    logger = logging.getLogger("Database")
    previous_disabled = logger.disabled
    logger.disabled = True
    try:
        db._init_schema()
    finally:
        logger.disabled = previous_disabled
    return db


class LevelsRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = make_db()

    async def asyncTearDown(self):
        self.db._sqlite_conn.close()

    async def test_admin_xp_does_not_increment_message_count(self):
        first = self.db.add_xp(10, 20, 100, increment_message_count=False)
        second = self.db.add_xp(10, 20, 25)

        self.assertEqual(first["message_count"], 0)
        self.assertEqual(second["message_count"], 1)
        self.assertEqual(self.db.get_user_level(10, 20)["message_count"], 1)

    async def test_level_jump_grants_all_crossed_stack_rewards(self):
        guild_id = 20
        self.db.set_level_reward(guild_id, 1, 101)
        self.db.set_level_reward(guild_id, 2, 102)

        class _Role:
            def __init__(self, ident, *, manage_roles=False):
                self.id = ident
                self.position = 1
                self.managed = False
                self.permissions = SimpleNamespace(manage_roles=manage_roles)

            def is_default(self):
                return False

            def __ge__(self, other):
                return self.position >= other.position

        roles = {101: _Role(101), 102: _Role(102)}

        class _Guild:
            id = guild_id
            name = "Guild"
            me = SimpleNamespace(top_role=SimpleNamespace(position=100))

            def get_role(self, ident):
                return roles.get(ident)

        class _Member:
            def __init__(self):
                self.roles = []
                self.added = []

            async def add_roles(self, *new_roles, reason=None):
                self.added.extend(role.id for role in new_roles)
                self.roles.extend(new_roles)

            async def remove_roles(self, *old_roles, reason=None):
                self.roles = [role for role in self.roles if role not in old_roles]

        cog = Levels(type("Bot", (), {"db": self.db})())
        member = _Member()
        await cog._assign_rewards(member, _Guild(), 0, 2, {"stack_rewards": 1})

        self.assertEqual(member.added, [101, 102])

    async def test_privileged_level_reward_is_not_assigned(self):
        guild_id = 21
        self.db.set_level_reward(guild_id, 1, 201)

        class _Role:
            id = 201
            position = 1
            managed = False
            permissions = SimpleNamespace(manage_roles=True)

            def is_default(self):
                return False

            def __ge__(self, other):
                return self.position >= other.position

        role = _Role()
        guild = SimpleNamespace(
            id=guild_id,
            name="Guild",
            me=SimpleNamespace(top_role=SimpleNamespace(position=100)),
            get_role=lambda _role_id: role,
        )
        member = SimpleNamespace(roles=[], add_roles=AsyncMock())
        cog = Levels(type("Bot", (), {"db": self.db})())

        await cog._assign_rewards(member, guild, 0, 1, {"stack_rewards": 1})

        member.add_roles.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
