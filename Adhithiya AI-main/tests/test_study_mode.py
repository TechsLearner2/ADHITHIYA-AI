import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins import study_mode


class StudyModeSmokeTests(unittest.TestCase):
    root = Path(__file__).resolve().parent / "_study_smoke_workspace"

    def setUp(self):
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cards_are_extracted_without_inventing_answers(self):
        cards = study_mode._cards_from_text(
            "Photosynthesis is the process plants use to make food. "
            "It needs light and carbon dioxide."
        )
        self.assertEqual(cards[0]["back"], "Photosynthesis is the process plants use to make food.")
        self.assertIn("What is Photosynthesis?", cards[0]["front"])

    def test_flashcard_save_requires_confirmation(self):
        state_file = self.root / "cards.json"
        with patch.object(study_mode, "STATE_FILE", state_file):
            pending = study_mode.run({
                "action": "generate_flashcards",
                "topic": "biology",
                "source_text": "A cell is the basic unit of life.",
            })
            self.assertIn("Confirm", pending)
            self.assertFalse(state_file.exists())

            saved = study_mode.run({
                "action": "generate_flashcards",
                "topic": "biology",
                "source_text": "A cell is the basic unit of life.",
                "confirmed": True,
            })
            self.assertIn("Saved 1 flashcards", saved)
            self.assertEqual(len(json.loads(state_file.read_text())["decks"]["biology"]), 1)

    def test_quiz_uses_supplied_source(self):
        with patch.object(study_mode.quiz, "run", return_value="quiz ready") as run_quiz:
            result = study_mode.run({
                "action": "start_quiz",
                "topic": "history",
                "source_text": "The treaty is an agreement between states.",
            })
        self.assertEqual(result, "quiz ready")
        args = run_quiz.call_args.args[0]
        self.assertEqual(args["action"], "start")
        self.assertTrue(args["questions"])

    def test_quiz_review_grades_answers(self):
        result = study_mode.run({
            "action": "review_quiz",
            "questions": [{
                "type": "multiple_choice",
                "question": "2 + 2?",
                "options": ["3", "4"],
                "answer": "4",
            }],
            "answers": ["4"],
        })
        self.assertIn("1/1 correct", result)


if __name__ == "__main__":
    unittest.main()
