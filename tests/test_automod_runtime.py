import unittest
from unittest.mock import patch

from cogs.automod import AutoMod, AutoModActions


class _DB:
    def __init__(self, exempt_bots=True, exempt_admins=True):
        self.exempt_bots = exempt_bots
        self.exempt_admins = exempt_admins

    def get_automod_config(self, _guild_id):
        return {
            "enabled": 1,
            "rules": {
                "ignored": {
                    "channels": [],
                    "roles": [],
                    "exempt_admins": self.exempt_admins,
                    "exempt_bots": self.exempt_bots,
                },
                "banned_words": {
                    "enabled": True,
                    "words": ["prohibido"],
                    "action": "warn",
                },
            },
        }


class _Bot:
    def __init__(self, db):
        self.db = db


class _Author:
    id = 50
    bot = True


class _Guild:
    id = 100
    owner_id = 1


class _Channel:
    id = 200


class _Message:
    guild = _Guild()
    author = _Author()
    channel = _Channel()
    content = "mensaje prohibido"
    mentions = []
    role_mentions = []


class AutoModRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_bot_exemption_is_configurable(self):
        exempt = AutoMod(_Bot(_DB(exempt_bots=True)))
        exempt_calls = []

        async def _record_exempt(*args):
            exempt_calls.append(args)

        exempt._execute_action = _record_exempt
        await exempt.on_message(_Message())
        self.assertEqual(exempt_calls, [])

        included = AutoMod(_Bot(_DB(exempt_bots=False)))
        included_calls = []

        async def _record_included(*args):
            included_calls.append(args)

        included._execute_action = _record_included
        await included.on_message(_Message())
        self.assertEqual(len(included_calls), 1)
        self.assertEqual(included_calls[0][1:3], ("banned_words", AutoModActions.WARN))

    async def test_action_cooldown_suppresses_repeated_sanction(self):
        cog = AutoMod(_Bot(_DB()))
        message = _Message()
        config = {"action_cooldown_seconds": 60}

        self.assertTrue(cog._action_allowed(message, "spam", "warn", config))
        self.assertFalse(cog._action_allowed(message, "spam", "warn", config))

    async def test_administrators_cannot_be_punished_via_exemption_toggle(self):
        class AdminAuthor:
            id = 50
            bot = False
            roles = []
            guild_permissions = type("Permissions", (), {"administrator": True})()

        message = _Message()
        message.author = AdminAuthor()
        cog = AutoMod(_Bot(_DB(exempt_admins=False)))
        calls = []

        async def record(*args):
            calls.append(args)

        cog._execute_action = record
        with patch("cogs.automod.discord.Member", AdminAuthor):
            await cog.on_message(message)

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
