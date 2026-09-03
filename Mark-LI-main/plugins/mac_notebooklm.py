"""NotebookLM workflows through the existing authenticated browser session."""

from actions.browser_control import browser_control

from ._macos import confirmed, finish, supported, unsupported


PLUGIN = {
    "name": "mac_notebooklm",
    "description": (
        "Open and control Google NotebookLM in the user's browser session. "
        "Use action open, ask, read, click, type, scroll, or press. "
        "Ask and other changes require confirmed=true. Never request or expose passwords."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "open, ask, read, click, type, scroll, or press.",
            },
            "question": {"type": "STRING", "description": "Question to ask NotebookLM."},
            "text": {"type": "STRING", "description": "Text to type."},
            "description": {"type": "STRING", "description": "Visible element to click or type into."},
            "key": {"type": "STRING", "description": "Browser key to press, such as Enter."},
            "direction": {"type": "STRING", "description": "up or down for scroll."},
            "amount": {"type": "INTEGER", "description": "Scroll amount in pixels."},
            "browser": {"type": "STRING", "description": "chrome, edge, firefox, or safari."},
            "confirmed": {"type": "BOOLEAN", "description": "Confirm asking or changing NotebookLM."},
        },
        "required": ["action"],
    },
}

_URL = "https://notebooklm.google.com/"


def _call(params: dict, action: str, **extra) -> str:
    browser = params.get("browser")
    request = {"action": action, "browser": browser, **extra}
    return browser_control(parameters=request)


def run(parameters: dict, player=None, session_memory=None) -> str:
    if not supported():
        return finish(player, unsupported("mac_notebooklm"))
    params = parameters if isinstance(parameters, dict) else {}
    action = str(params.get("action", "open")).strip().lower().replace("-", "_")

    if action == "open":
        result = _call(params, "go_to", url=_URL)
    elif action == "read":
        result = _call(params, "get_text")
    elif action == "ask":
        question = params.get("question")
        if not isinstance(question, str) or not question.strip():
            return finish(player, "Please provide the NotebookLM question.")
        if not confirmed(params):
            return finish(player, "Please confirm before asking NotebookLM that question.")
        result = _call(params, "smart_type", description="Ask a question", text=question.strip())
        if result.startswith(("Could not", "Type error")):
            return finish(player, result)
        result = _call(params, "press", key="Enter")
    elif action in {"click", "type"}:
        if not confirmed(params):
            return finish(player, f"Please confirm before controlling NotebookLM with {action}.")
        if action == "click":
            result = _call(params, "smart_click", description=str(params.get("description", "")).strip())
        else:
            result = _call(
                params,
                "smart_type",
                description=str(params.get("description", "")).strip(),
                text=str(params.get("text", "")),
            )
    elif action == "press":
        result = _call(params, "press", key=str(params.get("key", "Enter")))
    elif action == "scroll":
        result = _call(
            params,
            "scroll",
            direction=str(params.get("direction", "down")),
            amount=int(params.get("amount", 500)),
        )
    else:
        return finish(player, "Use NotebookLM action open, ask, read, click, type, scroll, or press.")
    return finish(player, result)
