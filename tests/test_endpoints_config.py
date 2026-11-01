"""Endpoint edits retain credentials and leave moderation/chat policy untouched."""
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.routes import guild
from cogs._llm_moderation import request_completion
from cogs.ia import IA
from llm_moderation_config import completion_output_tokens, validate_llm_config
from tests.test_managed_messages import make_db


class EndpointConfigTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db._sqlite_conn.close)
        self.db.set_automod_config(1, enabled=1, rules={"llm": {
            "enabled": True, "rules_text": "No insults", "endpoint_url": "https://first.example/v1",
            "model": "model", "api_key": "retained-secret"}, "spam": {"enabled": True}})

    async def test_endpoint_partial_edit_preserves_key_rules_and_chat_policy(self):
        before = self.db.get_automod_config(1)
        ai_before = self.db.get_ai_config(1)
        for empty in ("", None):
            with patch("api.routes.guild.resolve_endpoint_addresses", AsyncMock(return_value=["93.184.216.34"])):
                result = await guild.patch_endpoints_config(1, {"llm": {
                    "endpoint_url": "https://second.example/v1", "api_key": empty,
                    "context_window_tokens": 524288, "chat_reasoning_effort": "medium"}}, self.db, {})
            saved = self.db.get_automod_config(1)
            self.assertEqual(saved["rules"]["llm"]["api_key"], "retained-secret")
            self.assertEqual(saved["rules"]["llm"]["rules_text"], "No insults")
            self.assertEqual(saved["rules"]["spam"], before["rules"]["spam"])
            self.assertEqual(saved["enabled"], 1)
            self.assertEqual(self.db.get_ai_config(1), ai_before)
            self.assertTrue(result["llm"]["api_key_configured"])
            self.assertNotIn("retained-secret", json.dumps(result))
            self.assertNotIn("api_key", result["llm"])
            self.assertNotIn("rules_text", result["llm"])
        result = await guild.patch_endpoints_config(1, {"llm": {"api_key_clear": True}}, self.db, {})
        self.assertFalse(result["llm"]["api_key_configured"])
        self.assertEqual(self.db.get_automod_config(1)["rules"]["llm"]["api_key"], "")

    async def test_endpoint_rejects_policy_fields_bad_context_and_missing_consent(self):
        before = deepcopy(self.db.get_automod_config(1))
        for llm in ({"enabled": False}, {"rules_text": "Changed"}, {"context_window_tokens": True},
                    {"context_window_tokens": 100}, {"chat_reasoning_effort": "unknown"},
                    {"api_key_clear": "yes"}, {"api_key_clear": True, "api_key": "replacement"}):
            with self.subTest(llm=llm), self.assertRaises(HTTPException):
                await guild.patch_endpoints_config(1, {"llm": llm}, self.db, {})
        with patch("api.routes.guild.resolve_endpoint_addresses", AsyncMock(return_value=["127.0.0.1"])):
            with self.assertRaises(HTTPException) as error:
                await guild.patch_endpoints_config(1, {"llm": {"endpoint_url": "http://127.0.0.1/v1"}}, self.db, {})
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.db.get_automod_config(1), before)

    async def test_dns_wait_does_not_overwrite_a_newer_policy_or_key(self):
        async def resolve(_endpoint):
            self.db.set_automod_config(1, rules={"llm": {"rules_text": "New policy", "api_key": "new-secret"}})
            return ["93.184.216.34"]
        with patch("api.routes.guild.resolve_endpoint_addresses", side_effect=resolve):
            await guild.patch_endpoints_config(1, {"llm": {"endpoint_url": "https://changed.example/v1", "api_key": ""}}, self.db, {})
        cfg = self.db.get_automod_config(1)["rules"]["llm"]
        self.assertEqual(cfg["rules_text"], "New policy")
        self.assertEqual(cfg["api_key"], "new-secret")

    def test_key_clear_is_explicit_and_blank_values_never_clear(self):
        for update in ({}, {"api_key": ""}, {"api_key": None}, {"endpoint_url": "https://new.example/v1"}):
            result = validate_llm_config(update, {"api_key": "retained-secret"})
            self.assertEqual(result["api_key"], "retained-secret")
        self.assertEqual(validate_llm_config({"api_key_clear": True}, {"api_key": "retained-secret"})["api_key"], "")

    def test_deep_think_persists_without_changing_web_switch(self):
        self.db.set_ai_config(1, ai_deep_think=1)
        self.assertEqual(self.db.get_ai_config(1)["ai_deep_think"], 1)
        self.assertEqual(self.db.get_ai_config(1)["ai_web_enabled"], 0)
        with self.assertRaises(ValueError):
            self.db.set_ai_config(1, ai_deep_think=2)


class ReasoningTransportTests(unittest.IsolatedAsyncioTestCase):
    def test_shared_output_reserve_includes_provider_thinking_tokens(self):
        for effort, expected in (("none", 1000), ("auto", 8192), ("low", 8192), ("medium", 8192), ("high", 16384), ("max", 16384)):
            self.assertEqual(completion_output_tokens({"chat_reasoning_effort": effort}), expected)
            self.assertEqual(completion_output_tokens({"web_reasoning_effort": effort}, task="web", deep=True), 16384)

    async def test_reasoning_and_output_reserve_are_task_specific_for_both_protocols(self):
        for api_type in ("chat_completions", "responses"):
            cfg = {"endpoint_url": "https://endpoint.example/v1", "model": "test", "api_type": api_type,
                   "chat_reasoning_effort": "medium"}
            answer = ({"status": "completed", "output": [{"type": "message", "role": "assistant",
                       "content": [{"type": "output_text", "text": "Answer"}]}]} if api_type == "responses" else
                      {"choices": [{"finish_reason": "stop", "message": {"content": "Answer"}}]})
            for effort in (None, "none", "auto", "low", "medium", "high", "max"):
                with patch("cogs._llm_moderation.endpoint_json", AsyncMock(return_value=answer)) as endpoint:
                    await request_completion(None, cfg, [], reasoning_effort=effort, max_output_tokens=2048)
                payload = endpoint.await_args.args[2]
                selected = "medium" if effort is None else effort
                field = "reasoning" if api_type == "responses" else "reasoning_effort"
                expected = {"effort": selected} if api_type == "responses" else selected
                if selected == "auto":
                    self.assertNotIn(field, payload)
                else:
                    self.assertEqual(payload[field], expected)
                self.assertEqual(payload["max_output_tokens" if api_type == "responses" else "max_tokens"], 2048)
            with patch("cogs._llm_moderation.endpoint_json", AsyncMock(return_value=answer)) as endpoint:
                await request_completion(None, cfg, [], moderation=True, reasoning_effort="max", max_output_tokens=2048)
            payload = endpoint.await_args.args[2]
            self.assertEqual(payload["max_output_tokens" if api_type == "responses" else "max_tokens"], 512)
            if api_type == "responses":
                self.assertNotIn("reasoning", payload)
            else:
                self.assertEqual(payload["reasoning_effort"], "none")

    async def test_timeout_override_does_not_change_moderation_deadline(self):
        cfg = {"model": "test", "chat_reasoning_effort": "high"}
        answer = {"choices": [{"finish_reason": "stop", "message": {"content": "Answer"}}]}
        with patch("cogs._llm_moderation.endpoint_json", AsyncMock(return_value=answer)) as endpoint:
            await request_completion(None, cfg, [], timeout_seconds=300)
            self.assertEqual(endpoint.await_args.kwargs, {"timeout_seconds": 300})
            self.assertEqual(endpoint.await_args.args[2]["max_tokens"], 16384)
            await request_completion(None, cfg, [], moderation=True, timeout_seconds=300)
            self.assertEqual(endpoint.await_args.kwargs, {})
            self.assertEqual(endpoint.await_args.args[2]["max_tokens"], 512)

    async def test_only_offered_research_submission_can_use_larger_arguments(self):
        for api_type in ("chat_completions", "responses"):
            for name in ("submit_research", "search_web"):
                arguments = json.dumps({"facts": "x" * 5000})
                call = {"id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments}}
                answer = ({"status": "completed", "output": [{"type": "function_call", "call_id": "call_1", "name": name, "arguments": arguments}]}
                          if api_type == "responses" else {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [call]}}]})
                with patch("cogs._llm_moderation.endpoint_json", AsyncMock(return_value=answer)):
                    request = request_completion(None, {"model": "test", "api_type": api_type}, [],
                        tools=[{"type": "function", "function": {"name": name}}], structured=True)
                    if name == "submit_research":
                        result = await request
                        self.assertEqual(result["tool_calls"][0]["function"]["arguments"], arguments)
                    else:
                        with self.assertRaises(ValueError):
                            await request


class LegacyMentionSendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.author = SimpleNamespace(id=30, display_name="Ana", name="ana", mention="<@30>")
        self.target = SimpleNamespace(id=31, display_name="Luis", name="luis")
        self.guild = SimpleNamespace(id=1, members=[self.author, self.target])
        self.channel = SimpleNamespace(guild=self.guild)
        self.message = SimpleNamespace(author=self.author, guild=self.guild, mentions=[self.target],
            content="Pregunta a <@31>", channel=self.channel, reply=AsyncMock())
        self.cog = IA.__new__(IA)

    async def test_legacy_replies_ping_first_fragment_and_block_mass_mentions(self):
        await self.cog._send_reply(self.message, "Hola @Luis <@999> @everyone <@&9> " + "x" * 2100, False)
        calls = self.message.reply.await_args_list
        self.assertGreater(len(calls), 1)
        self.assertIn("<@31>", calls[0].args[0])
        self.assertNotIn("<@999>", calls[0].args[0])
        self.assertTrue(calls[0].kwargs["mention_author"])
        self.assertFalse(calls[1].kwargs["mention_author"])
        self.assertFalse(calls[0].kwargs["allowed_mentions"].everyone)
        self.assertFalse(calls[0].kwargs["allowed_mentions"].roles)
        self.assertFalse(calls[1].kwargs["allowed_mentions"].users)

    async def test_legacy_webhook_notifies_author_once(self):
        webhook = SimpleNamespace(name="Bot_ES_IA", send=AsyncMock())
        self.channel.webhooks = AsyncMock(return_value=[webhook])
        self.cog.db = SimpleNamespace(get_ai_config=lambda _guild_id: {})
        self.cog.bot = SimpleNamespace(user=SimpleNamespace(display_avatar=SimpleNamespace(url="https://avatar.example/image.png")))
        await self.cog._send_via_webhook(self.message, "@Luis " + "x" * 2100)
        first, second = webhook.send.await_args_list
        self.assertTrue(first.kwargs["content"].startswith("<@30> "))
        self.assertEqual({member.id for member in first.kwargs["allowed_mentions"].users}, {30, 31})
        self.assertFalse(second.kwargs["allowed_mentions"].users)

    async def test_member_first_mentioned_in_reply_continuation_is_notified_once(self):
        await self.cog._send_reply(self.message, "x" * 1990 + "<@31>" + "x" * 1985 + "<@31>", False)
        first, second, third = self.message.reply.await_args_list
        self.assertFalse(first.kwargs["allowed_mentions"].users)
        self.assertEqual({member.id for member in second.kwargs["allowed_mentions"].users}, {31})
        self.assertFalse(third.kwargs["allowed_mentions"].users)
        self.assertTrue(first.kwargs["mention_author"])
        self.assertFalse(second.kwargs["mention_author"])

    async def test_member_first_mentioned_in_webhook_continuation_is_notified_once(self):
        webhook = SimpleNamespace(name="Bot_ES_IA", send=AsyncMock())
        self.channel.webhooks = AsyncMock(return_value=[webhook])
        self.cog.db = SimpleNamespace(get_ai_config=lambda _guild_id: {})
        self.cog.bot = SimpleNamespace(user=SimpleNamespace(display_avatar=SimpleNamespace(url="https://avatar.example/image.png")))
        await self.cog._send_via_webhook(self.message, "x" * 1894 + "<@31>" + "x" * 1895 + "<@31>")
        first, second, third = webhook.send.await_args_list
        self.assertEqual({member.id for member in first.kwargs["allowed_mentions"].users}, {30})
        self.assertEqual({member.id for member in second.kwargs["allowed_mentions"].users}, {31})
        self.assertFalse(third.kwargs["allowed_mentions"].users)


if __name__ == "__main__":
    unittest.main()
