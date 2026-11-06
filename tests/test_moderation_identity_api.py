import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from api.routes.moderation import get_mod_cases, get_active_moderations
from api.routes.guild import get_automod_log
from cogs._moderation_history import moderation_details, identity_payload, public_channel
from cogs.moderation import Moderation


class _User:
    def __init__(self, user_id, display_name, name=None):
        self.id = int(user_id)
        self.display_name = display_name
        self.name = name or display_name.lower().replace(" ", "")
        self.discriminator = "0"
        self.display_avatar = SimpleNamespace(url=f"https://cdn.example/{self.id}.png")

    def __str__(self):
        return self.name


class _Guild:
    owner_id = 1

    def __init__(self, members):
        self._members = {m.id: m for m in members}

    def get_member(self, user_id):
        return self._members.get(int(user_id))


class _Bot:
    def __init__(self, guild):
        self._guild = guild

    def get_guild(self, guild_id):
        return self._guild

    def get_user(self, user_id):
        return None


class _DB:
    def list_cases(self, guild_id, user_id=None, limit=100, offset=0):
        return [
            {
                "id": 9,
                "guild_id": guild_id,
                "case_number": 2,
                "action_type": "TIMEOUT",
                "target_id": 533644219697463296,
                "moderator_id": 777777777777777777,
                "reason": "test",
            }
        ]

    def get_active_moderations(self, guild_id, limit=100):
        return self.list_cases(guild_id, limit=limit)

    def get_pending_moderation_actions(self, guild_id, limit=100):
        return [
            {
                "id": 1,
                "guild_id": guild_id,
                "user_id": 533644219697463296,
                "action_type": "TIMEOUT_EXPIRE",
            }
        ]


class ModerationIdentityApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_manual_timeout_persists_context_and_identity_without_real_actions(self):
        uid = 1423899890337054771
        target = _User(uid, "Usuario")
        target.mention, target.timeout = f"<@{uid}>", AsyncMock()
        actor = _User(999, "Moderador")
        actor.mention = "<@999>"
        guild = _Guild([target, actor])
        interaction = SimpleNamespace(guild=guild, guild_id=123, user=actor, channel_id=456)
        cog = Moderation.__new__(Moderation)
        cog.db = SimpleNamespace(log_action=Mock(return_value=7), add_pending_moderation_action=Mock())
        cog._safe_defer = AsyncMock(return_value=True)
        cog._has_mod_perms = Mock(return_value=True)
        cog._can_moderate = Mock(return_value=None)
        cog._fresh_moderation_context = AsyncMock(return_value=(actor, target, None))
        cog._safe_interaction_send, cog._send_log = AsyncMock(), AsyncMock()
        await Moderation.timeout_cmd.callback(cog, interaction, target, "5m", "Motivo real")
        target.timeout.assert_awaited_once()
        extra = cog.db.log_action.call_args.args[5]
        self.assertEqual(extra["channel_id"], "456")
        self.assertEqual(extra["target_user"]["id"], str(uid))
        self.assertEqual(extra["target_user"]["avatar_url"], target.display_avatar.url)
        self.assertEqual(extra["moderator_user"]["name"], actor.name)
        self.assertEqual(extra["duration_secs"], 300)
        self.assertIs(extra["public_at_capture"], False)

    def test_channel_visibility_requires_text_channel_and_public_history(self):
        class Channel:
            def __init__(self, view, history):
                self.permissions_for = Mock(return_value=SimpleNamespace(view_channel=view, read_message_history=history))
        guild = SimpleNamespace(default_role=object())
        with patch("cogs._moderation_history.discord.TextChannel", Channel):
            self.assertTrue(public_channel(Channel(True, True), guild))
            self.assertFalse(public_channel(Channel(False, True), guild))
            self.assertFalse(public_channel(Channel(True, False), guild))
            self.assertFalse(public_channel(SimpleNamespace(), guild))

    async def test_automod_log_preserves_exact_ids_and_resolves_legacy_identity(self):
        uid = 1423899890337054771
        guild = _Guild([_User(uid, "Nombre visible", "usuario")])
        db = SimpleNamespace(get_automod_log=lambda *args, **kwargs: [{
            "id": 8, "guild_id": uid + 1, "user_id": uid, "rule": "llm",
            "action_taken": "delete", "content": "message:1567890123456789012 Motivo: Invitación no permitida Regla: No invitar",
        }])
        rows = await get_automod_log(123, 50, db, {}, _Bot(guild))
        row = rows[0]
        self.assertEqual(row["user_id"], str(uid))
        self.assertEqual(row["guild_id"], str(uid + 1))
        self.assertEqual(row["target_user"]["id"], str(uid))
        self.assertEqual(row["target_user"]["name"], "usuario")
        self.assertEqual(row["target_avatar_url"], f"https://cdn.example/{uid}.png")
        self.assertEqual(row["reason_display"], "Invitación no permitida")
        self.assertEqual(row["rule_text"], "No invitar")
        self.assertEqual(row["message_id"], "1567890123456789012")
        self.assertEqual(row["action_label"], "Mensaje eliminado")

    async def test_case_uses_structured_reason_and_retains_departed_user_snapshot(self):
        uid = 1423899890337054771
        snapshot = identity_payload(uid, _User(uid, "Usuario expulsado"))
        db = SimpleNamespace(list_cases=lambda *args, **kwargs: [{
            "id": 2, "guild_id": 123, "target_id": uid, "moderator_id": 999,
            "action_type": "AUTO_KICK", "status": "failed",
            "reason": "LLM message:1567890123456789012 Regla antigua",
            "extra_data": json.dumps({"target_user": snapshot, "source": "llm",
                "decision": {"reason": "Enlace de invitación", "rule": "No invitar"}}),
        }])
        row = (await get_mod_cases(123, 100, 0, None, db, None, {}))[0]
        self.assertEqual(row["target_display"], "Usuario expulsado")
        self.assertEqual(row["target_avatar_url"], snapshot["avatar_url"])
        self.assertEqual(row["target_id"], str(uid))
        self.assertEqual(row["reason_display"], "Enlace de invitación")
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["action_label"], "Intento fallido: Expulsión")

    def test_legacy_reasons_and_allowlisted_details_do_not_invent_explanations(self):
        details = moderation_details({"reason": "LLM message:123 Regla: Motivo exacto", "action_type": "AUTO_WARN"})
        self.assertEqual((details["reason_display"], details["rule_text"]), ("Motivo exacto", "Regla"))
        self.assertEqual(moderation_details({"reason": "Motivo manual", "action_type": "WARN"})["reason_display"], "Motivo manual")
        self.assertEqual(moderation_details({"reason": "AutoMod (links): warn", "action_type": "AUTO_WARN"})["reason_display"], "Enlaces o invitaciones no permitidos")
        details = moderation_details({"extra_data": '{"api_key":"secret","prompt":"private"}', "reason": ""})
        self.assertNotIn("secret", json.dumps(details))
        self.assertNotIn("private", json.dumps(details))
        self.assertEqual(details["reason_display"], "Sin motivo registrado")
        self.assertEqual(moderation_details({"action_type": "AUTO_DELETE", "status": "applying"})["action_label"], "Sin confirmar: Mensaje eliminado")
        details = moderation_details({"reason": "LLM message:123 No insultar", "action_type": "AUTO_WARN"})
        self.assertEqual(details["reason_display"], "Motivo no disponible en el registro antiguo")
        self.assertEqual(details["rule_text"], "No insultar")

    async def test_cases_are_enriched_with_user_and_moderator_names(self):
        guild = _Guild([
            _User(533644219697463296, "Ezku"),
            _User(777777777777777777, "Mod Tortuga"),
        ])

        rows = await get_mod_cases(
            123,
            limit=100,
            offset=0,
            user_id=None,
            db=_DB(),
            bot=_Bot(guild),
            _user={"user_id": 1},
        )

        self.assertEqual(rows[0]["target_display"], "Ezku")
        self.assertEqual(rows[0]["moderator_display"], "Mod Tortuga")
        self.assertEqual(rows[0]["target_user"]["id"], "533644219697463296")
        self.assertTrue(rows[0]["target_user"]["resolved"])

    async def test_active_and_pending_are_enriched(self):
        guild = _Guild([_User(533644219697463296, "Ezku")])
        data = await get_active_moderations(
            123,
            limit=100,
            db=_DB(),
            bot=_Bot(guild),
            _user={"user_id": 1},
        )

        self.assertEqual(data["cases"][0]["target_display"], "Ezku")
        self.assertEqual(data["pending"][0]["target_display"], "Ezku")


if __name__ == "__main__":
    unittest.main()
