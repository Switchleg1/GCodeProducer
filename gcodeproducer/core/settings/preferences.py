"""Global application preferences (Qt-free; shared with the compute process).

Stored as JSON next to the profile libraries. Unlike machine/tool profiles these
apply to every job, and unlike QSettings window state they influence generated
output, so they travel inside ``Job.preferences``.
"""
from __future__ import annotations

from gcodeproducer.core.settings.settings_constants import SCHEMA, MESSAGES, DEFAULTS
import json
from pathlib import Path
from gcodeproducer.core.libraries.schemas import default_root
from gcodeproducer.core.parameters.type_conversion import coerce_bool


# Pop-up messages that offer "Don't show this again". Every message is still
# recorded in the Messages panel when its pop-up is disabled.


def settings_path(root: Path | None = None) -> Path:
    return Path(root or default_root()) / "settings.json"


def load(root: Path | None = None) -> dict:
    path = settings_path(root)
    data = dict(DEFAULTS)
    try:
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                data.update({k: v for k, v in stored.items() if k in DEFAULTS})
                if stored.get("warning_dialog") is False:      # pre-'messages' preference
                    data["messages"] = {**DEFAULTS["messages"], **dict(data.get("messages") or {}), "cam_warnings": False}
    except (OSError, ValueError):
        pass          # corrupt preferences must not prevent start-up; defaults apply
    return validated(data)


def save(data: dict, root: Path | None = None) -> None:
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(validated(data), indent=2), encoding="utf-8")


def validated(data: dict) -> dict:
    out = dict(DEFAULTS)
    stored = data.get("messages")
    out["messages"] = {key: coerce_bool(stored[key])
                       if isinstance(stored, dict) and stored.get(key) is not None else True for key in MESSAGES}
    for p in SCHEMA:
        v = data.get(p.name, p.default)
        if p.type == "bool":
            out[p.name] = p.coerce(v)
        elif p.type in ("float", "int"):
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = p.default
            if v != v:          # NaN
                v = p.default
            if p.min is not None:
                v = max(p.min, v)
            if p.max is not None:
                v = min(p.max, v)
            out[p.name] = int(v) if p.type == "int" else v
        elif p.type == "choice":
            try:
                out[p.name] = p.coerce(v)
            except (TypeError, ValueError):
                out[p.name] = p.default
        else:
            out[p.name] = v
    return out


def pref(job, key):
    """Preference lookup that is safe for jobs built without preferences (CLI/tests)."""
    prefs = getattr(job, "preferences", None) or {}
    return prefs.get(key, DEFAULTS[key])


def message_enabled(prefs: dict, key: str) -> bool:
    return bool((prefs.get("messages") or {}).get(key, True))
