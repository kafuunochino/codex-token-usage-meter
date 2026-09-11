"""Public official Codex prices, with validated disk cache and background refresh.

Only fixed public documentation URLs are requested. No rollout data, model
usage, account credentials, or conversation content is sent to the server.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

RATE_CARD_URL = "https://learn.chatgpt.com/docs/pricing"
SPEED_URL = "https://learn.chatgpt.com/docs/agent-configuration/speed"
RATE_CARD_AS_OF = "2026-09-11"
REFRESH_SECONDS = 6 * 60 * 60
RETRY_SECONDS = 15 * 60
CACHE_FILENAME = "official-prices-v1.json"


@dataclass(frozen=True)
class Rate:
    input: float
    cached: float
    output: float


# Verified fallback for offline first launch; all live rows replace these.
OFFICIAL_RATES = {
    "gpt-6-astra": Rate(250, 25, 1250),
    "gpt-5.6-sol": Rate(100, 10, 500),
    "gpt-5.6-terra": Rate(50, 5, 300),
    "gpt-5.6-luna": Rate(5, 0.5, 30),
    "daybreak-blue": Rate(100, 10, 500),
    "daybreak-red": Rate(312.5, 31.25, 1875),
    "gpt-5.5": Rate(125, 12.5, 750),
    "gpt-5.4": Rate(62.5, 6.25, 375),
    "gpt-5.4-mini": Rate(18.75, 1.875, 113),
    "gpt-image-2-image": Rate(200, 50, 750),
    "gpt-image-2-text": Rate(125, 31.25, 250),
    # Retained July snapshot for historical models absent from today's table.
    "gpt-5.3-codex": Rate(43.75, 4.375, 350),
    "gpt-5.2": Rate(43.75, 4.375, 350),
    "gpt-5.5-cyber": Rate(500, 50, 3000),
}
LEGACY_MODELS = {"gpt-5.3-codex", "gpt-5.2", "gpt-5.5-cyber"}
OFFICIAL_FAST = {
    "gpt-6-astra": 2.5, "gpt-5.6-sol": 2.5, "gpt-5.6-terra": 2.5,
    "gpt-5.6-luna": 2.5, "gpt-5.5": 2.5, "gpt-5.5-cyber": 2.5,
    "gpt-5.4": 2.0, "gpt-5.4-mini": 2.0,
}


def model_slug(label):
    text = label.strip().lower().replace("_", "-")
    text = text.translate(str.maketrans({"‑": "-", "–": "-", "—": "-"}))
    text = re.sub(r"[\s()]+", "-", text).strip("-")
    return re.sub(r"-+", "-", text)


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def valid_rate(raw):
    rate = Rate(**raw)
    values = (rate.input, rate.cached, rate.output)
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v < 0 or v > 1e9 for v in values):
        raise ValueError("Invalid price values")
    if rate.input <= 0 or rate.output <= 0 or rate.cached > rate.input:
        raise ValueError("Invalid price relationship")
    return rate


def parse_rate_card(document):
    parser = TableParser()
    parser.feed(document)
    # Also accept ordinary Markdown tables if the official publisher changes
    # its markdown serialization; require exactly the same units and columns.
    md_rows = []
    for line in document.splitlines():
        if line.strip().startswith("|"):
            row = [re.sub(r"[`*]", "", c.strip()) for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r"[-: ]*", c) for c in row):
                md_rows.append(row)
        elif md_rows:
            parser.tables.append(md_rows)
            md_rows = []
    if md_rows:
        parser.tables.append(md_rows)
    for table in parser.tables:
        if not table:
            continue
        header = [c.lower() for c in table[0]]
        if len(header) != 4 or "credits per 1m tokens" not in header[0]:
            continue
        if not ("input" in header[1] and "cached" in header[2] and "output" in header[3]):
            raise ValueError("Official price columns changed")
        rates, unavailable = {}, []
        for row in table[1:]:
            if not row:
                continue
            slug = model_slug(row[0])
            if "research preview" in " ".join(row[1:]).lower():
                unavailable.append(slug)
                continue
            if len(row) != 4:
                continue
            numbers = []
            for value in row[1:]:
                match = re.fullmatch(r"([\d,]+(?:\.\d+)?)\s*credits?", value, re.I)
                if not match:
                    raise ValueError("Unrecognized official token price")
                numbers.append(float(match.group(1).replace(",", "")))
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", slug):
                raise ValueError("Unrecognized official model label")
            rate = valid_rate(dict(zip(("input", "cached", "output"), numbers)))
            if slug in rates and rates[slug] != rate:
                raise ValueError("Conflicting official prices")
            rates[slug] = rate
        if len(rates) < 3:
            raise ValueError("Official rate table is incomplete")
        return rates, unavailable
    raise ValueError("Official token rate table not found")


def parse_fast_rates(document, models):
    # Parse only the Fast mode section, excluding the separate API price prose.
    section = document.split("## Fast mode", 1)[-1].split("Use `/fast", 1)[0]
    section = re.sub(r"\s+", " ", section.replace("**", ""))
    multipliers = {}
    clauses = re.split(r";|\. (?=[A-Z])", section)
    for clause in clauses:
        match = re.search(r"consumes? credits at (\d+(?:\.\d+)?)x", clause, re.I)
        if not match:
            continue
        multiplier = float(match.group(1))
        if not 1 <= multiplier <= 100:
            raise ValueError("Invalid Fast multiplier")
        subject = clause[:match.start()]
        for model in models:
            label = model.replace("-", " ")
            normalized = re.sub(r"[-\s]+", " ", subject.lower())
            # Exact labels or an explicitly named numeric GPT family.
            family = re.match(r"gpt-\d+(?:\.\d+)?", model)
            exact = re.search(r"\b" + re.escape(label) + r"\b", normalized)
            family_only = family and re.search(
                r"\b" + re.escape(family.group().replace("-", " "))
                + r"(?=\s*(?:,|and\b|$))", normalized)
            if exact or family_only:
                multipliers[model] = multiplier
    if not multipliers:
        raise ValueError("Official Fast rates not found")
    return multipliers


def approved_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "learn.chatgpt.com", "developers.openai.com", "platform.openai.com"
    } or parsed.username or parsed.password:
        raise ValueError("Only official HTTPS documentation is allowed")


class OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        approved_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_document(url):
    approved_url(url)
    request = Request(url, headers={"User-Agent": "TokenUsageMeter/1.0", "Accept": "text/markdown,text/html"})
    with build_opener(OfficialRedirects()).open(request, timeout=8) as response:
        approved_url(response.url)
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Official document exceeds size limit")
    return raw.decode("utf-8")


def cache_path(home):
    return Path(home) / "token-usage-meter" / CACHE_FILENAME


def read_cache(home):
    try:
        data = json.loads(cache_path(home).read_text(encoding="utf-8"))
        if data.get("version") != 1:
            return {}
        for key in ("unavailable", "current_models", "legacy_models"):
            if not isinstance(data.get(key, []), list) or any(
                not isinstance(v, str) for v in data.get(key, [])
            ):
                return {}
        for raw in data.get("rates", {}).values():
            valid_rate(raw)
        for v in data.get("fast", {}).values():
            if not isinstance(v, (float, int)) or not math.isfinite(v) or not 1 <= v <= 100:
                return {}
        for key in ("checked_at", "attempted_at"):
            v = data.get(key, 0)
            if not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                return {}
        return data
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def write_cache(home, data):
    path = cache_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def refresh_cache(home, force=False, fetch=fetch_document, now=None):
    now = time.time() if now is None else now
    lock = cache_path(home).with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return read_cache(home)
        data = read_cache(home)
        if not force and now - data.get("attempted_at", 0) < RETRY_SECONDS:
            return data
        data.update(version=1, attempted_at=now)
        write_cache(home, data)
        try:
            rates, unavailable = parse_rate_card(fetch(RATE_CARD_URL + ".md"))
            fast = parse_fast_rates(fetch(SPEED_URL + ".md"), rates)
            old_rates = data.get("rates", {})
            old_fast = data.get("fast", {})
            legacy = sorted((set(old_rates) | LEGACY_MODELS) - set(rates) - set(unavailable))
            merged = {**old_rates, **{k: asdict(v) for k, v in rates.items()}}
            for key in unavailable:
                merged.pop(key, None)
            # Retain Fast rates only for models absent from the fresh table.
            old_fast = {k: v for k, v in old_fast.items() if k in legacy}
            data.update(rates=merged, fast={**old_fast, **fast}, unavailable=unavailable,
                        current_models=sorted(rates), legacy_models=legacy,
                        checked_at=now, error=None)
        except (OSError, ValueError, TypeError) as exc:
            # A failed fetch/parse never destroys the last verified snapshot.
            data["error"] = f"{type(exc).__name__}: official prices could not be updated"
        write_cache(home, data)
        return data


def load_pricing(home, needed_models=(), auto=True, force=False):
    if force:
        data = refresh_cache(home, force=True)
    else:
        data = read_cache(home)
    rates = dict(OFFICIAL_RATES)
    rates.update({k: valid_rate(v) for k, v in data.get("rates", {}).items()})
    for key in data.get("unavailable", []):
        rates.pop(key, None)
    fast = {k: v for k, v in OFFICIAL_FAST.items() if k not in data.get("current_models", [])}
    fast.update(data.get("fast", {}))
    now = time.time()
    checked = data.get("checked_at", 0)
    stale = now - checked >= REFRESH_SECONDS
    unknown = any(m not in rates and m not in data.get("unavailable", []) for m in needed_models)
    retry_due = now - data.get("attempted_at", 0) >= RETRY_SECONDS
    if auto and not force and (stale or unknown) and retry_due:
        # Detached output prevents the helper from holding the widget pipe open.
        try:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--home", str(home)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        except OSError:
            pass
    return rates, fast, {
        "status": "cached" if checked and not stale and not data.get("error") else "stale" if checked else "bundled",
        "checked_at": checked or None,
        "source_url": RATE_CARD_URL,
        "speed_url": SPEED_URL,
        "refresh_hours": REFRESH_SECONDS // 3600,
        "auto_update": auto,
        "error": data.get("error"),
        "legacy_models": data.get("legacy_models", sorted(LEGACY_MODELS)),
        "basis": "current_rate_equivalent",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    options = parser.parse_args()
    result = refresh_cache(options.home, force=options.force)
    print(json.dumps({k: result.get(k) for k in ("checked_at", "error", "current_models")}))
    sys.exit(1 if result.get("error") else 0)
