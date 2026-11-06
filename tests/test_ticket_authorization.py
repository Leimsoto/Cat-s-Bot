import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

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
        self.cog._staff_config_locks = {}

    def test_old_claim_is_not_staff_authority(self):
        ticket = {"staff_id": 42, "category_name": "General"}
        claimed = _member(self.guild, 42)
        current_staff = _member(self.guild, 43, roles=(5,))

        self.assertFalse(self.cog._is_ticket_staff(claimed, ticket))
        self.assertTrue(self.cog._is_ticket_staff(current_staff, ticket))

    def test_any_category_support_role_can_claim_but_other_members_cannot(self):
        self.db.categories = [{"name": "General", "staff_role_ids": '["6", "7"]'}]
        ticket = {"category_name": "General"}
        for role_id in (6, 7):
            self.assertTrue(self.cog._is_ticket_staff(_member(self.guild, 42, roles=(role_id,)), ticket))
        self.assertFalse(self.cog._is_ticket_staff(_member(self.guild, 42, roles=(8,)), ticket))
        self.assertFalse(self.cog._is_ticket_staff(_member(self.guild, 42), ticket))
        self.assertTrue(self.cog._is_ticket_staff(_member(self.guild, 42, admin=True), ticket))

    def test_category_support_roles_keep_legacy_and_empty_list_clears_it(self):
        category = {"staff_role_id": 6}
        self.assertIn(6, self.cog._ticket_staff_role_ids(self.guild.id, category))
        category["staff_role_ids"] = "[]"
        self.assertNotIn(6, self.cog._ticket_staff_role_ids(self.guild.id, category))

    def test_everyone_cannot_become_ticket_staff_from_legacy_configuration(self):
        category = {"staff_role_id": self.guild.id}
        self.assertNotIn(self.guild.id, self.cog._ticket_staff_role_ids(self.guild.id, category))

    async def test_sync_updates_open_tickets_preserves_other_overwrites_and_retries(self):
        roles = {ident: discord.Object(ident) for ident in (5, 6, 7, 8, 9)}
        member = discord.Object(42)
        class Channel:
            @property
            def overwrites(channel):
                return dict(channel._overwrites)

            @overwrites.setter
            def overwrites(channel, values):
                channel._overwrites = values

            def __init__(channel, ident):
                channel.id = ident
                channel.guild = self.guild
                channel.overwrites = {
                    roles[6]: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
                    roles[9]: discord.PermissionOverwrite(view_channel=True),
                    member: discord.PermissionOverwrite(view_channel=True, attach_files=True),
                }
                channel.fail = False
                channel.edit = AsyncMock(side_effect=channel.apply)

            async def apply(channel, *, overwrites, reason):
                if channel.fail:
                    raise RuntimeError("Discord denied")
                channel.overwrites = overwrites

            def overwrites_for(channel, role):
                current = channel.overwrites.get(role, discord.PermissionOverwrite())
                return discord.PermissionOverwrite.from_pair(*current.pair())

        channels = {ident: Channel(ident) for ident in (20, 21)}
        self.guild.get_role = roles.get
        self.guild.get_channel = channels.get
        self.db.count_open_tickets_by_guild = lambda _guild_id: len(channels)
        self.db.get_all_tickets = lambda _guild_id, **_kwargs: [
            {"channel_id": ident, "category_name": "General"} for ident in channels
        ]
        previous = [{"id": 1, "name": "General", "staff_role_id": 6}]
        desired = [{"id": 1, "name": "Technical", "staff_role_ids": '["7", "8"]'}]
        config = self.db.get_ticket_config(10)
        channels[21].fail = True
        with self.assertRaises(RuntimeError):
            await self.cog.sync_staff_permissions(self.guild, config, config, previous, desired, grant=False)
        self.assertFalse(channels[20].overwrites[roles[6]].view_channel)
        self.assertTrue(channels[20].overwrites[roles[6]].attach_files)
        self.assertNotIn(roles[7], channels[20].overwrites)
        channels[21].fail = False
        await self.cog.sync_staff_permissions(self.guild, config, config, previous, desired, grant=False)
        self.db.categories = desired
        self.db.get_all_tickets = lambda _guild_id, **_kwargs: [
            {"channel_id": ident, "category_name": "Technical"} for ident in channels
        ]
        await self.cog.sync_staff_permissions(self.guild, config, config, previous, desired)
        for channel in channels.values():
            for ident in (5, 7, 8):
                self.assertTrue(channel.overwrites[roles[ident]].view_channel)
                self.assertTrue(channel.overwrites[roles[ident]].send_messages)
            self.assertFalse(channel.overwrites[roles[6]].view_channel)
            self.assertTrue(channel.overwrites[roles[9]].view_channel)
            self.assertTrue(channel.overwrites[member].attach_files)
        edits = [channel.edit.await_count for channel in channels.values()]
        await self.cog.sync_staff_permissions(self.guild, config, config, desired, desired)
        self.assertEqual([channel.edit.await_count for channel in channels.values()], edits)

    async def test_role_save_waits_for_creating_ticket_through_commit(self):
        previous = [{"id": 1, "name": "General", "staff_role_id": 6}]
        desired = [{"id": 1, "name": "General", "staff_role_ids": '["7"]'}]
        self.db.categories = previous
        started, finish = asyncio.Event(), asyncio.Event()
        async def create(*_args, **_kwargs):
            started.set()
            await finish.wait()
        self.cog._create_ticket_channel = AsyncMock(side_effect=create)
        self.cog.sync_staff_permissions = AsyncMock()
        interaction = _interaction(self.guild, _member(self.guild, 42), SimpleNamespace(id=20))
        creation = asyncio.create_task(self.cog.create_ticket_channel(interaction, previous[0], []))
        await started.wait()
        config = self.db.get_ticket_config(10)
        saving = asyncio.create_task(self.cog.apply_staff_configuration(
            self.guild, config, config, previous, desired, lambda: setattr(self.db, "categories", desired),
        ))
        await asyncio.sleep(0)
        self.cog.sync_staff_permissions.assert_not_awaited()
        finish.set()
        await creation
        await saving
        self.assertEqual(self.db.categories, desired)

    async def test_queued_creation_refetches_category_after_roles_change(self):
        old = {"id": 1, "name": "General", "staff_role_id": 6}
        fresh = {"id": 1, "name": "Technical", "staff_role_ids": '["7"]'}
        self.db.categories = [old]
        self.cog._create_ticket_channel = AsyncMock()
        interaction = _interaction(self.guild, _member(self.guild, 42), SimpleNamespace(id=20))
        lock = self.cog._staff_config_lock(10)
        async with lock:
            creation = asyncio.create_task(self.cog.create_ticket_channel(interaction, old, []))
            await asyncio.sleep(0)
            self.db.categories = [fresh]
        await creation
        self.assertIs(self.cog._create_ticket_channel.await_args.args[1], fresh)

    async def test_concurrent_role_saves_reject_stale_snapshot(self):
        previous = [{"id": 1, "name": "General", "staff_role_id": 6}]
        desired = [{"id": 1, "name": "General", "staff_role_ids": '["7"]'}]
        self.db.categories = previous
        entered, finish = asyncio.Event(), asyncio.Event()
        async def sync(*_args, **_kwargs):
            entered.set()
            await finish.wait()
        self.cog.sync_staff_permissions = AsyncMock(side_effect=sync)
        config = self.db.get_ticket_config(10)
        saving = asyncio.create_task(self.cog.apply_staff_configuration(
            self.guild, config, config, previous, desired, lambda: setattr(self.db, "categories", desired),
        ))
        await entered.wait()
        second = asyncio.create_task(self.cog.apply_staff_configuration(
            self.guild, config, config, previous, previous, lambda: self.fail("Stale save committed"),
        ))
        finish.set()
        await saving
        with self.assertRaises(RuntimeError):
            await second
        self.assertEqual(self.cog.sync_staff_permissions.await_count, 2)

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
