import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from cogs._role_safety import safe_for_automatic_assignment
from cogs.autoroles import AutoRoles
from cogs.custom_commands import _user_can_use
from cogs.moderation import (
    Moderation,
    _appeal_staff_allowed,
    _pending_appeal,
)
from cogs.rag_scraper import RAGScraper
from cogs.users import Users
from cogs.utilities import Utilities


class _Response:
    def __init__(self):
        self.messages = []

    async def send_message(self, content=None, **kwargs):
        self.messages.append((content, kwargs))


class _Member:
    def __init__(self, member_id=10, *, roles=(), **permissions):
        self.id = member_id
        self.roles = list(roles)
        defaults = {
            "administrator": False,
            "manage_guild": False,
            "manage_roles": False,
            "manage_channels": False,
        }
        defaults.update(permissions)
        self.guild_permissions = SimpleNamespace(**defaults)


class _Role:
    def __init__(self, role_id=20, *, position=1, managed=False, **permissions):
        self.id = role_id
        self.position = position
        self.managed = managed
        self.permissions = SimpleNamespace(**permissions)

    def is_default(self):
        return False

    def __ge__(self, other):
        return self.position >= other.position


class PermissionSecurityRegressionTest(unittest.IsolatedAsyncioTestCase):
    def test_restricted_custom_commands_fail_closed(self):
        member = SimpleNamespace(
            guild_permissions=SimpleNamespace(administrator=False), roles=[]
        )
        self.assertFalse(_user_can_use(member, "not-json"))
        self.assertFalse(
            _user_can_use(member, '{"everyone": false, "role_ids": []}')
        )

    def test_automatic_roles_reject_moderation_permissions(self):
        bot_member = SimpleNamespace(top_role=_Role(position=100))
        safe = _Role(position=10, administrator=False, manage_messages=False)
        privileged = _Role(position=10, administrator=False, manage_messages=True)
        self.assertTrue(safe_for_automatic_assignment(safe, bot_member))
        self.assertFalse(safe_for_automatic_assignment(privileged, bot_member))

        channel_privileged = _Role(position=10, administrator=False)
        channel_privileged.guild = SimpleNamespace(
            channels=[
                SimpleNamespace(
                    permissions_for=lambda _role: SimpleNamespace(manage_threads=True)
                )
            ]
        )
        self.assertFalse(
            safe_for_automatic_assignment(channel_privileged, bot_member)
        )

    def test_starboard_does_not_widen_channel_audience(self):
        member = object()
        source = SimpleNamespace(
            permissions_for=lambda _member: SimpleNamespace(view_channel=False)
        )
        destination = SimpleNamespace(
            permissions_for=lambda _member: SimpleNamespace(view_channel=True)
        )
        empty_role = object()
        guild = SimpleNamespace(
            default_role=object(), roles=[empty_role], members=[member]
        )
        self.assertFalse(
            Utilities._starboard_preserves_audience(guild, source, destination)
        )

    async def test_forceban_rechecks_present_member_hierarchy(self):
        target = object()
        guild = SimpleNamespace(
            get_member=lambda _user_id: target,
            fetch_member=AsyncMock(),
            ban=AsyncMock(),
        )
        interaction = SimpleNamespace(
            user=object(), guild=guild, response=_Response()
        )
        cog = Moderation.__new__(Moderation)
        cog.bot = SimpleNamespace(catbot_voice=None)
        cog._has_mod_perms = lambda *_args: True
        cog._can_moderate = lambda *_args: "jerarquía denegada"

        await Moderation.forceban.callback(cog, interaction, "20")

        guild.ban.assert_not_awaited()
        self.assertIn("jerarquía denegada", interaction.response.messages[0][0])

    async def test_custom_emoji_autorole_is_bound_to_exact_id(self):
        class _Emoji:
            name = "member"

            def __str__(self):
                return "<:member:999>"

        db = SimpleNamespace(
            get_autorole=lambda _message_id: {
                "guild_id": 1,
                "channel_id": 2,
                "mapping_data": '{"<:member:123>": 50, "member": 50}',
            }
        )
        bot = SimpleNamespace(
            user=SimpleNamespace(id=9999),
            db=db,
            get_guild=Mock(),
        )
        cog = AutoRoles(bot)
        payload = SimpleNamespace(
            user_id=10,
            message_id=20,
            guild_id=1,
            channel_id=2,
            emoji=_Emoji(),
        )

        await cog._handle_reaction(payload, add=True)

        bot.get_guild.assert_not_called()

    async def test_unmute_rechecks_target_hierarchy(self):
        cog = Moderation.__new__(Moderation)
        cog.bot = SimpleNamespace(catbot_voice=None)
        cog._has_mod_perms = lambda *_args: True
        cog._can_moderate = lambda *_args: "jerarquía denegada"
        cog._ensure_mute_role = AsyncMock()
        interaction = SimpleNamespace(
            user=object(), guild=object(), response=_Response()
        )

        await Moderation.unmute.callback(cog, interaction, object())

        cog._ensure_mute_role.assert_not_awaited()
        self.assertIn("jerarquía denegada", interaction.response.messages[0][0])

    async def test_clearwarns_does_not_treat_configured_mod_as_admin(self):
        actor = _Member(10)
        interaction = SimpleNamespace(
            user=actor,
            guild=SimpleNamespace(owner_id=99),
            response=_Response(),
        )
        cog = Moderation.__new__(Moderation)
        cog.bot = SimpleNamespace(catbot_voice=None)
        cog.db = SimpleNamespace(get_user=AsyncMock())

        with patch("cogs.moderation.discord.Member", _Member):
            await Moderation.clearwarns.callback(cog, interaction, object())

        self.assertIn("Administrador", interaction.response.messages[0][0])

    def test_mute_role_setup_needs_role_and_channel_authority(self):
        role = _Role(
            position=10,
            administrator=False,
            manage_guild=False,
            manage_roles=False,
            manage_channels=False,
            ban_members=False,
            kick_members=False,
            moderate_members=False,
        )
        guild = SimpleNamespace(owner_id=99)
        actor = _Member(10, manage_guild=True)
        actor.top_role = _Role(position=50)
        interaction = SimpleNamespace(user=actor, guild=guild)
        cog = Moderation.__new__(Moderation)

        with patch("cogs.moderation.discord.Member", _Member):
            self.assertFalse(cog._can_configure_mute_role(interaction, role))
            actor.guild_permissions.manage_roles = True
            actor.guild_permissions.manage_channels = True
            self.assertTrue(cog._can_configure_mute_role(interaction, role))

    def test_delegated_users_role_cannot_manage_privileged_roles(self):
        actor = _Member(10)
        actor.top_role = _Role(position=50)
        target = _Member(20)
        target.top_role = _Role(position=5)
        privileged = _Role(
            position=10,
            administrator=False,
            manage_guild=False,
            manage_roles=True,
            manage_channels=False,
            manage_webhooks=False,
            manage_messages=False,
            kick_members=False,
            ban_members=False,
            moderate_members=False,
            mute_members=False,
            deafen_members=False,
            move_members=False,
        )
        bot_member = SimpleNamespace(id=999, top_role=_Role(position=100))
        guild = SimpleNamespace(
            owner_id=99,
            default_role=object(),
            me=bot_member,
            get_member=lambda _member_id: bot_member,
        )
        interaction = SimpleNamespace(user=actor, guild=guild)
        cog = Users.__new__(Users)
        cog.bot = SimpleNamespace(user=SimpleNamespace(id=999))

        with patch("cogs.users.discord.Member", _Member):
            error = cog._validate_role_action(interaction, target, privileged)

        self.assertIn("administrativos", error)

    def test_appeals_require_current_staff_and_pending_guild_binding(self):
        staff_role = SimpleNamespace(id=55)
        actor = _Member(10, roles=[staff_role])
        interaction = SimpleNamespace(
            user=actor, guild=SimpleNamespace(id=7, owner_id=99), guild_id=7
        )
        db = SimpleNamespace(
            get_server_config=lambda _guild_id: {"staff_role_id": 55},
            get_config=lambda _guild_id: {},
            get_appeal=lambda _appeal_id: {
                "id": 1,
                "guild_id": 7,
                "user_id": 20,
                "action_type": "BAN",
                "status": "PENDING",
            },
        )
        bot = SimpleNamespace(db=db)

        with patch("cogs.moderation.discord.Member", _Member):
            self.assertTrue(_appeal_staff_allowed(bot, interaction))
        self.assertIsNotNone(_pending_appeal(bot, interaction, 1))
        db.get_appeal = lambda _appeal_id: {
            "guild_id": 8,
            "status": "PENDING",
        }
        self.assertIsNone(_pending_appeal(bot, interaction, 1))

    def test_rag_runtime_checks_current_permission(self):
        actor = _Member(10, manage_guild=True)
        interaction = SimpleNamespace(
            user=actor, guild=SimpleNamespace(owner_id=99)
        )
        with patch("cogs.rag_scraper.discord.Member", _Member):
            self.assertTrue(RAGScraper._authorized(interaction))
            self.assertFalse(RAGScraper._authorized(interaction, admin_only=True))


if __name__ == "__main__":
    unittest.main()
