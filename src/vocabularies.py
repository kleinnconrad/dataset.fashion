"""
Loads the fixed lists of values (vocabularies) from ``config/vocabularies.toml``.

The lists are slowly changing dimensions: every value has the day from which
it is offered to Gemini (``added``) and, once it is no longer offered, the day
of its retirement (``retired``). Retired values stay in the file, so the file
documents which values were valid at any time. ``parent`` links a value to the
value of the same list that it refines, so that series can be summed up to the
earlier values after a value was split. ``category`` assigns each garment type
to a garment category.

``src/schema.py`` builds the response schema from the active values, so a
change of the file changes the extraction hash of the records that follow.
"""
import logging
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "vocabularies.toml"
# Lists whose entries carry a category, and the list the category refers to
CATEGORY_LISTS: dict[str, str] = {"garment_type": "garment_category"}
_ENTRY_KEYS = frozenset({"value", "added", "retired", "parent", "category"})


@dataclass(frozen=True)
class VocabularyValue:
    """One value of a list.

    Attributes:
        value (str): The value as offered to Gemini and stored in the records.
        added (date): First day on which the value is offered.
        retired (Optional[date]): First day on which the value is no longer offered; None while it is active.
        parent (Optional[str]): Value of the same list that this value refines.
        category (Optional[str]): Category of the value (garment types only).
    """
    value: str
    added: date
    retired: Optional[date] = None
    parent: Optional[str] = None
    category: Optional[str] = None

    @property
    def active(self) -> bool:
        """True while the value is offered to Gemini."""
        return self.retired is None


@dataclass(frozen=True)
class Vocabulary:
    """A list of values with its history.

    Attributes:
        name (str): Name of the list, e.g. ``hair_style_type``.
        entries (tuple[VocabularyValue, ...]): All values in the order of the file, including retired ones.
    """
    name: str
    entries: tuple[VocabularyValue, ...]

    @property
    def active(self) -> tuple[str, ...]:
        """The values that are offered to Gemini, in the order of the file."""
        return tuple(entry.value for entry in self.entries if entry.active)

    @property
    def all_values(self) -> tuple[str, ...]:
        """All values that were ever offered, including retired ones."""
        return tuple(entry.value for entry in self.entries)

    def get(self, value: str) -> Optional[VocabularyValue]:
        """Returns the entry of a value, or None if the list has no such value."""
        return next((entry for entry in self.entries if entry.value == value), None)


def _date(name: str, value: str, key: str, raw: Any, required: bool) -> Optional[date]:
    """Checks a date of an entry.

    Raises:
        ValueError: If the date is missing although required, or not a TOML date.
    """
    if raw is None:
        if required:
            raise ValueError(f"{name}: value {value!r} has no {key} date")
        return None
    if not isinstance(raw, date):
        raise ValueError(f"{name}: {key} of {value!r} must be a date (YYYY-MM-DD), not {raw!r}")
    return raw


def _entry(name: str, raw: Any) -> VocabularyValue:
    """Converts and checks one entry of a list.

    Raises:
        ValueError: If the entry has unknown keys, no value or invalid dates.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{name}: every value must be a table, not {raw!r}")
    unknown = set(raw) - _ENTRY_KEYS
    if unknown:
        raise ValueError(f"{name}: unknown keys {sorted(unknown)} in {raw!r}")
    value = raw.get("value")
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name}: invalid value {value!r}")
    added = _date(name, value, "added", raw.get("added"), required=True)
    retired = _date(name, value, "retired", raw.get("retired"), required=False)
    if added is None:
        raise ValueError(f"{name}: value {value!r} has no added date")
    if retired is not None and retired <= added:
        raise ValueError(f"{name}: {value!r} is retired on {retired}, not after it was added on {added}")
    for key in ("parent", "category"):
        if raw.get(key) is not None and not isinstance(raw[key], str):
            raise ValueError(f"{name}: {key} of {value!r} must be a string")
    return VocabularyValue(value=value, added=added, retired=retired, parent=raw.get("parent"),
                           category=raw.get("category"))


def parse_vocabularies(data: dict[str, Any]) -> dict[str, Vocabulary]:
    """Builds and checks the lists from the parsed TOML document.

    Args:
        data: The TOML document: one table per list with an array ``values``.

    Returns:
        dict[str, Vocabulary]: The lists by name, in the order of the file.

    Raises:
        ValueError: If a list is empty or has no active value, a value occurs twice, a parent is not a
            value of the same list, or a category is missing or unknown.
    """
    vocabularies: dict[str, Vocabulary] = {}
    for name, table in data.items():
        if not isinstance(table, dict) or set(table) != {"values"} or not isinstance(table["values"], list):
            raise ValueError(f"{name}: a list must be a table with one array 'values'")
        entries = tuple(_entry(name, raw) for raw in table["values"])
        values = [entry.value for entry in entries]
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise ValueError(f"{name}: values occur more than once: {duplicates}")
        if not any(entry.active for entry in entries):
            raise ValueError(f"{name}: the list has no active value")
        for entry in entries:
            if entry.parent is not None and (entry.parent == entry.value or entry.parent not in values):
                raise ValueError(f"{name}: parent {entry.parent!r} of {entry.value!r} is not another value of the list")
            if entry.category is not None and name not in CATEGORY_LISTS:
                raise ValueError(f"{name}: {entry.value!r} has a category, which only {sorted(CATEGORY_LISTS)} use")
        vocabularies[name] = Vocabulary(name=name, entries=entries)
    for name, category_list in CATEGORY_LISTS.items():
        if name not in vocabularies:
            continue
        if category_list not in vocabularies:
            raise ValueError(f"{name}: the category list {category_list} is missing")
        categories = vocabularies[category_list].all_values
        for entry in vocabularies[name].entries:
            if entry.category not in categories:
                raise ValueError(f"{name}: {entry.value!r} has no category of {category_list}: {entry.category!r}")
    return vocabularies


def load_vocabularies(path: Path = CONFIG_PATH) -> dict[str, Vocabulary]:
    """Reads and checks the lists.

    Args:
        path: The TOML file.

    Returns:
        dict[str, Vocabulary]: The lists by name.

    Raises:
        ValueError: If the file breaks a rule of ``parse_vocabularies``.
    """
    with path.open("rb") as handle:
        return parse_vocabularies(tomllib.load(handle))


def vocabulary_version(vocabularies: dict[str, Vocabulary]) -> date:
    """Returns the day of the latest change of the lists: the latest added or retired date.

    Args:
        vocabularies: The lists.

    Returns:
        date: The version of the lists.
    """
    return max(day for vocabulary in vocabularies.values() for entry in vocabulary.entries
               for day in (entry.added, entry.retired) if day is not None)


VOCABULARIES: dict[str, Vocabulary] = load_vocabularies()
