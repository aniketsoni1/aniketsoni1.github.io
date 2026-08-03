---
layout: extension
title: "Code Trio"
permalink: /extensions/code-trio/
eyebrow: "VS Code extension"
ext_name: "Code Trio - Compare Beautify Spellcheck"
tagline: "Compare, three-way merge, code-aware spell check, and beautify - four offline developer tools in one VS Code extension. No network calls, no telemetry, ever."
description: "Code Trio for VS Code: compare/diff, three-way merge, code-aware spell check and beautify/format in one fully offline extension. Bundles Prettier; uses Ruff, Black, gofmt, rustfmt and clang-format when installed. Apache-2.0, no telemetry."
marketplace_id: "AniketSoni.code-trio-compare-beautify-spellcheck"
marketplace_url: "https://marketplace.visualstudio.com/items?itemName=AniketSoni.code-trio-compare-beautify-spellcheck"
repo_url: "https://github.com/aniketsoni1/code-trio-compare-beautify-spellcheck"
version: "0.2.1"
first_published: "July 2026"
---

Four offline developer tools in one VS Code extension: **compare/diff**, **three-way merge**, a **code-aware spell checker**, and a **beautifier/formatter**. Deterministic, private, and fully offline — no network calls, no telemetry, ever.

## Compare / diff

Line, word, or character granularity with ignore-whitespace, ignore-case and ignore-line-ending options, rendered in the native side-by-side diff editor.

Compare the active file against another file, two files selected in the Explorer, the clipboard, your current selection, the version saved on disk, any git ref, or the previous revision.

Word and character refinement is Unicode-correct, so accented characters and emoji are never split mid-glyph. Binary, oversized and minified input is refused or downgraded with a reason you can read, rather than producing a misleading empty diff.

## Three-way merge

diff3 with conflict navigation, and accept ours / theirs / both / base plus manual resolution.

Reads git's conflict stages directly, so it works on a real conflicted working tree with no manual extraction. Preview the merged result before anything is written; saving goes to a new file by default and is refused outright while any conflict is unresolved. Git staging is never touched.

## Spell check

Code-aware diagnostics that check comments and strings by default (identifiers are opt-in) and split `camelCase`, `snake_case`, `kebab-case` and `SCREAMING_CASE` before lookup.

URLs, file paths, hashes, UUIDs, hex values, versions, timestamps and base64 blobs are suppressed *before* any word is extracted — which is what makes it quiet enough to leave switched on.

Six dictionary scopes with documented precedence, including **per-folder dictionaries** for monorepos and multi-root workspaces, plus a session ignore list that writes nothing to disk.

## Beautify / format

Prettier is bundled. Ruff, Black, gofmt, rustfmt and clang-format are used when you already have them installed; nothing is ever downloaded.

A missing formatter tells you which executable it looked for and offers the setting to fix it, instead of silently doing something else. Includes a dry-run diff preview before anything is applied, opt-in format-on-save, and workspace-wide formatting behind an explicit confirmation.

All four tools surface through one Activity Bar panel with per-tool tabs, severity counts, search, sorting, keyboard navigation and Markdown/JSON export.

## Commands

All commands live under the `Code Trio:` category in the Command Palette.

| Group | Commands |
| --- | --- |
| Compare | Compare Active File With File / Clipboard / Git Ref, Compare Two Selected Files, Compare Selection With Clipboard, Compare With Saved Version On Disk, Compare With Previous Revision |
| Merge | Merge Conflicted File (Git), Merge Three Files, Next / Previous Merge Conflict, Preview Merged Result, Save Merged Result As |
| Spell | Spell Check Current File / Workspace, Fix All Spelling In File, Add Word To Dictionary, Ignore Word For This Session, Clear Session Ignore List, Open Workspace / Workspace Folder / User Dictionary, Show Dictionary Sources |
| Beautify | Beautify Document, Preview Beautify Changes, Beautify Changed Files Only, Beautify Entire Workspace, Show Available Formatters |
| Results | Show Results Panel, Export Results, Refresh, Clear |

### Default keybindings

| Shortcut | Action |
| --- | --- |
| `Ctrl`/`Cmd`+`Alt`+`B` | Beautify preview |
| `Ctrl`/`Cmd`+`Alt`+`S` | Spell check file |
| `Ctrl`/`Cmd`+`Alt`+`]` | Next merge conflict |
| `Ctrl`/`Cmd`+`Alt`+`[` | Previous merge conflict |

## Settings

Settings are namespaced per feature: `codeTrio.diff.*`, `codeTrio.spell.*`, `codeTrio.dictionaries.*`, `codeTrio.format.*` and `codeTrio.externalFormatters.*`. Every setting is resource-scoped, so a multi-root workspace can configure each folder differently.

Notable defaults: identifiers are not spell-checked unless you opt in, formatting shows a preview before applying, format-on-save is off until you enable it, and external formatter discovery is on but finds only what you have already installed.

## Privacy and trust

No network access and no telemetry.

Applying a format, writing to a dictionary and saving a merge are the only operations that change files, and all three are disabled in untrusted workspaces. The extension supports Workspace Trust in `limited` mode, so compare and spell diagnostics keep working in untrusted folders.

The results panel runs under a strict Content Security Policy: `default-src 'none'`, scripts and styles allowed only via a per-load nonce, and no remote origin of any kind. Git and external formatters are invoked with argument arrays and a minimal environment, never through a shell. Each of these properties is asserted by a test rather than merely claimed.

See the full [privacy policy]({{ '/extensions/privacy/' | relative_url }}) for details.

## Also available as a CLI

The same engines power a cross-platform `code-trio` CLI with `diff`, `merge`, `spell`, `format`, `report`, `dictionary`, `formatters`, `init`, `doctor` and `configure` commands, machine-readable JSON output, and a documented, stable exit-code contract.

## Links

- [Source, docs and issues on GitHub](https://github.com/aniketsoni1/code-trio-compare-beautify-spellcheck)
- [Changelog](https://github.com/aniketsoni1/code-trio-compare-beautify-spellcheck/blob/main/CHANGELOG.md)
- [Report an issue](https://github.com/aniketsoni1/code-trio-compare-beautify-spellcheck/issues)
- [Questions and discussion](https://github.com/aniketsoni1/code-trio-compare-beautify-spellcheck/discussions)
- License: [Apache-2.0](https://github.com/aniketsoni1/code-trio-compare-beautify-spellcheck/blob/main/LICENSE)
