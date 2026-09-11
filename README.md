# Codex Token Usage Meter

[简体中文](README.zh-CN.md)

A local-first Codex plugin and standalone macOS floating widget for inspecting token usage, prompt-cache effectiveness, account limits, Codex credits, and estimated budget usage in USD.

![Codex Token Usage Meter floating widget](plugins/token-usage-meter/assets/widget-preview.png)

## Features

- Refreshes the floating widget every five seconds by default, with 1, 5, 10, 30, and 60-second choices in the gear menu.
- Offers English (default) and Simplified Chinese widget labels, with the preference remembered across launches.
- Uses compact `K`, `W` (ten-thousand), `M`, and `B` token units while keeping USD amounts unabridged.
- Shows input, uncached input, cached input, cache-hit rate, output, reasoning output, and total tokens.
- Groups usage by model and service tier and detects supported Fast-mode multipliers.
- Automatically fetches official model token prices and Fast-mode multipliers every six hours, with cached/offline fallback and a manual update button.
- Converts estimated credits to USD using a configurable dollars-per-credit value.
- Shows the latest account-limit status when it is available in local rollout metadata.
- Runs locally and does not require an API key or upload conversation data.
- Aggregates all local active and archived Codex tasks, so parallel windows cannot make the display jump between sessions.
- Excludes parent-task history copied into subagent rollouts and ignores repeated cumulative snapshots, preventing duplicate totals.
- Recovers usage written while the widget was closed by reading new rollout data when reopened.
- Uses a bounded widget snapshot and drains its helper output while running, so large local histories cannot stall at “Connecting to Codex…”.
- Uses the native macOS window close control instead of a custom in-panel button.
- Provides a native always-on-top macOS panel, a terminal dashboard, and JSON output.
- Remembers the panel position and displays it on every macOS Space.

## How it works

Codex writes local JSONL rollout metadata under `~/.codex/sessions` and `~/.codex/archived_sessions`. The meter reads cumulative `token_count` snapshots and adds only non-negative changes between snapshots, so repeated events are not counted twice. Subagent rollout files can contain a copied prefix or a paginated inherited baseline; neither is charged to the child. Older logs that expose only per-event increments remain supported. Global mode stores a compact index at `~/.codex/token-usage-meter/all-index-v3.json`; it contains usage metadata, file offsets, and change-detection hashes, not conversation text. Upgrading rebuilds this index once from the original logs and preserves the old index. Later refreshes check file identity and small content fingerprints, then read newly appended bytes or re-index changed files.

Cached input is treated as a subset of input, and reasoning tokens are treated as a subset of output, so neither is charged twice. Estimated cost is calculated as:

```text
uncached input × input rate
+ cached input × cached-input rate
+ output × output rate
```

Rates are credits per one million tokens, fetched from [official Codex pricing](https://learn.chatgpt.com/docs/pricing#token-rates) and [Fast-mode documentation](https://learn.chatgpt.com/docs/agent-configuration/speed). Model rows are discovered automatically, including newly published models. USD conversion remains a configurable `$0.04` per credit assumption; actual credit purchase prices and discounts depend on the plan or agreement. Codex credits and API invoices are different billing systems; this tool estimates Codex credits only.

Prices update in the background every six hours while the meter runs. An unknown model triggers an earlier check, subject to a 15-minute cooldown. Network or document-parse failures retain the last validated cache and retry after 15 minutes. The cache is `~/.codex/token-usage-meter/official-prices-v1.json`. Offline first launch uses a September 11, 2026 snapshot. Retired models absent from today's table retain their last verified rates and are marked as legacy in JSON. Unpublished models or unknown Fast multipliers keep their token counts, but are excluded from cost; the widget shows an orange partial-price indicator. A publisher layout change can require a parser update; failed parsing is never treated as zero pricing.

The amount is the **current-rate equivalent of local history**. A price update recalculates that equivalent, not the historical amount billed on each date. The gear menu shows the price-check time and an **Update prices now** button; hovering over the amount explains the estimate and any unpriced models.

The displayed dollar amount is an estimate, not an invoice. Usage included in a ChatGPT plan may not create an additional cash charge.

## Requirements

- Codex desktop or CLI with local rollout metadata.
- Python 3.9 or later.
- macOS 13 or later for the native floating widget.
- Xcode Command Line Tools only when rebuilding the native app from Swift source.

The terminal and JSON reports also run on Linux with a compatible Codex data directory.

## Quick start: standalone macOS app

Clone the repository:

```bash
git clone https://github.com/kafuunochino/codex-token-usage-meter.git
cd codex-token-usage-meter
```

Build the only app copy at `~/Applications/Token Usage Widget.app`, enable launch at macOS login, and open it immediately:

```bash
python3 plugins/token-usage-meter/scripts/install_macos.py
```

Use `--no-autostart` if login launch is not wanted.

After installation, launch it from Applications or Spotlight. The app contains its own copy of the token parser, so no terminal command is required for normal use. If macOS blocks the first launch because the app is ad-hoc signed, Control-click the app and choose **Open**.

Closing the widget does not stop Codex from recording usage. Reopening it includes events written while the widget was not running. The standalone app reports the combined local history of the whole Codex installation, not one window or task. The first global index build can take time when the local rollout history is large; later starts use the saved index.

Click the gear icon in the widget header to choose the language and refresh interval. The compact footer begins with “Refreshed at” and shows the full date, weekday, time, and active refresh interval.

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

Add `--refresh-prices` to check official prices immediately, or `--offline-prices` to disable network requests and use cached/bundled prices. `--dollars-per-credit 0.04` overrides the USD conversion assumption. No API key is needed.

## Rebuild the macOS app

```bash
cd plugins/token-usage-meter
./widget/build_widget.sh
```

The build script embeds `token_usage.py` and `official_pricing.py`, applies an ad-hoc local signature, and updates the same `~/Applications/Token Usage Widget.app`. It does not leave additional app bundles in the repository or plugin cache.

## Privacy and limitations

- Usage is read from local rollout metadata. Price updates make HTTPS GET requests to fixed public official documentation URLs, without authentication; they do not call the OpenAI model API or transmit local usage or account data.
- It does not retain or transmit conversation text.
- Session scope reports one selected task. Use `--scope today` or `--scope all` for aggregation.
- Unknown models still show token totals, but cost is reported as unavailable instead of guessed.
- Rate cards and product behavior can change; check the linked official sources before relying on an estimate.
- Codex plugins cannot add custom fields to the Codex desktop lower-left chrome, so the native floating panel is used instead.

## Tests

```bash
python3 -m unittest discover -s plugins/token-usage-meter/tests -v
```
