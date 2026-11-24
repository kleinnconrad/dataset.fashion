"""Tests of the vocabulary file and its rules."""
import typing
from datetime import date
from typing import Any

import pytest

import schema
from vocabularies import VOCABULARIES, parse_vocabularies, vocabulary_version


def document(*entries: dict[str, Any], **lists: list[dict[str, Any]]) -> dict[str, Any]:
    """A TOML document with a list 'demo' of the given entries and further lists."""
    return {"demo": {"values": list(entries)}, **{name: {"values": values} for name, values in lists.items()}}


def test_repository_lists_build_the_schema() -> None:
    assert len(VOCABULARIES) == 35
    assert typing.get_args(schema.HairStyleType) == VOCABULARIES["hair_style_type"].active
    assert typing.get_args(schema.BaseColor) == VOCABULARIES["base_color"].active
    assert typing.get_args(schema.SecondaryColor) == (*VOCABULARIES["base_color"].active, "Not applicable")
    types = [entry.value for entry in VOCABULARIES["garment_type"].entries if entry.active]
    assert list(schema.GARMENT_CATEGORY_BY_TYPE) == types
    assert tuple(schema.GARMENT_TYPES_BY_CATEGORY) == VOCABULARIES["garment_category"].active


def test_every_value_of_schema_2_0_is_dated_from_its_first_records() -> None:
    entries = [entry for vocabulary in VOCABULARIES.values() for entry in vocabulary.entries]
    assert len(entries) == 352
    assert {entry.added for entry in entries} == {date(2026, 10, 11)}
    assert vocabulary_version(VOCABULARIES) == date(2026, 10, 11)


def test_retired_values_stay_in_the_list_but_are_not_offered() -> None:
    vocabularies = parse_vocabularies(document(
        {"value": "Down", "added": date(2026, 10, 11)},
        {"value": "Covered", "added": date(2026, 10, 11), "retired": date(2026, 12, 1)},
        {"value": "Headscarf", "added": date(2026, 12, 1), "parent": "Covered"},
    ))

    demo = vocabularies["demo"]
    assert demo.active == ("Down", "Headscarf")
    assert demo.all_values == ("Down", "Covered", "Headscarf")
    assert demo.get("Covered").retired == date(2026, 12, 1)
    assert demo.get("Headscarf").parent == "Covered"
    assert vocabulary_version(vocabularies) == date(2026, 12, 1)


@pytest.mark.parametrize("entries", [
    [{"value": "A", "added": date(2026, 10, 11)}, {"value": "A", "added": date(2026, 11, 1)}],
    [{"value": "A"}],
    [{"value": "A", "added": "2026-10-11"}],
    [{"value": "A", "added": date(2026, 10, 11), "retired": date(2026, 10, 11)}],
    [{"value": "A", "added": date(2026, 10, 11), "retired": date(2026, 11, 1)}],
    [{"value": "A", "added": date(2026, 10, 11), "parent": "B"}],
    [{"value": "A", "added": date(2026, 10, 11), "parent": "A"}],
    [{"value": "A", "added": date(2026, 10, 11), "note": "unknown key"}],
    [{"value": " A", "added": date(2026, 10, 11)}],
    [{"value": "A", "added": date(2026, 10, 11), "category": "Top"}],
])
def test_entries_that_break_a_rule_are_rejected(entries: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        parse_vocabularies(document(*entries))


def test_garment_types_need_a_known_category() -> None:
    categories = [{"value": "Top", "added": date(2026, 10, 11)}]
    valid = {"value": "T-shirt", "category": "Top", "added": date(2026, 10, 11)}
    assert parse_vocabularies({"garment_category": {"values": categories},
                               "garment_type": {"values": [valid]}})["garment_type"].get("T-shirt").category == "Top"
    for invalid in ({"value": "T-shirt", "added": date(2026, 10, 11)},
                    {"value": "T-shirt", "category": "Bottom", "added": date(2026, 10, 11)}):
        with pytest.raises(ValueError):
            parse_vocabularies({"garment_category": {"values": categories}, "garment_type": {"values": [invalid]}})
