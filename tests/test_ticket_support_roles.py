import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from fastapi import HTTPException

from api.routes.guild import get_tickets_config, patch_tickets_config, _ticket_category_role_updates
from api.routes.tickets import TicketCategoryPatch, patch_category
from cogs._role_safety import self_service_forbidden_role_ids
from cogs.tickets import Tickets
from tests.test_snowflake_api_serialization import make_db


class TicketSupportRolesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = make_db()
        self.db.add_ticket_category(10, "Support", "", "[]", "[]", staff_role_id=6)
        self.category_id = self.db.get_ticket_categories(10)[0]["id"]
        self.guild = SimpleNamespace(id=10)
        self.bot = SimpleNamespace(db=self.db, loop=asyncio.get_running_loop(), get_guild=lambda _: self.guild)
        self.cog = Tickets(self.bot)
        self.bot.get_cog = lambda _: self.cog

    async def asyncTearDown(self):
        self.db._sqlite_conn.close()

    async def update_category(self, **values):
        return await patch_category(
            10, self.category_id, TicketCategoryPatch(**values), request=None,
            db=self.db, bot=self.bot, user={"user_id": 99},
        )

    async def test_multiple_roles_round_trip_with_exact_ids_and_legacy_replacement(self):
        large_id = "1523702726393860373"
        ticket = self.db.create_ticket(10, 42, "Support")
        with patch("api.routes.guild._authorize_delegated_role_updates", new=AsyncMock()) as authorize:
            await self.update_category(name="Technical", staff_role_ids=[large_id, "7", "7"])
            self.assertEqual(authorize.await_args.args[2], {"staff_role_ids": [7, int(large_id)]})
        loaded = await get_tickets_config(10, self.db, {})
        category = loaded["categories"][0]
        self.assertEqual(category["staff_role_ids"], ["7", large_id])
        self.assertIsNone(category["staff_role_id"])
        self.assertEqual(self.db.get_ticket(ticket["id"])["category_name"], "Technical")
        self.assertTrue({7, int(large_id)} <= self_service_forbidden_role_ids(self.db, 10))
        self.assertNotIn(6, self_service_forbidden_role_ids(self.db, 10))
        with patch("api.routes.guild._authorize_delegated_role_updates", new=AsyncMock()):
            await self.update_category(staff_role_ids=[])
        self.assertEqual((await get_tickets_config(10, self.db, {}))["categories"][0]["staff_role_ids"], [])

    async def test_singular_client_remains_compatible_and_null_revokes(self):
        self.assertEqual((await get_tickets_config(10, self.db, {}))["categories"][0]["staff_role_ids"], ["6"])
        with patch("api.routes.guild._authorize_delegated_role_updates", new=AsyncMock()):
            await self.update_category(staff_role_id="8")
            self.assertEqual((await get_tickets_config(10, self.db, {}))["categories"][0]["staff_role_ids"], ["8"])
            await self.update_category(staff_role_id=None)
        self.assertEqual((await get_tickets_config(10, self.db, {}))["categories"][0]["staff_role_ids"], [])

    async def test_delegation_rejection_and_invalid_list_do_not_write(self):
        with patch("api.routes.guild._authorize_delegated_role_updates", new=AsyncMock(side_effect=HTTPException(403, "denied"))):
            with self.assertRaises(HTTPException):
                await self.update_category(staff_role_ids=["7"])
        self.assertEqual(self.db.get_ticket_categories(10)[0]["staff_role_id"], 6)
        with self.assertRaises(HTTPException):
            await _ticket_category_role_updates(None, 10, {"staff_role_ids": ["invalid"]}, {}, None, {})

    async def test_global_roles_preserve_precision_on_save_and_reload(self):
        large_id = "1523702726393860373"
        with patch("api.routes.guild._authorize_delegated_role_updates", new=AsyncMock()):
            await patch_tickets_config(10, {"allowed_roles": [large_id, "7"]}, request=None, db=self.db, bot=self.bot, user={})
        loaded = await get_tickets_config(10, self.db, {})
        self.assertEqual(json.loads(loaded["config"]["allowed_roles"]), [large_id, "7"])

    async def test_closing_a_ticket_during_revocation_does_not_skip_later_open_tickets(self):
        role = discord.Object(id=6)
        channels = {}
        tickets = []
        for index in range(101):
            ticket = self.db.create_ticket(10, 42, "Support")
            channel_id = 1000 + index
            self.db.update_ticket(ticket["id"], channel_id=channel_id, status="OPEN")
            channel = SimpleNamespace(id=channel_id, guild=self.guild,
                overwrites={role: discord.PermissionOverwrite(view_channel=True, send_messages=True)})
            channel.overwrites_for = lambda value, current=channel: current.overwrites[value]

            async def edit(*, overwrites, reason, current=channel):
                current.overwrites = overwrites
                if not closed:
                    closed.append(tickets[-1]["id"])
                    self.db.update_ticket(closed[0], status="CLOSED")

            channel.edit = AsyncMock(side_effect=edit)
            channels[channel_id] = channel
            tickets.append({**ticket, "channel_id": channel_id})
        closed = []
        self.guild.get_role = lambda ident: role if ident == role.id else None
        self.guild.get_channel = channels.get
        with patch("api.routes.guild._authorize_delegated_role_updates", new=AsyncMock()):
            await self.update_category(staff_role_ids=[])
        self.assertEqual(json.loads(self.db.get_ticket_categories(10)[0]["staff_role_ids"]), [])
        self.assertEqual(self.db.get_ticket(tickets[0]["id"])["status"], "OPEN")
        for ticket in tickets:
            if self.db.get_ticket(ticket["id"])["status"] == "OPEN":
                self.assertIs(channels[ticket["channel_id"]].overwrites_for(role).view_channel, False)
                self.assertIs(channels[ticket["channel_id"]].overwrites_for(role).send_messages, False)

    async def test_sync_failure_keeps_previous_roles_for_retry(self):
        self.db.count_open_tickets_by_guild = lambda _: 1
        cog = SimpleNamespace(apply_staff_configuration=AsyncMock(side_effect=RuntimeError("Discord denied")))
        bot = SimpleNamespace(get_guild=lambda _: SimpleNamespace(id=10), get_cog=lambda _: cog)
        async def bridge(_bot, factory, **_kwargs):
            return await factory()
        with patch("api.routes.guild._authorize_delegated_role_updates", new=AsyncMock()), patch("api.routes.guild.run_on_bot_loop", new=bridge):
            for attempt in range(2):
                if attempt:
                    async def apply(*args):
                        args[-1]()
                    cog.apply_staff_configuration.side_effect = apply
                try:
                    await patch_category(10, self.category_id, TicketCategoryPatch(staff_role_ids=["7"]), request=None, db=self.db, bot=bot, user={})
                except HTTPException as exc:
                    self.assertEqual(exc.status_code, 409)
                    self.assertEqual(self.db.get_ticket_categories(10)[0]["staff_role_id"], 6)
                else:
                    self.assertEqual(attempt, 1)
            self.assertEqual(cog.apply_staff_configuration.await_count, 2)
            self.assertEqual(cog.apply_staff_configuration.await_args.args[3][0]["staff_role_id"], 6)
            self.assertEqual(json.loads(self.db.get_ticket_categories(10)[0]["staff_role_ids"]), ["7"])

    async def test_name_only_edit_waits_for_role_save_and_retries_stale_snapshot(self):
        ticket = self.db.create_ticket(10, 42, "Support")
        entered, finish = asyncio.Event(), asyncio.Event()
        async def sync(*_args, grant):
            if not grant and not entered.is_set():
                entered.set()
                await finish.wait()
        self.cog.sync_staff_permissions = AsyncMock(side_effect=sync)
        with patch("api.routes.guild._authorize_delegated_role_updates", new=AsyncMock()):
            saving = asyncio.create_task(self.update_category(staff_role_ids=["7"]))
            await entered.wait()
            renaming = asyncio.create_task(self.update_category(name="Technical"))
            await asyncio.sleep(0)
            try:
                self.assertEqual(self.db.get_ticket_categories(10)[0]["name"], "Support")
            finally:
                finish.set()
                await saving
            with self.assertRaises(HTTPException) as raised:
                await renaming
            self.assertEqual(raised.exception.status_code, 409)
            await self.update_category(name="Technical")
        category = self.db.get_ticket_categories(10)[0]
        self.assertEqual(category["name"], "Technical")
        self.assertEqual(json.loads(category["staff_role_ids"]), ["7"])
        self.assertEqual(self.db.get_ticket(ticket["id"])["category_name"], "Technical")

    async def test_failed_grant_keeps_roles_protected_and_same_payload_retries(self):
        phases = []
        fail_grant = True
        async def sync(_guild, _old_config, _new_config, _old_categories, _new_categories, *, grant):
            nonlocal fail_grant
            phases.append(grant)
            forbidden = self_service_forbidden_role_ids(self.db, 10)
            if len(phases) == 1:
                self.assertIn(6, forbidden)
                self.assertNotIn(7, forbidden)
            if grant:
                self.assertIn(7, forbidden)
                self.assertNotIn(6, forbidden)
                if fail_grant:
                    fail_grant = False
                    raise RuntimeError("grant denied")
        self.cog.sync_staff_permissions = AsyncMock(side_effect=sync)
        with patch("api.routes.guild._authorize_delegated_role_updates", new=AsyncMock()) as authorize:
            with self.assertRaises(HTTPException) as raised:
                await self.update_category(staff_role_ids=["7"])
            self.assertIn("se guardó", raised.exception.detail)
            self.assertEqual(json.loads(self.db.get_ticket_categories(10)[0]["staff_role_ids"]), ["7"])
            await self.update_category(staff_role_ids=["7"])
            authorize.assert_awaited_once()
        self.assertEqual(phases, [False, True,False,True])
