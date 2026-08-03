---
layout: extension
title: "Support"
permalink: /extensions/support/
eyebrow: "VS Code extensions"
tagline: "Where to report a bug, request a feature, or ask a question about Code Trio, DocForge and Pipeline Failure Agent."
description: "Support for the VS Code extensions published by Aniket Abhishek Soni - Code Trio, DocForge and Pipeline Failure Agent. Issue trackers, what to include in a bug report, and security disclosure."
---

All three extensions are open source and developed in the open. **The GitHub issue tracker for the relevant repository is the fastest route** for anything actionable — it keeps the discussion public, searchable, and linked to the code.

## Where to file

| Extension | Issues | Discussions |
| --- | --- | --- |
| [Code Trio]({{ '/extensions/code-trio/' | relative_url }}) | [Open an issue](https://github.com/aniketsoni1/code-trio-compare-beautify-spellcheck/issues) | [Ask a question](https://github.com/aniketsoni1/code-trio-compare-beautify-spellcheck/discussions) |
| [Pipeline Failure Agent]({{ '/extensions/pipeline-failure-agent/' | relative_url }}) | [Open an issue](https://github.com/aniketsoni1/pipeline-failure-agent/issues) | — |
| [DocForge]({{ '/extensions/docforge/' | relative_url }}) | [Open an issue](https://github.com/aniketsoni1/doc-forge/issues) | — |

If you are not sure which extension is responsible, file against whichever one you were using — it will be moved if needed.

## What to include in a bug report

The more of this you can provide, the faster it gets fixed:

1. **Extension name and version** — visible in the Extensions panel, or run `Developer: Show Running Extensions`.
2. **VS Code version and operating system** — `Help → About` (or `Code → About` on macOS) has both.
3. **What you did** — the exact command you ran, or the steps to reproduce.
4. **What you expected** versus **what actually happened.**
5. **A minimal sample** — the smallest file, log excerpt or repository state that reproduces it.
6. **Any error output** — check `View → Output` and select the extension from the dropdown, plus `Help → Toggle Developer Tools → Console` for anything unhandled.

**Please redact secrets before posting.** Pipeline Failure Agent redacts secrets and PII from its own analysis and reports, but anything you paste into a GitHub issue by hand is public and is not covered by that.

## Diagnostics commands

Two of the extensions can tell you about their own state, which is often enough to resolve a problem immediately:

- **DocForge** — run `DocForge: Run Diagnostics` to see which generators are available and the attempt trail for the last generation.
- **Code Trio** — run `Code Trio: Show Available Formatters` to see which external formatters were discovered, and `Code Trio: Show Dictionary Sources` to see which dictionaries are in effect and in what precedence.
- **Pipeline Failure Agent** — the `code-trio`-style CLI equivalent, `pipeline-agent`, has a verbose mode useful for reproducing an investigation outside the editor.

## Feature requests

Feature requests are welcome as GitHub issues. It helps to describe the problem you are trying to solve rather than only the solution you have in mind — there is often a simpler path that fits the existing design.

Note that all three extensions are deliberately **deterministic-first and offline-capable**. Requests that would require always-on network access, telemetry, or a mandatory AI dependency are unlikely to be accepted, since those constraints are the point of the projects.

## Security issues

**Do not open a public issue for a security vulnerability.**

Each repository has a `SECURITY.md` describing the private disclosure process. Please follow it so the issue can be fixed before it is publicly known:

- [Code Trio SECURITY.md](https://github.com/aniketsoni1/code-trio-compare-beautify-spellcheck/blob/main/SECURITY.md)
- [Pipeline Failure Agent SECURITY.md](https://github.com/aniketsoni1/pipeline-failure-agent/blob/main/SECURITY.md)
- [DocForge SECURITY.md](https://github.com/aniketsoni1/doc-forge/blob/main/SECURITY.md)

## Contributing

Pull requests are welcome. Each repository has a `CONTRIBUTING.md` covering the local development setup, the verification pipeline (`npm run verify` — typecheck, lint, tests), and the expectations for a change. All three are Apache-2.0 licensed.

## Response expectations

These are independently maintained open-source projects, not a commercial product with a support contract. Issues are read and triaged as time allows, and well-documented reproductions are handled first. There is no guaranteed response time.

## Other enquiries

For anything that is not a bug, feature request or security report, the [contact form on the main site]({{ '/#contact' | absolute_url }}) reaches me directly.
