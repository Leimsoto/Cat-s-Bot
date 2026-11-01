import json
import unittest
from unittest.mock import AsyncMock, patch

from cogs._conversation_budget import (
    CONTEXT_CEILING, IMAGE_RESERVE, OUTPUT_RESERVE, TEMPLATE_MARGIN,
    ContextBudgetError, ConversationBudget,
)
from cogs._llm_moderation import auxiliary_url, endpoint_json


class ConversationBudgetTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.budget = ConversationBudget()
        self.cfg = {"endpoint_url": "https://provider.example/prefix/v1/chat/completions", "model": "strata", "api_key": "secret"}
        self.context = {"trigger": {"text": "mensaje actual"}, "personal_memories_untrusted": ["preferencias"],
            "conversation_untrusted": [{"message_id": str(index), "text": "a" * 3000} for index in range(200)]}

    async def test_manual_window_is_not_capped_at_256k_and_changes_cache_key(self):
        self.assertEqual(await self.budget.window(None, {**self.cfg, "context_window_tokens": 524288}), 524288)
        self.assertEqual(await self.budget.window(None, {**self.cfg, "context_window_tokens": 100000}), 100000)
        self.assertNotEqual(self.budget.connection_key(self.cfg), self.budget.connection_key({**self.cfg, "context_window_tokens": 524288}))

    async def test_research_allowance_subtracts_context_images_output_and_margin(self):
        cfg = {**self.cfg, "output_reserve": 4000}
        context = {"trigger": {"text": "question"}, "conversation_untrusted": [{"text": "history"}]}
        images = [{"type": "image_url"}]
        with patch.object(self.budget, "window", new=AsyncMock(return_value=40000)), patch.object(
                self.budget, "count", new=AsyncMock(return_value=10000)):
            allowance = await self.budget.research_allowance(object(), cfg, "rules", context, images)
        self.assertEqual(allowance, int((40000 - 10000 - IMAGE_RESERVE - 4000 - TEMPLATE_MARGIN) * .6))

    async def test_research_can_reclaim_old_history_but_never_required_context(self):
        with patch.object(self.budget, "window", new=AsyncMock(return_value=40000)), patch.object(
                self.budget, "count", new=AsyncMock(side_effect=[37000, 10000])) as count:
            allowance = await self.budget.research_allowance(object(), self.cfg, "rules", self.context, [])
        self.assertGreater(allowance, 10000)
        self.assertEqual(count.await_args.args[3]["conversation_untrusted"], [])
        self.assertEqual(count.await_args.args[3]["trigger"], self.context["trigger"])

    async def test_same_origin_auxiliary_routes_preserve_prefix_without_guessing_custom_routes(self):
        self.assertEqual(auxiliary_url(self.cfg["endpoint_url"], "models"), "https://provider.example/prefix/v1/models")
        self.assertEqual(auxiliary_url(self.cfg["endpoint_url"], "messages/count_tokens"), "https://provider.example/prefix/v1/messages/count_tokens")
        self.assertIsNone(auxiliary_url("https://provider.example/custom/generate", "models"))
        session = AsyncMock()
        with self.assertRaises(ValueError):
            await endpoint_json(session, {**self.cfg, "endpoint_url": "https://provider.example/custom/generate"}, auxiliary="models")
        session.get.assert_not_called()
        session.post.assert_not_called()

    async def test_native_count_uses_large_window_and_caches_metadata(self):
        async def endpoint(session, cfg, payload=None, *, auxiliary=None):
            if auxiliary == "models":
                return {"data": [{"id": "strata", "meta": {"n_ctx": CONTEXT_CEILING}}]}
            context = json.loads(payload["messages"][0]["content"][0]["text"])
            self.assertEqual(payload["system"], "reglas")
            self.assertEqual(payload["thinking"], {"type": "disabled"})
            return {"input_tokens": 100 + len(context["conversation_untrusted"]) * 1000}
        with patch("cogs._conversation_budget.endpoint_json", new=AsyncMock(side_effect=endpoint)) as request:
            fitted = await self.budget.fit(object(), self.cfg, "reglas", self.context, [])
            self.assertEqual(len(fitted["conversation_untrusted"]), 200)
            self.assertGreater(len(json.dumps(fitted)), CONTEXT_CEILING)
            await self.budget.window(object(), self.cfg)
        routes = [call.kwargs["auxiliary"] for call in request.await_args_list]
        self.assertEqual(routes.count("models"), 1)
        self.assertEqual(routes.count("messages/count_tokens"), 1)

    async def test_small_complete_context_reads_cold_window_once_without_count_or_count_authorization(self):
        context = {"trigger": {"text": "hola"}, "conversation_untrusted": [{"text": "á"} for _ in range(200)]}
        before_count = AsyncMock(return_value=True)
        with patch("cogs._conversation_budget.endpoint_json", AsyncMock(return_value={"data": [{"id": "strata", "meta": {"n_ctx": 32768}}]})) as request:
            for _ in range(2):
                self.assertEqual(await self.budget.fit(object(), self.cfg, "rules", context, [], before_count=before_count), context)
        self.assertEqual([call.kwargs["auxiliary"] for call in request.await_args_list], ["models"])
        before_count.assert_not_awaited()

    async def test_exact_utf8_full_context_bound_keeps_every_requested_turn(self):
        prompt = "reglas"
        context = {"trigger": {"text": "á🐈"}, "conversation_untrusted": [{"text": "primero"}, {"text": "último"}]}
        size = len((prompt + json.dumps(context, ensure_ascii=False)).encode("utf-8"))
        before_count = AsyncMock(return_value=True)
        with patch.object(self.budget, "window", AsyncMock(return_value=size + OUTPUT_RESERVE + TEMPLATE_MARGIN)), \
             patch.object(self.budget, "count", AsyncMock()) as count:
            fitted = await self.budget.fit(object(), self.cfg, prompt, context, [], before_count=before_count)
        self.assertEqual(fitted, context)
        count.assert_not_awaited()
        before_count.assert_not_awaited()

    async def test_smaller_reported_window_prevents_fast_path_for_context_that_only_fits_ceiling(self):
        context = {"trigger": "required", "conversation_untrusted": [{"text": "x" * 100, "id": index} for index in range(3)]}
        before_count = AsyncMock(return_value=True)
        async def endpoint(session, cfg, payload=None, *, auxiliary=None):
            if auxiliary == "models":
                return {"data": [{"id": "strata", "meta": {"n_ctx": OUTPUT_RESERVE + TEMPLATE_MARGIN + 100}}]}
            sent = json.loads(payload["messages"][0]["content"][0]["text"])
            return {"input_tokens": 5 + len(sent["conversation_untrusted"]) * 50}
        with patch("cogs._conversation_budget.endpoint_json", AsyncMock(side_effect=endpoint)) as request:
            fitted = await self.budget.fit(object(), self.cfg, "rules", context, [], before_count=before_count)
        counts = [call for call in request.await_args_list if call.kwargs["auxiliary"] == "messages/count_tokens"]
        self.assertEqual(len(counts), 3)
        self.assertEqual(before_count.await_count, len(counts))
        self.assertEqual(fitted["trigger"], "required")
        self.assertEqual(fitted["conversation_untrusted"], [context["conversation_untrusted"][-1]])

    async def test_image_reserve_is_applied_before_exact_full_context_fast_path(self):
        context = {"trigger": "required", "conversation_untrusted": [{"text": "history"}]}
        images = [{"type": "text", "text": "image attribution"},
                  {"type": "image_url", "image_url": {"url": "data:image/png;base64,SECRET_IMAGE"}}]
        size = len(("rules" + json.dumps(context, ensure_ascii=False) + "image attribution").encode("utf-8"))
        before_count = AsyncMock(return_value=True)
        with patch.object(self.budget, "window", AsyncMock(return_value=size + OUTPUT_RESERVE + TEMPLATE_MARGIN + IMAGE_RESERVE)), \
             patch.object(self.budget, "count", AsyncMock()) as count:
            self.assertEqual(await self.budget.fit(object(), self.cfg, "rules", context, images, before_count=before_count), context)
        count.assert_not_awaited()
        before_count.assert_not_awaited()

    async def test_unsupported_counter_cache_skips_egress_authorization_on_next_fit(self):
        before_count = AsyncMock(return_value=True)
        async def endpoint(session, cfg, payload=None, *, auxiliary=None):
            if auxiliary == "models":
                return {"data": [{"id": "strata", "meta": {"n_ctx": CONTEXT_CEILING}}]}
            raise ValueError("endpoint_http_404")
        with patch("cogs._conversation_budget.endpoint_json", AsyncMock(side_effect=endpoint)) as request:
            first = await self.budget.fit(object(), self.cfg, "rules", self.context, [], before_count=before_count)
            second = await self.budget.fit(object(), self.cfg, "rules", self.context, [], before_count=before_count)
        self.assertEqual(first, second)
        self.assertEqual([call.kwargs["auxiliary"] for call in request.await_args_list], ["models", "messages/count_tokens"])
        before_count.assert_awaited_once()

    async def test_smaller_reported_window_trims_oldest_only_with_bounded_counts(self):
        async def endpoint(session, cfg, payload=None, *, auxiliary=None):
            if auxiliary == "models":
                return {"data": [{"id": "strata", "meta": {"n_ctx": 8192}}]}
            context = json.loads(payload["messages"][0]["content"][0]["text"])
            return {"input_tokens": 100 + len(context["conversation_untrusted"]) * 1000}
        with patch("cogs._conversation_budget.endpoint_json", new=AsyncMock(side_effect=endpoint)) as request:
            fitted = await self.budget.fit(object(), self.cfg, "reglas", self.context, [])
        turns = fitted["conversation_untrusted"]
        self.assertGreater(len(turns), 0)
        self.assertLessEqual(len(turns), 5)
        self.assertEqual(turns[-1]["message_id"], "199")
        self.assertEqual(fitted["trigger"], self.context["trigger"])
        self.assertEqual(fitted["personal_memories_untrusted"], ["preferencias"])
        self.assertLessEqual(sum(call.kwargs["auxiliary"] == "messages/count_tokens" for call in request.await_args_list), 4)

    async def test_unavailable_counter_uses_conservative_utf8_bytes(self):
        self.context["conversation_untrusted"] = [{"text": "á" * 800, "message_id": str(index)} for index in range(30)]
        with patch.object(self.budget, "window", new=AsyncMock(return_value=12000)):
            fitted = await self.budget.fit(None, self.cfg, "reglas", self.context, [])
        available = 12000 - OUTPUT_RESERVE - TEMPLATE_MARGIN
        self.assertLessEqual(len(("reglas" + json.dumps(fitted, ensure_ascii=False)).encode()), available)
        self.assertEqual(fitted["conversation_untrusted"][-1]["message_id"], "29")
        self.assertLess(len(fitted["conversation_untrusted"]), 30)

    async def test_required_context_overflow_is_explicit_without_dropping_rules_or_trigger(self):
        with patch.object(self.budget, "window", new=AsyncMock(return_value=8192)), \
             patch.object(self.budget, "count", new=AsyncMock(return_value=9000)):
            with self.assertRaises(ContextBudgetError):
                await self.budget.fit(object(), self.cfg, "reglas", self.context, [])
        self.assertEqual(len(self.context["conversation_untrusted"]), 200)
        self.assertEqual(self.context["trigger"]["text"], "mensaje actual")

    async def test_unsupported_counter_falls_back_and_never_sends_image_binary_to_text_counter(self):
        async def endpoint(session, cfg, payload=None, *, auxiliary=None):
            if auxiliary == "models":
                return {"data": [{"id": "strata", "meta": {"n_ctx": 65536}}]}
            self.assertNotIn("SECRET_IMAGE", json.dumps(payload))
            raise ValueError("endpoint_http_404")
        images = [{"type": "text", "text": "image attribution"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,SECRET_IMAGE"}}]
        with patch("cogs._conversation_budget.endpoint_json", new=AsyncMock(side_effect=endpoint)) as request:
            fitted = await self.budget.fit(object(), self.cfg, "reglas", self.context, images)
        available = 65536 - OUTPUT_RESERVE - TEMPLATE_MARGIN - IMAGE_RESERVE
        self.assertLessEqual(len(("reglas" + "image attribution" + json.dumps(fitted, ensure_ascii=False)).encode()), available)
        self.assertEqual(request.await_count, 2)

    async def test_context_change_before_count_aborts_and_metadata_cache_is_bounded(self):
        current = AsyncMock(side_effect=[True, False])
        with patch.object(self.budget, "window", new=AsyncMock(return_value=65536)), \
             patch.object(self.budget, "count", new=AsyncMock()) as count:
            self.assertIsNone(await self.budget.fit(None, self.cfg, "reglas", self.context, [], current=current))
        count.assert_not_awaited()
        for index in range(40):
            await self.budget.window(None, {**self.cfg, "model": f"model{index}"})
        self.assertEqual(len(self.budget.metadata), 32)

    async def test_unsupported_counter_cache_has_ttl_key_isolation_and_bound(self):
        with patch("cogs._conversation_budget.endpoint_json", new=AsyncMock(side_effect=ValueError("endpoint_http_404"))) as request:
            for _ in range(2):
                self.assertIsNone(await self.budget.count(object(), self.cfg, "reglas", {}, []))
            self.assertEqual(request.await_count, 1)
            await self.budget.count(object(), {**self.cfg, "api_key": "rotated"}, "reglas", {}, [])
            await self.budget.count(object(), {**self.cfg, "model": "other"}, "reglas", {}, [])
            self.assertEqual(request.await_count, 3)
            stamp = self.budget.unavailable_counts[self.budget.connection_key(self.cfg)]
            with patch("cogs._conversation_budget.monotonic", return_value=stamp + 301):
                await self.budget.count(object(), self.cfg, "reglas", {}, [])
            self.assertEqual(request.await_count, 4)
            for index in range(40):
                await self.budget.count(object(), {**self.cfg, "model": f"model{index}"}, "reglas", {}, [])
            self.assertEqual(len(self.budget.unavailable_counts), 32)

    async def test_supported_counts_are_never_cached_as_values(self):
        with patch("cogs._conversation_budget.endpoint_json", new=AsyncMock(side_effect=[{"input_tokens": 10}, {"input_tokens": 20}])) as request:
            self.assertEqual(await self.budget.count(object(), self.cfg, "reglas", {}, []), 10)
            self.assertEqual(await self.budget.count(object(), self.cfg, "reglas", {"text": "different"}, []), 20)
        self.assertEqual(request.await_count, 2)


class ResponsesBudgetTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.budget = ConversationBudget()
        self.cfg = {"endpoint_url": "https://provider.example/prefix/v1/responses", "api_type": "responses", "model": "fixture", "api_key": "fake"}

    async def test_native_responses_text_count_preserves_input_format_without_image_binary(self):
        async def endpoint(session, cfg, payload=None, *, auxiliary=None):
            self.assertEqual(auxiliary, "responses/input_tokens")
            self.assertEqual(payload["model"], "fixture")
            self.assertEqual(payload["input"][0]["role"], "system")
            self.assertEqual(payload["input"][0]["content"], "rules")
            self.assertEqual(payload["input"][1]["content"][1], {"type": "input_text", "text": "image attribution"})
            self.assertNotIn("SECRET_IMAGE", json.dumps(payload))
            self.assertNotIn("thinking", payload)
            self.assertNotIn("messages", payload)
            return {"object": "response.input_tokens", "input_tokens": 123}
        with patch("cogs._conversation_budget.endpoint_json", new=AsyncMock(side_effect=endpoint)) as request:
            count = await self.budget.count(object(), self.cfg, "rules", {"trigger": "question"}, [{"type": "text", "text": "image attribution"}])
        self.assertEqual(count, 123)
        request.assert_awaited_once()

    async def test_api_type_separates_metadata_and_unsupported_count_cache(self):
        same_url = {**self.cfg, "endpoint_url": "https://provider.example/v1"}
        chat = {**same_url, "api_type": "chat_completions"}
        self.assertNotEqual(self.budget.connection_key(same_url), self.budget.connection_key(chat))
        self.assertEqual(self.budget.connection_key(chat), self.budget.connection_key({key: value for key, value in chat.items() if key != "api_type"}))
        with patch("cogs._conversation_budget.endpoint_json", new=AsyncMock(side_effect=ValueError("endpoint_http_404"))) as request:
            await self.budget.count(object(), same_url, "rules", {}, [])
            await self.budget.count(object(), same_url, "rules", {}, [])
            await self.budget.count(object(), chat, "rules", {}, [])
        self.assertEqual([call.kwargs["auxiliary"] for call in request.await_args_list], ["responses/input_tokens", "messages/count_tokens"])
        with patch("cogs._conversation_budget.endpoint_json", new=AsyncMock(side_effect=[{"data": [{"id": "fixture", "meta": {"n_ctx": 32768}}]}, {"data": [{"id": "fixture", "meta": {"n_ctx": 65536}}]}])):
            self.assertEqual(await self.budget.window(object(), same_url), 32768)
            self.assertEqual(await self.budget.window(object(), chat), 65536)

    async def test_unsupported_responses_counter_uses_fallback_with_shared_models_window(self):
        context = {"trigger": {"text": "question"}, "conversation_untrusted": [{"text": "á" * 1000, "message_id": index} for index in range(20)]}
        async def endpoint(session, cfg, payload=None, *, auxiliary=None):
            if auxiliary == "models":
                return {"data": [{"id": "fixture", "meta": {"n_ctx": 12000}}]}
            self.assertEqual(auxiliary, "responses/input_tokens")
            raise ValueError("endpoint_http_404")
        with patch("cogs._conversation_budget.endpoint_json", new=AsyncMock(side_effect=endpoint)) as request:
            fitted = await self.budget.fit(object(), self.cfg, "rules", context, [])
        self.assertEqual([call.kwargs["auxiliary"] for call in request.await_args_list], ["models", "responses/input_tokens"])
        self.assertLessEqual(len(("rules" + json.dumps(fitted, ensure_ascii=False)).encode()), 12000 - OUTPUT_RESERVE - TEMPLATE_MARGIN)
        self.assertEqual(fitted["conversation_untrusted"][-1]["message_id"], 19)

    async def test_replay_budget_counts_encrypted_sidecar_bytes_without_mutating_items(self):
        messages = [{"role": "assistant", "content": None, "_responses_output": [{"type": "reasoning", "id": "rs", "encrypted_content": "x" * 7000}]}]
        original = json.loads(json.dumps(messages))
        with patch.object(self.budget, "window", new=AsyncMock(return_value=8192)):
            self.assertFalse(await self.budget.replay_fits(None, self.cfg, messages))
            self.assertTrue(await self.budget.replay_fits(None, self.cfg, [{"role": "system", "content": "tiny"}]))
        self.assertEqual(messages, original)
