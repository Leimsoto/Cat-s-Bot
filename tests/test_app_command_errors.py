import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from discord import app_commands

from cogs.moderation import Moderation
from main import BotES


class _MemberTransformer:
    _error_display_name = "Member"


def _member_transform_error(value="ferosito0518"):
    return app_commands.TransformerError(
        value,
        discord.AppCommandOptionType.user,
        _MemberTransformer(),
    )


def _interaction():
    response = SimpleNamespace(
        is_done=lambda: False,
        send_message=AsyncMock(),
    )
    followup = SimpleNamespace(send=AsyncMock())
    return SimpleNamespace(
        command=SimpleNamespace(qualified_name="ban"),
        guild_id=123,
        extras={},
        response=response,
        followup=followup,
    )


class AppCommandErrorTest(unittest.IsolatedAsyncioTestCase):
    async def test_moderation_explains_unresolvable_member(self):
        interaction = _interaction()
        cog = Moderation.__new__(Moderation)

        with patch("cogs.moderation.logger.error") as log_error:
            await cog._handle_perm_error(interaction, _member_transform_error())

        interaction.response.send_message.assert_awaited_once()
        message = interaction.response.send_message.await_args.args[0]
        self.assertIn("miembro de este servidor", message)
        self.assertIn("lista de Discord", message)
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])
        self.assertTrue(interaction.extras["catsbot.app_command_error_handled"])
        interaction.followup.send.assert_not_awaited()
        log_error.assert_not_called()

    async def test_global_handler_does_not_repeat_locally_handled_error(self):
        interaction = _interaction()
        cog = Moderation.__new__(Moderation)
        bot = SimpleNamespace()

        error = _member_transform_error()
        await cog._handle_perm_error(interaction, error)
        with patch("main.logger.warning") as global_warning:
            await BotES.on_app_command_error(bot, interaction, error)

        interaction.response.send_message.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()
        global_warning.assert_not_called()

    async def test_global_handler_explains_unresolvable_member_without_local_handler(self):
        interaction = _interaction()
        bot = SimpleNamespace()

        with patch("main.logger.error") as log_error:
            await BotES.on_app_command_error(bot, interaction, _member_transform_error())

        interaction.response.send_message.assert_awaited_once()
        message = interaction.response.send_message.await_args.args[0]
        self.assertIn("usuario para este comando", message)
        self.assertIn("lista de Discord", message)
        self.assertTrue(interaction.response.send_message.await_args.kwargs["ephemeral"])
        interaction.followup.send.assert_not_awaited()
        log_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
