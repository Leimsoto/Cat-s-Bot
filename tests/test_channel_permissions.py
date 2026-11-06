import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from cogs.channels import (
    AutoReactModal,
    ChannelSetupView,
    Channels,
    ClearAllConfirmView,
    MediaTypesModal,
    check_channel_perms,
    has_effective_channel_permission,
)
from cogs.moderation import Moderation


class _Response:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


class _Channel:
    def __init__(self, permissions_by_member):
        self.id = 500
        self.permissions_by_member = permissions_by_member
        self.permission_updates = []

    def permissions_for(self, member):
        return self.permissions_by_member[member.id]

    def overwrites_for(self, _role):
        return SimpleNamespace(send_messages=False)

    async def set_permissions(self, role, **kwargs):
        self.permission_updates.append((role, kwargs))


class _DB:
    def __init__(self):
        self.channel_updates = []

    def get_server_config(self, _guild_id):
        # Simula el rol de soporte que antes producía el bypass.
        return {"channels_role_id": 777}

    def set_channel_config(self, channel_id, guild_id, **kwargs):
        self.channel_updates.append((channel_id, guild_id, kwargs))


def _permissions(**overrides):
    values = {
        "administrator": False,
        "manage_channels": False,
        "manage_threads": False,
        "manage_messages": False,
        "read_message_history": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class ChannelPermissionTest(unittest.IsolatedAsyncioTestCase):
    async def test_support_role_cannot_unlock_without_effective_manage_channels(self):
        support_member = SimpleNamespace(
            id=42,
            display_name="Soporte",
            guild_permissions=_permissions(manage_messages=True),
            roles=[SimpleNamespace(id=777)],
        )
        bot_member = SimpleNamespace(
            id=999,
            guild_permissions=_permissions(),
        )
        channel = _Channel(
            {
                support_member.id: _permissions(manage_messages=True, manage_channels=False),
                bot_member.id: _permissions(manage_channels=True),
            }
        )
        guild = SimpleNamespace(
            id=10,
            owner_id=1,
            me=bot_member,
            default_role=SimpleNamespace(id=10),
        )
        response = _Response()
        db = _DB()
        interaction = SimpleNamespace(
            user=support_member,
            guild=guild,
            guild_id=guild.id,
            channel=channel,
            response=response,
            client=SimpleNamespace(db=db),
        )
        cog = Channels.__new__(Channels)
        cog.db = db

        with patch.object(discord, "TextChannel", _Channel):
            await Channels.unlock.callback(cog, interaction)

        self.assertEqual(channel.permission_updates, [])
        self.assertEqual(db.channel_updates, [])
        self.assertIn("Gestionar Canales", response.messages[0][0])

    async def test_unlock_executes_with_effective_manage_channels(self):
        moderator = SimpleNamespace(
            id=43,
            display_name="Moderador",
            guild_permissions=_permissions(),
            roles=[],
        )
        bot_member = SimpleNamespace(id=999, guild_permissions=_permissions())
        channel = _Channel(
            {
                moderator.id: _permissions(manage_channels=True),
                bot_member.id: _permissions(manage_channels=True),
            }
        )
        guild = SimpleNamespace(
            id=10,
            owner_id=1,
            me=bot_member,
            default_role=SimpleNamespace(id=10),
        )
        response = _Response()
        db = _DB()
        interaction = SimpleNamespace(
            user=moderator,
            guild=guild,
            guild_id=guild.id,
            channel=channel,
            response=response,
            client=SimpleNamespace(db=db),
        )
        cog = Channels.__new__(Channels)
        cog.db = db

        with patch.object(discord, "TextChannel", _Channel):
            await Channels.unlock.callback(cog, interaction)

        self.assertEqual(len(channel.permission_updates), 1)
        self.assertIsNone(channel.permission_updates[0][1]["send_messages"])
        self.assertEqual(db.channel_updates[0][2], {"locked": 0})

    async def test_moderation_purge_cannot_use_configured_role_as_channel_bypass(self):
        support_member = SimpleNamespace(
            id=42,
            display_name="Soporte",
            guild_permissions=_permissions(),
            roles=[SimpleNamespace(id=777)],
        )
        bot_member = SimpleNamespace(id=999, guild_permissions=_permissions())
        channel = _Channel(
            {
                support_member.id: _permissions(manage_messages=False),
                bot_member.id: _permissions(
                    manage_messages=True,
                    read_message_history=True,
                ),
            }
        )
        guild = SimpleNamespace(id=10, owner_id=1, me=bot_member)
        response = _Response()
        interaction = SimpleNamespace(
            user=support_member,
            guild=guild,
            guild_id=guild.id,
            channel=channel,
            response=response,
        )
        cog = Moderation.__new__(Moderation)

        with patch.object(discord, "TextChannel", _Channel):
            await Moderation.purge.callback(cog, interaction, 2, None, "all")

        self.assertIn("Gestionar Mensajes", response.messages[0][0])

    async def test_all_sensitive_channel_commands_deny_support_role_bypass(self):
        support_member = SimpleNamespace(
            id=42,
            display_name="Soporte",
            guild_permissions=_permissions(manage_messages=True),
            roles=[SimpleNamespace(id=777)],
        )
        bot_member = SimpleNamespace(id=999, guild_permissions=_permissions())
        channel = _Channel(
            {
                support_member.id: _permissions(
                    manage_messages=False,
                    manage_channels=False,
                ),
                bot_member.id: _permissions(
                    manage_messages=True,
                    manage_channels=True,
                    read_message_history=True,
                ),
            }
        )
        guild = SimpleNamespace(
            id=10,
            owner_id=1,
            me=bot_member,
            default_role=SimpleNamespace(id=10),
        )
        db = _DB()
        cog = Channels.__new__(Channels)
        cog.db = db

        callbacks = (
            (Channels.lock.callback, ("incidente",), "Gestionar Canales"),
            (Channels.clear.callback, (2,), "Gestionar Mensajes"),
            (Channels.clearall.callback, (), "Gestionar Canales"),
            (Channels.slowmode.callback, (5,), "Gestionar Canales"),
            (Channels.channelsetup.callback, (), "Gestionar Canales"),
        )
        with patch.object(discord, "TextChannel", _Channel):
            for callback, args, expected_permission in callbacks:
                response = _Response()
                interaction = SimpleNamespace(
                    user=support_member,
                    guild=guild,
                    guild_id=guild.id,
                    channel=channel,
                    response=response,
                    client=SimpleNamespace(db=db),
                )
                await callback(cog, interaction, *args)
                self.assertIn(expected_permission, response.messages[0][0])

        self.assertEqual(channel.permission_updates, [])
        self.assertEqual(db.channel_updates, [])

    async def test_confirmation_and_setup_revalidate_after_permission_revocation(self):
        member = SimpleNamespace(
            id=42,
            guild_permissions=_permissions(),
        )
        bot_member = SimpleNamespace(id=999, guild_permissions=_permissions())
        channel = _Channel(
            {
                member.id: _permissions(manage_channels=False),
                bot_member.id: _permissions(manage_channels=True, manage_messages=True),
            }
        )
        guild = SimpleNamespace(
            id=10,
            owner_id=1,
            me=bot_member,
            get_channel=lambda channel_id: channel if channel_id == channel.id else None,
        )

        clear_response = _Response()
        clear_interaction = SimpleNamespace(
            user=member,
            guild=guild,
            guild_id=guild.id,
            channel=channel,
            response=clear_response,
        )
        self.assertFalse(
            await ClearAllConfirmView(member.id).interaction_check(clear_interaction)
        )

        setup_response = _Response()
        setup_interaction = SimpleNamespace(
            user=member,
            guild=guild,
            guild_id=guild.id,
            channel=channel,
            response=setup_response,
        )
        parent = ChannelSetupView(SimpleNamespace(db=_DB()), member.id, channel.id)
        self.assertFalse(await parent.interaction_check(setup_interaction))

    async def test_channel_setup_modals_abort_when_permission_was_revoked(self):
        parent = ChannelSetupView(SimpleNamespace(db=_DB()), 42, 500)
        parent._can_manage = AsyncMock(return_value=False)
        interaction = SimpleNamespace()

        await MediaTypesModal(parent).on_submit(interaction)
        await AutoReactModal(parent).on_submit(interaction)

        self.assertEqual(parent._can_manage.await_count, 2)

    async def test_bot_permissions_are_checked_in_target_channel(self):
        moderator = SimpleNamespace(
            id=43,
            guild_permissions=_permissions(),
        )
        bot_member = SimpleNamespace(id=999, guild_permissions=_permissions())
        channel = _Channel(
            {
                moderator.id: _permissions(manage_channels=True),
                bot_member.id: _permissions(manage_channels=False),
            }
        )
        response = _Response()
        interaction = SimpleNamespace(
            user=moderator,
            guild=SimpleNamespace(id=10, owner_id=1, me=bot_member),
            guild_id=10,
            channel=channel,
            response=response,
        )

        allowed = await check_channel_perms(
            interaction,
            channel,
            user_permission="manage_channels",
            bot_permissions=("manage_channels",),
        )

        self.assertFalse(allowed)
        self.assertIn("No tengo", response.messages[0][0])

    def test_channel_overwrite_is_authoritative(self):
        member = SimpleNamespace(
            id=42,
            guild_permissions=_permissions(manage_channels=True),
        )
        channel = _Channel({member.id: _permissions(manage_channels=False)})
        guild = SimpleNamespace(owner_id=1)

        self.assertFalse(
            has_effective_channel_permission(guild, channel, member, "manage_channels")
        )


if __name__ == "__main__":
    unittest.main()
