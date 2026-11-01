import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cogs.tickets import TicketCloseReasonModal, TicketModal, TicketTakeCloseView, Tickets


class _DB:
    def __init__(self):
        self.categories = []
        self.ticket = None

    def get_ticket_config(self, _guild_id):
        return {"allowed_roles": "[5]", "immune_roles": "[]"}

    def get_ticket_categories(self, _guild_id):
        return list(self.categories)

    def get_ticket_by_channel(self, channel_id):
        if self.ticket and int(self.ticket["channel_id"]) == int(channel_id):
            return dict(self.ticket)
        return None

    def update_ticket(self, _ticket_id, **values):
        self.ticket.update(values)


def _member(guild, member_id, *, roles=(), admin=False):
    return SimpleNamespace(
        id=member_id,
        guild=guild,
        guild_permissions=SimpleNamespace(administrator=admin),
        roles=[SimpleNamespace(id=role_id) for role_id in roles],
        display_name=f"member-{member_id}",
        mention=f"<@{member_id}>",
    )


def _interaction(guild, member, channel):
    return SimpleNamespace(
        guild=guild,
        guild_id=guild.id,
        user=member,
        channel=channel,
        response=SimpleNamespace(
            send_message=AsyncMock(),
            edit_message=AsyncMock(),
            defer=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
    )


class TicketAuthorizationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = SimpleNamespace(id=10, owner_id=99, get_role=lambda _id: None)
        self.db = _DB()
        self.cog = Tickets.__new__(Tickets)
        self.cog.db = self.db
        self.cog.bot = SimpleNamespace(db=self.db)

    def test_old_claim_is_not_staff_authority(self):
        ticket = {"staff_id": 42, "category_name": "General"}
        claimed = _member(self.guild, 42)
        current_staff = _member(self.guild, 43, roles=(5,))

        self.assertFalse(self.cog._is_ticket_staff(claimed, ticket))
        self.assertTrue(self.cog._is_ticket_staff(current_staff, ticket))

    async def test_claim_does_not_add_member_overwrite(self):
        self.db.ticket = {
            "id": 1,
            "guild_id": self.guild.id,
            "channel_id": 20,
            "staff_id": None,
            "status": "OPEN",
            "category_name": "General",
        }
        channel = SimpleNamespace(id=20, edit=AsyncMock())
        interaction = _interaction(self.guild, _member(self.guild, 42, roles=(5,)), channel)
        view = TicketTakeCloseView(self.cog, 1)

        await view.children[0].callback(interaction)

        self.assertEqual(self.db.ticket["staff_id"], 42)
        channel.edit.assert_not_awaited()

    async def test_close_modal_rejects_revoked_claim(self):
        self.db.ticket = {
            "id": 1,
            "guild_id": self.guild.id,
            "channel_id": 20,
            "staff_id": 42,
            "status": "OPEN",
            "category_name": "General",
        }
        channel = SimpleNamespace(id=20)
        interaction = _interaction(self.guild, _member(self.guild, 42), channel)
        self.cog.close_ticket = AsyncMock(return_value=True)
        modal = TicketCloseReasonModal(self.cog, self.db.ticket, channel)
        modal.reason._value = "done"

        await modal.on_submit(interaction)

        self.cog.close_ticket.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()

    async def test_ticket_modal_refetches_category_and_fails_if_removed(self):
        old = {"id": 7, "name": "Old", "questions": "[]"}
        modal = TicketModal(self.cog, old)
        interaction = _interaction(self.guild, _member(self.guild, 42), SimpleNamespace(id=20))
        self.cog.create_ticket_channel = AsyncMock()

        await modal.on_submit(interaction)

        self.cog.create_ticket_channel.assert_not_awaited()
        interaction.response.defer.assert_not_awaited()

        fresh = {"id": 7, "name": "Fresh", "questions": "[]"}
        self.db.categories = [fresh]
        await modal.on_submit(interaction)

        self.cog.create_ticket_channel.assert_awaited_once()
        self.assertIs(self.cog.create_ticket_channel.await_args.args[1], fresh)


if __name__ == "__main__":
    unittest.main()
