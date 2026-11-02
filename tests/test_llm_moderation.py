import asyncio
import json
import logging
import socket
import sqlite3
import threading
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
import discord

from api.routes.guild import get_automod_config, get_automod_log, patch_automod_config
from cogs._llm_moderation import EndpointResolver, LLMReview, UnsupportedToolsError, fingerprint, request_completion, validate_decision
from cogs.automod import AutoMod
from cogs.moderation import Moderation
from database.manager import DatabaseManager
from llm_moderation_config import DEFAULT_LLM_CONFIG, validate_llm_config


def message(message_id=10, text="insulto literal"):
    result = SimpleNamespace(id=message_id, content=text, author=SimpleNamespace(id=20),
                             guild=SimpleNamespace(id=30), channel=SimpleNamespace(id=40),
                             attachments=[], stickers=[], embeds=[], edited_at=None,
                             jump_url=f"https://discord.com/channels/30/40/{message_id}")
    result.channel.fetch_message = AsyncMock(return_value=result)
    result.channel.send = AsyncMock()
    result.guild.me = SimpleNamespace(id=999)
    result.channel.permissions_for = lambda _: SimpleNamespace(view_channel=True, read_message_history=True)
    return result


def decision(msg, **changes):
    return {"message_id": str(msg.id), "author_id": str(msg.author.id), "action": "warn",
            "duration_seconds": None, "reason": "Incumple la regla", "rule": "No insultar",
            "evidence": [{"source": "text", "id": str(msg.id), "quote": "insulto"}], **changes}


class DecisionTests(unittest.TestCase):
    def test_response_target_evidence_rule_and_duration_boundaries(self):
        msg = message()
        self.assertEqual(validate_decision(json.dumps(decision(msg)), msg, "No insultar", set())["action"], "warn")
        bad = [dict(author_id="other"), dict(message_id="other"), dict(action="purge"),
               dict(action="mute", duration_seconds=True), dict(action="mute", duration_seconds=2419201),
               dict(action="kick", duration_seconds=60), dict(action="delete", duration_seconds=60), dict(rule="Invented rule"), dict(evidence=[]),
               dict(evidence=[{"source": "text", "id": "9", "quote": "insulto"}]),
               dict(evidence=[{"source": "text", "id": "10", "quote": "not in trigger"}]),
               dict(evidence=[{"source": "image", "id": "55", "quote": "Unseen"}])]
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                validate_decision(json.dumps(decision(msg, **changes)), msg, "No insultar", set())
        for action, duration in (("none", None), ("delete", None), ("mute", 60), ("mute", 2419200), ("ban", None), ("ban", 1)):
            value = decision(msg, action=action, duration_seconds=duration)
            if action == "none":
                value.update(reason="", rule="", evidence=[])
            self.assertEqual(validate_decision(json.dumps(value), msg, "No insultar", set())["action"], action)

    def test_fenced_json_and_duplicate_fields_are_rejected(self):
        msg = message()
        for raw in ('```json\n{}\n```', '{"message_id":"10","message_id":"11"}'):
            with self.assertRaises(ValueError):
                validate_decision(raw, msg, "No insultar", set())

    def test_conversational_or_verbose_output_is_rejected_without_truncation(self):
        msg = message(text="x" * 161)
        values = [decision(msg, reason="x" * 161), decision(msg, rule="x" * 161),
                  decision(msg, evidence=[{"source": "text", "id": "10", "quote": "x" * 161}]),
                  decision(msg, evidence=[{"source": "text", "id": "10", "quote": "x"}] * 2),
                  decision(msg, action="none", reason="Here is my advice to you", rule="", evidence=[])]
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_decision(json.dumps(value), msg, "No insultar\n" + "x" * 161, set())
        for text in ('Hello! I think you should be nicer.', '{"action":"warn"',
                     'Here is the decision: ' + json.dumps(decision(msg))):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_decision(text, msg, "No insultar", set())

    def test_compact_no_action_has_no_explanation_or_evidence(self):
        msg = message()
        value = decision(msg, action="none", duration_seconds=None, reason="", rule="", evidence=[])
        self.assertEqual(validate_decision(json.dumps(value), msg, "No insultar", set()), value)

    def test_endpoint_and_config_reject_bad_trust_boundary_values(self):
        for changes in ({"context_mode": []}, {"context_messages": True}, {"context_messages": 51},
                        {"supports_images": "false"}, {"api_key": "secret\r\nInjected: value"},
                        {"endpoint_url": "https://key@example.com/v1"}, {"endpoint_url": "https://example.com/v1?key=x"},
                        {"endpoint_url": "http://example.com/v1"}, {"endpoint_url": "https://127.0.0.1/v1"}):
            with self.subTest(changes=changes), patch.dict("os.environ", {"CATBOT_LLM_ALLOWED_HOSTS": ""}), self.assertRaises(ValueError):
                validate_llm_config(changes)
        with patch.dict("os.environ", {"CATBOT_LLM_ALLOWED_HOSTS": "localhost"}):
            self.assertEqual(validate_llm_config({"endpoint_url": "http://localhost:8080/v1/chat/completions"})["endpoint_url"], "http://localhost:8080/v1/chat/completions")


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_only_signals_explicit_unsupported_tools_without_leaking_error(self):
        cfg = {"endpoint_url": "https://llm.example/v1", "api_key": "private-key", "model": "test"}
        tools = [{"type": "function", "function": {"name": "read_my_moderation_history"}}]
        cases = [
            (400, {"error": {"param": "tools", "code": "unsupported_parameter", "message": "provider-private"}}, True, True),
            (422, {"error": {"message": "Model does not support tool_choice. provider-private"}}, True, True),
            (400, {"error": {"message": "Invalid tools schema. provider-private"}}, True, False),
            (400, {"error": {"param": "model", "code": "unsupported_parameter"}}, True, False),
            (400, {"error": {"param": "model", "message": "Unsupported parameter model when using tools"}}, True, False),
            (400, {"error": {"message": "Invalid API key. provider-private"}}, True, False),
            (500, {"error": {"message": "tools not supported"}}, True, False),
            (400, {"error": {"message": "tools not supported"}}, False, False),
            (400, {"error": "tools not supported"}, True, False),
            (400, {"error": {"message": "tools not supported " + "x" * 20000}}, True, False),
        ]
        for status, data, with_tools, unsupported in cases:
            async def chunks(size):
                encoded = json.dumps(data).encode()
                for start in range(0, len(encoded), size):
                    yield encoded[start:start + size]
            class Response:
                content = SimpleNamespace(iter_chunked=chunks)
                async def __aenter__(self):
                    self.status = status
                    return self
                async def __aexit__(self, *args):
                    return False
            session = SimpleNamespace(post=Mock(return_value=Response()))
            with self.subTest(status=status, with_tools=with_tools, unsupported=unsupported):
                with self.assertRaises(ValueError) as raised:
                    await request_completion(session, cfg, [], tools=tools if with_tools else None, structured=with_tools)
                self.assertEqual(isinstance(raised.exception, UnsupportedToolsError), unsupported)
                self.assertEqual(str(raised.exception), "endpoint_tools_unsupported" if unsupported else f"endpoint_http_{status}")
                self.assertNotIn("private", str(raised.exception))

    async def test_channel_notice_mentions_only_author_and_escapes_model_mentions(self):
        msg = message()
        msg.author.send = AsyncMock()
        review, cfg = self.review(msg)
        await review.notify_deleted(msg, decision(msg, reason="<@77777777777777777> @everyone <@&88888888888888888>", rule="@here"))
        msg.channel.send.assert_awaited_once()
        msg.author.send.assert_not_awaited()
        text = msg.channel.send.await_args.args[0]
        self.assertTrue(text.startswith(f"<@{msg.author.id}> "))
        for unwanted in ("<@77777777777777777>", "@everyone", "<@&88888888888888888>", "@here"):
            self.assertNotIn(unwanted, text)
        mentions = msg.channel.send.await_args.kwargs["allowed_mentions"]
        self.assertEqual([user.id for user in mentions.users], [msg.author.id])
        self.assertFalse(mentions.everyone)
        self.assertFalse(mentions.roles)
        self.assertFalse(mentions.replied_user)

    async def test_transport_accepts_base_and_full_urls_without_mutating_config(self):
        cases = (
            ("https://provider.example/v1", "https://provider.example/v1/chat/completions"),
            ("https://provider.example/v1/", "https://provider.example/v1/chat/completions"),
            ("https://provider.example", "https://provider.example/v1/chat/completions"),
            ("https://provider.example/", "https://provider.example/v1/chat/completions"),
            ("https://provider.example/v1/chat/completions", "https://provider.example/v1/chat/completions"),
            ("https://provider.example/v1/chat/completions/", "https://provider.example/v1/chat/completions"),
            ("https://provider.example/custom/completions", "https://provider.example/custom/completions"),
            ("https://provider.example/custom/completions/", "https://provider.example/custom/completions/"),
        )
        for endpoint, expected in cases:
            with self.subTest(endpoint=endpoint):
                review, cfg = self.review(message())
                llm = cfg["rules"]["llm"]
                llm.update(endpoint_url=endpoint, api_key="stored-key")
                saved = deepcopy(llm)
                async def chunks(_size):
                    yield b'{"choices":[{"message":{"content":"result"}}]}'
                response = SimpleNamespace(status=200, content=SimpleNamespace(iter_chunked=chunks))
                context = AsyncMock()
                context.__aenter__.return_value = response
                review.session = SimpleNamespace(post=Mock(return_value=context))
                self.assertEqual(await review.request(llm, []), "result")
                args, kwargs = review.session.post.call_args
                self.assertEqual(args[0], expected)
                self.assertFalse(kwargs["allow_redirects"])
                self.assertEqual(kwargs["headers"], {"Authorization": "Bearer stored-key"})
                self.assertEqual(kwargs["json"]["max_tokens"], 512)
                self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})
                self.assertEqual(kwargs["json"]["reasoning_effort"], "none")
                self.assertEqual(llm, saved)

    async def test_transport_rejects_truncated_completion_even_if_content_is_valid_json(self):
        for finish_reason in ("stop", None, "length", "content_filter"):
            with self.subTest(finish_reason=finish_reason):
                msg = message()
                review, cfg = self.review(msg)
                raw = json.dumps(decision(msg))
                body = json.dumps({"choices": [{"finish_reason": finish_reason, "message": {"content": raw}}]}).encode()
                async def chunks(_size):
                    yield body
                context = AsyncMock()
                context.__aenter__.return_value = SimpleNamespace(status=200, content=SimpleNamespace(iter_chunked=chunks))
                review.session = SimpleNamespace(post=Mock(return_value=context))
                if finish_reason in ("stop", None):
                    self.assertEqual(await review.request(cfg["rules"]["llm"], []), raw)
                else:
                    with self.assertRaisesRegex(ValueError, "endpoint_incomplete_response"):
                        await review.review(msg, fingerprint(msg))
                    review.automod._execute_action.assert_not_awaited()

    async def test_raw_edits_route_content_but_ignore_embed_only_updates(self):
        cog = AutoMod(SimpleNamespace(db=SimpleNamespace()))
        cog.llm.enqueue = Mock()
        await cog.on_raw_message_edit(SimpleNamespace(data={"embeds": []}))
        cog.llm.enqueue.assert_not_called()
        payload = SimpleNamespace(data={"content": "edited"})
        await cog.on_raw_message_edit(payload)
        cog.llm.enqueue.assert_called_once_with(payload=payload)

    def review(self, msg):
        llm = {**DEFAULT_LLM_CONFIG, "enabled": True, "rules_text": "No insultar", "context_messages": 0,
               "endpoint_url": "https://llm.example/v1/chat/completions", "model": "moderator"}
        cfg = {"enabled": 0, "rules": {"llm": llm, "ignored": {}}}
        db = SimpleNamespace(get_automod_config=lambda _id: deepcopy(cfg), has_llm_message_action=lambda *_: False,
                             log_automod_action=lambda *args, **kwargs: self.logs.append(args))
        automod = SimpleNamespace(db=db, bot=SimpleNamespace(db=db, user=SimpleNamespace(id=999)), _execute_action=AsyncMock())
        review = LLMReview(automod)
        review.exempt = lambda *_: False
        review.versions[msg.id] = fingerprint(msg)
        self.logs = []
        return review, cfg

    async def test_unsupported_attachment_does_not_bypass_text_and_unseen_image_is_not_evidence(self):
        msg = message()
        msg.attachments = [SimpleNamespace(id=55, filename="audio.mp3", size=10, content_type="audio/mpeg")]
        review, _ = self.review(msg)
        review.request = AsyncMock(return_value=json.dumps(decision(msg)))
        with self.assertLogs("LLMModeration", level="DEBUG") as logged:
            await review.review(msg, fingerprint(msg))
        review.automod._execute_action.assert_awaited_once()
        self.assertIn("outcome=partial_coverage", "\n".join(logged.output))
        self.assertEqual(self.logs, [])
        self.assertIsInstance(review.request.await_args.args[1][2]["content"], str)

    async def test_clean_message_analysis_does_not_create_moderation_action(self):
        msg = message()
        review, _ = self.review(msg)
        review.request = AsyncMock(return_value=json.dumps(decision(msg, action="none", reason="", rule="", evidence=[])))
        with self.assertLogs("LLMModeration", level="DEBUG") as logged:
            await review.review(msg, fingerprint(msg))
        review.automod._execute_action.assert_not_awaited()
        self.assertEqual(self.logs, [])
        self.assertIn("outcome=none", "\n".join(logged.output))

    async def test_superseded_edit_and_changed_live_message_never_enforce(self):
        for edit_kind in ("version", "content", "config"):
            msg = message()
            review, cfg = self.review(msg)
            async def response(*_):
                if edit_kind == "version":
                    review.versions[msg.id] = "new-version"
                elif edit_kind == "content":
                    msg.channel.fetch_message.return_value = message(text="edited")
                else:
                    cfg["rules"]["llm"]["rules_text"] = "New rules"
                return json.dumps(decision(msg))
            review.request = response
            await review.review(msg, fingerprint(msg))
            review.automod._execute_action.assert_not_awaited()

    async def test_history_is_chronological_bounded_and_user_scoped(self):
        msg = message()
        previous = [message(9, "new"), message(8, "other user"), message(7, "old")]
        previous[1].author.id = 99
        seen = []
        async def history(**kwargs):
            seen.append(kwargs)
            for item in previous:
                yield item
        msg.channel.history = history
        review, cfg = self.review(msg)
        cfg["rules"]["llm"].update(context_messages=2, context_mode="user")
        rows, scanned = await review.history(msg, cfg["rules"]["llm"])
        self.assertEqual([row["message_id"] for row in rows], ["7", "9"])
        self.assertEqual(scanned, 3)
        self.assertEqual(seen[0]["limit"], 500)
        self.assertIs(seen[0]["before"], msg)

    async def test_reply_payload_links_trigger_and_history_without_duplicate_bodies(self):
        msg, parent, previous = message(), message(7, "una cita"), message(9, "respuesta")
        parent.author.id = 99
        msg.reference = SimpleNamespace(message_id=9, channel_id=40, guild_id=30)
        previous.reference = SimpleNamespace(message_id=7, channel_id=40, guild_id=30)
        async def history(**_):
            for source in (previous, parent):
                yield source
        msg.channel.history = history
        review, cfg = self.review(msg)
        cfg["rules"]["llm"].update(context_messages=2, context_mode="channel")
        review.request = AsyncMock(return_value=json.dumps(decision(msg, action="none", reason="", rule="", evidence=[])))
        await review.review(msg, fingerprint(msg))
        payload = review.request.await_args.args[1]
        context, trigger = json.loads(payload[1]["content"]), json.loads(payload[2]["content"])
        self.assertEqual(trigger["reply_to"], {"message_id": "9", "status": "in_context"})
        self.assertEqual(context["messages"][1]["reply_to"], {"message_id": "7", "status": "in_context"})
        self.assertEqual(context["messages"][0]["author_id"], "99")
        self.assertEqual(context["referenced_messages"], [])
        msg.channel.fetch_message.assert_awaited_once_with(msg.id)
        review.automod._execute_action.assert_not_awaited()

    async def test_user_context_adds_direct_reply_targets_outside_window_without_recursing(self):
        msg, previous, parent, older = message(), message(9), message(5, "x" * 5000), message(4, "otra persona")
        parent.author.id, older.author.id = 99, 98
        msg.reference = SimpleNamespace(message_id=5, channel_id=40, guild_id=30)
        previous.reference = SimpleNamespace(message_id=4, channel_id=40, guild_id=30)
        parent.reference = SimpleNamespace(message_id=3, channel_id=40, guild_id=30)
        async def history(**_):
            yield parent
            yield previous
        msg.channel.history = history
        msg.channel.fetch_message = AsyncMock(side_effect=lambda mid: {5: parent, 4: older, 10: msg}[mid])
        review, cfg = self.review(msg)
        cfg["rules"]["llm"].update(context_messages=1, context_mode="user")
        review.request = AsyncMock(return_value=json.dumps(decision(msg, action="none", reason="", rule="", evidence=[])))
        await review.review(msg, fingerprint(msg))
        payload = review.request.await_args.args[1]
        context, trigger = json.loads(payload[1]["content"]), json.loads(payload[2]["content"])
        self.assertEqual([row["message_id"] for row in context["messages"]], ["9"])
        self.assertEqual([row["author_id"] for row in context["referenced_messages"]], ["99", "98"])
        self.assertEqual(len(context["referenced_messages"][0]["text"]), 4000)
        self.assertTrue(context["referenced_messages"][0]["text_truncated"])
        self.assertEqual(trigger["reply_to"]["status"], "available")
        self.assertEqual(context["messages"][0]["reply_to"]["status"], "available")
        self.assertEqual([call.args[0] for call in msg.channel.fetch_message.await_args_list], [5, 4, 10])

    async def test_zero_context_keeps_reply_metadata_without_reading_context(self):
        msg = message()
        msg.reference = SimpleNamespace(message_id=5, channel_id=40, guild_id=30,
                                        resolved=message(5, "no debe enviarse"))
        msg.channel.history = Mock(side_effect=AssertionError("history disabled"))
        review, _ = self.review(msg)
        review.request = AsyncMock(return_value=json.dumps(decision(msg, action="none", reason="", rule="", evidence=[])))
        await review.review(msg, fingerprint(msg))
        payload = review.request.await_args.args[1]
        self.assertEqual(json.loads(payload[2]["content"])["reply_to"], {"message_id": "5", "status": "context_disabled"})
        self.assertNotIn("no debe enviarse", json.dumps(payload))
        msg.channel.fetch_message.assert_awaited_once_with(msg.id)

    async def test_reply_targets_fail_closed_for_scope_permissions_and_unavailable_sources(self):
        response = SimpleNamespace(status=404, reason="Not Found")
        cases = [
            ({"channel_id": 41}, None, "outside_scope"),
            ({"guild_id": 31}, None, "outside_scope"),
            ({}, "permissions", "forbidden"),
            ({}, "invisible", "forbidden"),
            ({}, "missing_member", "forbidden"),
            ({}, discord.NotFound(response, "gone"), "not_found"),
            ({}, discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "hidden"), "forbidden"),
            ({}, discord.HTTPException(SimpleNamespace(status=500, reason="Error"), "failure"), "unavailable"),
            ({}, asyncio.TimeoutError(), "timeout"),
            ({}, "wrong_source", "unavailable"),
        ]
        for changes, failure, status in cases:
            with self.subTest(status=status, changes=changes):
                msg = message()
                msg.reference = SimpleNamespace(**{"message_id": 5, "channel_id": 40, "guild_id": 30, **changes},
                                                resolved=message(5, "cached private text"))
                review, cfg = self.review(msg)
                cfg["rules"]["llm"]["context_messages"] = 1
                if failure == "permissions":
                    msg.channel.permissions_for = lambda _: SimpleNamespace(view_channel=True, read_message_history=False)
                elif failure == "invisible":
                    msg.channel.permissions_for = lambda _: SimpleNamespace(view_channel=False, read_message_history=True)
                elif failure == "missing_member":
                    msg.guild.me = None
                elif failure == "wrong_source":
                    wrong = message(5, "wrong channel text")
                    wrong.channel.id = 41
                    msg.channel.fetch_message.return_value = wrong
                else:
                    msg.channel.fetch_message.side_effect = failure
                reply, sources = await review.reply_context(msg, cfg["rules"]["llm"], [])
                self.assertEqual(reply, {"message_id": "5", "status": status})
                self.assertEqual(sources, [])
                if status == "outside_scope" or failure in ("permissions", "invisible", "missing_member"):
                    msg.channel.fetch_message.assert_not_awaited()

    async def test_forwarded_message_is_not_treated_as_a_reply(self):
        msg = message()
        msg.reference = SimpleNamespace(message_id=5, channel_id=40, guild_id=30,
                                        type=discord.MessageReferenceType.forward)
        review, cfg = self.review(msg)
        cfg["rules"]["llm"]["context_messages"] = 1
        reply, sources = await review.reply_context(msg, cfg["rules"]["llm"], [])
        self.assertIsNone(reply)
        self.assertEqual(sources, [])
        msg.channel.fetch_message.assert_not_awaited()

    async def test_reply_fetch_budget_prioritizes_trigger_and_deduplicates_targets(self):
        msg = message(30)
        msg.reference = SimpleNamespace(message_id=1, channel_id=40, guild_id=30)
        rows = [{"message_id": str(mid), "reply_to": {"message_id": str(target), "status": "unresolved"}}
                for mid, target in ((20, 5), (21, 4), (22, 3), (23, 2), (24, 1))]
        msg.channel.fetch_message = AsyncMock(side_effect=lambda mid: message(mid))
        review, cfg = self.review(msg)
        cfg["rules"]["llm"]["context_messages"] = 5
        reply, sources = await review.reply_context(msg, cfg["rules"]["llm"], rows)
        self.assertEqual(reply["status"], "available")
        self.assertEqual([call.args[0] for call in msg.channel.fetch_message.await_args_list], [1, 2, 3])
        self.assertEqual([row["message_id"] for row in sources], ["1", "2", "3"])
        self.assertEqual([row["reply_to"]["status"] for row in rows], ["limit_reached", "limit_reached", "available", "available", "available"])

    async def test_same_message_is_enforced_once_and_deterministic_claim_blocks_review(self):
        msg = message()
        review, _ = self.review(msg)
        review.request = AsyncMock(return_value=json.dumps(decision(msg)))
        await review.review(msg, fingerprint(msg))
        await review.review(msg, fingerprint(msg))
        review.automod._execute_action.assert_awaited_once()
        other = message(11)
        review.mark_deterministic(other.id)
        await review.review(other, "version")
        review.request.assert_awaited_once()

    async def test_dns_resolution_blocks_private_addresses_and_rebinding(self):
        resolver = EndpointResolver()
        resolver.resolver.resolve = AsyncMock(return_value=[{"host": "127.0.0.1"}])
        with patch.dict("os.environ", {"CATBOT_LLM_ALLOWED_HOSTS": ""}), self.assertRaises(OSError):
            await resolver.resolve("public.example", 443)
        with patch.dict("os.environ", {"CATBOT_LLM_ALLOWED_HOSTS": "public.example"}):
            self.assertEqual((await resolver.resolve("public.example", 443))[0]["host"], "127.0.0.1")
        await resolver.close()

    async def test_endpoint_failure_is_logged_without_punishment_or_provider_details(self):
        msg = message()
        review, _ = self.review(msg)
        review.request = AsyncMock(side_effect=RuntimeError("secret-provider-body"))
        import time
        review.queue.put_nowait((msg, None, fingerprint(msg), time.monotonic()))
        with self.assertLogs("LLMModeration", level="WARNING") as logged:
            task = asyncio.create_task(review.worker())
            await review.queue.join()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        review.automod._execute_action.assert_not_awaited()
        self.assertEqual(self.logs, [])
        self.assertIn("outcome=error_no_action", "\n".join(logged.output))
        self.assertNotIn("secret-provider-body", "\n".join(logged.output))

    async def test_images_are_only_downloaded_when_enabled_and_are_data_urls(self):
        msg = message()
        attachment = SimpleNamespace(id=55, filename="picture.png", content_type="image/png", size=3,
                                     read=AsyncMock(return_value=b"png"))
        msg.attachments = [attachment]
        review, cfg = self.review(msg)
        parts, image_ids, skipped = await review.image_parts(msg, cfg["rules"]["llm"])
        attachment.read.assert_not_awaited()
        self.assertEqual((parts, image_ids, skipped), ([], set(), 1))
        cfg["rules"]["llm"]["supports_images"] = True
        parts, image_ids, skipped = await review.image_parts(msg, cfg["rules"]["llm"])
        self.assertEqual(image_ids, {"55"})
        self.assertEqual(skipped, 0)
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        attachment.read.reset_mock()
        attachment.size = 8 * 1024 * 1024 + 1
        parts, image_ids, skipped = await review.image_parts(msg, cfg["rules"]["llm"])
        attachment.read.assert_not_awaited()
        self.assertEqual((parts, image_ids, skipped), ([], set(), 1))


class ConfigPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dns = patch("api.routes.guild.resolve_endpoint_addresses", AsyncMock(return_value=["93.184.216.34"]))
        self.dns.start()
        self.db = DatabaseManager.__new__(DatabaseManager)
        self.db.db_type = "sqlite"
        self.db._sqlite_lock = threading.Lock()
        self.db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.db._sqlite_conn.row_factory = sqlite3.Row
        with patch.object(logging.getLogger("Database"), "disabled", True):
            self.db._init_schema()

    async def asyncTearDown(self):
        self.dns.stop()
        self.db._sqlite_conn.close()

    async def test_config_key_redaction_preservation_clearing_and_default_disabled(self):
        initial = await get_automod_config(30, self.db, None)
        self.assertFalse(initial["rules"]["llm"]["enabled"])
        response = await patch_automod_config(30, {"rules": {"llm": {"api_key": "secret-value"}}}, self.db, None)
        public = response["config"]
        self.assertNotIn("secret-value", json.dumps(public))
        self.assertTrue(public["rules"]["llm"]["api_key_configured"])
        await patch_automod_config(30, public, self.db, None)
        self.assertEqual(self.db.get_automod_config(30)["rules"]["llm"]["api_key"], "secret-value")
        await patch_automod_config(30, {"rules": {"spam": {"enabled": True}}}, self.db, None)
        self.assertEqual(self.db.get_automod_config(30)["rules"]["llm"]["api_key"], "secret-value")
        await patch_automod_config(30, {"rules": {"llm": {"api_key_clear": True}}}, self.db, None)
        self.assertEqual(self.db.get_automod_config(30)["rules"]["llm"]["api_key"], "")
        self.assertTrue(self.db.get_automod_config(30)["rules"]["spam"]["enabled"])
        for body in ({"rules": []}, {"rules": {"llm": {"enabled": True}}}):
            with self.assertRaises(HTTPException):
                await patch_automod_config(30, body, self.db, None)

    async def test_endpoint_change_preserves_old_key_unless_explicitly_replaced(self):
        await patch_automod_config(30, {"rules": {"llm": {"endpoint_url": "https://one.example/v1/chat/completions", "api_key": "first-secret"}}}, self.db, None)
        await patch_automod_config(30, {"rules": {"llm": {"endpoint_url": "https://one.example/v1/chat/completions"}}}, self.db, None)
        self.assertEqual(self.db.get_automod_config(30)["rules"]["llm"]["api_key"], "first-secret")
        result = await patch_automod_config(30, {"rules": {"llm": {"endpoint_url": "https://two.example/v1/chat/completions"}}}, self.db, None)
        self.assertTrue(result["config"]["rules"]["llm"]["api_key_configured"])
        self.assertEqual(self.db.get_automod_config(30)["rules"]["llm"]["api_key"], "first-secret")
        await patch_automod_config(30, {"rules": {"llm": {"endpoint_url": "https://three.example/v1/chat/completions", "api_key": "new-secret"}}}, self.db, None)
        self.assertEqual(self.db.get_automod_config(30)["rules"]["llm"]["api_key"], "new-secret")

    async def test_action_log_excludes_diagnostics_before_limit_and_preserves_legacy_rows(self):
        for rule in ("llm", "spam"):
            for action in ("delete", "warn", "mute", "kick", "ban"):
                self.db.log_automod_action(30, rule, 20, "applied", action)
        expected = self.db.get_automod_log(30, limit=3)
        diagnostics = ("none", "partial_coverage", "skipped_changed", "error_no_action", "delete_failed", "deletion_notice_failed", "enforcement_not_confirmed")
        for outcome in diagnostics:
            self.db.log_automod_action(30, "llm", 20, "diagnostic", outcome)
        self.assertEqual(self.db._fetchone("SELECT COUNT(*) AS n FROM automod_log")["n"], 10)
        for outcome in diagnostics:
            self.db._execute(
                "INSERT INTO automod_log (guild_id, rule, user_id, content, action_taken, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (30, "llm", 20, "legacy diagnostic", outcome, "9999"),
            )
        self.db.log_automod_action(31, "spam", 21, "other guild", "warn")
        exposed = await get_automod_log(30, 3, self.db, None)
        self.assertEqual([row["id"] for row in exposed], [row["id"] for row in expected])
        self.assertTrue(all(isinstance(row["user_id"], str) for row in exposed))
        self.assertTrue(all(row["action_taken"] in {"delete", "warn", "mute", "kick", "ban"} for row in exposed))
        self.assertEqual(len(self.db.get_automod_log(30)), 10)
        self.assertEqual({row["rule"] for row in self.db.get_automod_log(30)}, {"llm", "spam"})
        self.assertEqual(self.db._fetchone("SELECT COUNT(*) AS n FROM automod_log")["n"], 18)

    async def test_persisted_message_claim_survives_worker_restart(self):
        self.assertFalse(self.db.has_llm_message_action(30, 10))
        self.db.add_warn_with_action(20, 30, 999, "AUTO_WARN", "LLM message:10 No insultar")
        self.assertTrue(self.db.has_llm_message_action(30, 10))
        self.assertFalse(self.db.has_llm_message_action(30, 1))

    def sanction_fixture(self, action, duration=None, message_id=10):
        msg = message(message_id)
        guild = msg.guild
        guild.owner_id, guild.name, guild.channels = 1, "Test guild", []
        roles = [discord.Role(guild=guild, state=None, data={
            "id": str(role_id), "name": str(role_id), "position": position,
            "permissions": str(permissions), "managed": False,
        }) for role_id, position, permissions in ((30, 0, 0), (50, 1, 0), (60, 10, discord.Permissions(ban_members=True, kick_members=True, manage_roles=True, view_audit_log=True).value))]
        target = SimpleNamespace(id=20, _roles=[], bot=False, kick=AsyncMock(), add_roles=AsyncMock(), send=AsyncMock())
        bot_member = SimpleNamespace(id=999, _roles=[60], bot=True, guild=guild, top_role=roles[2])
        msg.author = target
        msg.delete = AsyncMock()
        guild.fetch_member = AsyncMock(side_effect=lambda uid: target if uid == 20 else bot_member)
        guild.fetch_roles = AsyncMock(return_value=roles)
        current_ban = SimpleNamespace(reason="")
        async def ban(_member, **kwargs):
            current_ban.reason = kwargs["reason"]
        guild.ban = AsyncMock(side_effect=ban)
        guild.fetch_ban = AsyncMock(return_value=current_ban)
        bot = SimpleNamespace(db=self.db, user=SimpleNamespace(id=999), fetch_guild=AsyncMock(return_value=guild))
        cog = AutoMod(bot)
        chosen = decision(msg, action=action, duration_seconds=duration)
        config = cog.llm.action_config(msg, chosen)
        cog._fresh_policy_allows_action = AsyncMock(return_value=True)
        cog._current_policy_allows_action = lambda *_: config
        cog._log_to_modlog = AsyncMock()
        cog._build_embed = lambda *_, **__: None
        return msg, guild, target, roles, cog, chosen, config

    async def test_llm_delete_only_persists_reason_evidence_and_notifies_once(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("delete")
        cog._build_embed = Mock(return_value=None)
        await cog._execute_action(msg, "llm", "delete", config)
        msg.delete.assert_awaited_once()
        msg.channel.send.assert_awaited_once()
        target.send.assert_not_awaited()
        notification = msg.channel.send.await_args.args[0]
        self.assertTrue(notification.startswith(f"<@{target.id}> "))
        self.assertIn(chosen["reason"], notification)
        self.assertIn(chosen["rule"], notification)
        self.assertIn("eliminado tu mensaje", notification)
        mentions = msg.channel.send.await_args.kwargs["allowed_mentions"]
        self.assertFalse(mentions.everyone)
        self.assertFalse(mentions.roles)
        self.assertEqual([user.id for user in mentions.users], [target.id])
        cases = self.db.list_cases(30)
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual((case["action_type"], case["status"]), ("AUTO_DELETE", "active"))
        self.assertIn(chosen["reason"], case["reason"])
        self.assertEqual(case["evidence_url"], msg.jump_url)
        self.assertEqual(json.loads(case["extra_data"])["decision"]["evidence"], chosen["evidence"])
        self.assertEqual(cog._build_embed.call_args.kwargs["extra"]["Motivo"], chosen["reason"])
        logs = self.db.get_automod_log(30)
        self.assertEqual(logs[0]["action_taken"], "delete")
        self.assertIn(chosen["reason"], logs[0]["content"])
        metadata = json.loads(logs[0]["extra_data"])
        self.assertEqual((metadata["message_id"], metadata["channel_id"]), (str(msg.id), str(msg.channel.id)))
        self.assertEqual(metadata["reason"], chosen["reason"])
        self.assertEqual(metadata["target_user"]["id"], str(target.id))
        await cog._execute_action(msg, "llm", "delete", config)
        self.assertEqual(len(self.db.list_cases(30)), 1)
        msg.delete.assert_awaited_once()
        msg.channel.send.assert_awaited_once()

    async def test_llm_delete_failure_and_missing_message_never_send_success_notice(self):
        for index, exception in enumerate((discord.Forbidden, discord.NotFound)):
            msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("delete", message_id=10 + index)
            error = exception(SimpleNamespace(status=403 if index == 0 else 404, reason="failure"), "failure")
            msg.delete.side_effect = error
            cog._build_embed = Mock(return_value=None)
            await cog._execute_action(msg, "llm", "delete", config)
            msg.channel.send.assert_not_awaited()
            target.send.assert_not_awaited()
            case = next(row for row in self.db.list_cases(30) if row["reason"].startswith(f"LLM message:{msg.id} "))
            self.assertEqual(case["status"], "failed")
            self.assertEqual(cog.llm.action_outcomes[msg.id], "delete_failed")
            self.assertEqual(cog._build_embed.call_args.args[1], "delete_failed")
            self.assertEqual(self.db.get_automod_log(30), [])
            self.assertTrue(self.db.has_llm_message_action(30, msg.id))

    async def test_concurrent_llm_delete_replay_has_one_case_deletion_and_notice(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("delete")
        async def policy(*_):
            await asyncio.sleep(0)
            return True
        cog._fresh_policy_allows_action.side_effect = policy
        await asyncio.gather(
            cog._execute_action(msg, "llm", "delete", config),
            cog._execute_action(msg, "llm", "delete", config),
        )
        self.assertEqual(len(self.db.list_cases(30)), 1)
        msg.delete.assert_awaited_once()
        msg.channel.send.assert_awaited_once()
        target.send.assert_not_awaited()

    async def test_deletion_keeps_reason_audit_when_kick_is_blocked_by_hierarchy(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("kick")
        target._roles = [60]
        await cog._execute_action(msg, "llm", "kick", config)
        target.kick.assert_not_awaited()
        msg.delete.assert_awaited_once()
        msg.channel.send.assert_awaited_once()
        self.assertEqual(self.db.list_cases(30), [])
        logs = self.db.get_automod_log(30)
        self.assertEqual(logs[0]["action_taken"], "delete")
        self.assertIn(chosen["reason"], logs[0]["content"])

    async def test_llm_delete_policy_revoked_has_no_case_deletion_or_notice(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("delete")
        cog._fresh_policy_allows_action.return_value = False
        await cog._execute_action(msg, "llm", "delete", config)
        msg.delete.assert_not_awaited()
        msg.channel.send.assert_not_awaited()
        target.send.assert_not_awaited()
        self.assertEqual(self.db.list_cases(30), [])

    async def test_notice_generation_runs_after_warn_is_persisted(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("warn")
        async def check_notice(*args, **kwargs):
            self.assertEqual(self.db.get_user(20, 30)["warns"], 1)
            self.assertEqual(cog.llm.action_outcomes[msg.id], "warn")
            return args[2]
        with patch("cogs._managed_messages.category_settings", return_value={"automod": True}), patch("cogs._managed_messages.manage_payload", side_effect=check_notice) as rewrite:
            await cog._execute_action(msg, "llm", "warn", config)
        rewrite.assert_awaited_once()
        msg.channel.send.assert_awaited_once()

    async def test_failed_channel_notice_does_not_interrupt_warn_or_fall_back_to_dm(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("warn")
        msg.channel.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "channel unavailable")
        await cog._execute_action(msg, "llm", "warn", config)
        target.send.assert_not_awaited()
        self.assertEqual(self.db.get_user(20, 30)["warns"], 1)
        self.assertEqual(self.db.list_cases(30)[0]["action_type"], "AUTO_WARN")
        self.assertEqual({row["action_taken"] for row in self.db.get_automod_log(30)}, {"delete", "warn"})

    async def test_failed_removal_still_allows_warn_without_success_notice(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("warn")
        msg.delete.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "missing permission")
        await cog._execute_action(msg, "llm", "warn", config)
        msg.channel.send.assert_not_awaited()
        target.send.assert_not_awaited()
        self.assertEqual(self.db.get_user(20, 30)["warns"], 1)
        self.assertEqual([row["action_taken"] for row in self.db.get_automod_log(30)], ["warn"])

    async def test_llm_temporary_ban_uses_existing_atomic_case_and_expiry_scheduler(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("ban", 120)
        await cog._execute_action(msg, "llm", "ban", config)
        guild.ban.assert_awaited_once()
        rows = self.db.get_active_tempbans()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ban_duration"], 120)
        pending = self.db.get_pending_moderation_actions(30)
        self.assertTrue(any(row["action_type"] == "TEMPBAN_EXPIRE" for row in pending))
        self.assertEqual(cog.llm.action_outcomes[msg.id], "ban")

    async def test_llm_warn_is_only_warn_even_with_legacy_escalation_enabled(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("warn")
        self.db.set_config(30, warn_ban_enabled=1, warn_ban_threshold=1)
        await cog._execute_action(msg, "llm", "warn", config)
        self.assertEqual(self.db.get_user(20, 30)["warns"], 1)
        self.assertEqual([row["action_type"] for row in self.db.list_cases(30)], ["AUTO_WARN"])
        guild.ban.assert_not_awaited()
        target.kick.assert_not_awaited()

    async def test_llm_kick_bounds_audit_reason_and_retains_full_case_reason(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("kick")
        chosen["reason"] = "x" * 1500
        config.update(cog.llm.action_config(msg, chosen))
        await cog._execute_action(msg, "llm", "kick", config)
        self.assertEqual(len(target.kick.await_args.kwargs["reason"]), 512)
        self.assertIn("x" * 1500, self.db.list_cases(30)[0]["reason"])

    async def test_llm_policy_revoked_and_hierarchy_prevent_sanctions(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("kick")
        cog._fresh_policy_allows_action.return_value = False
        await cog._execute_action(msg, "llm", "kick", config)
        target.kick.assert_not_awaited()
        msg.delete.assert_not_awaited()
        cog._fresh_policy_allows_action.return_value = True
        target._roles = [60]
        await cog._execute_action(msg, "llm", "kick", config)
        target.kick.assert_not_awaited()
        self.assertEqual(self.db.list_cases(30), [])

    async def test_llm_mute_prepares_exact_duration_and_existing_expiry_job(self):
        msg, guild, target, roles, cog, chosen, config = self.sanction_fixture("mute", 321)
        self.db.set_config(30, mute_role_id=50)
        moderation = Moderation.__new__(Moderation)
        moderation.db, moderation.bot = self.db, cog.bot
        moderation._confirm_effective_mute = AsyncMock(return_value=target)
        moderation._confirm_mute_effect_state = AsyncMock(return_value="match")
        cog.bot.get_cog = lambda _: moderation
        cog._resolve_mute_role = AsyncMock(return_value=roles[1])
        with patch("cogs.automod.mute_role_has_effective_denies", return_value=True):
            await cog._execute_action(msg, "llm", "mute", config)
        target.add_roles.assert_awaited_once()
        case = self.db.list_cases(30)[0]
        self.assertEqual((case["action_type"], case["duration_seconds"], case["status"]), ("AUTO_MUTE", 321, "active"))
        self.assertTrue(any(row["action_type"] == "MUTE_EXPIRE" for row in self.db.get_pending_moderation_actions(30)))


class CompletionMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_incomplete_metadata_is_safe_and_distinguishes_limits_in_both_protocols(self):
        from cogs._llm_moderation import EndpointIncompleteResponse
        cases = [
            ("chat_completions", {"choices": [{"finish_reason": "length", "message": {"content": "PRIVATE_TRUNCATED"}}]}, "length"),
            ("chat_completions", {"choices": [{"finish_reason": "PRIVATE_REASON", "message": {"content": "PRIVATE_TRUNCATED"}}]}, "unknown"),
            ("responses", {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": "PRIVATE_TRUNCATED"}, "max_output_tokens"),
            ("responses", {"status": "incomplete", "incomplete_details": {"reason": {"PRIVATE_REASON": 1}}}, "unknown")]
        for protocol, body, reason in cases:
            with self.subTest(protocol=protocol, reason=reason), patch("cogs._llm_moderation.endpoint_json", new=AsyncMock(return_value=body)):
                with self.assertRaises(EndpointIncompleteResponse) as caught:
                    await request_completion(None, {"model": "fixture", "api_type": protocol}, [])
                self.assertEqual(caught.exception.reason, reason)
                self.assertEqual(str(caught.exception), "endpoint_incomplete_response")
                self.assertNotIn("PRIVATE", repr(caught.exception.__dict__))
