---
name: token-usage
description: Inspect local Codex rollout metadata and report input, uncached input, cached input, prompt-cache hit rate, output, reasoning, total tokens, Codex credits, account limit status, and estimated USD value. Use when the user asks how many tokens Codex used, what a task cost, how effective prompt caching was, or wants a live token/cost monitor that refreshes every five seconds.
---

# Token Usage

Use `scripts/token_usage.py`. It uses only the Python standard library and reads local JSONL rollout metadata. Prices auto-update from fixed public official documentation URLs; no local usage, account data, or conversation content is uploaded. Use `--offline-prices` to suppress network requests.

## macOS floating widget

When the user asks for a widget, floating panel, always-on-top display, or a visual alternative to the unavailable Codex lower-left extension point, run:

```bash
python3 <skill-dir>/scripts/launch_widget.py
```

Launching a GUI app may require tool approval. The widget opens near the lower-left of the primary screen on first use, stays above ordinary windows, appears on every Space, refreshes every five seconds by default, remembers its dragged position, and closes from the native macOS close button. Its gear popover offers English (default) or Simplified Chinese labels and 1, 5, 10, 30, or 60-second refresh intervals; both preferences persist across launches. It also shows the official-price check time and an Update prices now button. Do not also start the terminal dashboard unless the user asks for both.

Keep exactly one installed app at `~/Applications/Token Usage Widget.app`. The launcher updates this app from plugin sources when needed, then opens it; avoid app copies in source, cache, or output directories. The installed app bundles `token_usage.py` and `official_pricing.py`, so normal use needs no terminal. A login LaunchAgent may open that same app at macOS login. The widget aggregates active and archived local tasks, ignores repeated cumulative snapshots, and excludes inherited subagent history. Reopening it reads usage written while it was closed. The index stores usage metadata, file offsets, and change-detection hashes, never conversation text.

## Live dashboard

When the user asks to monitor, watch, refresh, or show live usage, run the script in a visible PTY and leave it running:

```bash
python3 <skill-dir>/scripts/token_usage.py --watch --interval 5 --scope all
```

Use the tool execution facility with `tty: true`. A five-second refresh is the default requirement. Tell the user where the live terminal is visible and how to stop it with Ctrl+C. Do not block the conversation by polling the process after the dashboard is visibly running.

Use `all` for the whole-Codex monitor. Use `session` only when the user explicitly asks about one task, and `today` when the user asks for today's aggregate.

## One-time report

For a concise snapshot, run:

```bash
python3 <skill-dir>/scripts/token_usage.py --scope all
```

Use `--json` when downstream processing needs structured output. Use `--session-file <path>` when the user identifies a specific rollout.

## Cost interpretation

- Treat cached tokens as a subset of input tokens. Charge uncached input as `input - cached`, cached input at the cached rate, and output at the output rate.
- Index v3 excludes the initial inherited cumulative baseline of paginated subagents and detects changed log files using file identity and content fingerprints. A version change rebuilds the index once from original logs; do not delete logs or seed counters with manually adjusted totals.
- Treat reasoning tokens as a subset of output tokens. Display them separately but never charge them twice.
- Preserve the script's `estimated` wording. Included plan usage is not necessarily an incremental cash charge.
- Prices update in the background every six hours, with earlier checks for unknown models and a 15-minute retry cooldown. Use `--refresh-prices` for a synchronous immediate check. Failed fetches or parses retain the last verified cache; first offline launch uses the bundled snapshot. The pricing cache lives at `~/.codex/token-usage-meter/official-prices-v1.json`.
- Report the amount as the current-rate equivalent of local history, not historical invoiced spend. USD uses the configurable $0.04/credit assumption; actual credit purchase terms vary. This is Codex credit pricing, not API invoicing. Cite https://learn.chatgpt.com/docs/pricing#token-rates and https://learn.chatgpt.com/docs/agent-configuration/speed when explaining updated rates.
- Unknown models or unpublished Fast multipliers are excluded from estimated cost, not from token totals. Check `estimate.unpriced_models`, `estimate.unpriced_tokens`, and `estimate.pricing` for coverage, freshness, and legacy model rates. Do not silently assign another model's price.
- Let automatic Fast-mode detection use rollout settings or the root `service_tier` in Codex config. If detection is uncertain, pass `--fast on` or `--fast off` based on verified current settings.
- For an unknown model, report token counts and `N/A` cost rather than guessing. Use `--rate model,input,cached,output` only with a verified credits-per-million rate.

## Product boundary

Codex plugins cannot add custom fields to the desktop app's lower-left chrome or to the CLI's fixed status-line item list. If asked to pin this metric there, explain that limitation briefly and offer the native floating widget as the closest supported experience. The CLI's `/statusline` can still show built-in total input and output token items, but not this plugin's cache-hit or USD fields.
