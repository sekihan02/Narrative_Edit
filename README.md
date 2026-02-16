# Narrative_Edit

Narrative_Edit は、小説執筆向けの縦書き入力エディタです。  
本文編集（縦書き・原稿用紙）と、プロット整理（登場人物・章メモ・進捗）を1つの画面で扱える構成を目指しています。

## 主な機能
- 縦書きエディタ（右から左へ列進行）
- 原稿用紙グリッド（初期40x40、行数/列数は変更可能）
- タブ編集（`Ctrl+T` / `Ctrl+W` / `Ctrl+Tab`）
- プロット情報パネル（概要・登場人物・章メモ・設定資料・進捗分析）
- プロット情報パネルの全体折り畳み / セクション折り畳み（状態保持）
- 本文ファイル横の sidecar 保存（`<本文>.narrative.json`）
- プロット単体の保存/読込（`*.plot.json`）
- PDF書き出し（A4横・40x40・方眼）
- 検索バー（`Ctrl+F`、`Enter` / `Shift+Enter`）
- 自動保存とセッション復元

## スクリーンショット
- エディタ全体
![Editor](docs/images/editor-overview.png)

- 別テーマ表示
![Editor2](docs/images/editor-overview2.png)

- PDF出力イメージ
![PDF Output](docs/images/pdf-output.png)

## リリース
- タグベースでリリースします（例: `v0.1.0`, `v0.2.0`）。
- GitHub Releases には変更点の要約を記載します。

## 実行方法
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python src\main.py
```

## EXE ビルド（Windows）
```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name Narrative_Edit --distpath dist --workpath build src\main.py
```

## ドキュメント
- 仕様書: `docs/specification.md`
- 開発メモ: `開発の流れ.txt`
