import unittest

from cogs.suggestions import Suggestions


class _SuggestionDB:
    def __init__(self):
        self.rows = {}
        self.next_id = 1

    def get_suggestions_config(self, _guild_id):
        return {
            "enabled": 1,
            "submit_channel_id": 20,
            "public_channel_id": 999,
            "auto_publish": 1,
            "min_length": 1,
            "max_length": 2000,
            "cooldown_seconds": 0,
        }

    def create_suggestion(self, guild_id, user_id, content):
        suggestion_id = self.next_id
        self.next_id += 1
        self.rows[suggestion_id] = {
            "id": suggestion_id,
            "guild_id": guild_id,
            "user_id": user_id,
            "content": content,
            "status": "PENDING",
        }
        return suggestion_id

    def update_suggestion(self, suggestion_id, **kwargs):
        self.rows[suggestion_id].update(kwargs)


class _Bot:
    def __init__(self, db):
        self.db = db


class _Avatar:
    url = "https://example.test/avatar.png"


class _Author:
    id = 30
    bot = False
    display_name = "Autor"
    display_avatar = _Avatar()
    mention = "<@30>"

    def __init__(self):
        self.notifications = []

    async def send(self, text):
        self.notifications.append(text)


class _Channel:
    id = 20

    def __init__(self):
        self.messages = []

    async def send(self, text, **_kwargs):
        self.messages.append(text)


class _Guild:
    id = 10
    name = "Guild"

    def get_channel(self, _channel_id):
        return None


class _Message:
    def __init__(self):
        self.author = _Author()
        self.channel = _Channel()
        self.guild = _Guild()
        self.content = "Contenido importante que no debe perderse"
        self.deleted = False

    async def delete(self):
        self.deleted = True


class SuggestionsRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_delivery_preserves_source_and_marks_failed(self):
        db = _SuggestionDB()
        cog = Suggestions(_Bot(db))
        message = _Message()

        await cog.on_message(message)

        self.assertFalse(message.deleted)
        self.assertEqual(db.rows[1]["status"], "FAILED")
        self.assertEqual(len(message.author.notifications), 1)
        self.assertIn("mensaje original se conservó", message.author.notifications[0])


if __name__ == "__main__":
    unittest.main()
