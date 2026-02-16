from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


APP_NAME = "Narrative_Edit"
LEGACY_APP_NAME = "Tag" + "Sumi"

DEFAULT_CONFIG: dict[str, Any] = {
    "config_schema": 5,
    "ui_language": "ja",
    "ui_theme": "soft_light",
    "font_size": 16,
    "recent_files_limit": 10,
    "recent_files": [],
    "autosave_enabled": True,
    "autosave_interval_sec": 5,
    "fallback_encodings": ["utf-8", "utf-8-sig", "cp932"],
    "manuscript_grid_rows": 40,
    "manuscript_grid_cols": 40,
    "show_manuscript_grid": True,
    "plot_panel_expanded": True,
    "plot_panel_sections": {
        "progress": True,
        "overview": True,
        "characters": True,
        "chapters": True,
        "setting": True,
    },
}


def _base_appdata_dir() -> Path:
    return Path(os.getenv("APPDATA", Path.home()))


def app_data_dir() -> Path:
    directory = _base_appdata_dir() / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def legacy_app_data_dir() -> Path:
    return _base_appdata_dir() / LEGACY_APP_NAME


def migrate_legacy_appdata() -> None:
    legacy = legacy_app_data_dir()
    current = app_data_dir()

    if not legacy.exists():
        return

    current_config = current / "config.json"
    legacy_config = legacy / "config.json"
    if not current_config.exists() and legacy_config.exists():
        try:
            shutil.copy2(legacy_config, current_config)
        except Exception:
            pass

    current_sessions = current / "sessions"
    legacy_sessions = legacy / "sessions"
    if current_sessions.exists() or not legacy_sessions.exists():
        return

    try:
        shutil.copytree(legacy_sessions, current_sessions)
    except Exception:
        pass


def config_path() -> Path:
    return app_data_dir() / "config.json"


def session_dir() -> Path:
    directory = app_data_dir() / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _deep_copy_defaults() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def load_config() -> dict[str, Any]:
    migrate_legacy_appdata()
    data = _deep_copy_defaults()
    path = config_path()
    if not path.exists():
        return data

    loaded: dict[str, Any] = {}
    try:
        candidate = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(candidate, dict):
            loaded = candidate
    except Exception:
        return data

    for key, value in loaded.items():
        data[key] = value

    try:
        schema = int(loaded.get("config_schema", 1))
    except Exception:
        schema = 1
    if schema < 2:
        # One-time migration: keep explicit custom values,
        # but move old default 20x20 to new default 40x40.
        try:
            row_value = int(loaded.get("manuscript_grid_rows", 20))
        except Exception:
            row_value = 20
        try:
            col_value = int(loaded.get("manuscript_grid_cols", 20))
        except Exception:
            col_value = 20

        if "manuscript_grid_rows" not in loaded or row_value == 20:
            data["manuscript_grid_rows"] = 40
        if "manuscript_grid_cols" not in loaded or col_value == 20:
            data["manuscript_grid_cols"] = 40
        if "show_manuscript_grid" not in loaded:
            data["show_manuscript_grid"] = False

    if schema < 3:
        # Requested default: grid should be visible unless user reconfigures after migration.
        data["show_manuscript_grid"] = True

    if schema < 4 and "plot_panel_sections" not in loaded:
        data["plot_panel_sections"] = dict(DEFAULT_CONFIG["plot_panel_sections"])
    if schema < 5 and "plot_panel_expanded" not in loaded:
        data["plot_panel_expanded"] = True

    data["manuscript_grid_rows"] = max(8, min(80, int(data.get("manuscript_grid_rows", 40))))
    data["manuscript_grid_cols"] = max(8, min(80, int(data.get("manuscript_grid_cols", 40))))
    raw_show_grid = data.get("show_manuscript_grid", True)
    if isinstance(raw_show_grid, str):
        data["show_manuscript_grid"] = raw_show_grid.strip().lower() in {"1", "true", "yes", "on"}
    else:
        data["show_manuscript_grid"] = bool(raw_show_grid)

    raw_panel_expanded = data.get("plot_panel_expanded", True)
    if isinstance(raw_panel_expanded, str):
        data["plot_panel_expanded"] = raw_panel_expanded.strip().lower() in {"1", "true", "yes", "on"}
    else:
        data["plot_panel_expanded"] = bool(raw_panel_expanded)

    default_sections = dict(DEFAULT_CONFIG["plot_panel_sections"])
    raw_sections = data.get("plot_panel_sections", {})
    normalized_sections: dict[str, bool] = {}
    for key, default_value in default_sections.items():
        raw_value = raw_sections.get(key, default_value) if isinstance(raw_sections, dict) else default_value
        if isinstance(raw_value, str):
            normalized_sections[key] = raw_value.strip().lower() in {"1", "true", "yes", "on"}
        else:
            normalized_sections[key] = bool(raw_value)
    data["plot_panel_sections"] = normalized_sections

    data["config_schema"] = 5
    return data


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def save_session(session_id: str, payload: dict[str, Any]) -> None:
    path = session_dir() / f"{session_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def remove_session(session_id: str) -> None:
    path = session_dir() / f"{session_id}.json"
    if path.exists():
        try:
            path.unlink()
        except Exception:
            pass


def load_sessions() -> list[dict[str, Any]]:
    migrate_legacy_appdata()
    sessions: list[dict[str, Any]] = []
    for file_path in sorted(session_dir().glob("*.json")):
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            payload["_session_file"] = str(file_path)
            sessions.append(payload)
    return sessions


def clear_sessions() -> None:
    for file_path in session_dir().glob("*.json"):
        try:
            file_path.unlink()
        except Exception:
            pass
