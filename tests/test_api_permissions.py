import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from api.deps import require_guild_admin


class _Perms:
    administrator = False
    manage_guild = True


class _Member:
    guild_permissions = _Perms()


class _Guild:
    id = 123
    owner_id = 999

    def get_member(self, user_id: int):
        return _Member() if user_id == 42 else None


class _Bot:
    def get_guild(self, guild_id: int):
        return _Guild() if guild_id == 123 else None


class DashboardPermissionTest(unittest.IsolatedAsyncioTestCase):
    async def test_live_guild_admin_fallback_allows_stale_jwt(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(bot=_Bot())))
        user = {"user_id": 42, "guilds": []}

        result = await require_guild_admin(123, request, user)

        self.assertIs(result, user)
        self.assertTrue(result["is_live_guild_admin"])

    async def test_non_member_still_forbidden(self):
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(bot=_Bot())))
        user = {"user_id": 777, "guilds": []}

        with self.assertRaises(HTTPException) as ctx:
            await require_guild_admin(123, request, user)

        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
