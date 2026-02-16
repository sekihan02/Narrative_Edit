from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class NewlineMode(str, Enum):
    LF = "lf"
    CRLF = "crlf"
    CR = "cr"


@dataclass
class ManuscriptGrid:
    rows: int = 40
    cols: int = 40

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ManuscriptGrid":
        rows = int(payload.get("rows", 40)) if isinstance(payload, dict) else 40
        cols = int(payload.get("cols", 40)) if isinstance(payload, dict) else 40
        return cls(rows=max(8, min(80, rows)), cols=max(8, min(80, cols)))

    def to_dict(self) -> dict[str, int]:
        return {"rows": self.rows, "cols": self.cols}


@dataclass
class ProgressGoals:
    daily_target_chars: int = 2000

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProgressGoals":
        if not isinstance(payload, dict):
            return cls()
        daily = int(payload.get("daily_target_chars", 2000))
        return cls(daily_target_chars=max(0, min(1_000_000, daily)))

    def to_dict(self) -> dict[str, int]:
        return {"daily_target_chars": self.daily_target_chars}


@dataclass
class CharacterProfile:
    name: str = ""
    role: str = ""
    goal: str = ""
    conflict: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CharacterProfile":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            name=str(payload.get("name", "")),
            role=str(payload.get("role", "")),
            goal=str(payload.get("goal", "")),
            conflict=str(payload.get("conflict", "")),
            notes=str(payload.get("notes", "")),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "role": self.role,
            "goal": self.goal,
            "conflict": self.conflict,
            "notes": self.notes,
        }


@dataclass
class ChapterMemo:
    number: int = 1
    title: str = ""
    purpose: str = ""
    summary: str = ""
    target_chars: int = 0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChapterMemo":
        if not isinstance(payload, dict):
            return cls()
        number = int(payload.get("number", 1))
        target = int(payload.get("target_chars", 0))
        return cls(
            number=max(1, min(9999, number)),
            title=str(payload.get("title", "")),
            purpose=str(payload.get("purpose", "")),
            summary=str(payload.get("summary", "")),
            target_chars=max(0, min(1_000_000, target)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "purpose": self.purpose,
            "summary": self.summary,
            "target_chars": self.target_chars,
        }


@dataclass
class NovelMetadata:
    work_title: str = ""
    genre: str = ""
    point_of_view: str = ""
    era_setting: str = ""
    logline: str = ""
    main_plot: str = ""
    sub_plot: str = ""
    world_notes: str = ""
    glossary_notes: str = ""
    reference_notes: str = ""
    characters: list[CharacterProfile] = field(default_factory=list)
    chapters: list[ChapterMemo] = field(default_factory=list)
    progress_goals: ProgressGoals = field(default_factory=ProgressGoals)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NovelMetadata":
        if not isinstance(payload, dict):
            return cls()

        characters: list[CharacterProfile] = []
        for item in payload.get("characters", []):
            characters.append(CharacterProfile.from_dict(item))

        chapters: list[ChapterMemo] = []
        for item in payload.get("chapters", []):
            chapters.append(ChapterMemo.from_dict(item))

        return cls(
            work_title=str(payload.get("work_title", "")),
            genre=str(payload.get("genre", "")),
            point_of_view=str(payload.get("point_of_view", "")),
            era_setting=str(payload.get("era_setting", "")),
            logline=str(payload.get("logline", "")),
            main_plot=str(payload.get("main_plot", "")),
            sub_plot=str(payload.get("sub_plot", "")),
            world_notes=str(payload.get("world_notes", "")),
            glossary_notes=str(payload.get("glossary_notes", "")),
            reference_notes=str(payload.get("reference_notes", "")),
            characters=characters,
            chapters=chapters,
            progress_goals=ProgressGoals.from_dict(payload.get("progress_goals", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_title": self.work_title,
            "genre": self.genre,
            "point_of_view": self.point_of_view,
            "era_setting": self.era_setting,
            "logline": self.logline,
            "main_plot": self.main_plot,
            "sub_plot": self.sub_plot,
            "world_notes": self.world_notes,
            "glossary_notes": self.glossary_notes,
            "reference_notes": self.reference_notes,
            "characters": [item.to_dict() for item in self.characters],
            "chapters": [item.to_dict() for item in self.chapters],
            "progress_goals": self.progress_goals.to_dict(),
        }


@dataclass
class DocumentState:
    tab_id: str = field(default_factory=lambda: str(uuid4()))
    path: Optional[str] = None
    is_dirty: bool = False
    encoding: str = "utf-8"
    newline: NewlineMode = NewlineMode.LF
    session_id: str = field(default_factory=lambda: str(uuid4()))
    display_name: Optional[str] = None
    metadata: NovelMetadata = field(default_factory=NovelMetadata)
    metadata_path: Optional[str] = None
    plot_path: Optional[str] = None
