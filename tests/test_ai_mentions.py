import unittest
from types import SimpleNamespace

from cogs._ai_mentions import format_ai_mentions, mention_context, split_ai_text


class AIMentionsTest(unittest.TestCase):
    def setUp(self):
        self.author = SimpleNamespace(id=30, display_name="Ana", name="ana", bot=False)
        self.other = SimpleNamespace(id=31, display_name="Luis", name="luis", bot=False)
        self.message = SimpleNamespace(author=self.author, mentions=[self.other], content="Pregunta a <@31>",
                                       guild=SimpleNamespace(members=[self.author, self.other]))

    def test_only_explicit_real_members_are_allowed_and_author_ping_is_first_only(self):
        text, mentions = format_ai_mentions("Hola <@30>, <@31> <@999> @everyone <@&77>", self.message)
        self.assertIn("<@31>", text)
        self.assertNotIn("<@999>", text)
        self.assertFalse(mentions.everyone)
        self.assertFalse(mentions.roles)
        self.assertTrue(mentions.replied_user)
        self.assertEqual({user.id for user in mentions.users}, {30, 31})
        _, continuation = format_ai_mentions(text, self.message, first_fragment=False)
        self.assertFalse(continuation.replied_user)
        self.assertFalse(continuation.users)

    def test_unique_exact_names_resolve_but_ambiguous_names_do_not(self):
        self.message.mentions = []
        self.message.content = "Pregunta a @Luis"
        self.assertEqual({row["user_id"] for row in mention_context(self.message)}, {"30", "31"})
        text, _ = format_ai_mentions("@Luis sabe", self.message)
        self.assertEqual(text, "<@31> sabe")
        self.message.guild.members.append(SimpleNamespace(id=32, display_name="Luis", name="other", bot=False))
        self.assertEqual({row["user_id"] for row in mention_context(self.message)}, {"30"})

    def test_member_named_without_at_in_question_can_be_mentioned_in_answer(self):
        self.message.mentions = []
        self.message.content = "Pregúntale a Luis"
        self.assertEqual(format_ai_mentions("@Luis sabe", self.message)[0], "<@31> sabe")

    def test_chunks_keep_complete_mentions(self):
        text = "a" * 29 + "<@123456789012345678>" + "b" * 50
        chunks = list(split_ai_text(text, 40))
        self.assertEqual("".join(chunks), text)
        self.assertTrue(any("<@123456789012345678>" in chunk for chunk in chunks))

    def test_new_member_in_later_fragment_pings_once_without_repeating_author(self):
        notified = set()
        _, first = format_ai_mentions("Hola", self.message, notified_user_ids=notified)
        _, second = format_ai_mentions("<@31> sabe", self.message, first_fragment=False, notified_user_ids=notified)
        _, third = format_ai_mentions("Otra vez <@31> <@30>", self.message, first_fragment=False, notified_user_ids=notified)
        self.assertTrue(first.replied_user)
        self.assertEqual({member.id for member in second.users}, {31})
        self.assertFalse(second.replied_user)
        self.assertFalse(third.users)
