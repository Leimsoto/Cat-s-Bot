import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from fastapi import HTTPException

from api.routes.voice_gen import ResendPanelBody, resend_panel
from cogs.voice_gen import (
    BanModal,
    BitrateModal,
    RenameModal,
    VCControlView,
    VoiceGen,
    _ban_target_error,
)


class _Response:
    def __init__(self):
        self.messages = []

    async def send_message(self, content, **kwargs):
        self.messages.append((content, kwargs))


class _Channel:
    id = 20

    def __init__(self):
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class VoiceGenBitrateTest(unittest.IsolatedAsyncioTestCase):
    async def test_bitrate_respects_actual_guild_limit(self):
        channel = _Channel()
        response = _Response()
        db = SimpleNamespace(
            get_voice_gen_channel=lambda channel_id: {
                "guild_id": 10,
                "owner_id": 42,
            } if channel_id == channel.id else None
        )
        guild = SimpleNamespace(
            id=10,
            owner_id=99,
            bitrate_limit=96_000,
            get_channel=lambda channel_id: channel if channel_id == channel.id else None,
        )
        interaction = SimpleNamespace(
            guild=guild,
            user=SimpleNamespace(
                id=42,
                guild_permissions=SimpleNamespace(administrator=False),
                voice=SimpleNamespace(channel=channel),
            ),
            response=response,
        )
        modal = BitrateModal(SimpleNamespace(db=db), channel.id)
        modal.bitrate._value = "128"

        await modal.on_submit(interaction)

        self.assertEqual(channel.edits, [])
        self.assertIn("8–96 kbps", response.messages[0][0])

    async def test_valid_bitrate_is_applied_in_bits_per_second(self):
        channel = _Channel()
        response = _Response()
        db = SimpleNamespace(
            get_voice_gen_channel=lambda channel_id: {
                "guild_id": 10,
                "owner_id": 42,
            } if channel_id == channel.id else None
        )
        guild = SimpleNamespace(
            id=10,
            owner_id=99,
            bitrate_limit=96_000,
            get_channel=lambda channel_id: channel if channel_id == channel.id else None,
        )
        interaction = SimpleNamespace(
            guild=guild,
            user=SimpleNamespace(
                id=42,
                guild_permissions=SimpleNamespace(administrator=False),
                voice=SimpleNamespace(channel=channel),
            ),
            response=response,
        )
        modal = BitrateModal(SimpleNamespace(db=db), channel.id)
        modal.bitrate._value = "96"

        await modal.on_submit(interaction)

        self.assertEqual(channel.edits, [{"bitrate": 96_000}])
        self.assertIn("96 kbps", response.messages[0][0])


class _Role:
    def __init__(self, position):
        self.position = position

    def __ge__(self, other):
        return self.position >= other.position


class _VoiceAuthDB:
    def __init__(self, channel_id, owner_id=42):
        self.channel_id = channel_id
        self.owner_id = owner_id

    def get_voice_gen_channel(self, channel_id):
        if channel_id != self.channel_id:
            return None
        return {"channel_id": channel_id, "guild_id": 10, "owner_id": self.owner_id}


class VoiceGenAuthorizationTest(unittest.IsolatedAsyncioTestCase):
    def _member(self, member_id, *, role=10, admin=False, voice=None):
        return SimpleNamespace(
            id=member_id,
            display_name=f"member-{member_id}",
            guild_permissions=SimpleNamespace(administrator=admin),
            top_role=_Role(role),
            voice=voice,
            move_to=AsyncMock(),
        )

    async def test_modal_edits_bound_channel_after_actor_switches_voice(self):
        target = _Channel()
        other = _Channel()
        other.id = 21
        db = _VoiceAuthDB(target.id)
        guild = SimpleNamespace(
            id=10,
            owner_id=99,
            get_channel=lambda channel_id: target if channel_id == target.id else other,
        )
        actor = self._member(42, voice=SimpleNamespace(channel=other))
        interaction = SimpleNamespace(guild=guild, user=actor, response=_Response())
        modal = RenameModal(SimpleNamespace(db=db), target.id)
        modal.name._value = "bound-target"

        await modal.on_submit(interaction)

        self.assertEqual(target.edits, [{"name": "bound-target"}])
        self.assertEqual(other.edits, [])

    async def test_modal_rechecks_owner_at_submit(self):
        target = _Channel()
        db = _VoiceAuthDB(target.id, owner_id=43)
        guild = SimpleNamespace(id=10, owner_id=99, get_channel=lambda _id: target)
        actor = self._member(42, voice=SimpleNamespace(channel=target))
        interaction = SimpleNamespace(guild=guild, user=actor, response=_Response())
        modal = RenameModal(SimpleNamespace(db=db), target.id)
        modal.name._value = "unauthorized"

        await modal.on_submit(interaction)

        self.assertEqual(target.edits, [])
        self.assertIn("Solo el dueño", interaction.response.messages[0][0])

    def test_ban_guard_protects_self_admin_and_hierarchy(self):
        actor = self._member(42, role=50)
        bot_member = self._member(999, role=100)
        guild = SimpleNamespace(id=10, owner_id=99, me=bot_member)

        self.assertIn("ti mismo", _ban_target_error(actor, actor, guild))
        self.assertIn("administrador", _ban_target_error(actor, self._member(43, admin=True), guild))
        self.assertIn("jerarquía", _ban_target_error(actor, self._member(44, role=50), guild))
        self.assertIsNone(_ban_target_error(actor, self._member(45, role=10), guild))

        guild_owner = self._member(99, role=200)
        self.assertIn(
            "jerarquía de roles",
            _ban_target_error(guild_owner, self._member(46, role=100), guild),
        )

    async def test_modal_and_slash_share_ban_guard(self):
        channel = _Channel()
        channel.set_permissions = AsyncMock()
        db = _VoiceAuthDB(channel.id)
        target = self._member(43, admin=True)
        actor = self._member(42, role=50, voice=SimpleNamespace(channel=channel))
        guild = SimpleNamespace(
            id=10,
            owner_id=99,
            me=self._member(999, role=100),
            get_channel=lambda _id: channel,
            get_member=lambda member_id: target if member_id == target.id else None,
        )

        modal_interaction = SimpleNamespace(guild=guild, user=actor, response=_Response())
        modal = BanModal(SimpleNamespace(db=db), channel.id)
        modal.user_id._value = str(target.id)
        await modal.on_submit(modal_interaction)

        slash_interaction = SimpleNamespace(guild=guild, user=actor, response=_Response())
        cog = VoiceGen.__new__(VoiceGen)
        cog.db = db
        await VoiceGen.vc_ban.callback(cog, slash_interaction, target)

        channel.set_permissions.assert_not_awaited()
        self.assertIn("administrador", modal_interaction.response.messages[0][0])
        self.assertIn("administrador", slash_interaction.response.messages[0][0])


class _PanelMessage:
    def __init__(self, message_id, *, delete_error=None):
        self.id = message_id
        self.deleted = False
        self.delete_error = delete_error
        self.edits = []
        self.author = SimpleNamespace(id=999)
        self.embeds = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)

    async def delete(self):
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted = True


class _PanelChannel:
    def __init__(self, channel_id, message=None):
        self.id = channel_id
        self.message = message
        self.messages = {message.id: message} if message else {}
        self.fetched = []
        self.sent = []

    async def fetch_message(self, message_id):
        self.fetched.append(message_id)
        return self.messages[message_id]

    async def send(self, **kwargs):
        self.message = _PanelMessage(1525524305302126797 + len(self.sent))
        self.messages[self.message.id] = self.message
        self.sent.append(kwargs)
        return self.message

    def history(self, **_kwargs):
        async def iterator():
            for message in list(self.messages.values()):
                yield message

        return iterator()


class _GeneratedVoiceChannel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.name = "Canal temporal"
        self.members = []
        self.deleted = False

    async def delete(self, **_kwargs):
        self.deleted = True


class _VoiceGenDB:
    def __init__(self, row=None, config=None):
        self.row = dict(row) if row else None
        self.config = {
            "enabled": 1,
            "auto_send_panel": 1,
            "panel_channel_id": None,
            "panel_message_channel_id": None,
            "panel_message_id": None,
            **(config or {}),
        }
        self.deleted = []

    def get_voice_gen_channel(self, channel_id):
        if self.row and int(self.row["channel_id"]) == int(channel_id):
            return dict(self.row)
        return None

    def get_voice_gen_config(self, _guild_id):
        return dict(self.config)

    def set_voice_gen_config(self, _guild_id, **kwargs):
        self.config.update(kwargs)

    def get_voice_gen_channels_by_guild(self, guild_id):
        if self.row and int(self.row["guild_id"]) == int(guild_id):
            return [dict(self.row)]
        return []

    def delete_voice_gen_channel(self, channel_id):
        self.deleted.append(channel_id)
        self.row = None

    def update_voice_gen_channel_panel(self, channel_id, panel_channel_id, panel_message_id):
        if not self.row or int(self.row["channel_id"]) != int(channel_id):
            return False
        self.row["panel_channel_id"] = panel_channel_id
        self.row["panel_message_id"] = panel_message_id
        return True


class VoiceGenCleanupTest(unittest.IsolatedAsyncioTestCase):
    def _cog(self, db):
        cog = VoiceGen.__new__(VoiceGen)
        cog.bot = SimpleNamespace(user=SimpleNamespace(id=999), db=db)
        cog.db = db
        cog._delete_locks = {}
        cog._panel_locks = {}
        cog._legacy_panel_swept = set()
        return cog

    async def test_deleting_generated_channel_keeps_permanent_panel(self):
        voice_channel_id = 1525524238008586270
        panel_channel_id = 1497055416062971949
        panel_message_id = 1525524305302126796
        panel_message = _PanelMessage(panel_message_id)
        panel_channel = _PanelChannel(panel_channel_id, panel_message)
        voice_channel = _GeneratedVoiceChannel(voice_channel_id)
        guild = SimpleNamespace(
            id=10,
            get_channel=lambda channel_id: panel_channel if channel_id == panel_channel_id else None,
        )
        db = _VoiceGenDB(
            {
                "channel_id": voice_channel_id,
                "guild_id": guild.id,
                "owner_id": 42,
                "panel_channel_id": panel_channel_id,
                "panel_message_id": panel_message_id,
            },
            {
                "panel_channel_id": panel_channel_id,
                "panel_message_channel_id": panel_channel_id,
                "panel_message_id": panel_message_id,
            },
        )
        cog = self._cog(db)

        removed = await cog._remove_generated_channel(guild, db.row, voice_channel)

        self.assertTrue(removed)
        self.assertTrue(voice_channel.deleted)
        self.assertFalse(panel_message.deleted)
        self.assertEqual(panel_channel.fetched, [])
        self.assertEqual(db.deleted, [voice_channel_id])
        self.assertEqual(db.config["panel_message_id"], panel_message_id)

    async def test_startup_sweep_deletes_all_legacy_per_vc_panels(self):
        voice_id = 1525524238008586270
        panel_channel_id = 1497055416062971949
        footer = SimpleNamespace(text=f"ID del canal: {voice_id}")
        embed = SimpleNamespace(footer=footer)
        message = _PanelMessage(1525524305302126796)
        message.embeds = [embed]
        panel_channel = _PanelChannel(panel_channel_id, message)
        guild = SimpleNamespace(
            id=10,
            get_channel=lambda channel_id: panel_channel if channel_id == panel_channel_id else None,
        )
        db = _VoiceGenDB(
            {
                "channel_id": voice_id,
                "guild_id": guild.id,
                "owner_id": 42,
                "panel_channel_id": panel_channel_id,
                "panel_message_id": message.id,
            },
            {"panel_channel_id": panel_channel_id},
        )
        cog = self._cog(db)

        scanned = await cog._cleanup_legacy_panels(guild)

        self.assertTrue(scanned)
        self.assertTrue(message.deleted)
        self.assertIsNone(db.row["panel_channel_id"])
        self.assertIsNone(db.row["panel_message_id"])

    async def test_send_panel_creates_one_message_then_reuses_and_updates_it(self):
        panel_channel_id = 1497055416062971949
        panel_channel = _PanelChannel(panel_channel_id)
        guild = SimpleNamespace(
            id=10,
            name="Guild",
            get_channel=lambda channel_id: panel_channel if int(channel_id) == panel_channel_id else None,
        )
        db = _VoiceGenDB(config={"panel_channel_id": panel_channel_id})
        cog = self._cog(db)

        with patch.object(discord, "TextChannel", _PanelChannel):
            created = await cog.send_panel(guild)
            reused = await cog.send_panel(guild)
            updated = await cog.send_panel(guild, force=True)

        self.assertTrue(created)
        self.assertTrue(reused)
        self.assertTrue(updated)
        self.assertEqual(len(panel_channel.sent), 1)
        self.assertEqual(len(panel_channel.message.edits), 1)
        self.assertEqual(db.config["panel_message_channel_id"], panel_channel_id)
        self.assertEqual(db.config["panel_message_id"], panel_channel.message.id)
        self.assertNotIn("ID del canal", panel_channel.sent[0]["embed"].footer.text)

    async def test_resend_api_publishes_without_an_active_vc(self):
        guild = SimpleNamespace(id=10)
        db = _VoiceGenDB()
        calls = []

        class _Cog:
            async def send_panel(self, target_guild, *, force=False):
                calls.append((target_guild, force))
                return True

        bot = SimpleNamespace(
            loop=asyncio.get_running_loop(),
            get_guild=lambda ident: guild if ident == guild.id else None,
            get_cog=lambda name: _Cog() if name == "VoiceGen" else None,
        )

        result = await resend_panel(
            guild.id,
            ResendPanelBody(),
            db,
            bot,
            {"user_id": 42},
        )

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(calls, [(guild, True)])

    async def test_resend_api_reports_cog_failure(self):
        guild = SimpleNamespace(id=10)
        db = _VoiceGenDB()

        class _Cog:
            async def send_panel(self, *_args, **_kwargs):
                return False

        bot = SimpleNamespace(
            loop=asyncio.get_running_loop(),
            get_guild=lambda ident: guild if ident == guild.id else None,
            get_cog=lambda name: _Cog() if name == "VoiceGen" else None,
        )

        with self.assertRaises(HTTPException) as raised:
            await resend_panel(
                guild.id,
                ResendPanelBody(),
                db,
                bot,
                {"user_id": 42},
            )

        self.assertEqual(raised.exception.status_code, 409)

    async def test_moving_panel_rolls_back_if_old_message_cannot_be_deleted(self):
        class _Forbidden(Exception):
            pass

        old_channel_id = 1497055416062971949
        new_channel_id = 1497055416062971950
        old_message_id = 1525524305302126796
        old_message = _PanelMessage(old_message_id, delete_error=_Forbidden("forbidden"))
        old_channel = _PanelChannel(old_channel_id, old_message)
        new_channel = _PanelChannel(new_channel_id)
        guild = SimpleNamespace(
            id=10,
            name="Guild",
            get_channel=lambda channel_id: {
                old_channel_id: old_channel,
                new_channel_id: new_channel,
            }.get(int(channel_id)),
        )
        db = _VoiceGenDB(
            config={
                "panel_channel_id": new_channel_id,
                "panel_message_channel_id": old_channel_id,
                "panel_message_id": old_message_id,
            }
        )
        cog = self._cog(db)

        with (
            patch.object(discord, "TextChannel", _PanelChannel),
            patch.object(discord, "Forbidden", _Forbidden),
        ):
            sent = await cog.send_panel(guild, force=True)

        new_message = new_channel.messages[1525524305302126797]
        self.assertFalse(sent)
        self.assertFalse(old_message.deleted)
        self.assertTrue(new_message.deleted)
        self.assertEqual(db.config["panel_message_id"], old_message_id)


class VoiceGenPermanentPanelAuthorizationTest(unittest.IsolatedAsyncioTestCase):
    def test_panel_view_is_persistent(self):
        view = VCControlView(SimpleNamespace(db=SimpleNamespace()))

        self.assertTrue(view.is_persistent())

    async def test_panel_targets_owners_current_generated_vc(self):
        channel = _Channel()
        channel.set_permissions = AsyncMock()
        db = _VoiceAuthDB(channel.id, owner_id=42)
        guild = SimpleNamespace(
            id=10,
            owner_id=99,
            default_role=SimpleNamespace(),
            get_channel=lambda channel_id: channel if channel_id == channel.id else None,
        )
        actor = SimpleNamespace(
            id=42,
            guild_permissions=SimpleNamespace(administrator=False),
            voice=SimpleNamespace(channel=channel),
        )
        interaction = SimpleNamespace(guild=guild, user=actor, response=_Response())
        view = VCControlView(SimpleNamespace(db=db))

        resolved = await view._channel(interaction)

        self.assertIs(resolved, channel)

    async def test_panel_rejects_non_owner_even_if_server_admin(self):
        channel = _Channel()
        db = _VoiceAuthDB(channel.id, owner_id=42)
        guild = SimpleNamespace(
            id=10,
            owner_id=99,
            get_channel=lambda channel_id: channel if channel_id == channel.id else None,
        )
        actor = SimpleNamespace(
            id=43,
            guild_permissions=SimpleNamespace(administrator=True),
            voice=SimpleNamespace(channel=channel),
        )
        interaction = SimpleNamespace(guild=guild, user=actor, response=_Response())
        view = VCControlView(SimpleNamespace(db=db))

        resolved = await view._channel(interaction)

        self.assertIsNone(resolved)
        self.assertIn("Solo el dueño", interaction.response.messages[0][0])

    async def test_panel_rejects_voice_channel_not_created_by_bot(self):
        channel = _Channel()
        db = _VoiceAuthDB(999, owner_id=42)
        guild = SimpleNamespace(
            id=10,
            owner_id=99,
            get_channel=lambda channel_id: channel if channel_id == channel.id else None,
        )
        actor = SimpleNamespace(
            id=42,
            guild_permissions=SimpleNamespace(administrator=False),
            voice=SimpleNamespace(channel=channel),
        )
        interaction = SimpleNamespace(guild=guild, user=actor, response=_Response())
        view = VCControlView(SimpleNamespace(db=db))

        resolved = await view._channel(interaction)

        self.assertIsNone(resolved)
        self.assertIn("no fue creado por el bot", interaction.response.messages[0][0])


if __name__ == "__main__":
    unittest.main()
