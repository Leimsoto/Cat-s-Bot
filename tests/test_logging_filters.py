import logging
import unittest

from main import DiscordVoiceReconnectFilter


class LoggingFilterTest(unittest.TestCase):
    def test_voice_reconnect_error_is_downgraded_without_traceback(self):
        try:
            raise RuntimeError("voice websocket closed")
        except RuntimeError:
            exc_info = __import__("sys").exc_info()

        record = logging.LogRecord(
            name="discord.voice_state",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Disconnected from voice... Reconnecting in 1.23s.",
            args=(),
            exc_info=exc_info,
        )

        self.assertTrue(DiscordVoiceReconnectFilter().filter(record))
        self.assertEqual(record.levelno, logging.WARNING)
        self.assertEqual(record.levelname, "WARNING")
        self.assertIsNone(record.exc_info)


if __name__ == "__main__":
    unittest.main()
