import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "skills" / "token-usage" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from token_usage import (  # noqa: E402
    DEFAULT_DOLLARS_PER_CREDIT,
    FileState,
    INDEX_FILENAME,
    OFFICIAL_RATES,
    Usage,
    aggregate,
    bucket_cost,
    load_all_index,
    read_updates,
    save_all_index,
    select_files,
    summary_dict,
    widget_summary_dict,
)


def token_event(last=None, total=None, timestamp="2026-07-17T00:00:01Z"):
    info = {}
    if last is not None:
        info["last_token_usage"] = last
    if total is not None:
        info["total_token_usage"] = total
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": info, "rate_limits": {}},
    }


class TokenUsageTests(unittest.TestCase):
    def write_records(self, path, records):
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    def test_cached_and_reasoning_tokens_are_not_double_charged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            self.write_records(
                path,
                [
                    {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
                    token_event(
                        last={
                            "input_tokens": 1000,
                            "cached_input_tokens": 400,
                            "output_tokens": 100,
                            "reasoning_output_tokens": 20,
                        },
                        total={
                            "input_tokens": 1000,
                            "cached_input_tokens": 400,
                            "output_tokens": 100,
                            "reasoning_output_tokens": 20,
                        },
                    ),
                ],
            )
            state = FileState()
            read_updates(path, state, "default")
            usage = state.buckets[("gpt-5.6-sol", "default")]
            self.assertEqual(usage.uncached_input_tokens, 600)
            self.assertEqual(usage.total_tokens, 1100)
            # 600*125 + 400*12.5 + 100*750, divided by one million.
            self.assertAlmostEqual(bucket_cost("gpt-5.6-sol", "default", usage, OFFICIAL_RATES, "chatgpt"), 0.155)

    def test_fast_mode_uses_official_multiplier(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            self.write_records(
                path,
                [
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "thread_settings_applied",
                            "thread_settings": {"model": "gpt-5.6-sol", "service_tier": "fast"},
                        },
                    },
                    token_event(
                        last={"input_tokens": 2000, "cached_input_tokens": 1000, "output_tokens": 200},
                        total={"input_tokens": 2000, "cached_input_tokens": 1000, "output_tokens": 200},
                    ),
                ],
            )
            state = FileState()
            read_updates(path, state, "default")
            usage = state.buckets[("gpt-5.6-sol", "fast")]
            standard = (1000 * 125 + 1000 * 12.5 + 200 * 750) / 1_000_000
            self.assertAlmostEqual(
                bucket_cost("gpt-5.6-sol", "fast", usage, OFFICIAL_RATES, "chatgpt"),
                standard * 2.5,
            )

    def test_total_usage_delta_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            self.write_records(
                path,
                [
                    {"type": "turn_context", "payload": {"model": "gpt-5.6-terra"}},
                    token_event(total={"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10}),
                    token_event(
                        total={"input_tokens": 150, "cached_input_tokens": 60, "output_tokens": 20},
                        timestamp="2026-07-17T00:00:02Z",
                    ),
                ],
            )
            state = FileState()
            read_updates(path, state, "default")
            usage = state.buckets[("gpt-5.6-terra", "default")]
            self.assertEqual(usage.input_tokens, 150)
            self.assertEqual(usage.cached_input_tokens, 60)
            self.assertEqual(usage.output_tokens, 20)

    def test_duplicate_cumulative_events_are_counted_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            total = {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10}
            self.write_records(
                path,
                [
                    {"type": "turn_context", "payload": {"model": "gpt-5.6-terra"}},
                    token_event(last=total, total=total),
                    token_event(last=total, total=total, timestamp="2026-07-17T00:00:02Z"),
                ],
            )
            state = FileState()
            read_updates(path, state, "default")
            usage = state.buckets[("gpt-5.6-terra", "default")]
            self.assertEqual(usage.input_tokens, 100)
            self.assertEqual(usage.cached_input_tokens, 40)
            self.assertEqual(usage.output_tokens, 10)

    def test_subagent_inherited_parent_history_is_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            inherited = [
                {
                    "type": "session_meta",
                    "payload": {
                        "id": "019f69f1-217b-7000-a000-000000000001",
                        "thread_source": "subagent",
                        "source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}},
                    },
                },
                {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "task_started",
                        "turn_id": "019f69f0-0000-7000-a000-000000000001",
                    },
                },
                token_event(
                    last={"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 80},
                    total={"input_tokens": 1000, "cached_input_tokens": 600, "output_tokens": 80},
                ),
                token_event(
                    last={"input_tokens": 500, "cached_input_tokens": 100, "output_tokens": 20},
                    total={"input_tokens": 1500, "cached_input_tokens": 700, "output_tokens": 100},
                    timestamp="2026-07-17T00:00:02Z",
                ),
            ]
            self.write_records(path, inherited)
            state = FileState()
            read_updates(path, state, "default")
            self.assertEqual(state.buckets, {})

            actual = [
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "task_started",
                        "turn_id": "019f69f1-3000-7000-a000-000000000001",
                    },
                },
                {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
                token_event(
                    last={
                        "input_tokens": 100,
                        "cached_input_tokens": 70,
                        "output_tokens": 10,
                        "reasoning_output_tokens": 2,
                    },
                    total={
                        "input_tokens": 1600,
                        "cached_input_tokens": 770,
                        "output_tokens": 110,
                        "reasoning_output_tokens": 2,
                    },
                    timestamp="2026-07-17T00:00:03Z",
                ),
                token_event(
                    last={
                        "input_tokens": 100,
                        "cached_input_tokens": 70,
                        "output_tokens": 10,
                        "reasoning_output_tokens": 2,
                    },
                    total={
                        "input_tokens": 1600,
                        "cached_input_tokens": 770,
                        "output_tokens": 110,
                        "reasoning_output_tokens": 2,
                    },
                    timestamp="2026-07-17T00:00:04Z",
                ),
            ]
            with path.open("a", encoding="utf-8") as handle:
                handle.write("".join(json.dumps(record) + "\n" for record in actual))
            read_updates(path, state, "default")

            usage = state.buckets[("gpt-5.6-sol", "default")]
            self.assertEqual(usage.input_tokens, 100)
            self.assertEqual(usage.cached_input_tokens, 70)
            self.assertEqual(usage.output_tokens, 10)
            self.assertEqual(usage.reasoning_output_tokens, 2)

    def test_partial_trailing_line_is_consumed_once_after_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            event_text = json.dumps(token_event(last={"input_tokens": 10, "output_tokens": 2}))
            path.write_text(
                json.dumps({"type": "turn_context", "payload": {"model": "gpt-5.6-luna"}})
                + "\n"
                + event_text[:10],
                encoding="utf-8",
            )
            state = FileState()
            read_updates(path, state, "default")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(event_text[10:] + "\n")
            read_updates(path, state, "default")
            first = state.buckets[("gpt-5.6-luna", "default")].total_tokens
            read_updates(path, state, "default")
            second = state.buckets[("gpt-5.6-luna", "default")].total_tokens
            self.assertEqual(first, 12)
            self.assertEqual(second, 12)

    def test_summary_marks_unknown_models_as_partially_priced(self):
        state = FileState()
        state.buckets[("future-model", "default")] = __import__("token_usage").Usage(input_tokens=100)
        buckets, total, limits, timestamp = aggregate([state])
        data = summary_dict(
            "session",
            [],
            buckets,
            total,
            limits,
            timestamp,
            OFFICIAL_RATES,
            DEFAULT_DOLLARS_PER_CREDIT,
            "chatgpt",
        )
        self.assertFalse(data["estimate"]["fully_priced"])
        self.assertIsNone(data["models"][0]["estimated_usd"])

    def test_widget_summary_omits_unbounded_file_and_rate_details(self):
        state = FileState()
        state.buckets[("gpt-5.6-sol", "default")] = Usage(
            input_tokens=100,
            cached_input_tokens=80,
            output_tokens=10,
        )
        buckets, total, limits, timestamp = aggregate([state])
        data = summary_dict(
            "all",
            [Path(f"/rollout-{index}.jsonl") for index in range(1000)],
            buckets,
            total,
            limits,
            timestamp,
            OFFICIAL_RATES,
            DEFAULT_DOLLARS_PER_CREDIT,
            "chatgpt",
        )
        compact = widget_summary_dict(data)
        encoded = json.dumps(compact, separators=(",", ":"))
        self.assertNotIn("files", compact)
        self.assertNotIn("rate_credits_per_million", encoded)
        self.assertEqual(compact["tokens"]["total_tokens"], 110)
        self.assertLess(len(encoded), 2048)

    def test_session_id_selects_exact_parallel_rollout(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            sessions = home / "sessions" / "2026" / "07" / "17"
            sessions.mkdir(parents=True)
            wanted = sessions / "rollout-2026-07-17T00-00-00-thread-wanted.jsonl"
            other = sessions / "rollout-2026-07-17T00-00-01-thread-other.jsonl"
            wanted.write_text("{}\n", encoding="utf-8")
            other.write_text("{}\n", encoding="utf-8")
            self.assertEqual(select_files(home, "session", None, "thread-wanted"), [wanted])

    def test_all_scope_includes_active_and_archived_rollouts(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            active = home / "sessions" / "rollout-active.jsonl"
            archived = home / "archived_sessions" / "rollout-archived.jsonl"
            active.parent.mkdir(parents=True)
            archived.parent.mkdir(parents=True)
            active.write_text("{}\n", encoding="utf-8")
            archived.write_text("{}\n", encoding="utf-8")
            self.assertEqual(select_files(home, "all", None, None), [archived, active])

    def test_all_index_round_trip_preserves_numeric_usage_only(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            rollout = home / "sessions" / "rollout.jsonl"
            state = FileState(
                offset=123,
                current_model="gpt-5.6-sol",
                current_tier="fast",
                previous_total=Usage(input_tokens=20, output_tokens=2),
                have_previous_total=True,
                metadata_initialized=True,
                is_subagent=True,
                session_start_ms=1752710400000,
                accounting_started=True,
                latest_event_timestamp="2026-07-17T00:00:01Z",
            )
            state.buckets[("gpt-5.6-sol", "fast")] = Usage(
                input_tokens=20,
                cached_input_tokens=10,
                output_tokens=2,
            )
            save_all_index(home, {rollout: state}, "default")
            loaded = load_all_index(home, "default")
            self.assertEqual(loaded[rollout].offset, 123)
            self.assertEqual(loaded[rollout].buckets[("gpt-5.6-sol", "fast")].total_tokens, 22)
            self.assertTrue(loaded[rollout].is_subagent)
            self.assertEqual(loaded[rollout].session_start_ms, 1752710400000)
            cache_text = (home / "token-usage-meter" / INDEX_FILENAME).read_text()
            self.assertNotIn("conversation", cache_text)


if __name__ == "__main__":
    unittest.main()
