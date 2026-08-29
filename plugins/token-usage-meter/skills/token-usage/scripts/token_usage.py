#!/usr/bin/env python3
"""Live local Codex token, cache-hit, credit, and USD estimator."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


RATE_CARD_URL = "https://help.openai.com/en/articles/20001106-codex-rate-card"
CREDIT_VALUE_URL = "https://help.openai.com/en/articles/20001147-codex-credits-for-students-terms-of-service"
RATE_CARD_AS_OF = "2026-07-16"
DEFAULT_DOLLARS_PER_CREDIT = 0.04  # Official example: 2,500 credits = $100.
INDEX_SCHEMA_VERSION = 2
INDEX_DIRECTORY = "token-usage-meter"
INDEX_FILENAME = "all-index-v2.json"


@dataclass(frozen=True)
class Rate:
    input: float
    cached: float
    output: float


# Credits per one million tokens from the official Codex token rate card.
OFFICIAL_RATES: Dict[str, Rate] = {
    "gpt-5.6-sol": Rate(125.0, 12.5, 750.0),
    "gpt-5.6-terra": Rate(62.5, 6.25, 375.0),
    "gpt-5.6-luna": Rate(25.0, 2.5, 150.0),
    "gpt-5.5": Rate(125.0, 12.5, 750.0),
    "gpt-5.5-cyber": Rate(500.0, 50.0, 3000.0),
    "gpt-5.4": Rate(62.5, 6.25, 375.0),
    "gpt-5.4-mini": Rate(18.75, 1.875, 113.0),
    "gpt-5.3-codex": Rate(43.75, 4.375, 350.0),
    "gpt-5.2": Rate(43.75, 4.375, 350.0),
    "gpt-image-2.0-image": Rate(200.0, 50.0, 750.0),
    "gpt-image-2.0-text": Rate(125.0, 31.25, 250.0),
}

MODEL_ALIASES = {
    "codex-auto-review": "gpt-5.3-codex",
    "gpt-image-2.0-(image)": "gpt-image-2.0-image",
    "gpt-image-2.0-(text)": "gpt-image-2.0-text",
}


@dataclass
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.cache_write_input_tokens += other.cache_write_input_tokens
        self.output_tokens += other.output_tokens
        self.reasoning_output_tokens += other.reasoning_output_tokens

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float:
        if self.input_tokens <= 0:
            return 0.0
        return 100.0 * self.cached_input_tokens / self.input_tokens


BucketKey = Tuple[str, str]


@dataclass
class FileState:
    offset: int = 0
    current_model: str = "unknown"
    current_tier: str = "default"
    buckets: Dict[BucketKey, Usage] = field(default_factory=dict)
    previous_total: Usage = field(default_factory=Usage)
    have_previous_total: bool = False
    metadata_initialized: bool = False
    is_subagent: bool = False
    session_start_ms: Optional[int] = None
    accounting_started: bool = True
    latest_rate_limits: Optional[Dict[str, Any]] = None
    latest_event_timestamp: str = ""

    def reset(self, default_tier: str) -> None:
        self.offset = 0
        self.current_model = "unknown"
        self.current_tier = default_tier
        self.buckets.clear()
        self.previous_total = Usage()
        self.have_previous_total = False
        self.metadata_initialized = False
        self.is_subagent = False
        self.session_start_ms = None
        self.accounting_started = True
        self.latest_rate_limits = None
        self.latest_event_timestamp = ""


def state_from_cache(value: Any, default_tier: str) -> Optional[FileState]:
    data = value if isinstance(value, dict) else {}
    buckets_raw = data.get("buckets")
    if not isinstance(buckets_raw, list):
        return None

    state = FileState(
        offset=safe_int(data.get("offset")),
        current_model=normalize_model(data.get("current_model")),
        current_tier=normalize_tier(data.get("current_tier") or default_tier),
        previous_total=usage_from_mapping(data.get("previous_total")),
        have_previous_total=bool(data.get("have_previous_total")),
        metadata_initialized=bool(data.get("metadata_initialized")),
        is_subagent=bool(data.get("is_subagent")),
        session_start_ms=(
            data.get("session_start_ms") if isinstance(data.get("session_start_ms"), int) else None
        ),
        accounting_started=bool(
            data.get("accounting_started", not bool(data.get("is_subagent")))
        ),
        latest_rate_limits=copy.deepcopy(data.get("latest_rate_limits"))
        if isinstance(data.get("latest_rate_limits"), dict)
        else None,
        latest_event_timestamp=str(data.get("latest_event_timestamp") or ""),
    )
    for row in buckets_raw:
        if not isinstance(row, dict):
            continue
        key = (normalize_model(row.get("model")), normalize_tier(row.get("tier")))
        state.buckets[key] = usage_from_mapping(row.get("usage"))
    return state


def state_to_cache(state: FileState) -> Dict[str, Any]:
    return {
        "offset": state.offset,
        "current_model": state.current_model,
        "current_tier": state.current_tier,
        "previous_total": asdict(state.previous_total),
        "have_previous_total": state.have_previous_total,
        "metadata_initialized": state.metadata_initialized,
        "is_subagent": state.is_subagent,
        "session_start_ms": state.session_start_ms,
        "accounting_started": state.accounting_started,
        "buckets": [
            {"model": model, "tier": tier, "usage": asdict(usage)}
            for (model, tier), usage in sorted(state.buckets.items())
        ],
        "latest_rate_limits": state.latest_rate_limits,
        "latest_event_timestamp": state.latest_event_timestamp,
    }


def all_index_path(home: Path) -> Path:
    return home / INDEX_DIRECTORY / INDEX_FILENAME


def load_all_index(home: Path, default_tier: str) -> Dict[Path, FileState]:
    path = all_index_path(home)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != INDEX_SCHEMA_VERSION:
        return {}
    if normalize_tier(payload.get("default_tier")) != default_tier:
        return {}

    files = payload.get("files")
    if not isinstance(files, dict):
        return {}
    states: Dict[Path, FileState] = {}
    for raw_path, raw_state in files.items():
        if not isinstance(raw_path, str):
            continue
        state = state_from_cache(raw_state, default_tier)
        if state is not None:
            states[Path(raw_path)] = state
    return states


def save_all_index(home: Path, states: Dict[Path, FileState], default_tier: str) -> None:
    path = all_index_path(home)
    payload = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "default_tier": default_tier,
        "files": {str(file): state_to_cache(state) for file, state in sorted(states.items())},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        # Reporting remains usable when the cache directory is read-only.
        return


def normalize_model(value: Any) -> str:
    model = str(value or "unknown").strip().lower().replace("_", "-")
    return MODEL_ALIASES.get(model, model)


def normalize_tier(value: Any) -> str:
    tier = str(value or "default").strip().lower()
    return "fast" if tier == "fast" else "default"


def safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def usage_from_mapping(value: Any) -> Usage:
    data = value if isinstance(value, dict) else {}
    input_tokens = safe_int(data.get("input_tokens"))
    cached = min(input_tokens, safe_int(data.get("cached_input_tokens")))
    output_tokens = safe_int(data.get("output_tokens"))
    reasoning = min(output_tokens, safe_int(data.get("reasoning_output_tokens")))
    return Usage(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        cache_write_input_tokens=safe_int(data.get("cache_write_input_tokens")),
        output_tokens=output_tokens,
        reasoning_output_tokens=reasoning,
    )


def usage_delta(current: Usage, previous: Usage) -> Usage:
    return Usage(
        input_tokens=max(0, current.input_tokens - previous.input_tokens),
        cached_input_tokens=max(0, current.cached_input_tokens - previous.cached_input_tokens),
        cache_write_input_tokens=max(0, current.cache_write_input_tokens - previous.cache_write_input_tokens),
        output_tokens=max(0, current.output_tokens - previous.output_tokens),
        reasoning_output_tokens=max(0, current.reasoning_output_tokens - previous.reasoning_output_tokens),
    )


def uuid_v7_milliseconds(value: Any) -> Optional[int]:
    """Read the millisecond timestamp prefix from a UUIDv7-like identifier."""
    compact = str(value or "").replace("-", "")
    if len(compact) < 12:
        return None
    prefix = compact[:12]
    if any(character not in "0123456789abcdefABCDEF" for character in prefix):
        return None
    try:
        return int(prefix, 16)
    except ValueError:
        return None


def read_updates(
    path: Path,
    state: FileState,
    default_tier: str,
    fast_override: str = "auto",
) -> None:
    """Read only new JSONL records and update aggregate metadata."""
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < state.offset:
        state.reset(default_tier)
    if state.offset == 0 and not state.buckets and state.current_tier == "default":
        state.current_tier = default_tier

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(state.offset)
            while True:
                line_start = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if not line.endswith("\n"):
                    # Leave a partially written trailing line for the next refresh.
                    handle.seek(line_start)
                    break
                if not any(
                    marker in line
                    for marker in (
                        "session_meta",
                        "task_started",
                        "token_count",
                        "turn_context",
                        "thread_settings_applied",
                    )
                ):
                    # Rollout files can contain very large tool and conversation payloads.
                    # Avoid decoding JSON that cannot affect usage accounting.
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                payload = record.get("payload")
                payload = payload if isinstance(payload, dict) else {}
                record_type = record.get("type")

                if record_type == "session_meta" and not state.metadata_initialized:
                    source = payload.get("source")
                    state.is_subagent = bool(
                        payload.get("thread_source") == "subagent"
                        or (isinstance(source, dict) and "subagent" in source)
                    )
                    state.session_start_ms = uuid_v7_milliseconds(payload.get("id"))
                    state.accounting_started = not state.is_subagent
                    state.metadata_initialized = True
                    continue

                if record_type == "turn_context":
                    state.current_model = normalize_model(payload.get("model"))
                    continue

                if record_type != "event_msg":
                    continue

                event_type = payload.get("type")
                if (
                    event_type == "task_started"
                    and state.is_subagent
                    and not state.accounting_started
                ):
                    turn_start_ms = uuid_v7_milliseconds(payload.get("turn_id"))
                    if (
                        state.session_start_ms is not None
                        and turn_start_ms is not None
                        and turn_start_ms >= state.session_start_ms
                    ):
                        state.accounting_started = True
                    continue

                if event_type == "thread_settings_applied":
                    settings = payload.get("thread_settings")
                    settings = settings if isinstance(settings, dict) else {}
                    if settings.get("model"):
                        state.current_model = normalize_model(settings.get("model"))
                    if settings.get("service_tier"):
                        state.current_tier = normalize_tier(settings.get("service_tier"))
                    continue

                if event_type != "token_count":
                    continue

                info = payload.get("info")
                info = info if isinstance(info, dict) else {}
                total_raw = info.get("total_token_usage")
                last_raw = info.get("last_token_usage")
                if isinstance(total_raw, dict):
                    total = usage_from_mapping(total_raw)
                    if state.have_previous_total:
                        increment = usage_delta(total, state.previous_total)
                    else:
                        increment = total
                    # Follow cumulative totals through inherited parent history,
                    # but do not add those inherited deltas to the child file.
                    state.previous_total = total
                    state.have_previous_total = True
                elif isinstance(last_raw, dict):
                    # Compatibility with older rollout formats that expose only
                    # the per-event increment.
                    increment = usage_from_mapping(last_raw)
                else:
                    continue

                if not state.accounting_started:
                    continue

                tier = state.current_tier
                if fast_override != "auto":
                    tier = "fast" if fast_override == "on" else "default"
                key = (state.current_model, tier)
                state.buckets.setdefault(key, Usage()).add(increment)

                rate_limits = payload.get("rate_limits")
                if isinstance(rate_limits, dict):
                    state.latest_rate_limits = copy.deepcopy(rate_limits)
                state.latest_event_timestamp = str(record.get("timestamp") or "")

            state.offset = handle.tell()
    except OSError:
        return


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def read_default_tier(home: Path) -> str:
    config = home / "config.toml"
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "default"
    # Only inspect root keys before the first TOML table.
    root_text = text.split("\n[", 1)[0]
    match = re.search(r'^\s*service_tier\s*=\s*["\']([^"\']+)["\']', root_text, re.MULTILINE)
    return normalize_tier(match.group(1) if match else "default")


def session_candidates(home: Path) -> List[Path]:
    files: List[Path] = []
    for directory in (home / "sessions", home / "archived_sessions"):
        if directory.is_dir():
            files.extend(directory.rglob("*.jsonl"))
    return files


def is_user_session(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            first = json.loads(handle.readline())
    except (OSError, json.JSONDecodeError):
        return True
    if first.get("type") != "session_meta":
        return True
    payload = first.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    return payload.get("thread_source", "user") == "user"


def file_rollout_date(path: Path) -> Optional[str]:
    match = re.search(r"rollout-(\d{4}-\d{2}-\d{2})T", path.name)
    return match.group(1) if match else None


def select_files(
    home: Path,
    scope: str,
    session_file: Optional[Path],
    session_id: Optional[str],
) -> List[Path]:
    if session_file:
        return [session_file.expanduser().resolve()] if session_file.exists() else []

    candidates = session_candidates(home)
    if session_id:
        return sorted([path for path in candidates if session_id in path.name])

    if scope == "session":
        active = [path for path in candidates if "archived_sessions" not in path.parts and is_user_session(path)]
        if not active:
            active = [path for path in candidates if is_user_session(path)]
        if not active:
            return []
        return [max(active, key=lambda path: path.stat().st_mtime_ns)]

    if scope == "today":
        today = datetime.now().astimezone().date().isoformat()
        return sorted(path for path in candidates if file_rollout_date(path) == today)

    return sorted(candidates)


def aggregate(states: Iterable[FileState]) -> Tuple[Dict[BucketKey, Usage], Usage, Optional[Dict[str, Any]], str]:
    buckets: Dict[BucketKey, Usage] = {}
    total = Usage()
    latest_limits: Optional[Dict[str, Any]] = None
    latest_timestamp = ""
    for state in states:
        for key, usage in state.buckets.items():
            buckets.setdefault(key, Usage()).add(usage)
            total.add(usage)
        if state.latest_event_timestamp >= latest_timestamp and state.latest_rate_limits is not None:
            latest_timestamp = state.latest_event_timestamp
            latest_limits = state.latest_rate_limits
    return buckets, total, latest_limits, latest_timestamp


def fast_multiplier(model: str, tier: str, billing_mode: str) -> float:
    if billing_mode != "chatgpt" or tier != "fast":
        return 1.0
    if model.startswith("gpt-5.6") or model.startswith("gpt-5.5"):
        return 2.5
    if model.startswith("gpt-5.4"):
        return 2.0
    return 1.0


def bucket_cost(
    model: str,
    tier: str,
    usage: Usage,
    rates: Dict[str, Rate],
    billing_mode: str,
) -> Optional[float]:
    rate = rates.get(model)
    if rate is None:
        return None
    standard = (
        usage.uncached_input_tokens * rate.input
        + usage.cached_input_tokens * rate.cached
        + usage.output_tokens * rate.output
    ) / 1_000_000.0
    return standard * fast_multiplier(model, tier, billing_mode)


def parse_custom_rate(value: str) -> Tuple[str, Rate]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("rate must be model,input,cached,output credits per 1M")
    model = normalize_model(parts[0])
    try:
        numbers = [float(part) for part in parts[1:]]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rate values must be numbers") from exc
    if any(number < 0 for number in numbers):
        raise argparse.ArgumentTypeError("rate values must be non-negative")
    return model, Rate(*numbers)


def format_reset(epoch: Any) -> str:
    try:
        moment = datetime.fromtimestamp(float(epoch)).astimezone()
    except (TypeError, ValueError, OSError, OverflowError):
        return "unknown"
    return moment.strftime("%Y-%m-%d %H:%M %Z")


def display_model(model: str) -> str:
    names = {
        "gpt-5.6-sol": "GPT-5.6 Sol",
        "gpt-5.6-terra": "GPT-5.6 Terra",
        "gpt-5.6-luna": "GPT-5.6 Luna",
        "gpt-5.5-cyber": "GPT-5.5 Cyber",
        "gpt-5.4-mini": "GPT-5.4 Mini",
        "gpt-5.3-codex": "GPT-5.3 Codex",
    }
    return names.get(model, model.upper() if model.startswith("gpt-") else model)


def summary_dict(
    scope: str,
    files: List[Path],
    buckets: Dict[BucketKey, Usage],
    total: Usage,
    limits: Optional[Dict[str, Any]],
    event_timestamp: str,
    rates: Dict[str, Rate],
    dollars_per_credit: float,
    billing_mode: str,
) -> Dict[str, Any]:
    rows = []
    known_credits = 0.0
    fully_priced = True
    for (model, tier), usage in sorted(buckets.items()):
        credits = bucket_cost(model, tier, usage, rates, billing_mode)
        if credits is None:
            fully_priced = False
        else:
            known_credits += credits
        rate = rates.get(model)
        rows.append(
            {
                "model": model,
                "tier": tier,
                "tokens": {
                    **asdict(usage),
                    "uncached_input_tokens": usage.uncached_input_tokens,
                    "total_tokens": usage.total_tokens,
                    "cache_hit_rate_percent": round(usage.cache_hit_rate, 4),
                },
                "rate_credits_per_million": asdict(rate) if rate else None,
                "fast_multiplier": fast_multiplier(model, tier, billing_mode),
                "estimated_credits": round(credits, 8) if credits is not None else None,
                "estimated_usd": round(credits * dollars_per_credit, 8) if credits is not None else None,
            }
        )
    return {
        "scope": scope,
        "files": [str(path) for path in files],
        "last_token_event": event_timestamp or None,
        "tokens": {
            **asdict(total),
            "uncached_input_tokens": total.uncached_input_tokens,
            "total_tokens": total.total_tokens,
            "cache_hit_rate_percent": round(total.cache_hit_rate, 4),
        },
        "models": rows,
        "estimate": {
            "fully_priced": fully_priced,
            "known_credits": round(known_credits, 8),
            "known_usd": round(known_credits * dollars_per_credit, 8),
            "dollars_per_credit": dollars_per_credit,
            "billing_mode": billing_mode,
            "rate_card_as_of": RATE_CARD_AS_OF,
            "rate_card_url": RATE_CARD_URL,
        },
        "rate_limits": limits,
    }


def widget_summary_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return only the fields consumed by the native widget.

    The regular JSON report intentionally includes every rollout path and the
    full per-model rate breakdown. That output grows with local history and can
    exceed a macOS pipe buffer. Keep the widget protocol small and stable.
    """
    return {
        "tokens": data["tokens"],
        "estimate": {
            "fully_priced": data["estimate"]["fully_priced"],
            "known_usd": data["estimate"]["known_usd"],
        },
        "models": [{"model": row["model"]} for row in data["models"]],
    }


def money(value: float) -> str:
    if value >= 100:
        return f"${value:,.2f}"
    if value >= 1:
        return f"${value:,.3f}"
    return f"${value:,.4f}"


def render_text(data: Dict[str, Any], watch: bool, interval: float) -> str:
    tokens = data["tokens"]
    estimate = data["estimate"]
    models = data["models"]
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    mode = f"LIVE / {interval:g}s" if watch else "SNAPSHOT"
    lines = [
        f"Codex Token Usage Meter  [{mode}]",
        "=" * 64,
        f"Scope: {data['scope']}    Updated: {now}    Files: {len(data['files'])}",
        "",
        f"Input total       {tokens['input_tokens']:>16,}",
        f"  Uncached input  {tokens['uncached_input_tokens']:>16,}",
        f"  Cached input    {tokens['cached_input_tokens']:>16,}",
        f"Cache hit rate    {tokens['cache_hit_rate_percent']:>15.1f}%",
        f"Output            {tokens['output_tokens']:>16,}",
        f"  Reasoning       {tokens['reasoning_output_tokens']:>16,}  (subset of output)",
        f"Total tokens      {tokens['total_tokens']:>16,}",
        "",
    ]

    credits = estimate["known_credits"]
    usd = estimate["known_usd"]
    prefix = "Estimated" if estimate["fully_priced"] else "Known-rate est."
    lines.extend(
        [
            f"{prefix} credits {credits:>14,.4f}",
            f"{prefix} USD     {money(usd):>14}",
        ]
    )
    if not estimate["fully_priced"]:
        unknown = sorted({row["model"] for row in models if row["estimated_credits"] is None})
        lines.append(f"Unpriced models: {', '.join(unknown)}")

    if models:
        lines.extend(["", "By model / tier:"])
        for row in models:
            usage = row["tokens"]
            cost = "N/A" if row["estimated_usd"] is None else money(row["estimated_usd"])
            multiplier = row["fast_multiplier"]
            suffix = f", x{multiplier:g}" if multiplier != 1.0 else ""
            lines.append(
                f"  {display_model(row['model'])} [{row['tier']}{suffix}]  "
                f"in {usage['input_tokens']:,} / cached {usage['cached_input_tokens']:,} "
                f"({usage['cache_hit_rate_percent']:.1f}%) / out {usage['output_tokens']:,} / {cost}"
            )

    limits = data.get("rate_limits")
    if isinstance(limits, dict):
        primary = limits.get("primary")
        primary = primary if isinstance(primary, dict) else {}
        if primary:
            used = primary.get("used_percent")
            try:
                used_text = f"{float(used):.1f}% used"
            except (TypeError, ValueError):
                used_text = "usage unknown"
            lines.extend(
                [
                    "",
                    f"Account limit: {used_text}; resets {format_reset(primary.get('resets_at'))}",
                ]
            )

    lines.extend(
        [
            "",
            f"Rate snapshot: {RATE_CARD_AS_OF}  {RATE_CARD_URL}",
            "Estimate only: included plan usage may not be an extra cash charge.",
            "Fast-mode multipliers apply only when detected or explicitly selected.",
            "Local metadata only; no conversation content is retained or sent.",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("session", "today", "all"), default="session")
    parser.add_argument("--watch", action="store_true", help="refresh continuously")
    parser.add_argument("--interval", type=float, default=5.0, help="watch refresh seconds (default: 5)")
    parser.add_argument("--json", action="store_true", help="emit one JSON snapshot")
    parser.add_argument(
        "--widget-json",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--no-cache", action="store_true", help="disable the persistent all-history index")
    parser.add_argument("--no-clear", action="store_true", help="do not clear the terminal between refreshes")
    parser.add_argument("--session-file", type=Path, help="read one explicit rollout JSONL file")
    parser.add_argument(
        "--session-id",
        help="select rollout filenames containing this session id (defaults to CODEX_THREAD_ID for session scope)",
    )
    parser.add_argument("--codex-home", type=Path, default=codex_home(), help="Codex data directory")
    parser.add_argument("--fast", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--billing-mode", choices=("chatgpt", "api"), default="chatgpt")
    parser.add_argument("--dollars-per-credit", type=float, default=DEFAULT_DOLLARS_PER_CREDIT)
    parser.add_argument(
        "--rate",
        action="append",
        type=parse_custom_rate,
        default=[],
        metavar="MODEL,INPUT,CACHED,OUTPUT",
        help="override credits per 1M for a model",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.interval <= 0:
        raise SystemExit("--interval must be greater than zero")
    if args.dollars_per_credit < 0:
        raise SystemExit("--dollars-per-credit must be non-negative")
    if args.json and args.widget_json:
        raise SystemExit("--json and --widget-json cannot be combined")
    if (args.json or args.widget_json) and args.watch:
        raise SystemExit("JSON output cannot be combined with --watch")

    home = args.codex_home.expanduser()
    default_tier = read_default_tier(home)
    rates = dict(OFFICIAL_RATES)
    for model, rate in args.rate:
        rates[model] = rate

    effective_session_id = args.session_id
    if not effective_session_id and args.scope == "session" and not args.session_file:
        effective_session_id = os.environ.get("CODEX_THREAD_ID") or None

    cache_enabled = (
        args.scope == "all"
        and not args.no_cache
        and not args.session_file
        and not args.session_id
        and args.fast == "auto"
    )
    states = load_all_index(home, default_tier) if cache_enabled else {}
    pinned_files: Optional[List[Path]] = None
    if args.scope == "session" or args.session_file or args.session_id:
        pinned_files = select_files(home, args.scope, args.session_file, effective_session_id)
        if not pinned_files and effective_session_id and not args.session_id and not args.session_file:
            pinned_files = select_files(home, args.scope, None, None)

    try:
        while True:
            files = pinned_files if pinned_files is not None else select_files(
                home, args.scope, args.session_file, effective_session_id
            )
            if not files:
                print(f"No Codex rollout files found under {home}", file=sys.stderr)
                return 2

            if cache_enabled:
                current_files = set(files)
                states = {path: state for path, state in states.items() if path in current_files}

            for path in files:
                state = states.setdefault(path, FileState(current_tier=default_tier))
                read_updates(path, state, default_tier, args.fast)

            if cache_enabled:
                save_all_index(home, states, default_tier)

            buckets, total, limits, event_timestamp = aggregate(states[path] for path in files if path in states)
            data = summary_dict(
                args.scope,
                files,
                buckets,
                total,
                limits,
                event_timestamp,
                rates,
                args.dollars_per_credit,
                args.billing_mode,
            )
            if args.widget_json:
                output = json.dumps(
                    widget_summary_dict(data),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            elif args.json:
                output = json.dumps(data, ensure_ascii=False, indent=2)
            else:
                output = render_text(data, args.watch, args.interval)
            if args.watch and not args.no_clear and sys.stdout.isatty():
                print("\033[2J\033[H", end="")
            print(output, flush=True)

            if not args.watch:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
