import unittest
from types import SimpleNamespace

from api.routes.guild import get_level_rewards, get_levels_config


class LevelsApiIdentityTest(unittest.IsolatedAsyncioTestCase):
    async def test_rewards_include_role_name_color_and_string_id(self):
        guild_id = 123
        role_id = 1497055412992872482
        role = SimpleNamespace(
            id=role_id,
            name="Veterano",
            color=SimpleNamespace(value=0x7C3AED),
        )
        guild = SimpleNamespace(get_role=lambda ident: role if ident == role_id else None)
        bot = SimpleNamespace(get_guild=lambda ident: guild if ident == guild_id else None)

        class DB:
            @staticmethod
            def get_xp_config(_guild_id):
                return {"guild_id": guild_id, "enabled": 1}

            @staticmethod
            def get_level_rewards(_guild_id):
                return [{"guild_id": guild_id, "level": 5, "role_id": role_id}]

        loaded = await get_levels_config(guild_id, DB(), bot, {"user_id": 42})
        reward = loaded["rewards"][0]
        self.assertEqual(reward["role_id"], str(role_id))
        self.assertEqual(reward["role_name"], "Veterano")
        self.assertEqual(reward["role_color"], "#7c3aed")
        self.assertTrue(reward["role_exists"])

        listed = await get_level_rewards(guild_id, DB(), bot, {"user_id": 42})
        self.assertEqual(listed["rewards"][0]["role_name"], "Veterano")


if __name__ == "__main__":
    unittest.main()
