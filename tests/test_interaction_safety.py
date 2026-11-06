import unittest
from types import SimpleNamespace

import discord

from cogs.moderation import Moderation


def _discord_not_found():
    response = SimpleNamespace(status=404, reason="Not Found", headers={})
    return discord.NotFound(response, {"message": "Unknown Webhook", "code": 10015})


class InteractionSafetyTest(unittest.IsolatedAsyncioTestCase):
    async def test_safe_send_swallows_expired_followup_webhook(self):
        class Response:
            def is_done(self):
                return True

        class Followup:
            async def send(self, *args, **kwargs):
                raise _discord_not_found()

        interaction = SimpleNamespace(response=Response(), followup=Followup())
        cog = Moderation.__new__(Moderation)

        self.assertFalse(await cog._safe_interaction_send(interaction, "ok", ephemeral=True))

    async def test_safe_defer_swallows_expired_interaction(self):
        class Response:
            def is_done(self):
                return False

            async def defer(self, *args, **kwargs):
                raise _discord_not_found()

        interaction = SimpleNamespace(response=Response())
        cog = Moderation.__new__(Moderation)

        self.assertFalse(await cog._safe_defer(interaction, ephemeral=True))


if __name__ == "__main__":
    unittest.main()
