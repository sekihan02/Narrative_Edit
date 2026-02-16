# Narrative_Edit Specification (v1)

## Title
**Narrative_Edit - Vertical manuscript editor for novel writing**

## Product Statement
Narrative_Edit is a lightweight but focused novel-writing editor that combines vertical writing, manuscript paper layout, and writing metadata in one window.

## Goals
1. Deliver practical vertical Japanese writing for daily novel drafting.
2. Keep manuscript-paper feeling with adjustable 20x20 default grid.
3. Keep all writing context (characters, chapter memos, goals) alongside text.
4. Prevent data loss with autosave, session restore, and sidecar metadata files.

## Core Layout
- Main window with `QSplitter`.
- Left: tab-based text editor area + search bar.
- Right: fixed info panel (`NovelInfoPanel`, default around 340px).
- Bottom: status (`Page/Col/Cell | Characters | Goal Rate | Save State`).

## Functional Requirements
### Editor
- Custom `QAbstractScrollArea` editor (`VerticalManuscriptEditor`).
- Vertical flow: top-to-bottom, columns right-to-left.
- Grid paper default `20 x 20`, configurable rows/cols.
- Typing, IME input, cursor movement, backspace/delete, enter.
- Find support (plain/regex, forward/backward).
- Undo/redo.

### Vertical Writing Rules (implemented baseline)
- Line-head prohibition handling for punctuation.
- Line-end prohibition handling for opening brackets.
- Major vertical glyph substitutions (quotes/brackets/punctuation).
- ASCII alnum rotation.
- 2-digit tate-chu-yoko priority token.

### Novel Info Panel
Five sections:
1. Overview: title, genre, POV, setting/era, logline, main plot, sub plot.
2. Characters: editable table (name, role, goal, conflict, notes).
3. Chapter Memos: editable table (number, title, purpose, summary, target chars).
4. References: world notes, glossary notes, reference notes.
5. Progress: daily target chars, current chars, achievement rate, remaining chars, estimated pages.

### Storage
- Text file stays as plain text.
- Metadata sidecar file: `<text_file>.narrative.json`.
- Sidecar includes app/schema metadata plus `NovelMetadata` payload.

### Sessions and Migration
- Autosave session schema: `meta.app = Narrative_Edit`, `schema = 2`.
- Session restore accepts compatibility set:
  - `meta.app in {legacy app name, Narrative_Edit}`
  - `schema in {1, 2}`
- First launch migration:
  - If legacy `%APPDATA%/<old-app-name>` exists and `%APPDATA%/Narrative_Edit` is missing data,
    copy legacy `config.json` and `sessions/`.

## Non-functional Requirements
- Smooth typing for novel-scale text (target around 30k chars).
- Startup and file I/O should stay lightweight.
- Keep UI language/theme switchable (`ja` / `en`, `soft_light` / `soft_dark`).

## Out of Scope (this version)
- Legacy Lens tab feature.
- Database storage.
- Advanced publishing pipeline.
