"""
Monthly review of the fixed lists of values (``config/vocabularies.toml``).

The review checks whether the lists are up to date, from two independent sources:

1. Research: Gemini with Google Search checks each reviewed list against the
   current fashion vocabulary. It proposes established or emerging terms that
   are missing, and values that are no longer in use. Gemini classifies every
   outfit with the closest listed value, so terms that the lists lack do not
   show up in the data by themselves; the research looks for them outside the
   data. Each proposal must name at least MIN_RESEARCH_SOURCES sources from
   different domains.
2. Data: the records of the last LOOKBACK_DAYS. The terms that Gemini named as
   missing (``unlisted_values``), aesthetics outside the list
   (``aesthetic_other``) and descriptions of garments of the type "Other" are
   counted per outfit and source and given to the research as hints. The
   share of each value shows values that dominate their list (candidates for
   a split), values without use (candidates for retirement) and the share of
   the catch-all values "Other" and "Unclear".

The review adds the valid research proposals to ``config/vocabularies.toml``
(``added`` is the day of the review; ``parent`` where a value refines another)
and a line per change to the change log in ``README.md``, and writes a report
in Markdown. Retirements and splits are reported only and carried out by hand.
The workflow ``vocabulary_review.yml`` opens a pull request with the changes and
the report; nothing changes until it is merged.
"""
import argparse
import json
import logging
import sys
import tomllib
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel

from discovery import SearchModel, parse_answers
from extraction import RunStopError, TransientExtractionError
from schema import REVIEWED_LISTS, VOCABULARY_OF_FIELD, Garment, OutfitAttributes
from settings import Settings
from storage import load_day
from vocabularies import CONFIG_PATH, VOCABULARIES, Vocabulary, parse_vocabularies

logger = logging.getLogger(__name__)

README_PATH = Path(__file__).resolve().parents[1] / "README.md"
# Records of this many days before the review are evaluated
LOOKBACK_DAYS = 90
# A term named as missing is reported once it occurs in this many outfits of this many sources
MIN_DATA_OUTFITS = 10
MIN_DATA_SOURCES = 3
# A research proposal needs sources from this many different domains
MIN_RESEARCH_SOURCES = 2
MAX_PROPOSALS_PER_LIST = 3
MAX_VALUE_CHARS = 40
# A value with this share of the observations of its list is reported as a candidate for a split
DOMINANT_SHARE = 0.6
MIN_OBSERVATIONS = 50
# No research request is started after this time, so that the pull request is opened before the workflow timeout
REVIEW_DEADLINE_MINUTES = 20
# Values that mark absence; they are left out of the shares
ABSENCE_VALUES = frozenset({"Not visible", "Not applicable"})
CATCH_ALL_VALUES = ("Other", "Other jacket", "Unclear")
# Lists sent to the research in one request each
LIST_GROUPS: dict[str, tuple[str, ...]] = {
    "garment types": ("garment_type",),
    "colors, patterns, materials and surface details": ("base_color", "pattern", "material", "finish", "design_detail"),
    "cut and fit": ("fit", "length", "neckline", "rise", "leg_shape", "overall_fit", "silhouette"),
    "styles, aesthetics, color strategies, occasions and settings": (
        "style_category", "aesthetic_tag", "color_palette_type", "color_contrast_strategy", "occasion", "setting"),
    "hair and makeup": ("hair_length", "hair_texture", "hair_style_type", "hair_color", "hair_parting",
                        "hair_finish", "makeup_style"),
}
RESEARCH_PROMPT = """\
You maintain the fixed lists of values of a dataset of outfits from personal style blogs worldwide. Gemini \
classifies every outfit photo with one value of each list. The dataset is collected for many years, so the lists \
must contain the terms that are established in fashion today and the terms that are clearly emerging, and the \
lists are reviewed every month. Today is {today}.

Check these lists ({group}) with Google Search:
{lists}

Propose changes only where a list is out of date:
- "add": a term that the list lacks and that is established in fashion writing of the last 24 months or clearly \
emerging in the last 12 months, for example in fashion magazines, trend reports or retailer category pages.
- "retire": a value that is no longer in use or that duplicates another value of the list.

Rules for new values:
- The value must be identifiable in outfit photos and must not overlap with an existing value; it is not a brand.
- Write it in the style of the list (capitalization, alternatives with a slash), in at most four words.
- If the value refines an existing value (the existing value stays), give that value as "parent".
- For garment types, give the garment category as "category", one of: {categories}.
- Name at least {min_sources} sources from different websites that use the term, as full URLs.
- At most {max_per_list} proposals per list. Propose nothing for lists that are up to date.
{hints}
Return only a JSON array, without other text, or [] if all lists are up to date:
[{{"list": "list name", "action": "add", "value": "New value", "parent": null, "category": null, \
"reason": "one sentence", "sources": ["https://...", "https://..."]}}]"""


class Proposal(BaseModel):
    """A change of a list proposed by the research."""
    list: str
    action: str
    value: str
    parent: Optional[str] = None
    category: Optional[str] = None
    reason: str = ""
    sources: list[str] = []


@dataclass
class TermStats:
    """A term named as missing from a list in the records.

    Attributes:
        spellings (Counter): Spellings of the term with their counts.
        outfits (int): Outfits that name the term.
        sources (set[str]): Sources of these outfits.
        examples (list[str]): Post URLs of up to three outfits.
    """
    spellings: Counter[str] = field(default_factory=Counter)
    outfits: int = 0
    sources: set[str] = field(default_factory=set)
    examples: list[str] = field(default_factory=list)

    @property
    def term(self) -> str:
        """The most common spelling."""
        return self.spellings.most_common(1)[0][0]


@dataclass
class DataSignals:
    """Evidence from the records of the review window.

    Attributes:
        records (int): Schema 2.x records in the window.
        usage (dict): Observations per value, per list.
        unlisted (dict): Terms named as missing, per list, keyed by the normalized term.
    """
    records: int = 0
    usage: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    unlisted: dict[str, dict[str, TermStats]] = field(default_factory=lambda: defaultdict(dict))

    def frequent_terms(self, list_name: str) -> list[TermStats]:
        """Terms of a list that reach MIN_DATA_OUTFITS and MIN_DATA_SOURCES, most frequent first."""
        terms = [stats for stats in self.unlisted.get(list_name, {}).values()
                 if stats.outfits >= MIN_DATA_OUTFITS and len(stats.sources) >= MIN_DATA_SOURCES]
        return sorted(terms, key=lambda stats: (-stats.outfits, stats.term))

    def top_terms(self, list_name: str, count: int = 10) -> list[TermStats]:
        """The most frequent terms of a list, whatever their count."""
        return sorted(self.unlisted.get(list_name, {}).values(), key=lambda stats: (-stats.outfits, stats.term))[:count]


@dataclass(frozen=True)
class Addition:
    """A value that the review adds to a list.

    Attributes:
        list_name (str): The list.
        value (str): The new value.
        parent (Optional[str]): Value of the list that the new value refines.
        category (Optional[str]): Garment category (garment types only).
        reason (str): Reason given by the research.
        sources (tuple[str, ...]): Source URLs.
        data_outfits (int): Outfits in the window that name the term as missing.
    """
    list_name: str
    value: str
    parent: Optional[str]
    category: Optional[str]
    reason: str
    sources: tuple[str, ...]
    data_outfits: int = 0


@dataclass
class ReviewResult:
    """Outcome of a review.

    Attributes:
        additions (list[Addition]): Values added to the lists.
        retirements (list[Proposal]): Proposed retirements (reported only).
        rejected (list[tuple[Proposal, str]]): Research proposals that failed a rule, with the reason.
        research_requests (int): Requests sent to Gemini.
        research_error (Optional[str]): Why the research stopped early, if it did.
        research_model (Optional[str]): Gemini model id of the research, if known.
        research_seconds (list[float]): Seconds per research request, including failed ones.
    """
    additions: list[Addition] = field(default_factory=list)
    retirements: list[Proposal] = field(default_factory=list)
    rejected: list[tuple[Proposal, str]] = field(default_factory=list)
    research_requests: int = 0
    research_error: Optional[str] = None
    research_model: Optional[str] = None
    research_seconds: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data signals
# ---------------------------------------------------------------------------

def normalize_term(term: str) -> str:
    """Returns the key of a term: case-folded, with single spaces."""
    return " ".join(term.casefold().split())


def _values(container: dict[str, Any], name: str) -> list[str]:
    """Returns the value(s) of a field as a list; lists such as design_details are flattened."""
    value = container.get(name)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return [value] if isinstance(value, str) else []


def load_window(data_dir: Path, today: date, days: int = LOOKBACK_DAYS) -> list[dict[str, Any]]:
    """Reads the schema 2.x records of the files of the last ``days`` days.

    Args:
        data_dir: Root folder of the dataset (``YYYY/MM/fashion_analytics_YYYY-MM-DD.json``).
        today: Day of the review.
        days: Length of the window.

    Returns:
        list[dict]: The records; legacy records (schema 1.x) are left out.
    """
    start = today - timedelta(days=days)
    records: list[dict[str, Any]] = []
    for path in sorted(data_dir.glob("*/*/fashion_analytics_*.json")):
        try:
            day = date.fromisoformat(path.stem.rsplit("_", 1)[-1])
        except ValueError:
            continue
        if start <= day <= today:
            records.extend(record for record in load_day(path) if "schema_version" in record)
    return records


def collect_signals(records: Iterable[dict[str, Any]]) -> DataSignals:
    """Counts the values of the reviewed lists and the terms named as missing.

    Args:
        records: Schema 2.x records.

    Returns:
        DataSignals: The counts.
    """
    signals = DataSignals()
    outfit_fields = [name for name, list_name in VOCABULARY_OF_FIELD.items() if name in OutfitAttributes.model_fields
                     and name not in Garment.model_fields]
    garment_fields = [name for name in VOCABULARY_OF_FIELD if name in Garment.model_fields]

    def note(list_name: str, term: Optional[str], record: dict[str, Any], seen: set[tuple[str, str]]) -> None:
        if not isinstance(term, str) or not term.strip():
            return
        key = normalize_term(term)
        stats = signals.unlisted[list_name].setdefault(key, TermStats())
        stats.spellings[" ".join(term.split())] += 1
        if (list_name, key) in seen:
            return
        seen.add((list_name, key))
        stats.outfits += 1
        stats.sources.add(str(record.get("source_id")))
        if len(stats.examples) < 3 and record.get("post_url"):
            stats.examples.append(str(record["post_url"]))

    for record in records:
        signals.records += 1
        for name in outfit_fields:
            signals.usage[VOCABULARY_OF_FIELD[name]].update(_values(record, name))
        signals.usage["aesthetic_tag"].update(_values(record, "aesthetic_tags"))
        seen: set[tuple[str, str]] = set()
        for garment in record.get("garments") or []:
            for name in garment_fields:
                signals.usage[VOCABULARY_OF_FIELD[name]].update(_values(garment, name))
            if garment.get("garment_type") == "Other":
                note("garment_type", garment.get("description"), record, seen)
        for item in record.get("unlisted_values") or []:
            if isinstance(item, dict) and item.get("field") in VOCABULARY_OF_FIELD:
                note(VOCABULARY_OF_FIELD[item["field"]], item.get("value"), record, seen)
        note("aesthetic_tag", record.get("aesthetic_other"), record, seen)
    return signals


def dominant_values(signals: DataSignals, list_name: str) -> list[tuple[str, float]]:
    """Values with at least DOMINANT_SHARE of the observations of a list (absence values left out)."""
    counts = {value: count for value, count in signals.usage.get(list_name, Counter()).items()
              if value not in ABSENCE_VALUES}
    total = sum(counts.values())
    if total < MIN_OBSERVATIONS:
        return []
    return [(value, count / total) for value, count in counts.items() if count / total >= DOMINANT_SHARE]


def unused_values(signals: DataSignals, vocabulary: Vocabulary, window_start: date) -> list[str]:
    """Active values without any observation, among the values added before the window started."""
    used = signals.usage.get(vocabulary.name, Counter())
    return [entry.value for entry in vocabulary.entries
            if entry.active and entry.added <= window_start and not used.get(entry.value)
            and entry.value not in ABSENCE_VALUES]


def catch_all_shares(signals: DataSignals, list_name: str) -> list[tuple[str, float]]:
    """Shares of the catch-all values of a list."""
    counts = signals.usage.get(list_name, Counter())
    total = sum(count for value, count in counts.items() if value not in ABSENCE_VALUES)
    return [(value, counts[value] / total) for value in CATCH_ALL_VALUES if total and counts.get(value)]


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------

def _field_descriptions(list_name: str) -> str:
    """Names the fields that use a list, with their descriptions."""
    names = [name for name, used in VOCABULARY_OF_FIELD.items() if used == list_name]
    if list_name == "aesthetic_tag":
        names = ["aesthetic_tags"]
    parts = []
    for name in names:
        info = Garment.model_fields.get(name) or OutfitAttributes.model_fields.get(name)
        parts.append(f"{name}: {info.description}" if info is not None else name)
    return "; ".join(parts)


def build_prompt(group: str, list_names: Sequence[str], vocabularies: dict[str, Vocabulary],
                 signals: DataSignals, today: date) -> str:
    """Builds the research prompt of a group of lists.

    Args:
        group: Name of the group.
        list_names: The lists of the group.
        vocabularies: All lists.
        signals: Evidence from the records, given as hints.
        today: Day of the review.

    Returns:
        str: The prompt.
    """
    blocks, hints = [], []
    for name in list_names:
        vocabulary = vocabularies[name]
        if name == "garment_type":
            values = "; ".join(f"{entry.value} ({entry.category})" for entry in vocabulary.entries if entry.active)
        else:
            values = "; ".join(vocabulary.active)
        blocks.append(f"- {name} (used by {_field_descriptions(name)})\n  Values: {values}")
        terms = signals.top_terms(name)
        if terms:
            hints.append(f"- {name}: " + ", ".join(f"{stats.term} ({stats.outfits} outfits, {len(stats.sources)} "
                                                   f"blogs)" for stats in terms))
        for value, share in dominant_values(signals, name):
            hints.append(f"- {name}: the value {value!r} covers {share:.0%} of the outfits; consider values that "
                         f"refine it (with it as parent).")
    hint_text = ""
    if hints:
        hint_text = ("\nHints from the dataset of the last {days} days (terms that Gemini named as missing, and "
                     "values that cover most outfits). Check them like other candidates:\n").format(days=LOOKBACK_DAYS)
        hint_text += "\n".join(hints) + "\n"
    return RESEARCH_PROMPT.format(
        today=today.isoformat(), group=group, lists="\n".join(blocks), hints=hint_text,
        categories=", ".join(vocabularies["garment_category"].active), min_sources=MIN_RESEARCH_SOURCES,
        max_per_list=MAX_PROPOSALS_PER_LIST,
    )


def _domain(url: str) -> Optional[str]:
    """Returns the host of a URL without www., or None for anything that is not an http(s) URL."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts.hostname.lower().removeprefix("www.")


def check_proposal(proposal: Proposal, allowed_lists: Sequence[str],
                   vocabularies: dict[str, Vocabulary]) -> Optional[str]:
    """Checks a research proposal against the rules of the lists.

    Args:
        proposal: The proposal.
        allowed_lists: Lists of the request that returned the proposal.
        vocabularies: All lists.

    Returns:
        Optional[str]: The reason for rejecting the proposal, or None if it is valid.
    """
    if proposal.list not in allowed_lists:
        return f"unknown list {proposal.list!r}"
    vocabulary = vocabularies[proposal.list]
    value = " ".join(proposal.value.split())
    known = {entry.value.casefold(): entry for entry in vocabulary.entries}
    if proposal.action == "retire":
        entry = known.get(value.casefold())
        return None if entry is not None and entry.active else f"{value!r} is not an active value"
    if proposal.action != "add":
        return f"unknown action {proposal.action!r}"
    if not value or len(value) > MAX_VALUE_CHARS:
        return "empty or too long value"
    if value.casefold() in known:
        entry = known[value.casefold()]
        return "already in the list" if entry.active else f"retired on {entry.retired}; values are not reused"
    if proposal.parent is not None and proposal.parent not in vocabulary.active:
        return f"parent {proposal.parent!r} is not an active value"
    if proposal.list == "garment_type" and proposal.category not in vocabularies["garment_category"].active:
        return f"garment category {proposal.category!r} is not an active category"
    domains = {domain for domain in map(_domain, proposal.sources) if domain}
    if len(domains) < MIN_RESEARCH_SOURCES:
        return f"sources from {len(domains)} domains, {MIN_RESEARCH_SOURCES} required"
    return None


def research(model: Any, vocabularies: dict[str, Vocabulary], signals: DataSignals, today: date,
             result: ReviewResult) -> None:
    """Asks Gemini with Google Search whether the reviewed lists are up to date, one request per group.

    Valid additions and retirements are added to ``result``; proposals that break a rule are kept as rejected.
    A quota or API error ends the research; the review continues with what was found.

    Args:
        model: A ``SearchModel`` or a test double with ``ask(prompt)``.
        vocabularies: All lists.
        signals: Evidence from the records.
        today: Day of the review.
        result: The review result, updated in place.
    """
    for group, list_names in LIST_GROUPS.items():
        prompt = build_prompt(group, list_names, vocabularies, signals, today)
        try:
            answer = model.ask(prompt)
        except (RunStopError, TransientExtractionError) as e:
            result.research_error = f"{group}: {e}"
            logger.error("Vocabulary research stopped at %s: %s", group, e)
            return
        result.research_requests += 1
        try:
            proposals = parse_answers(answer.text, Proposal)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("Vocabulary research for %s returned no valid JSON array: %s", group, e)
            continue
        per_list: Counter[str] = Counter()
        added: set[tuple[str, str]] = set()
        for proposal in proposals:
            reason = check_proposal(proposal, list_names, vocabularies)
            if reason is None and per_list[proposal.list] >= MAX_PROPOSALS_PER_LIST:
                reason = f"more than {MAX_PROPOSALS_PER_LIST} proposals for the list"
            value = " ".join(proposal.value.split())
            if reason is None and proposal.action == "add" and (proposal.list, value.casefold()) in added:
                reason = "proposed twice"
            if reason is not None:
                result.rejected.append((proposal, reason))
                continue
            per_list[proposal.list] += 1
            if proposal.action == "retire":
                result.retirements.append(proposal)
                continue
            added.add((proposal.list, value.casefold()))
            stats = signals.unlisted.get(proposal.list, {}).get(normalize_term(value))
            result.additions.append(Addition(
                list_name=proposal.list, value=value, parent=proposal.parent,
                category=proposal.category if proposal.list == "garment_type" else None,
                reason=" ".join(proposal.reason.split()), sources=tuple(proposal.sources),
                data_outfits=stats.outfits if stats else 0,
            ))
        logger.info("Vocabulary research for %s: %d proposals, %d valid.", group, len(proposals),
                    sum(per_list.values()))


# ---------------------------------------------------------------------------
# Changes of the files
# ---------------------------------------------------------------------------

def add_to_vocabularies(text: str, additions: Sequence[Addition], today: date) -> str:
    """Appends the new values to their lists in the text of ``config/vocabularies.toml``.

    Args:
        text: The file content.
        additions: The values to add.
        today: Day of the review, used as ``added``.

    Returns:
        str: The new content, checked with the rules of ``parse_vocabularies``.

    Raises:
        ValueError: If a list is not found or the result breaks a rule.
    """
    lines = text.split("\n")
    for addition in additions:
        try:
            header = lines.index(f"[{addition.list_name}]")
            end = next(index for index in range(header + 1, len(lines)) if lines[index] == "]")
        except (ValueError, StopIteration) as e:
            raise ValueError(f"list {addition.list_name} not found in the vocabulary file") from e
        parts = [f"value = {json.dumps(addition.value, ensure_ascii=False)}"]
        if addition.category is not None:
            parts.append(f"category = {json.dumps(addition.category, ensure_ascii=False)}")
        parts.append(f"added = {today.isoformat()}")
        if addition.parent is not None:
            parts.append(f"parent = {json.dumps(addition.parent, ensure_ascii=False)}")
        lines.insert(end, "    { " + ", ".join(parts) + " },")
    new_text = "\n".join(lines)
    parse_vocabularies(tomllib.loads(new_text))
    return new_text


def add_to_change_log(text: str, additions: Sequence[Addition], today: date) -> str:
    """Appends one line per new value to the change log table of the lists in ``README.md``.

    Args:
        text: The README content.
        additions: The values added.
        today: Day of the review.

    Returns:
        str: The new content.

    Raises:
        ValueError: If the README has no change log table.
    """
    lines = text.split("\n")
    try:
        header = lines.index("| Date | List | Change |")
    except ValueError as e:
        raise ValueError("README.md has no change log of the lists") from e
    end = header + 2
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    rows = []
    for addition in additions:
        refines = f" (refines {addition.parent})" if addition.parent else ""
        reason = addition.reason.replace("|", "/")
        rows.append(f"| {today.isoformat()} | `{addition.list_name}` | Added \"{addition.value}\"{refines}: {reason} |")
    return "\n".join(lines[:end] + rows + lines[end:])


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _cell(text: str) -> str:
    """Escapes a table cell."""
    return " ".join(str(text).replace("|", "/").split())


def build_report(result: ReviewResult, signals: DataSignals, vocabularies: dict[str, Vocabulary],
                 today: date, research_enabled: bool) -> str:
    """Builds the Markdown report of a review.

    Args:
        result: The review result.
        signals: Evidence from the records.
        vocabularies: The lists before the review.
        today: Day of the review.
        research_enabled: False if the review ran without research.

    Returns:
        str: The report.
    """
    window_start = today - timedelta(days=LOOKBACK_DAYS)
    lines = [f"# Vocabulary review {today:%Y-%m}", ""]
    research_state = (f"{result.research_requests} research requests with Google Search" if research_enabled
                      else "research turned off")
    details = [f"`{result.research_model}`"] if result.research_model else []
    if result.research_seconds:
        details.append("seconds per request: " + ", ".join(f"{seconds:g}" for seconds in result.research_seconds))
    if research_enabled and details:
        research_state += f" ({'; '.join(details)})"
    if result.research_error:
        research_state += f"; the research stopped early ({_cell(result.research_error)})"
    lines.append(f"Reviewed {len(REVIEWED_LISTS)} lists against {signals.records} records of "
                 f"{window_start} to {today}; {research_state}.")
    lines += ["", "## Proposed additions", ""]
    if result.additions:
        lines += ["These values are added to `config/vocabularies.toml` and the change log in this pull request. "
                  "To leave one out, remove its entry and its change log line before merging.", "",
                  "| List | Value | Refines | Reason | Sources | Outfits naming it |", "|---|---|---|---|---|---|"]
        for addition in result.additions:
            sources = ", ".join(f"[{_domain(url) or 'link'}]({url})" for url in addition.sources[:4])
            lines.append(f"| `{addition.list_name}` | {_cell(addition.value)} | {_cell(addition.parent or '')} | "
                         f"{_cell(addition.reason)} | {sources} | {addition.data_outfits} |")
    else:
        lines.append("None.")
    lines += ["", "## Proposed retirements (not applied)", ""]
    if result.retirements:
        lines += ["Retire a value by hand: set `retired` to the day from which it is no longer offered, and add a "
                  "line to the change log.", "", "| List | Value | Reason | Sources |", "|---|---|---|---|"]
        for proposal in result.retirements:
            sources = ", ".join(f"[{_domain(url) or 'link'}]({url})" for url in proposal.sources[:4])
            lines.append(f"| `{proposal.list}` | {_cell(proposal.value)} | {_cell(proposal.reason)} | {sources} |")
    else:
        lines.append("None.")
    lines += ["", "## Terms named as missing in the data", "",
              f"Terms with at least {MIN_DATA_OUTFITS} outfits from {MIN_DATA_SOURCES} blogs that the research "
              "did not add; add them by hand if they belong in the list.", ""]
    added = {(addition.list_name, normalize_term(addition.value)) for addition in result.additions}
    frequent = [(name, stats) for name in REVIEWED_LISTS for stats in signals.frequent_terms(name)
                if (name, normalize_term(stats.term)) not in added]
    if frequent:
        lines += ["| List | Term | Outfits | Blogs | Examples |", "|---|---|---|---|---|"]
        for name, stats in frequent:
            examples = ", ".join(f"[post]({url})" for url in stats.examples)
            lines.append(f"| `{name}` | {_cell(stats.term)} | {stats.outfits} | {len(stats.sources)} | {examples} |")
    else:
        lines.append("None.")
    lines += ["", "## Usage of the values", ""]
    usage_lines = []
    for name in REVIEWED_LISTS:
        for value, share in dominant_values(signals, name):
            usage_lines.append(f"- `{name}`: {_cell(value)} covers {share:.0%} of the observations; a split into "
                               f"more specific values (with it as parent) would make the list more informative.")
        for value, share in catch_all_shares(signals, name):
            if share >= 0.05:
                usage_lines.append(f"- `{name}`: the catch-all value {_cell(value)} covers {share:.0%} of the "
                                   f"observations.")
        unused = unused_values(signals, vocabularies[name], window_start) if signals.records else []
        if unused:
            usage_lines.append(f"- `{name}`: no observation in the window for {', '.join(map(_cell, unused))}.")
    lines += usage_lines or ["No value dominates its list, and every value was observed."]
    if result.rejected:
        lines += ["", "## Research proposals that failed a rule", "", "| List | Action | Value | Reason |",
                  "|---|---|---|---|"]
        for proposal, reason in result.rejected:
            lines.append(f"| `{_cell(proposal.list)}` | {_cell(proposal.action)} | {_cell(proposal.value)} | "
                         f"{_cell(reason)} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def review(data_dir: Path, today: date, model: Optional[Any], vocabularies: dict[str, Vocabulary] = VOCABULARIES,
           ) -> tuple[ReviewResult, DataSignals]:
    """Collects the data signals and, if a model is given, runs the research.

    Args:
        data_dir: Root folder of the dataset.
        today: Day of the review.
        model: A ``SearchModel``, or None to review without research.
        vocabularies: The lists.

    Returns:
        tuple: The review result and the data signals.
    """
    signals = collect_signals(load_window(data_dir, today))
    result = ReviewResult()
    if model is not None:
        result.research_model = getattr(model, "model", None)
        research(model, vocabularies, signals, today, result)
        result.research_seconds = list(getattr(model, "durations", []))
    return result, signals


def main(argv: Optional[list[str]] = None) -> int:
    """Runs the monthly review once and updates the vocabulary file and the change log.

    Args:
        argv: Arguments without the program name; None reads ``sys.argv``.

    Returns:
        int: 0 on success, 1 if the research stopped early, 2 if the API key is missing.
    """
    parser = argparse.ArgumentParser(description="Monthly review of the fixed lists of values.")
    parser.add_argument("--report", type=Path, required=True, help="file for the Markdown report")
    parser.add_argument("--data-dir", type=Path, help="root folder of the records (default: the dataset folder)")
    parser.add_argument("--no-research", action="store_true", help="review the data only, without Gemini")
    args = parser.parse_args(argv)
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    settings = Settings.from_env()
    today = datetime.now(timezone.utc).date()
    model = None
    if not args.no_research:
        try:
            model = SearchModel(settings, deadline_s=REVIEW_DEADLINE_MINUTES * 60)
        except ValueError as e:
            logger.error("Cannot start the vocabulary research: %s", e)
            return 2
    result, signals = review(args.data_dir or settings.output_dir, today, model)
    if result.additions:
        CONFIG_PATH.write_text(add_to_vocabularies(CONFIG_PATH.read_text(encoding="utf-8"), result.additions, today),
                               encoding="utf-8")
        README_PATH.write_text(add_to_change_log(README_PATH.read_text(encoding="utf-8"), result.additions, today),
                               encoding="utf-8")
    args.report.write_text(build_report(result, signals, VOCABULARIES, today, model is not None), encoding="utf-8")
    logger.info("Vocabulary review: %d additions, %d retirements proposed, %d proposals rejected.",
                len(result.additions), len(result.retirements), len(result.rejected))
    return 1 if result.research_error else 0


if __name__ == "__main__":
    sys.exit(main())
