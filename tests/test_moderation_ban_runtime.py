import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from cogs.moderation import Moderation, _parse_discord_user_id


TARGET_ID = 123456789012345678


def _not_found():
    response = SimpleNamespace(status=404, reason="Not Found", headers={})
    return discord.NotFound(
        response,
        {"message": "Unknown Member", "code": 10007},
    )


def _forbidden():
    response = SimpleNamespace(status=403, reason="Forbidden", headers={})
    return discord.Forbidden(
        response,
        {"message": "Missing Access", "code": 50001},
    )


def _discord_user(user_id=TARGET_ID):
    return discord.User(
        state=Mock(),
        data={
            "id": str(user_id),
            "username": "usuario_ausente",
            "discriminator": "0",
            "avatar": None,
            "global_name": None,
        },
    )


def _runtime(*, member=None, fetch_error=None):
    guild = SimpleNamespace(
        id=100,
        name="Servidor",
        get_member=Mock(return_value=member),
        fetch_member=AsyncMock(
            side_effect=fetch_error if fetch_error is not None else None
        ),
        ban=AsyncMock(),
    )
    response = SimpleNamespace(
        send_message=AsyncMock(),
        defer=AsyncMock(),
    )
    followup = SimpleNamespace(send=AsyncMock())
    actor = SimpleNamespace(
        id=200,
        mention="<@200>",
        display_name="Moderador",
    )
    interaction = SimpleNamespace(
        guild=guild,
        guild_id=guild.id,
        user=actor,
        response=response,
        followup=followup,
    )
    db = SimpleNamespace(
        log_action=Mock(return_value=77),
        set_tempban=Mock(),
        add_pending_moderation_action=Mock(),
    )
    cog = Moderation.__new__(Moderation)
    cog.bot = SimpleNamespace(catbot_voice=None, get_user=Mock(return_value=None))
    cog.db = db
    cog._has_mod_perms = Mock(return_value=True)
    cog._can_moderate = Mock(return_value=None)
    cog._dm = AsyncMock()
    cog._send_log = AsyncMock(return_value=True)
    return cog, interaction, guild, db


class ModerationBanRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def test_ban_exposes_selector_and_explicit_id_options(self):
        parameters = {parameter.name: parameter for parameter in Moderation.ban.parameters}

        self.assertEqual(
            parameters["usuario"].type,
            discord.AppCommandOptionType.user,
        )
        self.assertFalse(parameters["usuario"].required)
        self.assertEqual(
            parameters["usuario_id"].type,
            discord.AppCommandOptionType.string,
        )
        self.assertFalse(parameters["usuario_id"].required)

    def test_user_id_parser_accepts_ids_and_mentions_only(self):
        self.assertEqual(_parse_discord_user_id(str(TARGET_ID)), TARGET_ID)
        self.assertEqual(_parse_discord_user_id(f"<@{TARGET_ID}>"), TARGET_ID)
        self.assertEqual(_parse_discord_user_id(f"<@!{TARGET_ID}>"), TARGET_ID)
        for invalid in ("", "usuario", "-1", "0", str(2**64), f"id:{TARGET_ID}"):
            with self.subTest(invalid=invalid):
                self.assertIsNone(_parse_discord_user_id(invalid))

    async def test_ban_accepts_user_resolved_outside_guild(self):
        target = _discord_user()
        cog, interaction, guild, db = _runtime(fetch_error=_not_found())

        await Moderation.ban.callback(cog, interaction, usuario=target)

        interaction.response.defer.assert_awaited_once()
        guild.fetch_member.assert_awaited_once_with(TARGET_ID)
        guild.ban.assert_awaited_once()
        self.assertIs(guild.ban.await_args.args[0], target)
        cog._dm.assert_awaited_once()
        self.assertIs(cog._dm.await_args.args[0], target)
        self.assertEqual(db.log_action.call_args.args[1], TARGET_ID)
        self.assertEqual(
            db.log_action.call_args.args[5]["target_input"],
            "selector",
        )

    async def test_ban_by_raw_id_uses_snowflake_when_user_is_absent(self):
        cog, interaction, guild, db = _runtime(fetch_error=_not_found())

        await Moderation.ban.callback(
            cog,
            interaction,
            usuario_id=f"<@!{TARGET_ID}>",
            razon="Evasión de sanción",
            eliminar_mensajes=2,
        )

        guild.ban.assert_awaited_once()
        target = guild.ban.await_args.args[0]
        self.assertIsInstance(target, discord.Object)
        self.assertEqual(target.id, TARGET_ID)
        self.assertEqual(
            guild.ban.await_args.kwargs["delete_message_seconds"],
            2 * 86400,
        )
        cog._dm.assert_not_awaited()
        self.assertEqual(db.log_action.call_args.args[1], TARGET_ID)
        self.assertEqual(db.log_action.call_args.args[3], "BAN")
        self.assertEqual(db.log_action.call_args.args[5]["target_input"], "id")
        sent_embed = interaction.followup.send.await_args.kwargs["embed"]
        self.assertIn(str(TARGET_ID), sent_embed.fields[0].value)

    async def test_ban_by_id_preserves_temporary_ban_persistence(self):
        cog, interaction, guild, db = _runtime(fetch_error=_not_found())

        await Moderation.ban.callback(
            cog,
            interaction,
            usuario_id=str(TARGET_ID),
            razon="Ban temporal por ID",
            duracion="2h",
        )

        guild.ban.assert_awaited_once()
        self.assertEqual(db.log_action.call_args.args[3], "TEMPBAN")
        self.assertEqual(db.log_action.call_args.kwargs["duration_seconds"], 7200)
        db.set_tempban.assert_called_once_with(
            interaction.guild_id,
            TARGET_ID,
            interaction.user.id,
            "Ban temporal por ID",
            7200,
            case_id=77,
        )
        pending_args = db.add_pending_moderation_action.call_args.args
        self.assertEqual(pending_args[:3], (interaction.guild_id, TARGET_ID, "TEMPBAN_EXPIRE"))
        self.assertEqual(
            db.add_pending_moderation_action.call_args.kwargs["case_id"],
            77,
        )

    async def test_ban_by_id_rechecks_hierarchy_for_present_member(self):
        member = SimpleNamespace(id=TARGET_ID)
        cog, interaction, guild, db = _runtime(member=member)
        cog._can_moderate.return_value = "Tu rol no es suficientemente alto."

        await Moderation.ban.callback(
            cog,
            interaction,
            usuario_id=str(TARGET_ID),
        )

        cog._can_moderate.assert_called_once_with(interaction.user, member)
        guild.fetch_member.assert_not_awaited()
        guild.ban.assert_not_awaited()
        db.log_action.assert_not_called()
        self.assertIn(
            "rol no es suficientemente alto",
            interaction.followup.send.await_args.args[0],
        )

    async def test_ban_by_id_fails_closed_if_membership_cannot_be_checked(self):
        cog, interaction, guild, db = _runtime(fetch_error=_forbidden())

        await Moderation.ban.callback(
            cog,
            interaction,
            usuario_id=str(TARGET_ID),
        )

        guild.ban.assert_not_awaited()
        db.log_action.assert_not_called()
        self.assertIn(
            "No puedo verificar",
            interaction.followup.send.await_args.args[0],
        )

    async def test_ban_rejects_invalid_or_ambiguous_target_before_defer(self):
        cog, interaction, guild, db = _runtime(fetch_error=_not_found())

        await Moderation.ban.callback(cog, interaction, usuario_id="no-es-id")

        interaction.response.send_message.assert_awaited_once()
        interaction.response.defer.assert_not_awaited()
        guild.ban.assert_not_awaited()
        db.log_action.assert_not_called()

        target = _discord_user()
        cog, interaction, guild, db = _runtime(fetch_error=_not_found())
        await Moderation.ban.callback(
            cog,
            interaction,
            usuario=target,
            usuario_id=str(TARGET_ID),
        )

        self.assertIn(
            "solo una opción",
            interaction.response.send_message.await_args.args[0],
        )
        interaction.response.defer.assert_not_awaited()
        guild.ban.assert_not_awaited()
        db.log_action.assert_not_called()


if __name__ == "__main__":
    unittest.main()
