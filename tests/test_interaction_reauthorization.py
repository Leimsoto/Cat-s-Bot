import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from cogs.embeds import EmbedBuilder, EmbedBuilderView, Embeds, SaveEmbedModal, SendChannelSelectView
from cogs.radio import RadioStationSelectView
from cogs.scheduler import ScheduleCreateModal
from cogs.serverutils import ServerLogsView
from cogs.suggestions import DenyReasonModal, Suggestions
from cogs.tags import TagCreateModal, TagDeleteView, TagEditModal


class _Response:
    def __init__(self):
        self.messages = []

    def is_done(self):
        return False

    async def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))

    async def edit_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))


def _member(user_id=1, *, admin=False, manage_messages=False, roles=()):
    return SimpleNamespace(
        id=user_id,
        roles=[SimpleNamespace(id=role_id) for role_id in roles],
        guild_permissions=SimpleNamespace(
            administrator=admin,
            manage_messages=manage_messages,
        ),
    )


def _interaction(*, guild_id=10, user=None):
    guild = SimpleNamespace(id=guild_id, owner_id=999)
    return SimpleNamespace(
        guild=guild,
        guild_id=guild_id,
        user=user or _member(),
        response=_Response(),
    )


class InteractionReauthorizationTest(unittest.IsolatedAsyncioTestCase):
    async def test_suggestion_review_rechecks_role_guild_and_pending_state(self):
        class DB:
            def __init__(self):
                self.row = {"id": 1, "guild_id": 10, "status": "PENDING"}
                self.updates = []

            def get_server_config(self, _guild_id):
                return {"mod_role_id": 7, "staff_role_id": None}

            def get_suggestion(self, _suggestion_id):
                return dict(self.row)

            def update_suggestion(self, suggestion_id, **kwargs):
                self.updates.append((suggestion_id, kwargs))

        db = DB()
        cog = Suggestions.__new__(Suggestions)
        cog.db = db

        revoked = _interaction(user=_member(roles=()))
        await cog.publish_suggestion(revoked, 1)
        await DenyReasonModal(cog, 1).on_submit(_interaction(user=_member(roles=())))
        self.assertEqual(db.updates, [])

        staff = _interaction(user=_member(roles=(7,)))
        db.row["guild_id"] = 11
        self.assertFalse(await cog._authorize_review(staff, 1))
        db.row.update(guild_id=10, status="ACCEPTED")
        self.assertFalse(await cog._authorize_review(staff, 1))
        db.row["status"] = "PENDING"
        self.assertTrue(await cog._authorize_review(staff, 1))

    async def test_schedule_modal_rechecks_admin_and_channel_guild(self):
        db = SimpleNamespace(create_schedule=Mock())
        cog = SimpleNamespace(db=db)
        guild = SimpleNamespace(id=10, owner_id=999)
        channel = SimpleNamespace(id=20, guild=guild)

        modal = ScheduleCreateModal(cog, channel)
        revoked = _interaction(user=_member(admin=False))
        await modal.on_submit(revoked)

        other_channel = SimpleNamespace(id=20, guild=SimpleNamespace(id=11))
        modal = ScheduleCreateModal(cog, other_channel)
        await modal.on_submit(_interaction(user=_member(admin=True)))

        db.create_schedule.assert_not_called()

    async def test_radio_station_view_rechecks_invoker_and_admin(self):
        view = RadioStationSelectView(author_id=1, guild_id=10)

        self.assertFalse(
            await view.interaction_check(_interaction(user=_member(user_id=2, admin=True)))
        )
        self.assertFalse(
            await view.interaction_check(_interaction(user=_member(user_id=1, admin=False)))
        )
        self.assertTrue(
            await view.interaction_check(_interaction(user=_member(user_id=1, admin=True)))
        )

    async def test_embed_save_and_send_recheck_current_permissions(self):
        db = SimpleNamespace(
            get_server_config=Mock(return_value={"embed_role_id": 7}),
            save_embed=Mock(),
        )
        cog = Embeds.__new__(Embeds)
        cog.db = db
        builder_view = EmbedBuilderView(cog, EmbedBuilder(), 1, 10)

        revoked = _interaction(user=_member(user_id=1, roles=()))
        await SaveEmbedModal(builder_view).on_submit(revoked)
        db.save_embed.assert_not_called()
        self.assertTrue(
            await builder_view.interaction_check(
                _interaction(user=_member(user_id=1, roles=(7,)))
            )
        )

        parent = SimpleNamespace(
            interaction_check=AsyncMock(return_value=True),
            builder=SimpleNamespace(build=Mock()),
        )
        channel = SimpleNamespace(
            id=20,
            permissions_for=Mock(
                return_value=SimpleNamespace(view_channel=True, send_messages=False)
            ),
            send=AsyncMock(),
        )
        interaction = _interaction(user=_member(user_id=1, roles=(7,)))
        interaction.guild.get_channel = Mock(return_value=channel)
        select = SimpleNamespace(values=[SimpleNamespace(id=20)])
        view = SendChannelSelectView(parent)

        await SendChannelSelectView.select_channel(view, interaction, select)

        channel.send.assert_not_awaited()
        parent.builder.build.assert_not_called()

    async def test_tag_modals_and_delete_recheck_manage_messages(self):
        db = SimpleNamespace(
            create_tag=Mock(),
            update_tag=Mock(),
            delete_tag=Mock(),
        )
        cog = SimpleNamespace(db=db)
        revoked = _interaction(user=_member(user_id=1, manage_messages=False))

        await TagCreateModal(cog).on_submit(revoked)
        await TagEditModal(cog, "faq", "old").on_submit(
            _interaction(user=_member(user_id=1, manage_messages=False))
        )
        view = TagDeleteView(cog, "faq", author_id=1)
        await TagDeleteView.confirm(
            view, _interaction(user=_member(user_id=1, manage_messages=False)), None
        )

        db.create_tag.assert_not_called()
        db.update_tag.assert_not_called()
        db.delete_tag.assert_not_called()

    async def test_server_logs_callback_rechecks_current_admin(self):
        db = SimpleNamespace(set_server_config=Mock())
        cog = SimpleNamespace(db=db)
        view = ServerLogsView(cog, author_id=1, guild_id=10, events={})
        interaction = _interaction(user=_member(user_id=1, admin=False))
        interaction.data = {"values": []}

        await view._toggle_callback(interaction)

        db.set_server_config.assert_not_called()
        self.assertTrue(
            await view.interaction_check(_interaction(user=_member(user_id=1, admin=True)))
        )


if __name__ == "__main__":
    unittest.main()
