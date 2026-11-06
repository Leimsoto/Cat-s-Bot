import json
import logging
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta, timezone

from database.manager import DatabaseManager


class ModerationDatabaseMVPTest(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager.__new__(DatabaseManager)
        self.db.db_type = "sqlite"
        self.db._sqlite_lock = threading.Lock()
        self.db._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.db._sqlite_conn.row_factory = sqlite3.Row
        self.db._sqlite_conn.execute("PRAGMA foreign_keys = ON")
        self.db._sqlite_conn.execute("PRAGMA journal_mode = WAL")
        db_logger = logging.getLogger("Database")
        previous_disabled = db_logger.disabled
        db_logger.disabled = True
        try:
            self.db._init_schema()
        finally:
            db_logger.disabled = previous_disabled

    def tearDown(self):
        self.db._sqlite_conn.close()

    def test_moderation_case_pending_outbox_and_automod_normalization(self):
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

        case_id = self.db.log_action(
            123,
            456,
            789,
            "TEMPBAN",
            "smoke reason",
            extra_data={"delete_days": 1},
            status="active",
            evidence_url="https://example.com/evidence",
            duration_seconds=300,
            expires_at=expires,
        )
        case = self.db.get_case_by_id(123, case_id)
        self.assertIsNotNone(case)
        self.assertEqual(case["case_number"], 1)
        self.assertEqual(case["evidence_url"], "https://example.com/evidence")
        self.assertEqual(json.loads(case["extra_data"])["delete_days"], 1)
        self.assertEqual(self.db.get_case(123, 1)["id"], case_id)
        self.assertEqual(self.db.update_case(123, 1, status="expired")["status"], "expired")
        self.assertEqual(self.db.update_case_by_id(123, case_id, status="active")["status"], "active")
        self.assertEqual(len(self.db.list_cases(123, user_id=456)), 1)

        tempban_id = self.db.set_tempban(123, 456, 789, "smoke tempban", 300, case_id=case_id)
        self.assertGreater(tempban_id, 0)
        self.assertEqual(self.db.get_active_tempbans()[0]["case_id"], case_id)

        pending_id = self.db.add_pending_moderation_action(
            123,
            456,
            "TEMPBAN_EXPIRE",
            expires,
            case_id=case_id,
            extra={"source": "smoke"},
        )
        self.assertGreater(pending_id, 0)
        self.assertTrue(self.db.has_pending_moderation_action(123, 456, ["TEMPBAN_EXPIRE"]))
        cancelled = self.db.cancel_pending_moderation_actions(
            123,
            456,
            ["TEMPBAN_EXPIRE"],
            case_id=case_id,
            reason="smoke_cancel",
        )
        self.assertEqual(cancelled, 1)
        self.assertFalse(self.db.has_pending_moderation_action(123, 456, ["TEMPBAN_EXPIRE"]))

        rules = self.db._normalize_automod_rules(
            {
                "words": {"enabled": True, "words": ["x"]},
                "caps": {"max_caps_percent": 80},
                "spam": {"duplicate_threshold": 4},
                "invites": {"enabled": True},
            }
        )
        self.assertTrue(rules["banned_words"]["enabled"])
        self.assertEqual(rules["caps"]["min_percent"], 80)
        self.assertTrue(rules["duplicate"]["enabled"])
        self.assertEqual(rules["duplicate"]["threshold"], 4)
        self.assertTrue(rules["links"]["block_invites"])

        outbox_id = self.db.enqueue_log_outbox(
            123,
            "moderation",
            {"embed": {"title": "Smoke"}},
            channel_id=999,
        )
        self.assertGreater(outbox_id, 0)
        self.assertEqual(self.db.get_pending_log_outbox()[0]["id"], outbox_id)
        self.db.mark_log_outbox(outbox_id, "pending", "retry")
        self.assertEqual(self.db.get_pending_log_outbox()[0]["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
