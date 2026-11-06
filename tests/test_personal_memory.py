"""Automatic personal memories: isolated DB, Discord fixtures and mocked model."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from cogs._personal_memory import memory_candidate
from tests import test_conversation_memory as fixtures

database = fixtures.database


def proposal(quote="Prefiero respuestas breves", **extra):
    return {"role": "assistant", "content": "Perfecto.", "tool_calls": [{"id": "memory", "type": "function",
        "function": {"name": "remember_personal_preference", "arguments": json.dumps({"quote": quote, **extra})}}]}


class CandidateTest(unittest.TestCase):
    def test_only_exact_current_self_statement_without_external_identity(self):
        quote = "Prefiero respuestas breves"
        self.assertEqual(memory_candidate({"quote": quote}, quote), quote)
        self.assertEqual(memory_candidate({"quote": quote}, "<@999> Hola gato, " + quote), quote)
        self.assertEqual(memory_candidate({"quote": "uso Arch Linux"}, "Hola gato, uso Arch Linux"), "uso Arch Linux")
        self.assertEqual(memory_candidate({"quote": "Soy programador"}, "Soy programador"), "Soy programador")
        for args, trigger in (({"quote": quote}, "hola"), ({"quote": quote, "user_id": "31"}, quote),
                ({"quote": "A Luis le gusta el fútbol"}, "A Luis le gusta el fútbol"),
                ({}, quote), ({"quote": 7}, quote), ({"quote": "Prefiero mi contraseña abc123"}, "Prefiero mi contraseña abc123"),
                ({"quote": "Me gusta <@31>"}, "Me gusta <@31>"),
                ({"quote": "Prefiero respuestas breves"}, '> Prefiero respuestas breves'),
                ({"quote": "Me gusta mi tratamiento médico"}, "Me gusta mi tratamiento médico")):
            with self.subTest(args=args, trigger=trigger):
                self.assertIsNone(memory_candidate(args, trigger))


class PersonalMemoryDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.db = database()

    def tearDown(self):
        self.db._sqlite_conn.close()

    def save(self, message_id=100, user=30, channel=20, quote="Prefiero respuestas breves", revision=None):
        return self.db.save_ai_personal_memory(10, user, channel, message_id, quote,
            self.db.get_ai_memory_revision(10, channel, user) if revision is None else revision)

    def test_separate_manual_scoped_ownership_and_duplicate(self):
        self.db.set_ai_memory(10, "user", 30, 20, "Nota manual", True)
        memory_id = self.save()
        self.assertTrue(memory_id)
        self.assertEqual(self.db.get_ai_memories(10, "user", 30)[0]["content"], "Nota manual")
        self.assertFalse(self.save(message_id=101))
        self.assertEqual(len(self.db.get_ai_personal_memories(10, 30)), 1)
        self.assertFalse(self.db.edit_ai_personal_memory(10, 31, memory_id, "Cambio"))
        self.assertFalse(self.db.delete_ai_personal_memory(11, 30, memory_id))
        self.assertTrue(self.db.edit_ai_personal_memory(10, 30, memory_id, "Prefiero ejemplos"))
        self.assertEqual(self.db.get_ai_personal_memories(10, 30)[0]["content"], "Prefiero ejemplos")

    def test_pause_revision_and_delete_tombstone_prevent_stale_resurrection(self):
        revision = self.db.get_ai_memory_revision(10, 20, 30)
        memory_id = self.save()
        self.db.set_ai_personal_memory_enabled(10, 30, False)
        self.assertFalse(self.save(101))
        self.assertEqual(len(self.db.get_ai_personal_memories(10, 30)), 1)
        self.db.set_ai_personal_memory_enabled(10, 30, True)
        self.assertFalse(self.save(102, revision=revision))
        self.assertTrue(self.db.delete_ai_personal_memory(10, 30, memory_id))
        self.assertFalse(self.save(100))
        self.assertEqual(self.db.get_ai_personal_memories(10, 30), [])

    def test_clear_both_types_preserves_other_people_and_bounds(self):
        self.db.set_ai_memory(10, "user", 30, 20, "Manual")
        for index in range(22):
            self.save(100 + index, quote=f"Me gusta el juego {index}")
        self.assertEqual(len(self.db.get_ai_personal_memories(10, 30)), 20)
        self.save(200, user=31)
        self.db.clear_ai_memory(10, "user", 30)
        self.assertEqual(self.db.get_ai_personal_memories(10, 30), [])
        self.assertFalse(self.save(121))
        self.assertEqual(len(self.db.get_ai_personal_memories(10, 31)), 1)

    def test_source_edit_and_channel_clear_remove_only_derived_local_memories(self):
        self.save()
        self.save(101, user=31)
        self.save(102, user=31, channel=21, quote="Me gusta Python")
        self.db.invalidate_ai_chat(10, 20, 100)
        self.assertEqual(self.db.get_ai_personal_memories(10, 30), [])
        self.db.clear_ai_memory(10, "chat", 20)
        rows = self.db.get_ai_personal_memories(10, 31)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_channel"], 21)

    def test_reopen_preserves_settings_automatic_rows_and_manual_notes(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "personal.db"
            db = database(path)
            revision = db.get_ai_memory_revision(10, 20, 30)
            db.save_ai_personal_memory(10, 30, 20, 100, "Prefiero respuestas breves", revision)
            db.set_ai_personal_memory_enabled(10, 30, False)
            db._sqlite_conn.close()
            db = database(path)
            try:
                self.assertEqual(len(db.get_ai_personal_memories(10, 30)), 1)
                self.assertFalse(db.get_ai_personal_memory_settings(10, 30)["enabled"])
            finally:
                db._sqlite_conn.close()


class PersonalMemoryRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = fixtures.ConversationRuntimeTest()
        await self.fixture.asyncSetUp()

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()

    async def run_message(self, response, text="Prefiero respuestas breves"):
        f = self.fixture
        message = f.message(ping=True)
        message.content = text
        await f.engine.listen(message)
        request = AsyncMock(return_value=response)
        with patch("cogs._conversation.request_completion", new=request):
            await f.engine.process(f.cog._queue.get_nowait())
        return message, request

    async def test_opportunistic_same_call_save_notice_and_local_profile(self):
        f = self.fixture
        message, request = await self.run_message(proposal(), text="<@999> Hola gato, Prefiero respuestas breves")
        self.assertEqual(request.await_count, 1)
        rows = f.db.get_ai_personal_memories(10, 30)
        self.assertEqual(rows[0]["content"], "Prefiero respuestas breves")
        self.assertIn("guardado", message.reply.await_args.args[0])
        self.assertNotIn("Prefiero respuestas breves", message.reply.await_args.args[0])
        self.assertEqual((await f.engine.memories(f.message(channel_id=21)))[1], [])
        self.assertEqual((await f.engine.memories(f.message(user_id=31)))[1], [])
        self.assertEqual((await f.engine.memories(f.message()))[1][0]["text"], rows[0]["content"])

    async def test_bad_candidate_does_not_block_normal_reply_or_save(self):
        malformed = proposal()
        malformed["tool_calls"][0]["function"]["arguments"] = "{"
        duplicate = proposal()
        duplicate["tool_calls"] *= 2
        for response in (proposal(user_id="31"), proposal(quote="Me gusta el fútbol"), malformed, duplicate):
            with self.subTest(response=response):
                message, _ = await self.run_message(response)
                self.assertEqual(message.reply.await_args.args[0], "Perfecto.")
                self.assertEqual(self.fixture.db.get_ai_personal_memories(10, 30), [])

    async def test_unexpected_tool_cannot_authorize_memory_storage(self):
        response = proposal()
        response["tool_calls"].append({"id": "unknown", "type": "function", "function": {"name": "set_user_id", "arguments": "{}"}})
        message, _ = await self.run_message(response)
        self.assertEqual(self.fixture.db.get_ai_personal_memories(10, 30), [])
        self.assertNotIn("guardado", message.reply.await_args.args[0])

    async def test_paused_has_no_tool_and_normal_messages_have_no_extra_call(self):
        f = self.fixture
        f.db.set_ai_personal_memory_enabled(10, 30, False)
        message, request = await self.run_message("Hola")
        self.assertEqual(request.await_count, 1)
        tools = request.await_args.kwargs["tools"]
        self.assertNotIn("remember_personal_preference", [tool["function"]["name"] for tool in tools])
        self.assertEqual(message.reply.await_args.args[0], "Hola")

    async def test_clear_during_generation_discards_candidate_and_reply(self):
        f = self.fixture
        message = f.message(ping=True)
        message.content = "Prefiero respuestas breves"
        await f.engine.listen(message)
        async def complete(*args, **kwargs):
            f.db.clear_ai_memory(10, "user", 30)
            return proposal()
        with patch("cogs._conversation.request_completion", new=complete):
            await f.engine.process(f.cog._queue.get_nowait())
        self.assertEqual(f.db.get_ai_personal_memories(10, 30), [])
        message.reply.assert_not_awaited()

    async def test_storage_failure_keeps_answer_and_does_not_announce_save(self):
        with patch.object(self.fixture.db, "save_ai_personal_memory", side_effect=RuntimeError("private fixture")):
            message, _ = await self.run_message(proposal())
        message.reply.assert_awaited_once()
        self.assertEqual(message.reply.await_args.args[0], "Perfecto.")

    async def test_auto_addition_preserves_already_queued_replies_same_or_other_channel(self):
        f = self.fixture
        for index, channel_id in enumerate((20, 21)):
            first = f.message(200 + index * 2, ping=True)
            first.content = f"Me gusta el juego {index}"
            second = f.message(201 + index * 2, channel_id=channel_id, ping=True)
            await f.engine.listen(first)
            await f.engine.listen(second)
            revision = f.db.get_ai_memory_revision(10, 20, 30)
            with patch("cogs._conversation.request_completion", new=AsyncMock(side_effect=[proposal(first.content), "Aquí estoy."])) as provider:
                await f.engine.process(f.cog._queue.get_nowait())
                self.assertEqual(f.db.get_ai_memory_revision(10, 20, 30), revision)
                await f.engine.process(f.cog._queue.get_nowait())
            self.assertEqual(provider.await_count, 2)
            self.assertEqual(second.reply.await_args.args[0], "Aquí estoy.")

    async def test_automatic_addition_during_generation_does_not_discard_reply(self):
        f = self.fixture
        message = f.message(ping=True)
        await f.engine.listen(message)
        async def complete(*args, **kwargs):
            f.db.save_ai_personal_memory(10, 30, 20, 90, "Me gusta Python", f.db.get_ai_memory_revision(10, 20, 30))
            return "Respuesta conservada."
        with patch("cogs._conversation.request_completion", new=complete):
            await f.engine.process(f.cog._queue.get_nowait())
        self.assertEqual(message.reply.await_args.args[0], "Respuesta conservada.")

    async def test_deletion_during_delivery_does_not_save_or_announce(self):
        f = self.fixture
        message = f.message(ping=True)
        message.content = "Prefiero respuestas breves"
        sent = message.reply.return_value
        async def deliver(*args, **kwargs):
            f.db.clear_ai_memory(10, "user", 30)
            return sent
        message.reply.side_effect = deliver
        await f.engine.listen(message)
        with patch("cogs._conversation.request_completion", new=AsyncMock(return_value=proposal())):
            await f.engine.process(f.cog._queue.get_nowait())
        self.assertEqual(f.db.get_ai_personal_memories(10, 30), [])
        message.reply.assert_awaited_once()

    async def test_notice_failure_preserves_success_without_generic_error(self):
        f = self.fixture
        message = f.message(ping=True)
        message.content = "Prefiero respuestas breves"
        message.reply.side_effect = [message.reply.return_value,
            discord.HTTPException(SimpleNamespace(status=500, reason="server error"), "transient")]
        await f.engine.listen(message)
        with patch("cogs._conversation.request_completion", new=AsyncMock(return_value=proposal())):
            await f.engine.process(f.cog._queue.get_nowait())
        self.assertEqual(len(f.db.get_ai_personal_memories(10, 30)), 1)
        self.assertEqual(message.reply.await_count, 2)
        self.assertEqual(message.reply.await_args_list[0].args[0], "Perfecto.")
        f.cog._inc.assert_called_with("success")

    async def test_private_commands_edit_delete_pause_and_existing_clean_command(self):
        from cogs.ia import IA
        f = self.fixture
        await self.run_message(proposal())
        memory_id = f.db.get_ai_personal_memories(10, 30)[0]["memory_id"]
        interaction = SimpleNamespace(guild=f.guild, guild_id=10, channel_id=20, user=f.members[30],
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await IA.ai_memory.callback(f.cog, interaction, "ver")
        self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])
        self.assertIn(memory_id, interaction.followup.send.await_args.args[0])
        await IA.ai_memory.callback(f.cog, interaction, "editar_auto", texto="Prefiero ejemplos", recuerdo=memory_id)
        self.assertEqual(f.db.get_ai_personal_memories(10, 30)[0]["content"], "Prefiero ejemplos")
        interaction.user = f.members[31]
        await IA.ai_memory.callback(f.cog, interaction, "borrar_auto", recuerdo=memory_id)
        self.assertEqual(len(f.db.get_ai_personal_memories(10, 30)), 1)
        interaction.user = f.members[30]
        await IA.ai_memory.callback(f.cog, interaction, "pausar_auto")
        self.assertFalse(f.db.get_ai_personal_memory_settings(10, 30)["enabled"])
        self.assertEqual(len(f.db.get_ai_personal_memories(10, 30)), 1)
        await IA.ai_memory.callback(f.cog, interaction, "borrar_auto", recuerdo=memory_id)
        self.assertEqual(f.db.get_ai_personal_memories(10, 30), [])
        f.cog._chat_histories = {}
        f.db.set_ai_memory(10, "user", 30, 20, "Manual")
        await IA.iaclear.callback(f.cog, interaction)
        self.assertEqual(f.db.get_ai_memories(10, "user", 30), [])
        self.assertEqual(f.db.get_ai_personal_memories(10, 30), [])

    async def test_tool_without_content_continues_only_on_memory_proposal_for_both_protocols(self):
        from tests.test_conversation_responses import response, text_item, function_item
        f = self.fixture
        for index, protocol in enumerate(("chat_completions", "responses")):
            f.db.set_automod_config(10, rules={"llm": {"endpoint_url": "https://provider.example/v1",
                "api_type": protocol, "model": "fictitious", "enabled": False}})
            quote = f"Me gusta el lenguaje {protocol}"
            message = f.message(200 + index, ping=True)
            message.content = quote
            await f.engine.listen(message)
            if protocol == "responses":
                replies = [response(function_item("remember_personal_preference", {"quote": quote}, "memory", "memory_item")),
                    response(text_item("Perfecto."))]
            else:
                first = proposal(quote)
                first["content"] = None
                replies = [{"choices": [{"finish_reason": "tool_calls", "message": first}]},
                    {"choices": [{"finish_reason": "stop", "message": {"content": "Perfecto."}}]}]
            with patch("cogs._llm_moderation.endpoint_json", new=AsyncMock(side_effect=replies)) as provider:
                await f.engine.process(f.cog._queue.get_nowait())
            self.assertEqual(provider.await_count, 2)
            self.assertEqual(message.reply.await_args_list[0].args[0], "Perfecto.")
            self.assertIn(quote, [row["content"] for row in f.db.get_ai_personal_memories(10, 30)])
