import asyncio
import json
import logging
import sqlite3
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from fastapi import HTTPException

from api.routes.guild import get_ai_message_settings, patch_ai_message_settings
from cogs._managed_messages import manage_payload, render_managed_message_payload, send_managed
from cogs.tickets import Tickets
from cogs.welcomes import Welcomes
from database.manager import DatabaseManager


def make_db():
    db = DatabaseManager.__new__(DatabaseManager)
    db.db_type = "sqlite"
    db._sqlite_lock = threading.Lock()
    db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
    db._sqlite_conn.row_factory = sqlite3.Row
    db._sqlite_conn.execute("PRAGMA foreign_keys = ON")
    logger = logging.getLogger("Database")
    previous = logger.disabled
    logger.disabled = True
    try:
        db._init_schema()
    finally:
        logger.disabled = previous
    return db


class ManagedMessagesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = make_db()
        self.bot = SimpleNamespace(db=self.db)
        self.db.set_automod_config(1, rules={"llm": {
            "enabled": False, "endpoint_url": "https://example.com/v1", "model": "test-model"
        }})

    def tearDown(self):
        self.db._sqlite_conn.close()

    async def test_default_and_template_false_never_request_model(self):
        self.db.set_server_config(1, ai_message_categories=json.dumps({"welcomes": True}))
        with patch("cogs._managed_messages.request_completion", new_callable=AsyncMock) as request:
            payload = await render_managed_message_payload(self.bot, 1, {"content": "Hola", "enabled": False})
            self.assertEqual(payload, {"content": "Hola", "embed": None})
            await manage_payload(self.bot, 1, payload, category="tickets")
            request.assert_not_awaited()

    async def test_opt_in_works_without_chat_or_moderation_enabled_and_preserves_facts(self):
        self.db.set_ai_config(1, ai_system_prompt="Tono felino y amable", ai_enabled=0)
        suffix = "\nREGLA_FINAL_COMPLETA"
        rules = "R" * (12000 - len(suffix)) + suffix
        self.db.set_automod_config(1, rules={"llm": {"rules_text": rules}})
        captured = []
        async def complete(session, cfg, messages):
            captured.append((cfg, messages))
            values = json.loads(messages[1]["content"])
            return json.dumps([text.replace("Hola", "¡Bienvenido!").replace("Disfruta", "Pásalo bien") for text in values])
        raw = {"ai_managed": True, "content": "Hola {user}, eres el miembro 42 de {server}.", "embed": {
            "title": "Hecho inmutable", "description": "Disfruta https://example.com/info",
            "fields": [{"name": "ID", "value": "123"}], "footer": "Pie fijo", "image": "https://example.com/picture.png",
        }}
        with patch("cogs._managed_messages.request_completion", side_effect=complete):
            payload = await render_managed_message_payload(self.bot, 1, raw, {"user": "<@123>", "server": "Mi servidor"})
        self.assertIn("¡Bienvenido! <@123>", payload["content"])
        self.assertIn("42 de Mi servidor", payload["content"])
        self.assertEqual(payload["embed"].description, "Pásalo bien https://example.com/info")
        self.assertEqual(payload["embed"].fields[0].value, "123")
        self.assertEqual(payload["embed"].title, "Hecho inmutable")
        self.assertEqual(payload["embed"].footer.text, "Pie fijo")
        self.assertEqual(payload["embed"].image.url, "https://example.com/picture.png")
        self.assertFalse(captured[0][0]["enabled"])
        self.assertIn("Tono felino y amable", captured[0][1][0]["content"])
        self.assertTrue(captured[0][1][0]["content"].endswith(rules))

    async def test_malformed_invented_facts_mentions_sanctions_and_token_reorder_fall_back(self):
        payload = {"content": "Hola <@123>, tienes 42 puntos", "embed": None}
        answers = ["not JSON", '["Hola @everyone"]', '["Hola 99"]', '["baneado"]',
                   '["Hola ⟦1⟧, tienes ⟦0⟧ puntos"]', '["Hola ⟦0⟧, tienes ⟦1⟧ puntos https://evil.example"]']
        for answer in answers:
            with self.subTest(answer=answer), patch("cogs._managed_messages.request_completion", AsyncMock(return_value=answer)):
                self.assertIs(await manage_payload(self.bot, 1, payload, enabled=True), payload)

    async def test_endpoint_failure_and_missing_configuration_fall_back(self):
        payload = {"content": "Hola", "embed": None}
        with patch("cogs._managed_messages.request_completion", AsyncMock(side_effect=TimeoutError)):
            self.assertIs(await manage_payload(self.bot, 1, payload, enabled=True), payload)
        self.db.set_automod_config(1, rules={"llm": {"endpoint_url": "", "model": ""}})
        with patch("cogs._managed_messages.request_completion", new_callable=AsyncMock) as request:
            self.assertEqual(await manage_payload(self.bot, 1, payload, enabled=True), payload)
            request.assert_not_awaited()

    async def test_sanction_statement_and_factual_embed_fields_are_never_rewritten(self):
        embed = discord.Embed(description="<@123> fue silenciado durante cinco minutos.")
        embed.add_field(name="Motivo", value="Texto original")
        payload = {"content": "Ban aplicado por 10 minutos.", "embed": embed}
        with patch("cogs._managed_messages.request_completion", new_callable=AsyncMock) as request:
            self.assertIs(await manage_payload(self.bot, 1, payload, enabled=True), payload)
            request.assert_not_awaited()

    async def test_deletion_and_timeout_statements_keep_reason_rule_and_negation_exact(self):
        for description in ("<@123> tu mensaje fue eliminado. Motivo: spam. Regla: enlaces.",
                            "<@123> fue aislado durante cinco minutos. Motivo: spam.",
                            "El mensaje no fue borrado porque la acción falló."):
            payload = {"embed": discord.Embed(description=description)}
            with self.subTest(description=description), patch("cogs._managed_messages.request_completion", new_callable=AsyncMock) as request:
                self.assertIs(await manage_payload(self.bot, 1, payload, enabled=True), payload)
                request.assert_not_awaited()

    async def test_reserved_marker_in_template_or_variable_falls_back_before_model(self):
        with patch("cogs._managed_messages.request_completion", new_callable=AsyncMock) as request:
            for raw, variables in (({"ai_managed": True, "content": "Hola ⟦0⟧"}, {}),
                                   ({"ai_managed": True, "content": "Hola {user}"}, {"user": "user ⟦1⟧"})):
                payload = await render_managed_message_payload(self.bot, 1, raw, variables)
                self.assertIn("⟦", payload["content"])
            request.assert_not_awaited()

    async def test_original_escaped_mentions_keep_their_escape_after_template_substitution(self):
        raw = {"ai_managed": True, "content": r"Hola \{user} y \@everyone"}
        with patch("cogs._managed_messages.request_completion", AsyncMock(return_value='["Buenas ⟦0⟧ y ⟦1⟧"]')):
            payload = await render_managed_message_payload(self.bot, 1, raw, {"user": "<@123>"})
        self.assertEqual(payload["content"], r"Buenas \<@123> y \@everyone")

    async def test_welcome_path_honors_individual_opt_in_and_retains_inviter_fact(self):
        class Channel:
            send = AsyncMock()
        channel = Channel()
        guild = SimpleNamespace(id=1, name="Servidor", member_count=42, get_channel=lambda _: channel)
        member = SimpleNamespace(guild=guild, mention="<@123>", display_name="Miembro")
        inviter = SimpleNamespace(mention="<@456>")
        cog = Welcomes(self.bot)
        for managed in (False, True):
            self.db.set_welcome_config(1, enabled=1, channel_id=50, embed_data=json.dumps({
                "ai_managed": managed, "content": "Hola {user}", "embed": {"description": "Disfruta"}
            }))
            with patch("cogs.welcomes.discord.TextChannel", Channel), patch("cogs._managed_messages.request_completion",
                    AsyncMock(return_value='["Buenas ⟦0⟧", "Pásalo bien"]')) as request:
                await cog._send_welcome(member, inviter)
            self.assertEqual(request.await_count, int(managed))
            self.assertIn("<@456>", channel.send.await_args.kwargs["embed"].description)
            self.assertIn("<@123>", channel.send.await_args.kwargs["content"])

    async def test_ticket_panel_accepts_nested_editor_text_only_without_losing_view(self):
        class Channel:
            send = AsyncMock()
        channel = Channel()
        config = {"panel_embed_data": json.dumps({"content": "Abre un ticket", "enabled": False, "embed": {}})}
        db = SimpleNamespace(get_ticket_categories=lambda _: [{"id": 1, "name": "Soporte"}],
                             get_ticket_config=lambda _: config, set_ticket_config=lambda *a, **k: None)
        cog = Tickets(SimpleNamespace(db=db))
        guild = SimpleNamespace(id=1, get_channel=lambda _: channel)
        with patch("cogs.tickets.discord.TextChannel", Channel):
            success, _ = await cog.send_panel_to_channel(guild, 50)
        self.assertTrue(success)
        sent = channel.send.await_args.kwargs
        self.assertEqual(sent["content"], "Abre un ticket")
        self.assertIsNone(sent["embed"])
        self.assertEqual(sent["view"].children[0].options[0].value, "1")

    async def test_category_send_preserves_options_and_default_argument_shape(self):
        send = AsyncMock()
        view, mentions = object(), discord.AllowedMentions.none()
        await send_managed(self.bot, 1, "tickets", send, "Hola", view=view, allowed_mentions=mentions)
        send.assert_awaited_once_with("Hola", view=view, allowed_mentions=mentions)
        send.reset_mock()
        self.db.set_server_config(1, ai_message_categories='{"tickets":true}')
        with patch("cogs._managed_messages.request_completion", AsyncMock(return_value='["Buenas"]')):
            await send_managed(self.bot, 1, "tickets", send, "Hola", view=view, allowed_mentions=mentions, delete_after=10)
        send.assert_awaited_once_with(content="Buenas", view=view, allowed_mentions=mentions, delete_after=10)

    async def test_category_api_roundtrip_strict_boolean_and_known_keys(self):
        result = await get_ai_message_settings(1, self.db, {})
        self.assertFalse(any(result["categories"].values()))
        result = await patch_ai_message_settings(1, {"categories": {"welcomes": True}}, self.db, {})
        self.assertTrue(result["categories"]["welcomes"])
        self.assertEqual(result, await get_ai_message_settings(1, self.db, {}))
        for body in ({"categories": {"welcomes": 1}}, {"categories": {"unknown": True}}, {"categories": {}, "extra": True}):
            with self.assertRaises(HTTPException):
                await patch_ai_message_settings(1, body, self.db, {})

    async def test_burst_has_two_slots_and_busy_messages_use_template_immediately(self):
        entered, release = asyncio.Event(), asyncio.Event()
        active = 0
        async def rewrite(*args):
            nonlocal active
            active += 1
            if active == 2:
                entered.set()
            await release.wait()
            return ["Buenas"]
        payload = {"content": "Hola", "embed": None}
        with patch("cogs._managed_messages._rewrite", side_effect=rewrite):
            tasks = [asyncio.create_task(manage_payload(self.bot, 1, payload, enabled=True)) for _ in range(8)]
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.sleep(0)
            self.assertEqual(active, 2)
            self.assertEqual(sum(task.done() for task in tasks), 6)
            release.set()
            results = await asyncio.gather(*tasks)
        self.assertEqual(sum(row is payload for row in results), 6)

    async def test_ai_context_requires_captured_same_channel_audience_and_excludes_raw_content(self):
        self.db.log_automod_action(1, "spam", 20, "SECRET RAW CONTENT", "warn",
                                  extra={"channel_id": "30", "reason": "Demasiados mensajes", "public_at_capture": False})
        self.db.log_automod_action(1, "spam", 21, "OTHER SECRET", "delete",
                                  extra={"channel_id": "30", "reason": "Regla visible", "public_at_capture": True})
        self.db.log_automod_action(1, "spam", 22, "PRIVATE", "warn",
                                  extra={"channel_id": "99", "public_at_capture": True})
        self.db.log_automod_action(1, "legacy", 23, "NO CHANNEL", "warn")
        mine = self.db.get_ai_moderation_context(1, 30, 20)
        self.assertEqual({row["user_id"] for row in mine}, {"20"})
        others = self.db.get_ai_moderation_context(1, 30, 999)
        self.assertEqual(others, [])
        self.assertNotIn("SECRET", json.dumps(mine))
        self.assertNotIn("extra_data", json.dumps(mine))
        self.db.log_action(1, 20, 100, "MUTE", "Pendiente", extra_data={"channel_id": "30"}, status="pending")
        self.assertIn("pending", [row["status"] for row in self.db.get_ai_moderation_context(1, 30, 20)])

    async def test_legacy_evidence_url_proves_channel_but_never_exposes_unknown_visibility_reason(self):
        self.db.log_action(1, 20, 100, "WARN", "PRIVATE LEGACY REASON",
                           evidence_url="https://discord.com/channels/1/30/123")
        self.db.log_action(1, 20, 100, "KICK", "OTHER CHANNEL",
                           evidence_url="https://discord.com/channels/1/99/123")
        rows = self.db.get_ai_moderation_context(1, 30, 20)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "WARN")
        self.assertEqual(rows[0]["reason"], "")
        self.assertIsNone(rows[0]["public_at_capture"])
        self.assertTrue(rows[0]["channel_verified"])


if __name__ == "__main__":
    unittest.main()
