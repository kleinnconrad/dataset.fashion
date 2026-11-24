"""Tests for the weekly maintenance in src/discovery.py, with a fake search model and a fake web."""
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors, types

import discovery as discovery_module
from discovery import (
    SEARCH_REQUEST_TIMEOUT_MS,
    SEARCH_RETRY_ATTEMPTS,
    SEARCH_RETRY_INITIAL_DELAY_S,
    SEARCH_RETRY_STATUS_CODES,
    DeadlineReachedError,
    SearchAnswer,
    SearchModel,
    discover_sources,
    lookup_countries,
    parse_json_array,
    recheck_paused_sources,
    search_focuses,
    weekly_focus,
    weekly_maintenance,
)
from extraction import (
    CallBudgetExceededError,
    FatalRequestError,
    QuotaExhaustedError,
    TransientExtractionError,
    create_client,
)
from settings import DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_SEARCH_MODEL, Settings
from sources import SourceEntry, SourceRegistry
from state import RUN_LOG_FILE

TODAY = date(2026, 10, 11)


class FakeSearchModel:
    """Returns prepared answers in order and records the prompts.

    An answer is an exception to raise, a ``SearchAnswer``, a text, or a value sent as JSON text.
    """

    def __init__(self, answers: list[Any]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.calls = 0

    def ask(self, prompt: str) -> SearchAnswer:
        self.calls += 1
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, SearchAnswer):
            return answer
        return SearchAnswer(text=answer if isinstance(answer, str) else json.dumps(answer))


def entry(source_id: str, status: str = "active", **fields: Any) -> SourceEntry:
    """Builds a registry entry."""
    values: dict[str, Any] = {"source_id": source_id, "homepage": f"https://{source_id}/", "status": status,
                              "status_since": TODAY - timedelta(days=20), "origin": "legacy",
                              "added": TODAY - timedelta(days=20), "feed_url": f"https://{source_id}/feed/"}
    values.update(fields)
    return SourceEntry(**values)


def registry_with(tmp_path: Path, *entries: SourceEntry) -> SourceRegistry:
    """Builds a registry in a temporary folder."""
    registry = SourceRegistry.load(tmp_path)
    for item in entries:
        registry.put(item)
    return registry


def recent_feed(rss: Any, domain: str, days_ago: list[int]) -> bytes:
    """Builds a feed with posts ``days_ago`` before TODAY."""
    return rss([(f"Outfit {d}", f"https://{domain}/outfit-{d}/", TODAY - timedelta(days=d)) for d in days_ago])


@pytest.mark.parametrize(
    "text",
    ['[{"a": 1}]', 'Here you go:\n```json\n[{"a": 1}]\n```', 'Answer: [{"a": 1}] Hope this helps.'],
)
def test_parse_json_array(text: str) -> None:
    assert parse_json_array(text) == [{"a": 1}]


@pytest.mark.parametrize("text", ["No blogs found.", "[not json]", ""])
def test_parse_json_array_rejects_other_answers(text: str) -> None:
    with pytest.raises(ValueError):
        parse_json_array(text)


def test_focus_changes_every_week() -> None:
    monday = TODAY - timedelta(days=TODAY.weekday())
    assert weekly_focus(monday) == weekly_focus(monday + timedelta(days=6))
    assert weekly_focus(monday) != weekly_focus(monday + timedelta(days=7))


def test_country_lookup_sets_model_countries_once(tmp_path: Path) -> None:
    registry = registry_with(
        tmp_path,
        entry("alpha.example", country="US", country_basis="feed_language"),
        entry("beta.example", status="dormant"),
        entry("gamma.example", country="FR", country_basis="model"),
        entry("delta.example", status="rejected"),
    )
    model = FakeSearchModel([[
        {"domain": "alpha.example", "country": "gb", "language": "en"},
        {"domain": "www.beta.example", "country": "Germany", "language": "de"},
    ]])
    assert lookup_countries(registry, model, TODAY) == 1
    assert "gamma.example" not in model.prompts[0] and "delta.example" not in model.prompts[0]
    alpha, beta = registry.get("alpha.example"), registry.get("beta.example")
    assert (alpha.country, alpha.country_basis, alpha.language) == ("GB", "model", "en")
    # "Germany" is not an ISO code: the country stays unknown, but the lookup is recorded
    assert (beta.country, beta.country_basis, beta.language, beta.country_lookup) == (None, "unknown", "de", TODAY)
    assert lookup_countries(registry, FakeSearchModel([]), TODAY + timedelta(days=7)) == 0


def test_failed_lookup_is_retried_next_time(tmp_path: Path) -> None:
    registry = registry_with(tmp_path, entry("alpha.example"))
    lookup_countries(registry, FakeSearchModel(["Sorry, I cannot help."]), TODAY)
    assert registry.get("alpha.example").country_lookup is None


def test_discovery_admits_and_records_candidates(tmp_path: Path, web: Any, rss: Any) -> None:
    registry = registry_with(tmp_path, entry("known.example"))
    # The proposed post links the blog's feed
    web.add("https://new.example/2026/10/fall-look/",
            b'<html><head><link rel="alternate" type="application/rss+xml" href="/blog/feed/"></head></html>')
    web.add_feed("https://new.example/blog/feed/", recent_feed(rss, "new.example", [3, 10]))
    web.add("https://nofeed.example/", b"<html><body>Blog without feed</body></html>")
    model = FakeSearchModel([[
        {"post_url": "https://new.example/2026/10/fall-look/", "country": "SE", "language": "sv"},
        {"homepage": "https://www.known.example/", "country": "US"},
        {"homepage": "https://www.instagram.com/someone/"},
        {"homepage": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"},
        {"homepage": "https://nofeed.example/"},
        {"homepage": "not a url"},
    ]])
    summary = discover_sources(registry, model, TODAY, web, focuses=[weekly_focus(TODAY)])
    assert dict(summary) == {"probation": 1, "known": 1, "not a blog": 2, "rejected": 1, "invalid url": 1}
    new = registry.get("new.example")
    assert (new.status, new.origin, new.country, new.country_basis, new.language) == (
        "probation", "discovery", "SE", "model", "sv")
    assert (new.homepage, new.feed_url) == ("https://new.example/", "https://new.example/blog/feed/")
    assert registry.get("nofeed.example").note == "no feed found"
    assert "known.example" in model.prompts[0]
    assert "October 2026 or September 2026" in model.prompts[0]


def test_search_sources_are_candidates_without_a_list(tmp_path: Path, web: Any, rss: Any) -> None:
    registry = registry_with(tmp_path, entry("known.example"))
    web.add_feed("https://grounded.example/feed/", recent_feed(rss, "grounded.example", [2, 9]))
    answer = SearchAnswer(text="I could not find posts from these months.",
                          source_domains=("grounded.example", "vogue.com", "known.example"))
    summary = discover_sources(registry, FakeSearchModel([answer]), TODAY, web, focuses=[weekly_focus(TODAY)])
    assert dict(summary) == {"answer without list": 1, "from search sources": 3, "probation": 1,
                             "not a blog": 1, "known": 1}
    assert registry.get("grounded.example").country_basis != "model"


def test_source_domains_come_from_the_grounding_metadata() -> None:
    def chunk(title: Any) -> SimpleNamespace:
        return SimpleNamespace(web=SimpleNamespace(domain=None, title=title, uri="https://vertexaisearch.cloud.google.com/x"))

    metadata = SimpleNamespace(grounding_chunks=[chunk("WWW.Petite-Style.com"), chunk("My October outfits"),
                                                 chunk("petite-style.com"), SimpleNamespace(web=None), chunk(None)])
    response = SimpleNamespace(candidates=[SimpleNamespace(grounding_metadata=metadata)])
    assert discovery_module._source_domains(response) == ("petite-style.com",)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("gb", "GB"), ("UK", "GB"), ("EL", "GR"), ("Germany", None), ("U1", None), (None, None)],
)
def test_valid_country(answer: Any, expected: Any) -> None:
    assert discovery_module.valid_country(answer) == expected


def test_discovery_respects_the_weekly_limit(tmp_path: Path, web: Any, rss: Any,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery_module, "MAX_ADMISSIONS_PER_WEEK", 1)
    registry = registry_with(tmp_path)
    for name in ("one.example", "two.example"):
        web.add_feed(f"https://{name}/feed/", recent_feed(rss, name, [2, 5]))
    model = FakeSearchModel([[{"homepage": "https://one.example/"}, {"homepage": "https://two.example/"}]])
    summary = discover_sources(registry, model, TODAY, web)
    assert dict(summary) == {"probation": 1, "weekly limit reached": 1}
    assert "two.example" not in registry


def test_search_focuses_follow_the_focus_of_the_week() -> None:
    first = discovery_module.SEARCH_FOCUS.index(weekly_focus(TODAY))
    focuses = search_focuses(TODAY, 3)
    assert focuses[0] == weekly_focus(TODAY)
    assert focuses == [discovery_module.SEARCH_FOCUS[(first + n) % len(discovery_module.SEARCH_FOCUS)] for n in range(3)]
    assert len(set(search_focuses(TODAY, 50))) == len(discovery_module.SEARCH_FOCUS)


def test_discovery_continues_after_searches_without_blogs(tmp_path: Path, web: Any, rss: Any) -> None:
    registry = registry_with(tmp_path)
    web.add_feed("https://found.example/feed/", recent_feed(rss, "found.example", [2, 5]))
    model = FakeSearchModel(["No blogs found.", [{"post_url": "https://found.example/"}],
                             TransientExtractionError("busy")])
    log: list[dict[str, Any]] = []
    summary = discover_sources(registry, model, TODAY, web, focuses=["focus a", "focus b", "focus c"], search_log=log)
    assert dict(summary) == {"answer without list": 1, "probation": 1, "no answer": 1}
    assert log == [
        {"focus": "focus a", "answer": "No blogs found.", "candidates": 0, "admitted": []},
        {"focus": "focus b", "candidates": 1, "admitted": ["found.example"]},
        {"focus": "focus c", "error": "busy"},
    ]
    assert ["Focus: focus b." in prompt for prompt in model.prompts] == [False, True, False]
    # A blog found by an earlier search is excluded in the later prompts
    assert "found.example" not in model.prompts[1] and "found.example" in model.prompts[2]


def test_discovery_stops_at_the_weekly_limit_and_the_call_budget(tmp_path: Path, web: Any, rss: Any,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    web.add_feed("https://one.example/feed/", recent_feed(rss, "one.example", [2, 5]))
    monkeypatch.setattr(discovery_module, "MAX_ADMISSIONS_PER_WEEK", 1)
    model = FakeSearchModel([[{"post_url": "https://one.example/"}]])
    assert dict(discover_sources(registry_with(tmp_path), model, TODAY, web)) == {"probation": 1}
    assert model.calls == 1

    monkeypatch.setattr(discovery_module, "MAX_DISCOVERY_CALLS", 3)
    model = FakeSearchModel([[], []])
    model.calls = 1
    summary = discover_sources(registry_with(tmp_path / "other"), model, TODAY, web)
    assert dict(summary) == {"call budget reached": 1} and model.calls == 3


def test_discovery_is_skipped_when_the_registry_is_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery_module, "MAX_ADMITTED_SOURCES", 1)
    model = FakeSearchModel([])
    summary = discover_sources(registry_with(tmp_path, entry("a.example")), model, TODAY)
    assert dict(summary) == {"registry full": 1} and model.calls == 0


def test_paused_sources_return_when_they_publish_again(tmp_path: Path, web: Any, rss: Any) -> None:
    registry = registry_with(
        tmp_path,
        entry("sleepy.example", status="dormant", previous_status="active"),
        entry("flaky.example", status="broken", previous_status="probation", feed_url=None,
              consecutive_feed_failures=1),
        entry("quiet.example", status="dormant", previous_status="active"),
    )
    web.add_feed("https://sleepy.example/feed/", recent_feed(rss, "sleepy.example", [4, 12]))
    web.add_feed("https://flaky.example/feed/", recent_feed(rss, "flaky.example", [1, 2]))
    web.add_feed("https://quiet.example/feed/", recent_feed(rss, "quiet.example", [150]))
    changes = recheck_paused_sources(registry, TODAY, web)
    assert sorted(changes) == [("flaky.example", "broken", "probation"), ("sleepy.example", "dormant", "active")]
    assert registry.get("flaky.example").feed_url == "https://flaky.example/feed/"
    assert registry.get("quiet.example").status == "dormant"


def test_weekly_maintenance_saves_and_logs(tmp_path: Path, web: Any, rss: Any) -> None:
    settings = Settings(output_dir=tmp_path)
    registry_with(settings.state_dir, entry("alpha.example"), entry("beta.example", status="dormant")).save()
    web.add_feed("https://beta.example/feed/", recent_feed(rss, "beta.example", [200]))
    model = FakeSearchModel([[{"domain": "alpha.example", "country": "AU"}], [], [], [], []])
    summary = weekly_maintenance(settings, TODAY, model, web)
    assert summary["countries_set"] == 1 and summary["candidates"] == {} and summary["gemini_calls"] == 5
    assert [search["focus"] for search in summary["searches"]] == search_focuses(TODAY)
    assert summary["searches"][0] == {"focus": weekly_focus(TODAY), "candidates": 0, "admitted": [], "answer": "[]"}
    assert SourceRegistry.load(settings.state_dir).get("alpha.example").country == "AU"
    log = (settings.state_dir / RUN_LOG_FILE).read_text(encoding="utf-8").splitlines()
    assert json.loads(log[-1])["mode"] == "maintenance"


def test_quota_stop_keeps_the_rechecked_registry(tmp_path: Path, web: Any, rss: Any) -> None:
    settings = Settings(output_dir=tmp_path)
    registry_with(settings.state_dir, entry("sleepy.example", status="dormant", previous_status="active")).save()
    web.add_feed("https://sleepy.example/feed/", recent_feed(rss, "sleepy.example", [1, 3]))
    summary = weekly_maintenance(settings, TODAY, FakeSearchModel([QuotaExhaustedError("quota")]), web)
    assert summary["stopped_early"].startswith("QuotaExhaustedError") and not summary["fatal"]
    assert SourceRegistry.load(settings.state_dir).get("sleepy.example").status == "active"


class FakeClient:
    """Test double for genai.Client that raises a prepared error or returns a text."""

    def __init__(self, outcome: Any) -> None:
        self.models = SimpleNamespace(generate_content=self.generate_content)
        self.outcome = outcome
        self.configs: list[Any] = []
        self.model_ids: list[str] = []

    def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.configs.append(config)
        self.model_ids.append(model)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return SimpleNamespace(text=self.outcome)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}),
         QuotaExhaustedError),
        (errors.ClientError(400, {"error": {"code": 400, "message": "bad", "status": "INVALID_ARGUMENT"}}),
         FatalRequestError),
        (errors.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}}),
         TransientExtractionError),
    ],
)
def test_search_model_maps_api_errors(outcome: Exception, expected: type) -> None:
    model = SearchModel(Settings(), client=FakeClient(outcome), sleep=lambda s: None)
    with pytest.raises(expected):
        model.ask("prompt")


def test_search_model_call_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery_module, "MAX_DISCOVERY_CALLS", 1)
    sleeps: list[float] = []
    model = SearchModel(Settings(), client=FakeClient("[]"), sleep=sleeps.append)
    assert model.ask("prompt") == SearchAnswer(text="[]")
    with pytest.raises(CallBudgetExceededError):
        model.ask("prompt")
    assert sleeps == []


def test_search_model_sets_a_thinking_level_and_no_temperature() -> None:
    client = FakeClient("[]")
    SearchModel(Settings(), client=client, sleep=lambda s: None).ask("prompt")

    assert client.configs[0].thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
    assert client.configs[0].temperature is None


class TimedFakeSearchModel(FakeSearchModel):
    """FakeSearchModel that reports a fixed duration per request, like SearchModel."""

    def __init__(self, answers: list[Any], seconds: float) -> None:
        super().__init__(answers)
        self.model = "fake-model"
        self.durations: list[float] = []
        self.seconds = seconds

    @property
    def last_seconds(self) -> Any:
        return self.durations[-1] if self.durations else None

    def ask(self, prompt: str) -> SearchAnswer:
        self.durations.append(self.seconds)
        return super().ask(prompt)


class SlowClient(FakeClient):
    """FakeClient whose requests advance a clock."""

    def __init__(self, outcome: Any, now: list[float], seconds: float) -> None:
        super().__init__(outcome)
        self.now = now
        self.seconds = seconds

    def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.now[0] += self.seconds
        return super().generate_content(model=model, contents=contents, config=config)


def test_search_model_starts_no_request_after_the_time_budget() -> None:
    now = [0.0]
    model = SearchModel(Settings(), client=SlowClient("[]", now, 250.0), sleep=lambda s: None,
                        clock=lambda: now[0], deadline_s=600)

    model.ask("first")
    model.ask("second")
    model.ask("third")
    with pytest.raises(DeadlineReachedError, match="time budget of 10 minutes used up"):
        model.ask("fourth")

    assert model.calls == 3 and model.durations == [250.0, 250.0, 250.0] and model.last_seconds == 250.0


def test_search_model_records_the_duration_of_failed_requests() -> None:
    now = [0.0]
    error = errors.ServerError(504, {"error": {"code": 504, "message": "Deadline", "status": "DEADLINE_EXCEEDED"}})
    model = SearchModel(Settings(), client=SlowClient(error, now, 300.0), sleep=lambda s: None, clock=lambda: now[0])

    with pytest.raises(TransientExtractionError):
        model.ask("prompt")

    assert model.durations == [300.0]


def test_search_requests_use_the_search_model() -> None:
    client = FakeClient("[]")
    model = SearchModel(Settings(gemini_model="extraction-model", gemini_search_model="search-model"), client=client,
                        sleep=lambda s: None)

    model.ask("prompt")

    assert model.model == "search-model" and client.model_ids == ["search-model"]


def test_the_search_model_is_set_separately_from_the_extraction_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_SEARCH_MODEL", raising=False)
    assert (Settings.from_env().gemini_model, Settings.from_env().gemini_search_model) == (
        DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_SEARCH_MODEL) == ("gemini-3.8-flash", "gemini-3.5-flash-lite")

    monkeypatch.setenv("GEMINI_SEARCH_MODEL", " other-model ")
    assert Settings.from_env().gemini_search_model == "other-model"
    assert Settings.from_env().gemini_model == DEFAULT_GEMINI_MODEL


def test_overloaded_responses_are_retried_but_not_the_server_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(discovery_module, "create_client", lambda **kwargs: calls.append(kwargs) or FakeClient("[]"))

    SearchModel(Settings())

    assert calls == [{"attempts": SEARCH_RETRY_ATTEMPTS, "status_codes": SEARCH_RETRY_STATUS_CODES,
                      "initial_delay_s": SEARCH_RETRY_INITIAL_DELAY_S, "timeout_ms": SEARCH_REQUEST_TIMEOUT_MS}]
    assert 503 in SEARCH_RETRY_STATUS_CODES and 504 not in SEARCH_RETRY_STATUS_CODES
    # The client timeout lies above the server deadline of five minutes
    assert SEARCH_REQUEST_TIMEOUT_MS > 300_000


def test_the_client_applies_the_retry_rules() -> None:
    client = create_client(api_key="test-key", attempts=SEARCH_RETRY_ATTEMPTS, status_codes=SEARCH_RETRY_STATUS_CODES,
                           initial_delay_s=SEARCH_RETRY_INITIAL_DELAY_S, timeout_ms=SEARCH_REQUEST_TIMEOUT_MS)

    options = client._api_client._http_options
    assert options.timeout == SEARCH_REQUEST_TIMEOUT_MS
    assert options.retry_options.attempts == SEARCH_RETRY_ATTEMPTS
    assert options.retry_options.http_status_codes == list(SEARCH_RETRY_STATUS_CODES)
    assert options.retry_options.initial_delay == SEARCH_RETRY_INITIAL_DELAY_S


def test_time_budget_stops_the_maintenance_and_keeps_its_progress(tmp_path: Path, web: Any, rss: Any) -> None:
    settings = Settings(output_dir=tmp_path)
    registry_with(settings.state_dir, entry("sleepy.example", status="dormant", previous_status="active")).save()
    web.add_feed("https://sleepy.example/feed/", recent_feed(rss, "sleepy.example", [1, 3]))
    model = FakeSearchModel([[], DeadlineReachedError("time budget used up")])

    summary = weekly_maintenance(settings, TODAY, model, web)

    assert summary["stopped_early"].startswith("DeadlineReachedError") and not summary["fatal"]
    assert len(summary["searches"]) == 1
    assert SourceRegistry.load(settings.state_dir).get("sleepy.example").status == "active"
    log = (settings.state_dir / RUN_LOG_FILE).read_text(encoding="utf-8").splitlines()
    assert json.loads(log[-1])["stopped_early"].startswith("DeadlineReachedError")


def test_run_log_records_the_duration_of_every_request(tmp_path: Path, web: Any) -> None:
    settings = Settings(output_dir=tmp_path)
    registry_with(settings.state_dir, entry("alpha.example")).save()
    model = TimedFakeSearchModel([[{"domain": "alpha.example", "country": "AU"}], [], [], [], []], seconds=240.0)


    summary = weekly_maintenance(settings, TODAY, model, web)

    assert summary["gemini_model"] == "fake-model"
    assert summary["gemini_seconds"] == [240.0] * 5
    assert [search["seconds"] for search in summary["searches"]] == [240.0] * 4
