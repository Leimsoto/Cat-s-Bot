"""Model-directed research completion, checkpoints and real failure boundaries."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests import test_conversation_memory as fixtures


report = fixtures.research_report


def fact(claim, url, quote):
    return {"claim": claim, "status": "supported", "support": [{"url": url, "quote": quote}]}


class ModelResearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = fixtures.ConversationRuntimeTest()
        await self.fixture.asyncSetUp()
        self.engine = self.fixture.engine
        self.fixture.db.set_ai_config(10, ai_web_enabled=1)
        await self.engine.listen(self.fixture.message(ping=True))
        self.job = self.fixture.cog._queue.get_nowait()

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()

    def call(self, name, argument, index=0):
        return {"role": "assistant", "tool_calls": [self.fixture.tool_call(name, argument, f"call{index}")]}

    async def test_model_can_exceed_all_old_search_read_and_round_quotas(self):
        self.engine.web = SimpleNamespace(search_web=AsyncMock(return_value={"results": []}),
            read_webpage=AsyncMock(side_effect=lambda url, **_: {"url": url, "text": "Release 9 is current."}), close=AsyncMock())
        replies = [self.call("search_web", f"Example query {index}", index) for index in range(22)]
        replies += [self.call("read_webpage", f"https://official.example/{index}", index + 22) for index in range(14)]
        replies.append(report([fact("Current version", "https://official.example/13", "Release 9 is current.")], sufficient=True))
        with patch("cogs._conversation.request_completion", new=AsyncMock(side_effect=replies)):
            result = await self.engine.web_context(self.job)
        self.assertEqual(self.engine.web.search_web.await_count, 22)
        self.assertEqual(self.engine.web.read_webpage.await_count, 14)
        self.assertTrue(result["complete"])
        self.assertTrue(result["assessment"]["sufficient"])

    async def test_insufficient_checkpoint_continues_with_quotes_dates_and_material_gaps(self):
        first, second = "https://official.example/version", "https://official.example/performance"
        version = fact("Current version", first, "Release 9 is current.")
        performance = fact("Performance", second, "Performance improved 20 percent.")
        self.engine.web = SimpleNamespace(search_web=AsyncMock(return_value={"results": []}), close=AsyncMock(),
            read_webpage=AsyncMock(side_effect=[
                {"url": first, "text": "Release 9 is current.\n\n" + "RAW_CORPUS " * 500, "retrieved_at_utc": "2030-01-02", "published_at_untrusted": "2030-01-01"},
                {"url": second, "text": "Performance improved 20 percent."}]))
        replies = [self.call("read_webpage", first),
            report([version, {"claim": "Performance", "status": "unknown", "support": []}], gaps=["Performance unverified"]),
            self.call("read_webpage", second, 1), report([version, performance], sufficient=True)]
        with patch("cogs._conversation.request_completion", new=AsyncMock(side_effect=replies)) as provider:
            result = await self.engine.web_context(self.job)
        self.assertEqual(provider.await_count, 4)
        resumed = json.dumps(provider.await_args_list[2].args[2])
        self.assertIn("Performance unverified", resumed)
        self.assertIn("2030-01-01", resumed)
        self.assertIn("Release 9 is current.", resumed)
        self.assertNotIn("RAW_CORPUS", resumed)
        self.assertTrue(result["assessment"]["sufficient"])
        self.assertEqual(result["assessment"]["facts"][0]["support"][0]["retrieved_at_utc"], "2030-01-02")

    async def test_missing_report_and_provider_timeout_are_errors_not_partial_completion(self):
        for response in ({"role": "assistant", "content": "done"}, TimeoutError()):
            with self.subTest(response=response):
                provider = AsyncMock(side_effect=response) if isinstance(response, Exception) else AsyncMock(return_value=response)
                with patch("cogs._conversation.request_completion", new=provider), self.assertRaises((ValueError, TimeoutError)):
                    await self.engine.web_context(self.job)

    async def test_model_can_request_essential_clarification_without_claiming_sufficiency(self):
        question = "¿Qué modelo y revisión de la GPU tienes?"
        with patch("cogs._conversation.request_completion", new=AsyncMock(return_value=report(
                gaps=["Unknown hardware revision"], clarification=question))):
            result = await self.engine.web_context(self.job)
        self.assertEqual(result["clarification_required"], question)
        self.assertFalse(result["assessment"]["sufficient"])
        self.assertTrue(result["complete"])

    async def test_identical_requests_and_checkpoint_state_fail_as_no_progress(self):
        self.engine.web = SimpleNamespace(search_web=AsyncMock(return_value={"results": []}), close=AsyncMock())
        replies = [self.call("search_web", "Example", 1), report(gaps=["Version unknown"]),
                   self.call("search_web", "Example", 2), report(gaps=["Version unknown"])]
        with patch("cogs._conversation.request_completion", new=AsyncMock(side_effect=replies)), self.assertRaisesRegex(ValueError, "research_no_progress"):
            await self.engine.web_context(self.job)

    async def test_cancellation_interrupts_research_without_continuing_tools(self):
        entered = asyncio.Event()
        async def pending(*_, **__):
            entered.set()
            await asyncio.Event().wait()
        self.engine.web = SimpleNamespace(search_web=AsyncMock(), close=AsyncMock())
        with patch("cogs._conversation.request_completion", new=pending):
            task = asyncio.create_task(self.engine.web_context(self.job))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.engine.web.search_web.assert_not_awaited()
