"""Tests of the monthly vocabulary review with a fake research model."""
import json
import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pytest

import vocabulary_review as review_module
from discovery import SearchAnswer
from extraction import QuotaExhaustedError, clean_unlisted_values
from schema import UnlistedValue
from vocabularies import CONFIG_PATH, VOCABULARIES, parse_vocabularies
from vocabulary_review import (
    LIST_GROUPS,
    MIN_DATA_OUTFITS,
    Addition,
    DataSignals,
    ReviewResult,
    add_to_change_log,
    add_to_vocabularies,
    build_prompt,
    build_report,
    collect_signals,
    dominant_values,
    research,
    review,
    unused_values,
)

TODAY = date(2026, 12, 1)
README = Path(__file__).resolve().parents[1] / "README.md"


def record(source: str, number: int, hair: str = "Down", unlisted: Optional[list[dict[str, str]]] = None,
           aesthetic_other: Optional[str] = None, garments: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """A schema 2.1 record with the fields the review reads."""
    return {
        "schema_version": "2.1", "source_id": source, "post_url": f"https://{source}/post-{number}",
        "hair_style_type": hair, "hair_finish": "Natural", "aesthetic_tags": [], "aesthetic_other": aesthetic_other,
        "unlisted_values": unlisted or [],
        "garments": garments or [{"garment_type": "Jeans", "primary_color": "Blue", "design_details": ["Pockets"]}],
    }


class FakeModel:
    """Returns a fixed answer per group of lists and counts the requests."""

    def __init__(self, answers: dict[str, list[dict[str, Any]]], fail_after: Optional[int] = None) -> None:
        self.answers = answers
        self.prompts: list[str] = []
        self.fail_after = fail_after

    def ask(self, prompt: str) -> SearchAnswer:
        if self.fail_after is not None and len(self.prompts) >= self.fail_after:
            raise QuotaExhaustedError("quota exhausted")
        self.prompts.append(prompt)
        group = next(name for name in LIST_GROUPS if f"({name})" in prompt)
        return SearchAnswer(text=json.dumps(self.answers.get(group, [])), source_domains=("vogue.com",))


SOURCES = ["https://www.vogue.com/article/space-buns", "https://www.elle.com/hair/space-buns"]


def test_signals_count_values_and_terms_named_as_missing() -> None:
    records = [record(f"blog{i % 4}.com", i, unlisted=[{"field": "hair_style_type", "value": "Space  buns"}])
               for i in range(12)]
    records.append(record("blog9.com", 99, aesthetic_other="Indie sleaze", garments=[
        {"garment_type": "Other", "description": "Kilt", "primary_color": "Green", "design_details": []}]))

    signals = collect_signals(records)

    assert signals.records == 13
    assert signals.usage["hair_style_type"]["Down"] == 13
    assert signals.usage["base_color"] == {"Blue": 12, "Green": 1}
    assert signals.usage["design_detail"]["Pockets"] == 12
    space_buns = signals.unlisted["hair_style_type"]["space buns"]
    assert (space_buns.term, space_buns.outfits, len(space_buns.sources)) == ("Space buns", 12, 4)
    assert len(space_buns.examples) == 3
    assert signals.unlisted["aesthetic_tag"]["indie sleaze"].outfits == 1
    assert signals.unlisted["garment_type"]["kilt"].outfits == 1
    assert [stats.term for stats in signals.frequent_terms("hair_style_type")] == ["Space buns"]
    assert signals.frequent_terms("aesthetic_tag") == []


def test_frequent_terms_need_enough_outfits_and_blogs() -> None:
    few_blogs = collect_signals([record("one.com", i, unlisted=[{"field": "material", "value": "Mesh"}])
                                 for i in range(MIN_DATA_OUTFITS + 5)])
    assert few_blogs.frequent_terms("material") == []


def test_dominant_and_unused_values() -> None:
    signals = collect_signals([record(f"b{i}.com", i, hair="Down" if i < 45 else "Braid") for i in range(60)])

    assert dominant_values(signals, "hair_style_type") == [("Down", 0.75)]
    unused = unused_values(signals, VOCABULARIES["hair_style_type"], date(2026, 11, 1))
    assert "Ponytail" in unused and "Down" not in unused and "Not visible" not in unused
    assert unused_values(signals, VOCABULARIES["hair_style_type"], date(2026, 10, 1)) == []


def test_prompt_names_the_lists_values_and_data_hints() -> None:
    signals = collect_signals([record(f"blog{i % 4}.com", i, unlisted=[{"field": "hair_style_type",
                                                                         "value": "Space buns"}]) for i in range(60)])

    prompt = build_prompt("hair and makeup", LIST_GROUPS["hair and makeup"], VOCABULARIES, signals, TODAY)

    assert "hair_style_type (used by hair_style_type: How the hair is worn.)" in prompt
    assert "Values: Down; Ponytail; Bun/Updo" in prompt
    assert "Space buns (60 outfits, 4 blogs)" in prompt
    assert "the value 'Down' covers 100% of the outfits" in prompt
    assert "Today is 2026-12-01" in prompt


def test_research_keeps_valid_proposals_and_rejects_the_others() -> None:
    model = FakeModel({
        "hair and makeup": [
            {"list": "hair_style_type", "action": "add", "value": "Space buns", "parent": "Bun/Updo",
             "reason": "Two high buns.", "sources": SOURCES},
            {"list": "hair_style_type", "action": "add", "value": "down", "sources": SOURCES},
            {"list": "hair_style_type", "action": "add", "value": "Bubble braid", "sources": [SOURCES[0]]},
            {"list": "hair_finish", "action": "retire", "value": "Wet look", "reason": "Rare.", "sources": SOURCES},
            {"list": "hair_finish", "action": "retire", "value": "Glossy", "sources": SOURCES},
            {"list": "makeup_style", "action": "add", "value": "Latte makeup", "parent": "Glam", "sources": SOURCES},
            {"list": "material", "action": "add", "value": "Mesh", "sources": SOURCES},
        ],
        "garment types": [
            {"list": "garment_type", "action": "add", "value": "Kilt", "sources": SOURCES},
            {"list": "garment_type", "action": "add", "value": "Balaclava", "category": "Headwear",
             "reason": "Knitted hood.", "sources": SOURCES},
        ],
    })
    signals = collect_signals([record("a.com", 1, unlisted=[{"field": "hair_style_type", "value": "Space buns"}])])
    result = ReviewResult()

    research(model, VOCABULARIES, signals, TODAY, result)

    assert len(model.prompts) == len(LIST_GROUPS) == result.research_requests
    assert [(a.list_name, a.value, a.parent, a.category, a.data_outfits) for a in result.additions] == [
        ("garment_type", "Balaclava", None, "Headwear", 0),
        ("hair_style_type", "Space buns", "Bun/Updo", None, 1),
    ]
    assert [(p.list, p.value) for p in result.retirements] == [("hair_finish", "Wet look")]
    reasons = {proposal.value: reason for proposal, reason in result.rejected}
    assert reasons == {
        "down": "already in the list",
        "Bubble braid": "sources from 1 domains, 2 required",
        "Glossy": "'Glossy' is not an active value",
        "Latte makeup": "parent 'Glam' is not an active value",
        "Mesh": "unknown list 'material'",
        "Kilt": "garment category None is not an active category",
    }


def test_a_quota_error_ends_the_research_with_what_was_found() -> None:
    model = FakeModel({}, fail_after=2)
    result = ReviewResult()

    research(model, VOCABULARIES, DataSignals(), TODAY, result)

    assert result.research_requests == 2
    assert result.research_error is not None and "quota exhausted" in result.research_error


def test_additions_are_appended_to_their_lists_and_the_change_log() -> None:
    additions = [
        Addition("hair_style_type", "Space buns", "Bun/Updo", None, "Two high buns.", tuple(SOURCES), 12),
        Addition("garment_type", "Balaclava", None, "Headwear", "Knitted hood.", tuple(SOURCES)),
    ]

    vocabularies = parse_vocabularies(tomllib.loads(
        add_to_vocabularies(CONFIG_PATH.read_text(encoding="utf-8"), additions, TODAY)))
    readme = add_to_change_log(README.read_text(encoding="utf-8"), additions, TODAY)

    hair = vocabularies["hair_style_type"]
    assert hair.active[-1] == "Space buns" and hair.active[:-1] == VOCABULARIES["hair_style_type"].active
    assert (hair.get("Space buns").added, hair.get("Space buns").parent) == (TODAY, "Bun/Updo")
    assert vocabularies["garment_type"].get("Balaclava").category == "Headwear"
    log = readme[readme.index("| Date | List | Change |"):].split("\n\n")[0].split("\n")
    assert log[-2:] == [
        '| 2026-12-01 | `hair_style_type` | Added "Space buns" (refines Bun/Updo): Two high buns. |',
        '| 2026-12-01 | `garment_type` | Added "Balaclava": Knitted hood. |',
    ]


def test_report_lists_additions_retirements_terms_and_usage(tmp_path: Path) -> None:
    records = [record(f"blog{i % 4}.com", i, unlisted=[{"field": "material", "value": "Mesh"}]) for i in range(60)]
    model = FakeModel({"hair and makeup": [
        {"list": "hair_style_type", "action": "add", "value": "Space buns", "parent": "Bun/Updo",
         "reason": "Two high buns.", "sources": SOURCES},
        {"list": "hair_finish", "action": "retire", "value": "Wet look", "reason": "Rare.", "sources": SOURCES},
    ]})
    day_dir = tmp_path / "2026" / "11"
    day_dir.mkdir(parents=True)
    (day_dir / "fashion_analytics_2026-11-20.json").write_text(json.dumps(records), encoding="utf-8")
    (day_dir / "fashion_analytics_2026-08-01.json").write_text(json.dumps([record("old.com", 1)]), encoding="utf-8")

    result, signals = review(tmp_path, TODAY, model)
    report = build_report(result, signals, VOCABULARIES, TODAY, research_enabled=True)

    assert signals.records == 60
    assert "Reviewed 26 lists against 60 records of 2026-09-02 to 2026-12-01; 5 research requests" in report
    assert "| `hair_style_type` | Space buns | Bun/Updo | Two high buns. | [vogue.com](" in report
    assert "| `hair_finish` | Wet look | Rare. |" in report
    assert "| `material` | Mesh | 60 | 4 |" in report
    assert "- `hair_style_type`: Down covers 100% of the observations" in report


def test_main_without_research_writes_only_the_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, readme = tmp_path / "vocabularies.toml", tmp_path / "README.md"
    config.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    readme.write_text(README.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(review_module, "CONFIG_PATH", config)
    monkeypatch.setattr(review_module, "README_PATH", readme)
    (tmp_path / "data").mkdir()

    code = review_module.main(["--report", str(tmp_path / "report.md"), "--data-dir", str(tmp_path / "data"),
                               "--no-research"])

    assert code == 0
    assert "research turned off" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert config.read_text(encoding="utf-8") == CONFIG_PATH.read_text(encoding="utf-8")


def test_unlisted_values_are_cleaned() -> None:
    values = [UnlistedValue(field="hair_style_type", value=value) for value in
              ("Space buns", " space buns ", "Ponytail", "", "x" * 61)]
    values.append(UnlistedValue(field="material", value="Mesh"))

    cleaned = clean_unlisted_values(values)

    assert [(item.field, item.value) for item in cleaned] == [("hair_style_type", "Space buns"), ("material", "Mesh")]
