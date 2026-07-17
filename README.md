# Codex Token Usage Meter

[简体中文](README.zh-CN.md)

A local-first Codex plugin and standalone macOS floating widget for inspecting token usage, prompt-cache effectiveness, account limits, Codex credits, and estimated USD value.

![Codex Token Usage Meter floating widget](plugins/token-usage-meter/assets/widget-preview.png)

## Features

- Refreshes the floating widget every five seconds.
- Uses compact `K`, `W` (ten-thousand), `M`, and `B` token units while keeping USD amounts unabridged.
- Shows input, uncached input, cached input, cache-hit rate, output, reasoning output, and total tokens.
- Groups usage by model and service tier and detects supported Fast-mode multipliers.
- Estimates Codex credits with a bundled snapshot of the official Codex token rate card.
- Converts estimated credits to USD using a configurable dollars-per-credit value.
- Shows the latest account-limit status when it is available in local rollout metadata.
- Runs locally and does not require an API key or upload conversation data.
- Aggregates all local active and archived Codex tasks, so parallel windows cannot make the display jump between sessions.
- Recovers usage written while the widget was closed by reading new rollout data when reopened.
- Provides a native always-on-top macOS panel, a terminal dashboard, and JSON output.
- Remembers the panel position and displays it on every macOS Space.

## How it works

Codex writes local JSONL rollout metadata under `~/.codex/sessions` and `~/.codex/archived_sessions`. The meter reads `token_count` events from those files and uses per-event increments when present. If only cumulative totals are available, it calculates non-negative deltas between events. Global mode stores a compact index at `~/.codex/token-usage-meter/all-index-v1.json`; it contains numeric usage state and file offsets only, not conversation text. After the initial index build, each refresh reads only newly appended bytes.

Cached input is treated as a subset of input, and reasoning tokens are treated as a subset of output, so neither is charged twice. Estimated cost is calculated as:

```text
uncached input × input rate
+ cached input × cached-input rate
+ output × output rate
```

Rates are credits per one million tokens. The bundled rate snapshot links to the [official Codex rate card](https://help.openai.com/en/articles/20001106-codex-rate-card). USD conversion defaults to `$0.04` per credit, based on the official example of 2,500 credits for $100 in the [Codex credits terms](https://help.openai.com/en/articles/20001147-codex-credits-for-students-terms-of-service).

The displayed dollar amount is an estimate, not an invoice. Usage included in a ChatGPT plan may not create an additional cash charge.

## Requirements

- Codex desktop or CLI with local rollout metadata.
- Python 3.9 or later.
- macOS 13 or later for the native floating widget.
- Xcode Command Line Tools only when rebuilding the native app from Swift source.

The terminal and JSON reports can run on other platforms when a compatible Codex data directory is available.

## Quick start: standalone macOS app

Clone the repository:

```bash
git clone https://github.com/kafuunochino/codex-token-usage-meter.git
cd codex-token-usage-meter
```

Then double-click:

```text
plugins/token-usage-meter/assets/TokenUsageWidget.app
```

The app contains its own copy of the token parser, so no terminal command is required after download. If macOS blocks the first launch because the app is ad-hoc signed, Control-click the app and choose **Open**.

To copy the app into `~/Applications`, enable launch at macOS login, and open it immediately:

```bash
python3 plugins/token-usage-meter/scripts/install_macos.py
```

Use `--no-autostart` if login launch is not wanted.

Closing the widget does not stop Codex from recording usage. Reopening it includes events written while the widget was not running. The standalone app reports the combined local history of the whole Codex installation, not one window or task. The first global index build can take time when the local rollout history is large; later starts use the saved index.

## Install as a Codex plugin

From the cloned repository root:

```bash
codex plugin marketplace add "$PWD"
codex plugin add token-usage-meter@codex-token-usage-meter
```

Start a new Codex task so the installed skill is loaded, then ask:

```text
Open my live token usage widget.
```

## Command-line usage

One-time report for the current task:

```bash
python3 plugins/token-usage-meter/skills/token-usage/scripts/token_usage.py --scope session
```

Five-second live terminal dashboard:

```bash
python3 plugins/token-usage-meter/skills/token-usage/scripts/token_usage.py --watch --interval 5 --scope session
```

Today's aggregate:

```bash
python3 plugins/token-usage-meter/skills/token-usage/scripts/token_usage.py --scope today
```

Machine-readable JSON:

```bash
python3 plugins/token-usage-meter/skills/token-usage/scripts/token_usage.py --scope session --json
```

## Rebuild the macOS app

```bash
cd plugins/token-usage-meter
./widget/build_widget.sh
```

The build script embeds `token_usage.py` into the app bundle and applies an ad-hoc local signature.

## Privacy and limitations

- The meter reads local rollout metadata only; it does not call the OpenAI API.
- It does not retain or transmit conversation text.
- Session scope reports one selected task. Use `--scope today` or `--scope all` for aggregation.
- Unknown models still show token totals, but cost is reported as unavailable instead of guessed.
- Rate cards and product behavior can change; check the linked official sources before relying on an estimate.
- Codex plugins cannot add custom fields to the Codex desktop lower-left chrome, so the native floating panel is used instead.

## Tests

```bash
python3 -m unittest discover -s plugins/token-usage-meter/tests -v
```
