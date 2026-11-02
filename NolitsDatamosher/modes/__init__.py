import importlib
import pkgutil
import sys
import traceback
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_REQUIRED = ("NAME", "HELP", "add_arguments", "run")


def load_modes():   # mode loader
    from ._common import _log

    found = {}

    for info in sorted(pkgutil.iter_modules([str(_PKG_DIR)]), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue

        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
        except Exception:
            _log(f"mode file {info.name}.py failed to import, skipping:\n{traceback.format_exc()}", "err")
            continue

        missing = [a for a in _REQUIRED if not hasattr(mod, a)]

        if missing:
            _log(f"mode file {info.name}.py is missing {', '.join(missing)}, skipping", "err")
            continue

        if mod.NAME in found:
            _log(f"mode name '{mod.NAME}' in {info.name}.py is already taken by {found[mod.NAME].__name__}, skipping", "err")
            continue

        found[mod.NAME] = mod
        
    return found