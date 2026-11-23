"""Consistent classification for natural-language tool return values."""


_FAILURE_MARKERS = (
    "could not", "cannot", "can't", "unable to", "error:", "error (", "error ",
    "failed", "failure", "unknown tool", "unknown action", "not available",
    "currently disabled", "not installed", "not found", "access denied",
    "permission denied", "unsupported operating system", "not supported",
    "no application name", "timed out", "timeout", "please provide", "please specify",
    "please confirm", "confirmation required",
)

_LEARNABLE_MARKERS = (
    "failed", "failure", "error:", "error (", "error ", "timed out", "timeout",
    "permission denied", "access denied", "not installed", "could not open",
    "could not launch", "unable to launch", "unable to open",
)


def is_tool_failure(result: object) -> bool:
    """Whether a tool's spoken result clearly indicates it did not succeed."""
    text = str(result or "").casefold().strip()
    return any(marker in text for marker in _FAILURE_MARKERS)


def is_learnable_failure(result: object) -> bool:
    """Only technical failures merit background research, not missing user input."""
    text = str(result or "").casefold().strip()
    if any(marker in text for marker in (
        "please provide", "please specify", "please confirm",
        "confirmation required", "unknown action", "unknown tool",
        "not available", "currently disabled", "not supported",
    )):
        return False
    return any(marker in text for marker in _LEARNABLE_MARKERS)
