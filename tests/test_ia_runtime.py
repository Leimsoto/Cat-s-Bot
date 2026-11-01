import unittest
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import discord

from cogs.ia import (
    IA,
    _api_error_status_code,
    _is_leaked_api_key_error,
    _normalize_discord_ai_text,
    types,
    ChannelJobQueue,
)


class IAQueueAndRateTest(unittest.IsolatedAsyncioTestCase):
    def job(self, number, user=30):
        return {"conversation": True, "number": number, "message": SimpleNamespace(
            guild=SimpleNamespace(id=10), channel=SimpleNamespace(id=20), author=SimpleNamespace(id=user))}

    async def test_worker_queue_serves_other_speaker_and_preserves_order_and_bound(self):
        queue = ChannelJobQueue(maxsize=3)
        release, first_started, other_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        order, running, peak = [], 0, 0
        async def process(job):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            order.append(job["number"])
            try:
                if job["number"] == 1:
                    first_started.set()
                    await release.wait()
                elif job["number"] == 3:
                    other_started.set()
            finally:
                running -= 1
        for job in (self.job(1), self.job(2), self.job(3, user=31)):
            queue.put_nowait(job)
        with self.assertRaises(asyncio.QueueFull):
            queue.put_nowait(self.job(4))
        cog = SimpleNamespace(_queue=queue, _process_job=process)
        workers = [asyncio.create_task(IA._worker_loop(cog, index)) for index in range(2)]
        try:
            await asyncio.wait_for(first_started.wait(), 2)
            await asyncio.wait_for(other_started.wait(), 2)
            self.assertEqual(order, [1, 3])
            release.set()
            await asyncio.wait_for(queue.join(), 2)
            self.assertEqual(order, [1, 3, 2])
            self.assertLessEqual(peak, 2)
            self.assertEqual(queue.active_channels, set())
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def test_cancelled_waiter_does_not_lose_turns_or_task_accounting(self):
        queue = ChannelJobQueue(maxsize=3)
        queue.put_nowait(self.job(1))
        queue.put_nowait(self.job(2))
        first = await queue.get()
        waiter = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        queue.release(first)
        queue.task_done()
        second = await asyncio.wait_for(queue.get(), 1)
        self.assertEqual(second["number"], 2)
        queue.release(second)
        queue.task_done()
        await asyncio.wait_for(queue.join(), 1)

    async def test_strata_has_no_inherited_default_quota_but_honors_operator_limits(self):
        keys = ("AI_RATE_CAPACITY", "AI_RATE_PERIOD", "AI_STRATA_RATE_CAPACITY", "AI_STRATA_RATE_PERIOD", "GEMINI_API_KEY")
        with patch.dict(os.environ):
            for key in keys:
                os.environ.pop(key, None)
            cog = IA(_Bot())
            cog._rate_tokens = 0
            self.assertTrue(await cog._acquire_slot(provider="strata"))
            self.assertFalse(await cog._acquire_slot(max_wait=-1))
            os.environ["AI_RATE_CAPACITY"] = "3"
            limited = IA(_Bot())
            for _ in range(3):
                self.assertTrue(await limited._acquire_slot(provider="strata"))
            self.assertFalse(await limited._acquire_slot(max_wait=-1, provider="strata"))
            self.assertEqual(limited._rate_tokens, 3)
            os.environ["AI_STRATA_RATE_CAPACITY"] = "7"
            os.environ["AI_STRATA_RATE_PERIOD"] = "20"
            custom = IA(_Bot())
            self.assertEqual((custom._strata_rate_cap, custom._strata_rate_period), (7, 20))


class _DB:
    def __init__(self, **overrides):
        self.config = {
            "ai_provider": "gemini",
            "ai_enabled": 1,
            "ai_response_mode": "all",
            "ai_channel_id": 20,
            "ai_role_id": None,
            "ai_model": "gemma-4-26b-a4b-it",
            "ai_system_prompt": "Responde con claridad.",
        }
        self.config.update(overrides)

    def get_ai_config(self, _guild_id):
        return dict(self.config)


class _BotUser:
    id = 999
    display_name = "Bot"
    name = "bot"


class _Bot:
    def __init__(self, **config):
        self.db = _DB(**config)
        self.user = _BotUser()


class _Author:
    id = 30
    display_name = "Ana"
    name = "ana"
    bot = False
    roles = []


class _Guild:
    id = 10


class _Channel:
    id = 20

    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(text)

    def typing(self):
        return _Typing()


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Message:
    def __init__(self):
        self.author = _Author()
        self.author.roles = []
        self.guild = _Guild()
        self.channel = _Channel()
        self.content = "hola"
        self.mentions = []
        self.attachments = []
        self.stickers = []
        self.webhook_id = None
        self.reference = None


class IAMultimodalRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_image_attachment_becomes_inline_data(self):
        cog = IA(_Bot())
        image = SimpleNamespace(filename="cat.png")
        message = _Message()
        message.attachments = [image]
        cog._fetch_attachment = AsyncMock(return_value=(b"image", "image/png"))

        parts = await cog._build_user_parts(message, "Describe esta imagen")

        self.assertEqual(parts[0].text, "Describe esta imagen")
        self.assertEqual(parts[1].inline_data.data, b"image")
        self.assertEqual(parts[1].inline_data.mime_type, "image/png")
        self.assertEqual(cog._metrics["multimodal"], 1)

    async def test_gif_attachment_uses_explicit_non_visual_fallback(self):
        for content_type in ("image/gif", "application/octet-stream"):
            with self.subTest(content_type=content_type):
                cog = IA(_Bot())
                image = SimpleNamespace(
                    filename="cat.gif",
                    content_type=content_type,
                    size=7,
                    url="https://cdn.discordapp.com/attachments/cat.gif",
                )
                message = _Message()
                message.content = ""
                message.attachments = [image]
                cog._download_media = AsyncMock()

                parts = await cog._build_user_parts(message, "")

                self.assertEqual(len(parts), 1)
                self.assertEqual(parts[0].text, "[Adjunto no procesable: cat.gif]")
                self.assertIsNone(parts[0].inline_data)
                self.assertEqual(cog._metrics["multimodal"], 0)
                cog._download_media.assert_not_awaited()

    async def test_sticker_only_message_becomes_inline_data(self):
        cog = IA(_Bot())
        sticker = SimpleNamespace(
            id=123,
            name="gato",
            format=discord.StickerFormatType.png,
            url="https://cdn.discordapp.com/stickers/123.png",
        )
        message = _Message()
        message.content = ""
        message.stickers = [sticker]
        cog._fetch_sticker = AsyncMock(return_value=(b"sticker", "image/png"))

        parts = await cog._build_user_parts(message, "")

        self.assertEqual(parts[0].text, "[Sticker de Discord: gato]")
        self.assertEqual(parts[1].inline_data.data, b"sticker")
        self.assertEqual(parts[1].inline_data.mime_type, "image/png")
        self.assertNotIn("Mensaje sin contenido", " ".join(p.text or "" for p in parts))
        self.assertEqual(cog._metrics["multimodal"], 1)

    async def test_png_sticker_formats_map_to_supported_image_mime(self):
        cog = IA(_Bot())
        cases = (
            (discord.StickerFormatType.png, "image/png", "png"),
            (discord.StickerFormatType.apng, "image/png", "png"),
        )

        for sticker_format, expected_mime, extension in cases:
            with self.subTest(sticker_format=sticker_format):
                url = f"https://cdn.discordapp.com/stickers/123.{extension}"
                sticker = SimpleNamespace(
                    id=123, name="gato", format=sticker_format, url=url
                )
                cog._download_media = AsyncMock(
                    return_value=(b"sticker", expected_mime)
                )

                result = await cog._fetch_sticker(sticker)

                self.assertEqual(result, (b"sticker", expected_mime))
                cog._download_media.assert_awaited_once_with(
                    url=url,
                    label="sticker 'gato'",
                    mime=expected_mime,
                )

    async def test_unsupported_stickers_use_explicit_non_visual_fallback(self):
        cases = (
            (
                discord.StickerFormatType.gif,
                "https://media.discordapp.net/stickers/123.gif",
            ),
            (
                discord.StickerFormatType.lottie,
                "https://cdn.discordapp.com/stickers/123.json",
            ),
        )

        for sticker_format, url in cases:
            with self.subTest(sticker_format=sticker_format):
                cog = IA(_Bot())
                sticker = SimpleNamespace(
                    id=123,
                    name="gato-animado",
                    format=sticker_format,
                    url=url,
                )
                message = _Message()
                message.content = ""
                message.stickers = [sticker]
                cog._download_media = AsyncMock()

                parts = await cog._build_user_parts(message, "")

                self.assertEqual(len(parts), 1)
                self.assertIn("Sticker no procesable visualmente", parts[0].text)
                self.assertIn("gato-animado", parts[0].text)
                self.assertNotEqual(parts[0].text, "[Mensaje sin contenido]")
                self.assertIsNone(parts[0].inline_data)
                cog._download_media.assert_not_awaited()


class IAGuildKeyRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def _configured_cog(self, **config):
        cog = IA(_Bot(**config))
        cog._get_client_for_guild = lambda _guild_id: object()
        cog._get_system_prompt = lambda _guild: "Prompt"
        cog._build_user_parts = AsyncMock(return_value=["part"])
        return cog

    async def test_disabled_module_ignores_ai_channel_messages(self):
        cog = self._configured_cog(ai_enabled=0)
        message = _Message()

        await cog.on_message(message)

        self.assertEqual(cog._queue.qsize(), 0)
        cog._build_user_parts.assert_not_awaited()
        self.assertEqual(message.channel.sent, [])

    async def test_all_mode_accepts_messages_without_mention_in_ai_channel(self):
        cog = self._configured_cog(ai_response_mode="all")
        message = _Message()

        await cog.on_message(message)

        self.assertEqual(cog._queue.qsize(), 1)
        self.assertFalse(cog._queue.get_nowait()["message"].mentions)

    async def test_mentions_mode_ignores_messages_without_mention_in_ai_channel(self):
        cog = self._configured_cog(ai_response_mode="mentions")
        message = _Message()

        await cog.on_message(message)

        self.assertEqual(cog._queue.qsize(), 0)
        cog._build_user_parts.assert_not_awaited()

    async def test_mentions_mode_accepts_direct_mention_in_ai_channel(self):
        cog = self._configured_cog(ai_response_mode="mentions")
        message = _Message()
        message.mentions = [cog.bot.user]

        await cog.on_message(message)

        self.assertEqual(cog._queue.qsize(), 1)

    async def test_unknown_response_mode_preserves_all_mode_compatibility(self):
        cog = self._configured_cog(ai_response_mode="legacy-value")
        message = _Message()

        await cog.on_message(message)

        self.assertEqual(cog._queue.qsize(), 1)

    async def test_role_ping_still_works_outside_ai_channel(self):
        cog = self._configured_cog(ai_response_mode="mentions", ai_role_id=77)
        message = _Message()
        message.channel.id = 21
        message.author.roles = [SimpleNamespace(id=77)]
        message.mentions = [cog.bot.user]

        await cog.on_message(message)

        self.assertEqual(cog._queue.qsize(), 1)
        self.assertFalse(cog._queue.get_nowait()["is_ai_channel"])

    def test_discord_output_replaces_latex_arrows_outside_code(self):
        text = (
            "Menú $\\rightarrow$ Administración \\Rightarrow Información\n"
            "`$\\rightarrow$`\n"
            "```tex\n$\\leftarrow$\n```"
        )

        self.assertEqual(
            _normalize_discord_ai_text(text),
            (
                "Menú → Administración ⇒ Información\n"
                "`$\\rightarrow$`\n"
                "```tex\n$\\leftarrow$\n```"
            ),
        )

    async def test_process_job_sends_and_remembers_discord_safe_text(self):
        cog = IA(_Bot())
        cog._get_client_for_guild = lambda _guild_id: object()
        cog._generate_with_retries = AsyncMock(
            return_value=SimpleNamespace(
                text="Ve al Menú $\\rightarrow$ Administración."
            )
        )
        cog._send_reply = AsyncMock()
        message = _Message()
        job = {
            "message": message,
            "ctx_id": "10_20_30",
            "config": None,
            "is_ai_channel": True,
            "user_parts": [types.Part.from_text(text="¿Dónde está?")],
        }

        await cog._process_job(job)

        cog._send_reply.assert_awaited_once_with(
            message,
            "Ve al Menú → Administración.",
            True,
        )
        model_turn = cog._chat_histories["10_20_30"][-1]
        self.assertEqual(model_turn.parts[0].text, "Ve al Menú → Administración.")

    async def test_assigned_guild_key_works_without_fallback_client(self):
        cog = IA(_Bot())
        cog.client = None
        cog._fallback_key = None
        cog._get_client_for_guild = lambda _guild_id: object()
        cog._get_system_prompt = lambda _guild: "Prompt"

        async def build_parts(_message, _text):
            return ["part"]

        cog._build_user_parts = build_parts
        message = _Message()

        await cog.on_message(message)

        self.assertEqual(cog._queue.qsize(), 1)
        job = cog._queue.get_nowait()
        self.assertIs(job["message"], message)
        self.assertEqual(job["user_parts"], ["part"])
        self.assertEqual(job["ctx_id"], "10_20_30")
        self.assertEqual(message.channel.sent, [])

    async def test_leaked_key_403_is_not_misclassified_as_rate_limit(self):
        class LeakedKeyError(Exception):
            status_code = 403

        error = LeakedKeyError(
            "403 PERMISSION_DENIED: Your API key was reported as leaked."
        )
        self.assertEqual(_api_error_status_code(error), 403)
        self.assertTrue(_is_leaked_api_key_error(error))

        cog = IA(_Bot())
        cog.client = object()

        class _Models:
            calls = 0

            def generate_content(self, **_kwargs):
                self.calls += 1
                raise error

        models = _Models()
        cog.client = type("Client", (), {"models": models})()

        with self.assertRaises(LeakedKeyError):
            await cog._generate_with_retries(
                "gemma-4-26b-a4b-it", [], None, retries=3
            )

        self.assertEqual(models.calls, 1)
        self.assertEqual(cog._metrics["errors_403"], 1)
        self.assertEqual(cog._metrics["errors_429"], 0)
        self.assertNotIn("gemma-4-26b-a4b-it", cog._model_backoff)

        async def reject(**_kwargs):
            raise error

        cog._generate_with_retries = reject
        cog._get_client_for_guild = lambda _guild_id: object()
        message = _Message()
        job = {
            "message": message,
            "ctx_id": "10_30",
            "config": None,
            "is_ai_channel": True,
            "user_parts": [types.Part.from_text(text="hola")],
        }
        await cog._process_job(job)
        self.assertEqual(len(message.channel.sent), 1)
        self.assertIn("reportó como filtrada", message.channel.sent[0])


if __name__ == "__main__":
    unittest.main()
