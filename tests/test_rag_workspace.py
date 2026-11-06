import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from cogs.rag_scraper import RAGScraper
from api.routes.rag import RAGConfigPatch, RAGExportRequest, export_rag_messages, get_rag_status, patch_rag_config
from rag.workspace import RAGWorkspaceManager


class RAGWorkspaceManagerTest(unittest.TestCase):
    def test_workspace_isolated_config_raw_sqlite_and_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = RAGWorkspaceManager(Path(tmp) / "workspaces")
            guild_id = 1497055416062971949

            root = mgr.ensure_workspace(guild_id)
            self.assertTrue((root / "config.yaml").is_file())
            self.assertTrue((root / "raw.sqlite").is_file())
            for subdir in ("checkpoints", "exports", "logs", "synthesis", "vectorstore", "tmp"):
                self.assertTrue((root / subdir).is_dir())

            cfg = mgr.save_config(
                guild_id,
                {"enabled": False, "excluded_channel_ids": [1497055415400136681]},
            )
            self.assertFalse(cfg["enabled"])
            self.assertEqual(cfg["excluded_channel_ids"], ["1497055415400136681"])

            mgr.upsert_channel(
                guild_id,
                {"channel_id": 1497055415400136681, "name": "faq", "type": "TextChannel"},
            )
            mgr.upsert_thread(
                guild_id,
                {
                    "thread_id": 1497055415400136699,
                    "parent_channel_id": 1497055415400136681,
                    "name": "post",
                },
            )
            msg = {
                "message_id": 1497055416062971949,
                "channel_id": 1497055415400136681,
                "thread_id": 1497055415400136699,
                "author_id": 1523702726393860373,
                "content": "hola tortuguitas",
                "attachments": [{"filename": "a.txt"}],
                "created_at": "2026-01-01T00:00:01+00:00",
            }
            mgr.upsert_message(guild_id, msg)
            mgr.upsert_message(guild_id, {**msg, "content": "hola editado"})
            mgr.mark_message_deleted(guild_id, 1497055416062971949, 1497055415400136681)
            mgr.upsert_message(
                guild_id,
                {
                    "message_id": 1497056539406503957,
                    "channel_id": 1497055415400136681,
                    "author_id": 123456789012345679,
                    "author_name": "Cat's Bot#9633",
                    "content": "",
                    "clean_content": "",
                    "created_at": "2026-01-01T00:00:02+00:00",
                    "embeds": [
                        {
                            "title": "Título embed",
                            "description": "Descripción completa del embed",
                            "fields": [{"name": "Campo", "value": "Valor del campo"}],
                            "footer": {"text": "Footer embed"},
                        }
                    ],
                    "raw": {
                        "stickers": [{"id": "999", "name": "Sticker Uno", "url": "https://example.com/sticker.png"}],
                        "components": [{"type": 1, "components": []}],
                    },
                },
            )
            mgr.upsert_message(
                guild_id,
                {
                    "message_id": 1497056539406503999,
                    "channel_id": 1497055415400136681,
                    "author_id": 1482003679698747554,
                    "author_name": "hasthlort4",
                    "content": "",
                    "clean_content": "",
                    "created_at": "2026-01-01T00:00:03+00:00",
                },
            )
            mgr.set_checkpoint(
                guild_id,
                "messages:1497055415400136681",
                channel_id=1497055415400136681,
                last_message_id=1497055416062971949,
                status="running",
                meta={"before_message_id": "1497055416062971949"},
            )

            stats = mgr.stats(guild_id)
            self.assertEqual(stats["guild_id"], str(guild_id))
            self.assertEqual(stats["counts"]["channels"], 1)
            self.assertEqual(stats["counts"]["threads"], 1)
            self.assertEqual(stats["counts"]["messages"], 3)
            self.assertEqual(stats["deleted_messages"], 1)

            with closing(sqlite3.connect(mgr.raw_db_path(guild_id))) as conn:
                row = conn.execute("SELECT content, attachments_json FROM messages").fetchone()
                self.assertEqual(row[0], "hola editado")
                self.assertEqual(json.loads(row[1])[0]["filename"], "a.txt")

            exported = mgr.export_messages(guild_id, format="markdown", include_deleted=True)
            self.assertEqual(exported["count"], 3)
            self.assertTrue(exported["filename"].endswith(".md"))
            exported_text = Path(exported["path"]).read_text(encoding="utf-8")
            self.assertIn("hola editado", exported_text)
            self.assertIn("a.txt", exported_text)
            self.assertIn("Título embed", exported_text)
            self.assertIn("Descripción completa del embed", exported_text)
            self.assertIn("Valor del campo", exported_text)
            self.assertIn("Sticker Uno", exported_text)
            self.assertIn("Componentes/interacciones", exported_text)
            self.assertIn("Sin contenido textual capturado", exported_text)

            jsonl = mgr.export_messages(guild_id, format="jsonl")
            # Por defecto no incluye borrados, así que el mensaje marcado deleted se omite.
            self.assertEqual(jsonl["count"], 2)

            latest_one = mgr.export_messages(guild_id, format="txt", include_deleted=True, limit=1)
            latest_text = Path(latest_one["path"]).read_text(encoding="utf-8")
            self.assertEqual(latest_one["selection"], "últimos 1")
            self.assertEqual(latest_one["count"], 1)
            self.assertIn("hasthlort4", latest_text)
            self.assertNotIn("hola editado", latest_text)

            all_messages = mgr.export_messages(guild_id, format="jsonl", include_deleted=True, limit=1, export_all=True)
            self.assertEqual(all_messages["selection"], "todo")
            self.assertEqual(all_messages["count"], 3)


class RAGApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_status_and_config_are_string_safe_and_use_injected_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = RAGWorkspaceManager(Path(tmp) / "workspaces")
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(rag_workspace=mgr)))
            guild_id = 1497055416062971949

            patched = await patch_rag_config(
                guild_id,
                RAGConfigPatch(enabled=False, excluded_channel_ids=[1497055415400136681]),
                request,
                bot=None,
                _user={"user_id": 1},
            )
            self.assertEqual(patched["guild_id"], str(guild_id))
            self.assertFalse(patched["config"]["enabled"])
            self.assertEqual(patched["config"]["excluded_channel_ids"], ["1497055415400136681"])

            status = await get_rag_status(guild_id, request, bot=None, _user={"user_id": 1})
            self.assertEqual(status["guild_id"], str(guild_id))
            self.assertIn("raw_db", status["stats"])

            mgr.upsert_channel(guild_id, {"channel_id": 1497055415400136681, "name": "general"})
            mgr.upsert_message(
                guild_id,
                {
                    "message_id": 1497055416062971949,
                    "channel_id": 1497055415400136681,
                    "author_id": 1523702726393860373,
                    "content": "export desde api",
                },
            )
            exported = await export_rag_messages(
                guild_id,
                RAGExportRequest(format="txt", channel_id="1497055415400136681", export_all=True),
                request,
                bot=None,
                _user={"user_id": 1},
            )
            self.assertEqual(exported["export"]["count"], 1)
            self.assertTrue(exported["export"]["filename"].endswith(".txt"))
            self.assertIn("export desde api", Path(exported["export"]["path"]).read_text(encoding="utf-8"))


class RAGBackfillSchedulingTest(unittest.IsolatedAsyncioTestCase):
    async def test_completed_sources_do_not_starve_later_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = RAGWorkspaceManager(Path(tmp) / "workspaces")
            guild = SimpleNamespace(id=123)
            cog = RAGScraper.__new__(RAGScraper)
            cog.workspace = mgr
            cog._guild_locks = {}
            cog._config = lambda _guild_id: {  # noqa: E731 - test double compacto
                "enabled": True,
                "backfill_enabled": True,
                "max_sources_per_cycle": 1,
                "capture_archived_threads": False,
                "history_batch_size": 10,
                "excluded_channel_ids": [],
            }

            sources = ["completed-a", "completed-b", "pending-c"]
            processed = []

            def iter_sources(_guild, _cfg):
                return iter(sources)

            async def backfill_source(_guild, source, _cfg):
                if str(source).startswith("completed"):
                    return None
                processed.append(source)
                return 1

            cog._iter_sources = iter_sources
            cog._backfill_source = backfill_source

            result = await cog.backfill_guild(guild, max_sources=1)

            self.assertEqual(processed, ["pending-c"])
            self.assertEqual(result["sources"], 1)
            self.assertEqual(result["captured"], 1)


class RAGSlashCommandRegistrationTest(unittest.TestCase):
    def test_rag_group_contains_export_subcommand(self):
        names = {cmd.name for cmd in RAGScraper.rag_group.commands}
        self.assertIn("status", names)
        self.assertIn("config", names)
        self.assertIn("backfill", names)
        self.assertIn("export", names)


if __name__ == "__main__":
    unittest.main()
