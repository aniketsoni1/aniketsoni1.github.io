---
layout: extension
title: "Pipeline Failure Agent"
permalink: /extensions/pipeline-failure-agent/
eyebrow: "VS Code extension"
ext_name: "Pipeline Failure Agent"
tagline: "Investigate failed data pipelines, jobs, queries and workflows without leaving VS Code - deterministic-first, evidence-labeled, with optional AI that is off by default."
description: "Pipeline Failure Agent for VS Code: root-cause analysis for failed data pipelines across Databricks, Snowflake, dbt, GitHub, MongoDB and Jira. Deterministic-first, secret/PII redaction, no telemetry, optional AI off by default. Apache-2.0."
marketplace_id: "AniketSoni.pipeline-failure-agent-vscode"
marketplace_url: "https://marketplace.visualstudio.com/items?itemName=AniketSoni.pipeline-failure-agent-vscode"
repo_url: "https://github.com/aniketsoni1/pipeline-failure-agent"
version: "0.1.1"
first_published: "July 2026"
---

Investigate failed data pipelines, jobs, queries and workflows **without leaving VS Code**. Point it at a failed run or a log file and it isolates the earliest meaningful failure from cascading noise, classifies it, compares the failed run against a healthy baseline, correlates root causes across platforms, and produces a ranked, **evidence-labeled** incident report — right inside an editor panel.

> **Deterministic-first and private by design.** All analysis runs locally, secrets and PII are redacted before anything is inspected, and there is **no telemetry**. AI assistance is entirely optional and **off by default** — the full investigation works without it.

The extension is a thin UI over the **same shared core** as the `pipeline-agent` CLI, so the two tools always agree — no investigation logic is duplicated.

## Features

- **Root-cause report panel** — ranked hypotheses with a transparent `0..1` confidence score, rendered in an interactive webview.
- **Evidence labeling** — every finding is tagged `confirmed`, `strong_correlation`, `inference`, `assumption`, or `missing_information`, so you always know how much to trust it.
- **Earliest-failure isolation** — separates the first meaningful error from the cascade of downstream noise it triggers.
- **Failed-vs-baseline diff** — compares a failed run against a known-good run to surface what actually changed.
- **Cross-platform correlation** — connects failures across Databricks, Snowflake, dbt, GitHub, MongoDB and Jira to find a shared root cause.
- **Activity Bar panel** — **Connections** and **Recent Failures** tree views; click a failure to investigate it.
- **Investigate a log file** — run against the active `.log` editor, or right-click any `.log` file in the Explorer.
- **Investigate a run by id** — pick a platform and enter a run / query / operation id.
- **Markdown incident report** — export the full report to a `.md` file with one command.
- **Approval-gated Jira issues** — file an incident to Jira, but only after an explicit confirmation. No silent writes.
- **Secret / PII redaction** — deny-by-default redaction runs at every ingest boundary, before any analysis.
- **Optional AI** — off by default; when enabled it only summarizes and ranks, and can never trigger a write.

## Getting started

### 1. Install

Search **"Pipeline Failure Agent"** in the VS Code Extensions panel, or use the command at the top of this page.

### 2. Open the panel

Click the **Pipeline Failure Agent** icon in the Activity Bar. You will see two tree views: **Connections** (the platforms available to investigate) and **Recent Failures**.

### 3. Investigate a failure

| You have… | Do this |
| --- | --- |
| A local log file | Open the `.log` file and run **Pipeline Agent: Investigate Active Log File** — or right-click the file in the Explorer. |
| A platform run | Run **Pipeline Agent: Investigate Run…**, pick the platform, and paste the run / query / operation id. |
| A failure in the sidebar | Click it in **Recent Failures** (hover for the inline investigate action). |

All actions are also in the Command Palette (`Cmd`/`Ctrl`+`Shift`+`P` → type "Pipeline Agent").

### 4. Read the report

The report panel opens with the ranked root-cause hypotheses, each with its confidence score and labeled evidence. Where a baseline is available, the failed-vs-healthy diff is shown inline.

### 5. Export or file it

**Pipeline Agent: Export Incident Report** writes the full report to a Markdown file. **Pipeline Agent: Create Jira Issue from Report** opens an approval modal first, then files the incident to Jira.

## Commands

| Command | Description |
| --- | --- |
| `Pipeline Agent: Investigate Active Log File` | Analyze the log in the active editor |
| `Pipeline Agent: Investigate Run…` | Analyze a platform run by id |
| `Pipeline Agent: Export Incident Report` | Save the last report as Markdown |
| `Pipeline Agent: Create Jira Issue from Report` | File the incident to Jira (approval-gated) |
| `Pipeline Agent: Refresh` | Re-scan connections and recent failures |

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `pfa.redaction` | `strict` | Secret/PII redaction level applied before analysis (`strict` \| `standard` \| `none`) |
| `pfa.correlate` | `true` | Correlate change events and historical incidents across connectors |
| `pfa.ai.enabled` | `false` | Enable optional AI-assisted explanation. Local analysis always runs regardless |
| `pfa.ai.provider` | `""` | AI provider id (only used when `pfa.ai.enabled` is `true`) |

## Privacy

Analysis runs locally in your VS Code environment. Secrets and PII are redacted before any content is inspected, credentials are stored only in VS Code **SecretStorage** — never written to `settings.json` or logs — and the extension sends **no telemetry**.

The only outbound calls are to the platforms you explicitly connect, such as Jira when you approve an issue. AI is off unless you turn it on, and even then it can never initiate a write.

See the full [privacy policy]({{ '/extensions/privacy/' | relative_url }}) for details.

## Requirements

- VS Code **1.85** or later.
- A failed pipeline/job log file, or access to a supported platform run (Databricks, Snowflake, dbt, GitHub, MongoDB, Jira).
- *Optional:* an AI provider, only if you enable `pfa.ai.enabled`.

## Links

- [Source, docs and issues on GitHub](https://github.com/aniketsoni1/pipeline-failure-agent)
- [Changelog](https://github.com/aniketsoni1/pipeline-failure-agent/blob/main/CHANGELOG.md)
- [Report an issue](https://github.com/aniketsoni1/pipeline-failure-agent/issues)
- License: [Apache-2.0](https://github.com/aniketsoni1/pipeline-failure-agent/blob/main/LICENSE)
