import asyncio
import hashlib
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import discord
from fastapi import FastAPI, HTTPException

from api.deps import get_bot, get_db, require_guild_admin
from api.routes.moderation import cases_router
from cogs import _moderation_evidence as evidence
from tests.test_managed_messages import make_db

PNG = b"\x89PNG\r\n\x1a\nsynthetic image bytes"


class EvidenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db._sqlite_conn.close)
        self.parent = self.db.log_action(100, 20, 10, "WARN", "reason")
        self.child = self.db.log_action(100, 20, 999, "AUTO_MUTE", "reason", parent_case_id=self.parent)

    def test_real_bytes_survive_sqlite_backup_and_child_inherits_without_duplication(self):
        record = evidence.artifact("image.png", PNG, uploader_id=10)
        self.db.add_case_evidence(100, self.parent, [record])
        child = self.db.list_case_evidence(100, self.child)
        self.assertEqual(len(child), 1)
        self.assertTrue(child[0]["inherited"])
        self.assertEqual(self.db.get_case_evidence(100, self.child, child[0]["id"])["content"], PNG)
        self.assertEqual(self.db.list_case_evidence(101, self.child), [])
        self.assertIsNone(self.db.get_case_evidence(101, self.child, child[0]["id"]))
        backup = sqlite3.connect(":memory:")
        self.addCleanup(backup.close)
        self.db._sqlite_conn.backup(backup)
        self.assertEqual(backup.execute("SELECT content FROM case_evidence").fetchall(), [(PNG,)])

    def test_append_is_immutable_and_does_not_change_case_status(self):
        self.db.add_case_evidence(100, self.parent, [evidence.artifact("a.png", PNG)])
        self.db.update_case_by_id(100, self.parent, status="expired")
        self.db.add_case_evidence(100, self.parent, [evidence.artifact("b.png", PNG + b"later")])
        items = self.db.list_case_evidence(100, self.parent)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["sha256"], hashlib.sha256(PNG).hexdigest())
        self.assertEqual(self.db.get_case_by_id(100, self.parent)["status"], "expired")

    def test_storage_failure_does_not_lose_a_valid_warn(self):
        with patch.object(self.db, "add_case_evidence", side_effect=OSError("disk full")):
            warns, case = self.db.add_warn_with_action(20, 100, 10, "WARN", "valid", evidence=[evidence.artifact("a.png", PNG)])
        self.assertEqual(warns, 1)
        self.assertEqual(self.db.get_case_by_id(100, case)["status"], "active")

    def test_quota_rejection_is_atomic(self):
        with patch.object(evidence, "MAX_CASE_BYTES", len(PNG)):
            with self.assertRaises(ValueError):
                self.db.add_case_evidence(100, self.parent, [evidence.artifact("a.png", PNG), evidence.artifact("b.png", PNG)])
        self.assertEqual(self.db.list_case_evidence(100, self.parent), [])

    def test_concurrent_uploads_cannot_exceed_case_quota(self):
        def append():
            try:
                self.db.add_case_evidence(100, self.parent, [evidence.artifact("a.png", PNG)])
                return True
            except ValueError:
                return False
        with patch.object(evidence, "MAX_CASE_BYTES", len(PNG)), ThreadPoolExecutor(2) as executor:
            outcomes = list(executor.map(lambda _: append(), range(2)))
        self.assertEqual(sorted(outcomes), [False, True])
        self.assertEqual(len(self.db.list_case_evidence(100, self.parent)), 1)


class EvidenceAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = make_db()
        self.case = self.db.log_action(100, 20, 10, "WARN", "reason")
        self.app = FastAPI()
        self.app.include_router(cases_router)
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.app.dependency_overrides[get_bot] = lambda: None
        self.app.dependency_overrides[require_guild_admin] = lambda: {"user_id": 10, "is_master_admin": True}
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")
        self.path = f"/api/moderation/100/cases/{self.case}/evidence"

    async def asyncTearDown(self):
        await self.client.aclose()
        self.db._sqlite_conn.close()

    async def upload(self, data=PNG, path=None, **headers):
        return await self.client.post(path or self.path, content=data,
            headers={"X-Filename": "test.png", "Content-Type": "image/png", **headers})

    async def test_append_list_download_and_cross_guild_or_case_denied(self):
        response = await self.upload()
        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        downloaded = await self.client.get(item["download_url"])
        self.assertEqual(downloaded.content, PNG)
        self.assertEqual(downloaded.headers["x-content-type-options"], "nosniff")
        self.assertIn("attachment", downloaded.headers["content-disposition"])
        denied = await self.client.get(item["download_url"].replace("/100/", "/101/"))
        self.assertEqual(denied.status_code, 404)
        other = self.db.log_action(100, 21, 10, "WARN", "other")
        self.assertEqual((await self.client.get(f"/api/moderation/100/cases/{other}/evidence/{item['id']}" )).status_code, 404)

    async def test_invalid_or_oversize_upload_does_not_create_phantom_evidence(self):
        self.assertEqual((await self.upload(b"<html>bad</html>")).status_code, 400)
        self.assertEqual((await self.upload(PNG + b"x" * evidence.MAX_FILE_BYTES)).status_code, 413)
        self.assertEqual((await self.client.post(self.path, content=PNG, headers={"Content-Type": "image/png"})).status_code, 400)
        self.assertEqual(self.db.list_case_evidence(100, self.case), [])

    async def test_permission_denial_prevents_upload_and_download(self):
        async def denied():
            raise HTTPException(403, "denied")
        self.app.dependency_overrides[require_guild_admin] = denied
        self.assertEqual((await self.upload()).status_code, 403)
        self.assertEqual((await self.client.get(self.path)).status_code, 403)
        self.assertEqual(self.db.list_case_evidence(100, self.case), [])

    async def test_manage_guild_only_cannot_query_private_evidence(self):
        self.app.dependency_overrides[require_guild_admin] = lambda: {
            "user_id": 10, "_live_guild_admin_status": {"manage_guild": True}}
        with patch.object(self.db, "get_case", side_effect=AssertionError("must authorize before querying")):
            for method, path in (("GET", self.path), ("POST", self.path), ("GET", self.path + "/unknown")):
                result = await self.client.request(method, path, content=PNG)
                self.assertEqual(result.status_code, 403)

    async def test_fresh_owner_and_administrator_can_read_evidence(self):
        for field in ("is_owner", "administrator"):
            self.app.dependency_overrides[require_guild_admin] = lambda: {
                "user_id": 10, "_live_guild_admin_status": {field: True}}
            self.assertEqual((await self.client.get(self.path)).status_code, 200)


class EvidenceCaptureTests(unittest.IsolatedAsyncioTestCase):
    def context_fixture(self):
        guild = SimpleNamespace(id=100, name="Synthetic")
        channel = SimpleNamespace(id=200, name="private", guild=guild)
        message = SimpleNamespace(id=300, author=SimpleNamespace(id=20), channel=channel,
            content="real <script>text</script>", attachments=[], created_at="2026-11-03T00:00:00Z")
        async def history(**kwargs):
            yield message
        channel.history = history
        bot = SimpleNamespace(user=SimpleNamespace(id=999))
        return bot, guild, channel, message

    async def test_fallback_context_stores_real_json_png_and_media_bytes(self):
        bot, guild, channel, message = self.context_fixture()
        message.attachments = [SimpleNamespace(id=1, filename="clip.mp4", size=12)]
        with patch.object(evidence, "_authorized_channel", new=AsyncMock(return_value=channel)), \
             patch.object(evidence, "render_snapshot", new=AsyncMock(return_value=PNG)), \
             patch.object(evidence, "preserve_attachment", new=AsyncMock(return_value=evidence.artifact("clip.mp4", b"1234ftypisom", source="discord_attachment"))):
            records = await evidence.capture_context(bot, guild, channel=channel, actor_id=10)
        self.assertEqual([item["kind"] for item in records], ["context", "snapshot", "attachment"])
        self.assertIn(b"real <script>text</script>", records[0]["content"])
        self.assertEqual(records[1]["content"], PNG)
        self.assertEqual(records[2]["content"], b"1234ftypisom")

    async def test_access_revocation_after_partial_capture_discards_private_bytes(self):
        bot, guild, channel, message = self.context_fixture()
        message.attachments = [SimpleNamespace(id=1, filename="clip.mp4", size=12)]
        with patch.object(evidence, "_authorized_channel", new=AsyncMock(side_effect=[channel, ValueError("channel_access_denied")])), \
             patch.object(evidence, "render_snapshot", new=AsyncMock(return_value=PNG)), \
             patch.object(evidence, "preserve_attachment", new=AsyncMock(side_effect=TimeoutError)):
            records = await evidence.capture_context(bot, guild, channel=channel, actor_id=10)
        self.assertTrue(all(item["content"] is None for item in records))
        self.assertEqual(records[0]["error"], "source_access_changed")

    async def test_access_revoked_during_explicit_upload_discards_source_but_keeps_own_file(self):
        bot, guild, channel, message = self.context_fixture()
        message.attachments = [SimpleNamespace(id=1, filename="private.png", size=len(PNG))]
        own_file = SimpleNamespace(id=2, filename="own.png", size=len(PNG))
        revoked = False

        async def authorize(*args):
            if revoked:
                raise ValueError("channel_access_denied")
            return channel

        async def preserve(item, *, source, **kwargs):
            nonlocal revoked
            if source == "moderator_attachment":
                revoked = True
            return evidence.artifact(item.filename, PNG, source=source)

        with patch.object(evidence, "_authorized_channel", new=AsyncMock(side_effect=authorize)), \
             patch.object(evidence, "render_snapshot", new=AsyncMock(return_value=PNG)), \
             patch.object(evidence, "preserve_attachment", new=AsyncMock(side_effect=preserve)):
            records = await evidence.capture_context(bot, guild, channel=channel, actor_id=10, attachment=own_file)
        self.assertEqual([(item["filename"], item["source"]) for item in records if item["content"] is not None],
            [("own.png", "moderator_attachment")])
        self.assertTrue(any(item["error"] == "source_access_changed" for item in records))
        self.assertEqual(records[-1]["content"], PNG)

    async def test_channel_permission_denial_prevents_reading_history(self):
        bot, guild, channel, message = self.context_fixture()
        channel.history = AsyncMock(side_effect=AssertionError("must not read"))
        with patch.object(evidence, "_authorized_channel", new=AsyncMock(side_effect=ValueError("channel_access_denied"))):
            records = await evidence.capture_context(bot, guild, channel=channel, actor_id=10)
        channel.history.assert_not_called()
        self.assertEqual(records[0]["error"], "channel_access_denied")

    async def test_total_capture_budget_includes_json_snapshot_and_real_attachment_size(self):
        bot, guild, channel, message = self.context_fixture()
        message.attachments = [SimpleNamespace(id=1, filename="a.png", size=1)]
        with patch.object(evidence, "MAX_UPLOAD_BYTES", 1200), \
             patch.object(evidence, "_authorized_channel", new=AsyncMock(return_value=channel)), \
             patch.object(evidence, "render_snapshot", new=AsyncMock(return_value=PNG)), \
             patch.object(evidence, "preserve_attachment", new=AsyncMock(return_value=evidence.artifact("a.png", PNG + b"x" * 1100))):
            records = await evidence.capture_context(bot, guild, channel=channel)
        self.assertLessEqual(sum(item["size"] for item in records), 1200)
        self.assertEqual(records[-1]["error"], "capture_budget_exceeded")

    async def test_context_is_captured_before_automod_deletes_message(self):
        from tests import test_warn_escalation as fixtures
        fixture = fixtures.WarnEscalationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        events = []
        async def capture(*args, **kwargs):
            events.append("capture")
            return [evidence.artifact("context.json", b"{}", kind="context", content_type="application/json")]
        fixture.message.delete.side_effect = lambda: events.append("delete")
        with patch("cogs.automod.capture_context", side_effect=capture):
            await fixture.auto_warn()
        self.assertEqual(events, ["capture", "delete"])
        case = fixture.db.list_cases(100)[0]
        self.assertEqual(fixture.db.case_evidence_summary(100, case["id"])["evidence_count"], 1)
        with patch("cogs.automod.capture_context", side_effect=capture), \
             patch.object(fixture.db, "add_case_evidence", side_effect=OSError("disk full")):
            await fixture.auto_warn()
        self.assertEqual(fixture.db.list_cases(100)[0]["action_type"], "AUTO_WARN")
        embed = fixture.automod._log_to_modlog.await_args.args[1]
        evidence_field = next(field for field in embed.fields if field.name == "Evidencia")
        self.assertTrue(evidence_field.value.startswith("0 archivos"), evidence_field.value)

    async def test_deterministic_delete_without_case_does_not_capture_or_claim_saved_files(self):
        from tests.test_warn_escalation import WarnEscalationTests
        fixture = WarnEscalationTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.db.set_automod_config(100, rules={"banned_words": {
            "enabled": True, "words": ["prohibido"], "action": "delete"}})
        with patch("cogs.automod.capture_context", new=AsyncMock(return_value=[])) as capture:
            await fixture.automod._execute_action(fixture.message, "banned_words", "delete", {})
        capture.assert_not_awaited()
        fixture.message.delete.assert_awaited_once()
        self.assertEqual(fixture.db.list_cases(100), [])
        embed = fixture.automod._log_to_modlog.await_args.args[1]
        self.assertNotIn("Evidencia", [field.name for field in embed.fields])

    async def test_fresh_channel_permissions_and_private_thread_membership_are_required(self):
        from tests.test_mute_permission_snapshot import MutePermissionSnapshotTests
        fixture = MutePermissionSnapshotTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        bot = fixture.cog.bot
        channel = fixture.fresh_channel
        result = await evidence._authorized_channel(bot, fixture.guild, channel, 20)
        self.assertEqual(result.id, 500)
        data = {**fixture.channel_data, "permission_overwrites": [
            *fixture.channel_data["permission_overwrites"],
            {"id": "20", "type": 1, "allow": "0", "deny": str(discord.Permissions(read_message_history=True).value)}]}
        blocked = discord.TextChannel(state=fixture.state, guild=fixture.guild, data=data)
        discord.Guild.fetch_channels.return_value = [blocked]
        with self.assertRaisesRegex(ValueError, "channel_access_denied"):
            await evidence._authorized_channel(bot, fixture.guild, channel, 20)
        discord.Guild.fetch_channels.return_value = [channel]
        thread = discord.Thread(guild=fixture.guild, state=fixture.state, data={
            "id": "600", "parent_id": "500", "type": 12, "name": "private", "owner_id": "20",
            "message_count": 0, "member_count": 1,
            "thread_metadata": {"archived": False, "auto_archive_duration": 60,
                "archive_timestamp": "2026-11-03T00:00:00+00:00", "locked": False}})
        with patch.object(discord.Thread, "fetch_member", new=AsyncMock(side_effect=discord.Forbidden(
            SimpleNamespace(status=403, reason="forbidden"), "not a member"))) as membership:
            with self.assertRaisesRegex(ValueError, "private_thread_access_denied"):
                await evidence._authorized_channel(bot, fixture.guild, thread, 20)
        membership.assert_awaited_once_with(20)

    async def test_manual_warn_kick_and_ban_capture_attachment_before_the_sink(self):
        from tests.test_manual_warn_hierarchy import ManualWarnHierarchyTests
        for action in ("warn", "kick", "ban"):
            fixture = ManualWarnHierarchyTests()
            fixture.setUp()
            try:
                events = []
                async def capture(*args):
                    events.append("capture")
                    self.assertEqual(fixture.db.list_cases(100), [])
                    return [evidence.artifact("a.png", PNG, source="moderator_attachment", uploader_id=10)]
                async def sink(member, **kwargs):
                    events.append(action)
                    fixture.guild.fetch_ban = AsyncMock(return_value=SimpleNamespace(reason=kwargs["reason"]))
                fixture.guild.kick.side_effect = sink
                fixture.guild.ban.side_effect = sink
                kwargs = {"usuario": fixture.target, "razon": "Valid reason", "archivo": SimpleNamespace(filename="a.png"),
                    "mensaje_url": "https://discord.com/channels/100/500/1"}
                with patch("cogs.moderation.capture_manual", side_effect=capture):
                    command = getattr(fixture.cog, action)
                    await command.callback(fixture.cog, fixture.interaction, **kwargs)
                self.assertEqual(events[0], "capture")
                case = fixture.db.list_cases(100)[0]
                self.assertEqual(fixture.db.list_case_evidence(100, case["id"])[0]["source"], "moderator_attachment")
            finally:
                fixture.tearDown()

    async def test_manual_mute_and_case_append_preserve_evidence_without_changing_sanction(self):
        from tests.test_mute_role_lifecycle import MuteRoleLifecycleTests
        fixture = MuteRoleLifecycleTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.server_roles[20] = [200]
        records = [evidence.artifact("a.png", PNG, source="moderator_attachment", uploader_id=10)]
        with patch("cogs.moderation.capture_manual", new=AsyncMock(return_value=records)):
            await fixture.cog.mute.callback(fixture.cog, fixture.interaction, fixture.current_member(20), "5m", "Valid reason",
                archivo=SimpleNamespace(filename="a.png"))
            case = fixture.db.list_cases(100)[0]
            self.assertEqual(fixture.db.list_case_evidence(100, case["id"])[0]["sha256"], hashlib.sha256(PNG).hexdigest())
            await fixture.cog.case_evidence.callback(fixture.cog, fixture.interaction, case["case_number"], archivo=SimpleNamespace(filename="a.png"))
        self.assertEqual(len(fixture.db.list_case_evidence(100, case["id"])), 2)
        self.assertEqual(fixture.db.get_case_by_id(100, case["id"])["status"], "active")

    async def test_attachment_url_and_size_fail_closed_without_network(self):
        for url, size, error in [("http://127.0.0.1/private", 1, "invalid_attachment_url"),
            ("https://cdn.discordapp.com/attachments/1/2/file", evidence.MAX_FILE_BYTES + 1, "file_too_large")]:
            attachment = SimpleNamespace(url=url, size=size, filename="evidence.png")
            with patch("aiohttp.ClientSession", side_effect=AssertionError("must not access network")):
                result = await evidence.preserve_attachment(attachment, source="test")
            self.assertEqual(result["error"], error)
            self.assertIsNone(result["content"])

    async def test_expired_and_redirected_cdn_attachments_are_failure_records(self):
        class Response:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        class Session(Response):
            def __init__(self, **kwargs):
                pass
            def get(self, *args, **kwargs):
                self.kwargs = kwargs
                return response
        for status in (403, 302):
            response = Response()
            response.status = status
            attachment = SimpleNamespace(url="https://cdn.discordapp.com/attachments/1/2/a", size=1, filename="a.png")
            with patch("aiohttp.ClientSession", Session):
                result = await evidence.preserve_attachment(attachment, source="test")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error"], "attachment_unavailable")

    async def test_cdn_media_is_downloaded_as_real_bytes_without_following_redirects(self):
        class Response:
            status = 200
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        async def chunks(size):
            yield b"ID3"
            yield b"actual audio"
        response = Response()
        response.content = SimpleNamespace(iter_chunked=chunks)
        requests = []
        class Session(Response):
            def __init__(self, **kwargs):
                pass
            def get(self, url, **kwargs):
                requests.append(kwargs)
                return response
        attachment = SimpleNamespace(url="https://cdn.discordapp.com/attachments/1/2/a", size=15, filename="a.mp3")
        with patch("aiohttp.ClientSession", Session):
            result = await evidence.preserve_attachment(attachment, source="discord_attachment")
        self.assertEqual(result["content"], b"ID3actual audio")
        self.assertEqual(result["content_type"], "audio/mpeg")
        self.assertEqual(requests, [{"allow_redirects": False}])

    async def test_invalid_source_does_not_fetch_or_fall_back_to_another_channel(self):
        bot = SimpleNamespace(user=SimpleNamespace(id=999), fetch_channel=AsyncMock())
        result = await evidence.capture_context(bot, SimpleNamespace(id=100), message_url="https://discord.com/channels/101/1/2")
        self.assertEqual(result[0]["error"], "invalid_message_source")
        bot.fetch_channel.assert_not_awaited()

    def test_media_sniff_rejects_html_and_svg_despite_filename(self):
        for data in (b"<svg></svg>", b"<!doctype html><html>", b"unknown"):
            with self.assertRaises(ValueError):
                evidence.media_type(data)
        for data, mime in [(PNG, "image/png"), (b"ID3audio", "audio/mpeg"), (b"1234ftypisom", "video/mp4")]:
            self.assertEqual(evidence.media_type(data), mime)


if __name__ == "__main__":
    unittest.main()
