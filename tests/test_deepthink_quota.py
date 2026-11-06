import inspect
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from api.deps import require_guild_admin
from api.routes.guild import get_ia_config, patch_ia_config
from database.manager import DatabaseManager
from tests.test_managed_messages import make_db


class DeepThinkQuotaTests(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db._sqlite_conn.close)
        self.db.set_ai_config(1, ai_deep_think=1, ai_deep_think_daily_limit=2)
        self.now = datetime(2026, 11, 1, 23, 59, tzinfo=timezone.utc)

    def reserve(self, request, user=10, guild=1, now=None):
        return self.db.reserve_ai_deep_think(guild, user, request, now=now or self.now)

    def test_limits_are_per_user_guild_and_utc_day(self):
        self.assertTrue(self.reserve(100)['accepted'])
        self.assertTrue(self.reserve(101)['accepted'])
        denied = self.reserve(102)
        self.assertEqual((denied['status'], denied['used'], denied['remaining']), ('limit', 2, 0))
        self.assertEqual(denied['reset_at'], '2026-11-02T00:00:00+00:00')
        self.assertTrue(self.reserve(103, user=11)['accepted'])
        self.db.set_ai_config(2, ai_deep_think=1, ai_deep_think_daily_limit=2)
        self.assertTrue(self.reserve(104, guild=2)['accepted'])
        self.assertTrue(self.reserve(105, now=self.now + timedelta(minutes=2))['accepted'])
        # Local midnight must not reset the quota before UTC midnight.
        local = self.now.astimezone(timezone(timedelta(hours=2)))
        self.assertEqual(self.reserve(106, now=local)['status'], 'limit')

    def test_request_retry_and_refund_are_idempotent_even_next_day(self):
        self.assertTrue(self.reserve(100)['accepted'])
        self.assertEqual(self.reserve('100')['status'], 'duplicate')
        self.assertTrue(self.db.refund_ai_deep_think(1, 10, 100))
        self.assertFalse(self.db.refund_ai_deep_think(1, 10, 100))
        self.assertFalse(self.db.refund_ai_deep_think(2, 10, 100))
        self.assertEqual(self.reserve(100)['status'], 'refunded')
        self.assertEqual(self.reserve(100, now=self.now + timedelta(days=1))['status'], 'refunded')
        fresh = self.reserve(101)
        self.assertTrue(fresh['accepted'])
        self.assertEqual(fresh['used'], 1)

    def test_current_config_applies_without_resetting_spent_quota(self):
        self.reserve(100)
        self.db.set_ai_config(1, ai_deep_think_daily_limit=1)
        self.assertEqual(self.reserve(101)['status'], 'limit')
        self.db.set_ai_config(1, ai_deep_think_daily_limit=3)
        self.assertTrue(self.reserve(102)['accepted'])
        self.db.set_ai_config(1, ai_deep_think_daily_limit=0)
        self.assertEqual(self.reserve(103)['status'], 'disabled')
        self.db.set_ai_config(1, ai_deep_think_daily_limit=3, ai_deep_think=0)
        self.assertEqual(self.reserve(104)['status'], 'disabled')

    def test_additive_migration_preserves_existing_settings_and_is_idempotent(self):
        db = DatabaseManager.__new__(DatabaseManager)
        db.db_type = 'sqlite'
        db._sqlite_lock = threading.Lock()
        db._sqlite_conn = sqlite3.connect(':memory:', check_same_thread=False)
        db._sqlite_conn.row_factory = sqlite3.Row
        self.addCleanup(db._sqlite_conn.close)
        db._sqlite_conn.executescript('CREATE TABLE ai_config (guild_id INTEGER PRIMARY KEY, ai_deep_think INTEGER); INSERT INTO ai_config VALUES (1, 1);')
        db._migrate_ai_config()
        db._migrate_ai_config()
        self.assertEqual(db.get_ai_config(1)['ai_deep_think'], 1)
        self.assertEqual(db.get_ai_config(1)['ai_deep_think_daily_limit'], 3)
        db._ensure_ai_deep_think_tables()
        db._ensure_ai_deep_think_tables()
        self.assertTrue(db.reserve_ai_deep_think(1, 10, 100)['accepted'])

    def test_two_connections_cannot_spend_last_slot_twice_and_persist_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'quota.db'
            databases = []
            try:
                for _ in range(2):
                    db = DatabaseManager.__new__(DatabaseManager)
                    db.db_type = 'sqlite'
                    db._sqlite_lock = threading.Lock()
                    db._sqlite_conn = sqlite3.connect(path, check_same_thread=False)
                    db._sqlite_conn.row_factory = sqlite3.Row
                    db._sqlite_conn.executescript('CREATE TABLE IF NOT EXISTS ai_config (guild_id INTEGER PRIMARY KEY, ai_deep_think INTEGER DEFAULT 1, ai_deep_think_daily_limit INTEGER DEFAULT 1); INSERT OR IGNORE INTO ai_config (guild_id) VALUES (1);')
                    db._ensure_ai_deep_think_tables()
                    databases.append(db)
                barrier = threading.Barrier(2)
                def reserve(index):
                    barrier.wait()
                    return databases[index].reserve_ai_deep_think(1, 10, 100 + index, now=self.now)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(reserve, range(2)))
                self.assertEqual(sum(result['accepted'] for result in results), 1)
                self.assertEqual({result['status'] for result in results}, {'reserved', 'limit'})
                winner = next(index for index, result in enumerate(results) if result['accepted'])
                self.assertEqual(databases[1 - winner].reserve_ai_deep_think(1, 10, 100 + winner, now=self.now)['status'], 'duplicate')
                barrier.reset()
                def retry_same_request(index):
                    barrier.wait()
                    return databases[index].reserve_ai_deep_think(1, 11, 200, now=self.now)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    duplicate_results = list(pool.map(retry_same_request, range(2)))
                self.assertEqual({result['status'] for result in duplicate_results}, {'reserved', 'duplicate'})
                self.assertEqual(sum(result['accepted'] for result in duplicate_results), 1)
                databases[0]._sqlite_conn.close()
                databases[0]._sqlite_conn = sqlite3.connect(path, check_same_thread=False)
                databases[0]._sqlite_conn.row_factory = sqlite3.Row
                self.assertEqual(databases[0].reserve_ai_deep_think(1, 10, 300, now=self.now)['status'], 'limit')
            finally:
                for db in databases:
                    db._sqlite_conn.close()


class DeepThinkConfigApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = make_db()
        self.addCleanup(self.db._sqlite_conn.close)

    async def test_admin_config_roundtrip_preserves_roles_endpoints_and_secret_redaction(self):
        self.db.set_ai_config(1, ai_restricted_role_ids=['44'], ai_web_enabled=1)
        self.db.set_automod_config(1, rules={'llm': {'api_key': 'test-secret', 'endpoint_url': 'https://example.com/v1', 'model': 'test'}})
        result = await patch_ia_config(1, {'ai_deep_think': True, 'ai_deep_think_daily_limit': 7}, None, self.db, None, {})
        self.assertEqual(result['ai_deep_think_daily_limit'], 7)
        self.assertEqual(result['ai_restricted_role_ids'], ['44'])
        self.assertEqual(result['ai_web_enabled'], 1)
        self.assertNotIn('test-secret', str(result))
        loaded = await get_ia_config(1, self.db, {})
        self.assertEqual(loaded['ai_deep_think_daily_limit'], 7)
        self.assertEqual(self.db.get_automod_config(1)['rules']['llm']['api_key'], 'test-secret')
        self.assertIs(inspect.signature(patch_ia_config).parameters['user'].default.dependency, require_guild_admin)
        self.assertIs(inspect.signature(get_ia_config).parameters['_user'].default.dependency, require_guild_admin)

    async def test_invalid_limits_and_client_usage_are_rejected_without_mutation(self):
        before = self.db.get_ai_config(1)
        for value in (-1, 1001, True, 1.0, '3', None):
            with self.subTest(value=value), self.assertRaises(HTTPException) as caught:
                await patch_ia_config(1, {'ai_deep_think': 1, 'ai_deep_think_daily_limit': value}, None, self.db, None, {})
            self.assertEqual(caught.exception.status_code, 400)
            self.assertEqual(self.db.get_ai_config(1), before)
        with self.assertRaises(HTTPException):
            await patch_ia_config(1, {'used': 0}, None, self.db, None, {})
        for limit in (0, 1000):
            result = await patch_ia_config(1, {'ai_deep_think_daily_limit': limit}, None, self.db, None, {})
            self.assertEqual(result['ai_deep_think_daily_limit'], limit)
