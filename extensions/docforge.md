---
layout: extension
title: "DocForge"
permalink: /extensions/docforge/
eyebrow: "VS Code extension"
ext_name: "DocForge - Document Generator"
tagline: "Generate polished Markdown or HTML documents from a prompt, using whatever AI you already have - with an always-on offline fallback so it never hard-fails."
description: "DocForge for VS Code: generate Markdown or HTML documents from a prompt using the VS Code Language Model API, a compatible AI extension, your own API key, or fully offline built-in templates. Sanitized HTML, strict CSP, no telemetry. Apache-2.0."
marketplace_id: "AniketSoni.docforge-vscode"
marketplace_url: "https://marketplace.visualstudio.com/items?itemName=AniketSoni.docforge-vscode"
repo_url: "https://github.com/aniketsoni1/doc-forge"
version: "0.2.0"
first_published: "July 2026"
---

Generate polished **Markdown** or **HTML** documents from a prompt — using whatever AI you already have, with an always-on **offline fallback** so it never hard-fails.

## What it does

Run **DocForge: New Document from Prompt**, describe what you want, pick a format and a generator, and DocForge opens a live, themed, sanitized preview you can **Insert** into the editor or **Save** to disk.

DocForge resolves the best available generator in a transparent priority ladder, and always tells you which one ran:

1. **VS Code Language Model API** — the sanctioned, vendor-neutral way to use Copilot and other LM providers.
2. **Compatible AI extension** — best-effort, only via a documented `generateDocument` API.
3. **Bring-your-own-key** — Anthropic or OpenAI, with the key stored in VS Code SecretStorage.
4. **Built-in templates** — deterministic, fully offline, always available.

If no AI is available — or the workspace is untrusted, or you are offline — DocForge still produces a clean document from its built-in templates.

## Features

- Prompt-to-document for Markdown and sanitized, themed HTML
- Live preview webview with a strict Content Security Policy
- Generator picker (Auto / a specific model / Built-in templates)
- Provenance line, so you never wonder which generator produced the output
- Insert-into-editor, Copy, and Save-as actions
- **Cancellable** generation; cancelling aborts the provider request
- **Diff before overwrite** when saving over an existing file
- Actionable errors: which provider failed, why, and what to do next
- Token, cost and duration reporting, always labelled when estimated
- Respects Workspace Trust: untrusted workspaces use the offline generator only
- No telemetry; AI and network calls are opt-in and disclosed

## Commands

| Command | Description |
| --- | --- |
| `DocForge: New Document from Prompt` | The main flow (default keybinding `Ctrl`/`Cmd`+`Alt`+`D`) |
| `DocForge: Set API Key` | Store a bring-your-own key in SecretStorage |
| `DocForge: Clear API Key` | Remove the stored key |
| `DocForge: Improve Selected Text` | Transform a selection, with diff review (`Ctrl`/`Cmd`+`Alt`+`I`) |
| `DocForge: Regenerate Section` | Rewrite one section, preserving its neighbours exactly |
| `DocForge: Run Diagnostics` | Show generator availability and the last generation's attempt trail |

## Settings

### Generation

- `docforge.defaultFormat` — `md` or `html`
- `docforge.tone`, `docforge.length`

### Providers

- `docforge.enableAi` — turn off to force the offline template generator
- `docforge.provider`, `docforge.model` — for the bring-your-own-key generator
- `docforge.requestTimeoutMs` — abort a BYO-key request after this long

### Reporting

- `docforge.pricing` — override the indicative price table used for cost estimates

Cost figures are always **estimates**, never a bill.

## Privacy and security

Local-first by default. The template generator is fully offline.

AI generators are opt-in; keys live in SecretStorage and are never written to settings. All model HTML is sanitized against an allowlist before it is shown or saved, and every webview uses a strict Content Security Policy.

See the full [privacy policy]({{ '/extensions/privacy/' | relative_url }}) for details.

## Links

- [Source, docs and issues on GitHub](https://github.com/aniketsoni1/doc-forge)
- [Changelog](https://github.com/aniketsoni1/doc-forge/blob/main/CHANGELOG.md)
- [Report an issue](https://github.com/aniketsoni1/doc-forge/issues)
- License: [Apache-2.0](https://github.com/aniketsoni1/doc-forge/blob/main/LICENSE)
