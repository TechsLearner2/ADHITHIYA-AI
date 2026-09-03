"""Student study mode composed from the existing local plugins.

This plugin deliberately does not call another cloud service.  NotebookLM is
used only through its already-authenticated browser session, while flashcards
are kept in a small, user-readable JSON file under ``memory/``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from threading import Lock

from ._macos import confirmed, finish
from . import mac_notebooklm, mac_reminders, mac_calendar, pomodoro, quiz


STATE_FILE = Path(__file__).resolve().parent.parent / "memory" / "study_flashcards.json"
_LOCK = Lock()
_MAX_CARDS = 300
_MAX_TEXT = 500

PLUGIN = {
    "name": "study_mode",
    "description": (
        "Student study mode for ADHITHIYA. Use it to work with NotebookLM, "
        "generate and review locally stored flashcards, start a quiz from supplied "
        "text or NotebookLM output, track deadlines with macOS Reminders/Calendar, "
        "and start/stop/check a Pomodoro focus session. NotebookLM asking, external "
        "calendar/reminder changes, and persistent flashcard changes require "
        "confirmed=true. Never request passwords."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "notebooklm | generate_flashcards | list_flashcards | "
                    "review_flashcards | clear_flashcards | start_quiz | stop_quiz | "
                    "deadline_create | deadline_list | focus. Aliases are accepted."
                ),
            },
            "topic": {"type": "STRING", "description": "Subject or deck name."},
            "source_text": {
                "type": "STRING",
                "description": "Supplied notes/text, or text returned by NotebookLM.",
            },
            "cards": {
                "type": "ARRAY",
                "description": "Optional cards with front/question and back/answer fields.",
                "items": {"type": "OBJECT"},
            },
            "card_id": {"type": "STRING", "description": "Flashcard id to review."},
            "answer": {"type": "STRING", "description": "Answer given for a flashcard."},
            "correct": {"type": "BOOLEAN", "description": "Whether the answer was correct."},
            "notebooklm_action": {
                "type": "STRING",
                "description": "NotebookLM action: open, read, or ask.",
            },
            "browser": {
                "type": "STRING",
                "description": "Browser for NotebookLM: chrome, edge, firefox, or safari.",
            },
            "question": {"type": "STRING", "description": "Question for NotebookLM."},
            "questions": {
                "type": "ARRAY",
                "description": "Optional quiz questions in the quiz plugin format.",
                "items": {"type": "OBJECT"},
            },
            "answers": {
                "type": "ARRAY",
                "description": "Answers in question order for review_quiz.",
                "items": {"type": "STRING"},
            },
            "title": {"type": "STRING", "description": "Deadline/reminder title."},
            "due": {"type": "STRING", "description": "ISO due date/time for a reminder."},
            "start": {"type": "STRING", "description": "ISO calendar event start."},
            "end": {"type": "STRING", "description": "ISO calendar event end."},
            "use_calendar": {
                "type": "BOOLEAN",
                "description": "Use Calendar instead of Reminders for a deadline.",
            },
            "focus_action": {
                "type": "STRING",
                "description": "Focus action: start, stop, status, or stats.",
            },
            "work_minutes": {"type": "INTEGER", "description": "Focus minutes."},
            "break_minutes": {"type": "INTEGER", "description": "Break minutes."},
            "task": {"type": "STRING", "description": "Focus task."},
            "confirmed": {
                "type": "BOOLEAN",
                "description": "Explicitly approve the exact persistent or external action.",
            },
        },
        "required": ["action"],
    },
}


def _text(value, limit: int = _MAX_TEXT) -> str:
    return str(value or "").strip()[:limit]


def _topic(parameters: dict) -> str:
    return _text(parameters.get("topic"), 80) or "General"


def _load() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("decks"), dict):
            decks = {}
            for name, cards in data["decks"].items():
                if not isinstance(name, str) or not isinstance(cards, list):
                    continue
                decks[name[:80]] = [
                    card for card in cards[:_MAX_CARDS]
                    if isinstance(card, dict)
                    and _text(card.get("front"))
                    and _text(card.get("back"))
                ]
            return {"version": 1, "decks": decks}
    except (OSError, ValueError, TypeError):
        pass
    return {"version": 1, "decks": {}}


def _save(data: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Keep one bounded, human-readable file and avoid writing arbitrary paths.
    with _LOCK:
        STATE_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def _normalise(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())


def _explicit_cards(raw) -> list[dict]:
    result = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        front = _text(item.get("front") or item.get("question"))
        back = _text(item.get("back") or item.get("answer"))
        if front and back:
            result.append({"front": front, "back": back})
    return result[:50]


def _cards_from_text(source: str) -> list[dict]:
    """Extract conservative cards from text without inventing facts."""
    cards = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", source):
        sentence = _text(sentence)
        if len(sentence) < 12:
            continue
        match = re.match(r"^(.{2,100}?)\s+(?:is|are|means|refers to|:)\s+(.+)$", sentence, re.I)
        if match:
            front = f"What is {match.group(1).strip()}?"
            back = sentence
        else:
            words = sentence.split()
            if len(words) < 6:
                continue
            front = "Recall this point from the notes:"
            back = sentence
        cards.append({"front": front[:_MAX_TEXT], "back": back[:_MAX_TEXT]})
        if len(cards) >= 20:
            break
    return cards


def _new_cards(topic: str, parameters: dict) -> list[dict]:
    cards = _explicit_cards(parameters.get("cards"))
    source = _text(parameters.get("source_text"), 12000)
    if not cards and source:
        cards = _cards_from_text(source)
    if not cards and parameters.get("notebooklm_action") == "read":
        result = mac_notebooklm.run(
            {"action": parameters.get("notebooklm_action") or "read",
             "browser": parameters.get("browser")},
            player=None,
        )
        if result and not result.startswith(("Could not", "Please", "mac_notebooklm is")):
            cards = _cards_from_text(result)
    now = datetime.now().isoformat(timespec="seconds")
    return [
        {
            "id": f"{_normalise(topic).replace(' ', '-')[:30] or 'general'}-{i + 1}",
            "front": card["front"],
            "back": card["back"],
            "created": now,
            "reviews": 0,
            "correct": 0,
        }
        for i, card in enumerate(cards)
    ]


def _generate(parameters: dict, player) -> str:
    topic = _topic(parameters)
    cards = _new_cards(topic, parameters)
    if not cards:
        return finish(player, "Provide study text, cards, or NotebookLM text first.")
    if not confirmed(parameters):
        preview = "\n".join(
            f"- {card['front']} → {card['back']}" for card in cards[:5]
        )
        return finish(
            player,
            f"I prepared {len(cards)} flashcards for {topic}. "
            f"Preview:\n{preview}\nConfirm to save them locally with confirmed=true.",
        )
    data = _load()
    deck = data["decks"].setdefault(topic, [])
    existing = {(c.get("front"), c.get("back")) for c in deck}
    added = 0
    for card in cards:
        if (card["front"], card["back"]) not in existing:
            deck.append(card)
            existing.add((card["front"], card["back"]))
            added += 1
    data["decks"][topic] = deck[-_MAX_CARDS:]
    _save(data)
    return finish(player, f"Saved {added} flashcards in the local {topic} deck.")


def _list(parameters: dict, player) -> str:
    topic = _topic(parameters)
    deck = _load()["decks"].get(topic, [])
    if not deck:
        return finish(player, f"No flashcards are saved for {topic}.")
    lines = [f"{topic}: {len(deck)} flashcards"]
    lines.extend(f"{i + 1}. {card['front']}" for i, card in enumerate(deck[:20]))
    return finish(player, "\n".join(lines))


def _review(parameters: dict, player) -> str:
    topic = _topic(parameters)
    data = _load()
    deck = data["decks"].get(topic, [])
    if not deck:
        return finish(player, f"No flashcards are saved for {topic}.")
    card_id = _text(parameters.get("card_id"), 80)
    card = next((c for c in deck if c.get("id") == card_id), deck[0])
    if parameters.get("answer") is None and parameters.get("correct") is None:
        return finish(player, f"Flashcard {card.get('id')}: {card.get('front')}")
    if not confirmed(parameters):
        return finish(player, "Confirm to save this flashcard review with confirmed=true.")
    correct = parameters.get("correct")
    if correct is None:
        correct = _normalise(_text(parameters.get("answer"))) == _normalise(card.get("back", ""))
    try:
        reviews = max(0, int(card.get("reviews", 0)))
    except (TypeError, ValueError):
        reviews = 0
    try:
        correct_count = max(0, int(card.get("correct", 0)))
    except (TypeError, ValueError):
        correct_count = 0
    card["reviews"] = reviews + 1
    card["correct"] = correct_count + (1 if correct else 0)
    _save(data)
    verdict = "correct" if correct else "not quite"
    return finish(player, f"That answer was {verdict}. Answer: {card.get('back')}")


def _quiz(parameters: dict, player) -> str:
    topic = _topic(parameters)
    raw_questions = parameters.get("questions")
    if not raw_questions:
        cards = _new_cards(topic, parameters)
        raw_questions = [
            {
                "type": "open",
                "question": card["front"],
                "answer": card["back"],
                "note": "Review the source notes and explain the idea in your own words.",
            }
            for card in cards[:10]
        ]
    if not raw_questions:
        return finish(player, "Provide study text, NotebookLM text, or quiz questions first.")
    return finish(
        player,
        quiz.run({"action": "start", "topic": topic, "questions": raw_questions},
                 player=player),
    )


def _review_quiz(parameters: dict, player) -> str:
    questions = quiz.clean_questions(parameters.get("questions"))
    answers = parameters.get("answers")
    if not questions or not isinstance(answers, list):
        return finish(player, "Provide quiz questions and answers in matching order.")
    right = deferred = wrong = 0
    for question, answer in zip(questions, answers):
        result = quiz.grade(question, _text(answer))
        if result is True:
            right += 1
        elif result is None:
            deferred += 1
        else:
            wrong += 1
    total = min(len(questions), len(answers))
    missing = max(0, len(questions) - len(answers))
    return finish(
        player,
        f"Quiz review: {right}/{total} correct, {wrong} incorrect"
        + (f", {deferred} need explanation" if deferred else "")
        + (f", {missing} unanswered" if missing else "") + ".",
    )


def _deadline(parameters: dict, player, action: str) -> str:
    use_calendar = bool(parameters.get("use_calendar") or parameters.get("start"))
    target = mac_calendar if use_calendar else mac_reminders
    if action == "deadline_list":
        return finish(player, target.run({"action": "list"}, player=player))
    title = _text(parameters.get("title")) or _topic(parameters)
    if not confirmed(parameters):
        kind = "calendar event" if use_calendar else "reminder"
        return finish(player, f"Confirm creating the {kind} '{title}' with confirmed=true.")
    if use_calendar:
        args = {
            "action": "create",
            "title": title,
            "start": _text(parameters.get("start") or parameters.get("due")),
            "end": _text(parameters.get("end") or parameters.get("start") or parameters.get("due")),
            "notes": f"Study deadline: {_topic(parameters)}",
            "confirmed": True,
        }
    else:
        args = {
            "action": "create",
            "title": title,
            "due": _text(parameters.get("due")),
            "confirmed": True,
        }
    return finish(player, target.run(args, player=player))


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters if isinstance(parameters, dict) else {}
    action = _text(parameters.get("action"), 50).lower().replace("-", "_").replace(" ", "_")
    if action in {
        "notebooklm", "notebook", "study_session", "notebooklm_open",
        "notebooklm_read", "notebooklm_ask",
    }:
        args = dict(parameters)
        action_suffix = action.removeprefix("notebooklm_")
        requested = _text(args.get("notebooklm_action"), 20).lower()
        args["action"] = requested or (
            action_suffix if action_suffix in {"open", "read", "ask"} else "open"
        )
        return finish(player, mac_notebooklm.run(args, player=player))
    if action in {
        "generate_flashcards", "flashcards_generate", "flashcard_generate",
        "add_flashcards",
    }:
        return _generate(parameters, player)
    if action in {"list_flashcards", "flashcards", "deck"}:
        return _list(parameters, player)
    if action in {"review_flashcards", "flashcard_review", "review"}:
        return _review(parameters, player)
    if action in {"clear_flashcards", "flashcards_clear"}:
        if not confirmed(parameters):
            return finish(player, "Confirm clearing this local flashcard deck with confirmed=true.")
        data = _load()
        data["decks"].pop(_topic(parameters), None)
        _save(data)
        return finish(player, f"Cleared the local {_topic(parameters)} flashcard deck.")
    if action in {"start_quiz", "generate_quiz", "quiz", "quiz_generate"}:
        return _quiz(parameters, player)
    if action in {"review_quiz", "quiz_review"}:
        return _review_quiz(parameters, player)
    if action in {"stop_quiz", "quiz_stop"}:
        return finish(player, quiz.run({"action": "stop"}, player=player))
    if action in {"deadline_create", "create_deadline", "deadline", "add_deadline"}:
        return _deadline(parameters, player, "deadline_create")
    if action in {"deadline_list", "deadlines"}:
        return _deadline(parameters, player, "deadline_list")
    if action in {
        "focus", "focus_session", "pomodoro", "focus_start", "focus_stop",
        "focus_status", "focus_stats",
    }:
        args = dict(parameters)
        suffix = action.removeprefix("focus_")
        requested = _text(args.get("focus_action"), 20).lower()
        args["action"] = requested or (
            suffix if suffix in {"start", "stop", "status", "stats"} else "status"
        )
        return finish(player, pomodoro.run(args, player=player))
    return finish(player, "Use study_mode for NotebookLM, flashcards, quizzes, deadlines, or focus sessions.")
