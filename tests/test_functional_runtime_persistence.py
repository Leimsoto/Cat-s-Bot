import json
import logging
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta, timezone

from database.manager import DatabaseManager


class FunctionalRuntimePersistenceTest(unittest.TestCase):
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

    def test_entity_numbers_ticket_states_and_report_resolution_are_atomic(self):
        first = self.db.create_ticket(10, 101, "General")
        second = self.db.create_ticket(10, 102, "General")
        other_guild = self.db.create_ticket(20, 201, "General")

        self.assertEqual((first["global_number"], second["global_number"]), (1, 2))
        self.assertEqual(other_guild["global_number"], 1)
        self.assertEqual(first["status"], "CREATING")
        self.assertTrue(
            self.db.transition_ticket_status(
                first["id"], "CREATING", "OPEN", channel_id=999
            )
        )
        self.assertFalse(
            self.db.transition_ticket_status(first["id"], "CREATING", "OPEN")
        )
        self.assertEqual(self.db.get_ticket(first["id"])["status"], "OPEN")

        case_a = self.db.log_action(10, 101, 500, "WARN", "a")
        case_b = self.db.log_action(10, 102, 500, "WARN", "b")
        case_other = self.db.log_action(20, 201, 600, "WARN", "c")
        self.assertEqual(self.db.get_case_by_id(10, case_a)["case_number"], 1)
        self.assertEqual(self.db.get_case_by_id(10, case_b)["case_number"], 2)
        self.assertEqual(self.db.get_case_by_id(20, case_other)["case_number"], 1)

        report_id = self.db.create_report(10, 1, 2, "motivo")
        self.assertFalse(self.db.resolve_report(report_id, 20, "RESOLVED"))
        self.assertTrue(self.db.resolve_report(report_id, 10, "RESOLVED"))
        self.assertFalse(self.db.resolve_report(report_id, 10, "DISMISSED"))
        self.assertEqual(self.db.get_report(report_id)["status"], "RESOLVED")

    def test_starboard_rolemenu_reminders_and_lockdown_persist(self):
        self.db.upsert_starboard_entry(10, 1000, 2000, 3000, 4)
        row = self.db.get_starboard_entry(10, 1000)
        self.assertEqual(row["star_count"], 4)
        self.db.upsert_starboard_entry(10, 1000, 2001, 3001, 7)
        row = self.db.get_starboard_entry(10, 1000)
        self.assertEqual((row["source_channel_id"], row["starboard_message_id"], row["star_count"]), (2001, 3001, 7))
        self.db.delete_starboard_entry(10, 1000)
        self.assertIsNone(self.db.get_starboard_entry(10, 1000))

        self.db.save_role_menu(4000, 10, 2000, [5000, 5001], "Elige", 2, "Roles", "Descripción")
        menus = self.db.get_role_menus(10)
        self.assertEqual(len(menus), 1)
        self.assertEqual(menus[0]["role_ids"], [5000, 5001])
        self.db.delete_role_menu(4000, 10)
        self.assertEqual(self.db.get_role_menus(10), [])

        due = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.db.create_reminder("rem-1", 101, "recordar", due, guild_id=10)
        self.assertEqual(self.db.get_due_reminders(datetime.now(timezone.utc).isoformat())[0]["reminder_id"], "rem-1")
        self.assertTrue(self.db.claim_reminder("rem-1"))
        self.assertFalse(self.db.claim_reminder("rem-1"))
        self.assertEqual(self.db.recover_processing_reminders(), 1)
        self.assertTrue(self.db.claim_reminder("rem-1"))
        self.db.complete_reminder("rem-1")
        reminder = self.db._fetchone(
            "SELECT * FROM persistent_reminders WHERE reminder_id = ?", ("rem-1",)
        )
        self.assertEqual(reminder["status"], "sent")
        self.assertEqual(reminder["attempts"], 2)

        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        self.db.save_raid_lockdown(10, 2, expires)
        self.db.save_raid_lockdown(10, 4, expires)
        lockdown = self.db.get_raid_lockdown(10)
        self.assertEqual(lockdown["original_verification_level"], 2)
        self.assertEqual(len(self.db.get_active_raid_lockdowns()), 1)
        self.db.delete_raid_lockdown(10)
        self.assertIsNone(self.db.get_raid_lockdown(10))

    def test_giveaway_participants_finalization_and_runtime_claims(self):
        self.db.create_giveaway(10, 20, 30, "Premio", 1_800_000_000, 1, "[]", "[]")
        joined, participants = self.db.toggle_giveaway_participant(30, 100)
        self.assertTrue(joined)
        self.assertEqual(participants, [100])
        joined, participants = self.db.toggle_giveaway_participant(30, 200)
        self.assertTrue(joined)
        self.assertEqual(participants, [100, 200])
        joined, participants = self.db.toggle_giveaway_participant(30, 100)
        self.assertFalse(joined)
        self.assertEqual(participants, [200])
        self.assertEqual(self.db.list_giveaway_participants(30), [200])
        self.assertEqual(json.loads(self.db.get_giveaway(30)["participants"]), [200])

        self.assertTrue(self.db.claim_giveaway_finalization(30, [200]))
        self.assertFalse(self.db.claim_giveaway_finalization(30, [200]))
        self.assertTrue(self.db.release_giveaway_finalization(30))
        self.assertTrue(self.db.claim_giveaway_finalization(30, [200]))
        self.assertTrue(self.db.complete_giveaway_finalization(30))
        self.assertEqual(self.db.get_giveaway(30)["ended"], 1)

        now = datetime.now(timezone.utc).isoformat()
        pending_id = self.db.add_pending_moderation_action(10, 100, "UNMUTE", now)
        self.assertTrue(self.db.claim_pending_moderation_action(pending_id))
        self.assertFalse(self.db.claim_pending_moderation_action(pending_id))
        self.assertEqual(self.db.recover_processing_moderation_actions(), 1)
        self.assertTrue(self.db.claim_pending_moderation_action(pending_id))

        outbox_id = self.db.enqueue_log_outbox(10, "moderation", {"embed": {"title": "x"}}, 20)
        self.assertTrue(self.db.claim_log_outbox(outbox_id))
        self.assertFalse(self.db.claim_log_outbox(outbox_id))
        self.assertEqual(self.db.recover_processing_log_outbox(), 1)
        self.assertTrue(self.db.claim_log_outbox(outbox_id))


if __name__ == "__main__":
    unittest.main()
