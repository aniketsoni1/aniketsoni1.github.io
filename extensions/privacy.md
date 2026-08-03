---
layout: extension
title: "Privacy Policy"
permalink: /extensions/privacy/
eyebrow: "VS Code extensions"
tagline: "How Code Trio, DocForge and Pipeline Failure Agent handle your data. The short version: they do not collect any of it."
description: "Privacy policy for the VS Code extensions published by Aniket Abhishek Soni - Code Trio, DocForge and Pipeline Failure Agent. No telemetry, no analytics, no data collection. All processing is local by default."
---

**Last updated:** 3 August 2026

This policy covers the three Visual Studio Code extensions published on the Visual Studio Marketplace under the publisher **Aniket Abhishek Soni**:

- [Code Trio - Compare Beautify Spellcheck]({{ '/extensions/code-trio/' | relative_url }})
- [Pipeline Failure Agent]({{ '/extensions/pipeline-failure-agent/' | relative_url }})
- [DocForge - Document Generator]({{ '/extensions/docforge/' | relative_url }})

## Summary

**None of these extensions collect, transmit, or store your personal data.** There is no telemetry, no analytics, no crash reporting, no usage tracking, and no account or sign-up of any kind. All processing happens locally on your machine by default.

## What is collected

Nothing.

The extensions do not implement telemetry of any kind. They do not use VS Code's telemetry APIs, do not send usage events, and do not report errors to any remote service. No identifier — anonymous, hashed, or otherwise — is generated or transmitted.

## Network access

| Extension | Network behaviour |
| --- | --- |
| Code Trio | **No network access at all.** The extension makes zero outbound requests under any configuration. |
| DocForge | **Opt-in only.** No requests unless you explicitly enable AI generation. The built-in template generator is fully offline. |
| Pipeline Failure Agent | **Opt-in only.** Requests are made solely to platforms you have explicitly configured and connected (for example Databricks, Snowflake, dbt, GitHub, MongoDB or Jira), and only when you initiate an action. |

Where an extension does make a request on your behalf, it goes directly from your machine to the service you configured. No request is proxied through, logged by, or visible to the extension author or any third party acting for them.

### Optional AI features

DocForge and Pipeline Failure Agent can optionally use AI. In both cases AI is **off by default** and the extension is fully functional without it.

When you enable it, content is sent to the provider **you** choose and configure — either through the VS Code Language Model API (which uses your existing Copilot or other configured provider) or with your own API key for Anthropic or OpenAI. That content is then subject to that provider's privacy policy, not this one. The extension author receives none of it and has no visibility into it.

In Pipeline Failure Agent, AI can only summarize and rank findings. It can never initiate a write to any connected system.

## Credentials and secrets

API keys and platform credentials are stored exclusively in **VS Code SecretStorage**, which delegates to your operating system's credential store. They are never written to `settings.json`, never written to logs, never included in exported reports, and never transmitted anywhere except to the service they authenticate against.

You can remove a stored key at any time — for example with `DocForge: Clear API Key`.

## Local data

The extensions read and write files only in response to an explicit action:

- **Code Trio** writes formatted files, dictionary entries, and merged output. Saving a merge writes to a new file by default. Git staging is never modified.
- **DocForge** writes generated documents when you choose Save, showing a diff first if you are overwriting an existing file.
- **Pipeline Failure Agent** writes exported incident reports as Markdown when you run the export command.

Dictionaries and settings live in your workspace or user configuration, under your control. Nothing is written to a remote location.

## Secret and PII redaction

Pipeline Failure Agent applies deny-by-default redaction at every ingest boundary, **before** any analysis is performed. Secrets and personally identifiable information detected in logs are redacted from the analysis input, from the report, and from anything sent to an AI provider if you have enabled one. The default redaction level is `strict`.

## Workspace Trust

All three extensions respect [VS Code Workspace Trust](https://code.visualstudio.com/docs/editing/workspaces/workspace-trust). In an untrusted workspace, operations that write to disk or execute external tools are disabled:

- Code Trio runs in `limited` mode — compare and spell diagnostics keep working, while formatting, dictionary writes and merge saves are disabled.
- DocForge falls back to the offline template generator only.

## Third-party tools

Code Trio bundles Prettier. It will additionally use Ruff, Black, gofmt, rustfmt and clang-format **only if they are already installed on your machine**. Nothing is ever downloaded or installed on your behalf. External formatters and git are invoked with explicit argument arrays and a minimal environment, never through a shell.

## Webview security

Every webview panel across the three extensions runs under a strict Content Security Policy with `default-src 'none'`, scripts and styles permitted only via a per-load nonce, and no remote origin permitted. Model-generated HTML in DocForge is sanitized against an allowlist before it is rendered or saved.

## This website

This policy covers the extensions. The website you are reading it on is a static site hosted on GitHub Pages. Any analytics on it are cookieless and are disclosed separately; the extensions neither read from nor write to it.

## Changes to this policy

Material changes will be reflected in the "last updated" date above and in the changelog of the affected repository. Because the extensions are open source under Apache-2.0, you can verify every claim on this page against the source.

## Contact

Questions about this policy, or a suspected privacy issue, can be raised through the [support page]({{ '/extensions/support/' | relative_url }}) or by opening an issue on the relevant GitHub repository. Security-sensitive reports should follow the `SECURITY.md` disclosure process in the repository rather than a public issue.
