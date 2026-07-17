---
name: token-usage
description: Inspect local Codex rollout metadata and report input, uncached input, cached input, prompt-cache hit rate, output, reasoning, total tokens, Codex credits, account limit status, and estimated USD value. Use when the user asks how many tokens Codex used, what a task cost, how effective prompt caching was, or wants a live token/cost monitor that refreshes every five seconds.
---

# Token Usage

Use `scripts/token_usage.py`. It uses only the Python standard library, reads local JSONL rollout metadata, and sends no data over the network.

## macOS floating widget

When the user asks for a widget, floating panel, always-on-top display, or a visual alternative to the unavailable Codex lower-left extension point, run:

```bash
python3 <skill-dir>/scripts/launch_widget.py
```

Launching a GUI app may require tool approval. The widget opens near the lower-left of the primary screen on first use, stays above ordinary windows, appears on every Space, refreshes every five seconds, remembers its dragged position, and closes from its × button. Do not also start the terminal dashboard unless the user asks for both.

The packaged app contains its own copy of `token_usage.py`, so it can be copied to `~/Applications` and launched by double-clicking without a terminal command. A separately installed login LaunchAgent may open that standalone app at macOS login. The widget aggregates all local Codex tasks, including archived rollouts, and uses a persistent numeric index so parallel windows cannot make the display jump between sessions. Closing the widget does not stop Codex accounting: reopening it reads additions written while the widget was not running. The index contains file offsets and usage totals only, never conversation content.

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
- Treat reasoning tokens as a subset of output tokens. Display them separately but never charge them twice.
- Preserve the script's `estimated` wording. Included plan usage is not necessarily an incremental cash charge.
- Use the bundled official rate-card snapshot unless the user explicitly asks to refresh prices. If prices are refreshed, update the script and cite the current official Codex rate card.
- Let automatic Fast-mode detection use rollout settings or the root `service_tier` in Codex config. If detection is uncertain, pass `--fast on` or `--fast off` based on verified current settings.
- For an unknown model, report token counts and `N/A` cost rather than guessing. Use `--rate model,input,cached,output` only with a verified credits-per-million rate.

## Product boundary

Codex plugins cannot add custom fields to the desktop app's lower-left chrome or to the CLI's fixed status-line item list. If asked to pin this metric there, explain that limitation briefly and offer the native floating widget as the closest supported experience. The CLI's `/statusline` can still show built-in total input and output token items, but not this plugin's cache-hit or USD fields.
