"""Conservative checks for missing software after a plugin reports failure.

Only diagnose a missing requirement when the plugin's error names it and a
read-only host check confirms it is unavailable. This module never installs or
launches software.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sys


# Import names differ from some package distribution names.
_DISTRIBUTIONS = {
    "win32com": "pywin32",
    "pythoncom": "pywin32",
    "pywintypes": "pywin32",
    "pil": "Pillow",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "sklearn": "scikit-learn",
    "serial": "pyserial",
}
_PACKAGE_IMPORTS = {
    "pywin32": ("win32com", "pythoncom", "pywintypes"),
    "pillow": ("PIL",),
    "opencv-python": ("cv2",),
    "pyyaml": ("yaml",),
    "beautifulsoup4": ("bs4",),
    "scikit-learn": ("sklearn",),
    "pyserial": ("serial",),
}
_KNOWN_PYTHON_PACKAGES = {
    "pyperclip", "pycaw", "comtypes", "psutil", "pyautogui", "pywinauto",
    "win32com", "pythoncom", "pywintypes", "pywin32", "pillow", "pil",
    "opencv-python", "cv2", "pyyaml", "yaml", "beautifulsoup4", "bs4",
    "scikit-learn", "sklearn", "pyserial", "serial",
}
_SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]{0,95}$")
_SAFE_EXECUTABLE = re.compile(r"^[A-Za-z0-9_./\\:+ -]{1,260}$")
_PACKAGE_FILLER = {"and", "or", "the", "a", "an", "optional", "required", "python"}
_NO_MODULE = re.compile(r"No module named\s+['\"]([A-Za-z_][A-Za-z0-9_.]*)['\"]", re.I)
_NEEDED_PACKAGES = re.compile(
    r"\b(?:needs?|requires?)\s+(?:(?:the|a|an|optional|required|python)\s+)*"
    r"([A-Za-z][A-Za-z0-9_.+-]*(?:\s*(?:,|and|or)\s*"
    r"[A-Za-z][A-Za-z0-9_.+-]*)*)\s+(?:python\s+)?(?:packages?|modules?)\b",
    re.I,
)
_MISSING_EXECUTABLE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<name>[A-Za-z0-9_./\\:+-]+)\)?\s+"
    r"(?:is\s+)?(?:not installed|not available|not found|is missing|"
    r"not on (?:the )?PATH)\b",
    re.I,
)
_NEEDED_EXECUTABLE = re.compile(
    r"\b(?:needs?|requires?)\s+(?:the\s+)?"
    r"(?P<name>[A-Za-z0-9_.+-]+)\s+(?:installed|available)\b",
    re.I,
)
_DEPENDENCY_CONTEXT = re.compile(
    r"\b(?:need(?:s|ed)?|require(?:s|d)?|missing|not installed|"
    r"modulenotfounderror|importerror)\b",
    re.I,
)


def _module_available(name: str) -> bool:
    """Return whether a Python module can be resolved without importing it."""
    if name in sys.modules and sys.modules[name] is not None:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _package_import_names(name: str) -> tuple[str, ...]:
    return _PACKAGE_IMPORTS.get(name.casefold(), (name,))


def _distribution_name(module_name: str) -> str:
    root = module_name.split(".", 1)[0]
    return _DISTRIBUTIONS.get(root.casefold(), root.replace("_", "-"))


def _exception_chain(error: BaseException | None):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def _module_candidates(message: str, error: BaseException | None) -> list[str]:
    names: list[str] = []
    for cause in _exception_chain(error):
        if isinstance(cause, ModuleNotFoundError) and cause.name:
            names.append(cause.name)
    names.extend(_NO_MODULE.findall(message))

    for match in _NEEDED_PACKAGES.finditer(message):
        names.extend(
            name for name in re.findall(r"[A-Za-z][A-Za-z0-9_.+-]*", match.group(1))
            if name.casefold() not in _PACKAGE_FILLER
        )

    # Some plugins name optional Python modules without spelling out "package".
    # Only trust these names in the immediate context of a dependency error.
    for known in sorted(
        _KNOWN_PYTHON_PACKAGES,
        key=lambda item: message.casefold().find(item.casefold())
        if item.casefold() in message.casefold() else len(message),
    ):
        for match in re.finditer(rf"(?<![A-Za-z0-9_.+-]){re.escape(known)}(?![A-Za-z0-9_.+-])", message, re.I):
            context = message[max(0, match.start() - 100):match.end() + 60]
            if _DEPENDENCY_CONTEXT.search(context):
                names.append(match.group(0))

    out = []
    seen = set()
    for name in names:
        if not _SAFE_NAME.fullmatch(name):
            continue
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _missing_python_modules(names: list[str]) -> list[tuple[str, str]]:
    missing = []
    seen = set()
    for name in names:
        modules = _package_import_names(name)
        if any(_module_available(module) for module in modules):
            continue
        distribution = _distribution_name(name)
        key = distribution.casefold()
        if key not in seen:
            seen.add(key)
            missing.append((name, distribution))
    return missing


def _is_safe_executable(name: str) -> bool:
    if _SAFE_NAME.fullmatch(name):
        return True
    return (("/" in name or "\\" in name)
            and _SAFE_EXECUTABLE.fullmatch(name) is not None)


def _executable_candidates(message: str) -> list[str]:
    names = [match.group("name").strip("'\"`.,;:()[]{}")
             for match in _MISSING_EXECUTABLE.finditer(message)]
    names.extend(match.group("name").strip("'\"`.,;:()[]{}")
                 for match in _NEEDED_EXECUTABLE.finditer(message))
    out = []
    seen = set()
    for name in names:
        if not name or not _is_safe_executable(name):
            continue
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _executable_from_spawn_error(error: BaseException | None) -> list[str]:
    """Extract command names only from FileNotFound errors raised by subprocess."""
    candidates = []
    for cause in _exception_chain(error):
        if not isinstance(cause, FileNotFoundError):
            continue
        tb = cause.__traceback__
        from_subprocess = False
        while tb is not None:
            code = tb.tb_frame.f_code
            if (code.co_name == "_execute_child"
                    and os.path.basename(code.co_filename).casefold() == "subprocess.py"):
                from_subprocess = True
                break
            tb = tb.tb_next
        filename = cause.filename
        if from_subprocess and isinstance(filename, str) and _SAFE_EXECUTABLE.fullmatch(filename):
            candidates.append(filename)
    return candidates


def _include_detail(message: str) -> str:
    detail = " ".join(str(message or "").split())
    if len(detail) > 500:
        detail = detail[:497] + "..."
    return f" Plugin detail: {detail}" if detail else ""


def diagnose_missing_software(
    plugin_name: str,
    result: object,
    error: BaseException | None = None,
) -> str:
    """Explain a confirmed missing package or executable, else return ``''``.

    The check is deliberately conservative: generic plugin errors and ordinary
    missing user files are left untouched. Python packages are checked with
    ``find_spec``; executables with ``shutil.which``. No software is installed.
    """
    message = str(result or "")
    missing_modules = _missing_python_modules(_module_candidates(message, error))
    if missing_modules:
        module_names = ", ".join(f"'{name}'" for name, _ in missing_modules)
        distributions = list(dict.fromkeys(dist for _, dist in missing_modules))
        distribution_names = " ".join(distributions)
        return (
            f"The '{plugin_name}' plugin failed because required Python module(s) "
            f"{module_names} are not available in ADHITHIYA's active environment. "
            f"Install the corresponding package(s) ({', '.join(distributions)}) "
            f"there (for example, `python -m pip install {distribution_names}`), "
            f"then retry.{_include_detail(message)}"
        )

    executables = _executable_from_spawn_error(error)
    executables.extend(_executable_candidates(message))
    seen_executables = set()
    for executable in executables:
        key = executable.casefold()
        if key in seen_executables:
            continue
        seen_executables.add(key)
        if shutil.which(executable) is None:
            return (
                f"The '{plugin_name}' plugin failed because required executable "
                f"'{executable}' was not found on PATH. It may be uninstalled or "
                "installed outside PATH; install it using its official instructions "
                "and make it available on PATH, then retry."
                f"{_include_detail(message)}"
            )
    return ""
