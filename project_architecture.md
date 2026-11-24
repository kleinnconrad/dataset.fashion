# Fashion Analytics Pipeline Architecture

This document describes the structure of the pipeline: the directory layout, the pipeline run and the weekly run, and how failures are handled. The modules are described in [src/README.md](src/README.md).

## Table of Contents
- [1. Directory Structure](#1-directory-structure)
- [2. Pipeline Run](#2-pipeline-run)
- [3. Weekly Run](#3-weekly-run)
- [4. Monthly Vocabulary Review](#4-monthly-vocabulary-review)
- [5. Failure Handling](#5-failure-handling)
- [6. Setup Steps](#6-setup-steps)

---

## 1. Directory Structure

```text
dataset.fashion/
├── .github/
│   ├── dependabot.yml
│   └── workflows/
│       ├── ci.yml                  # lint, tests, commit messages
│       ├── daily_scraper.yml       # pipeline run, Tuesdays and Fridays 02:07 Europe/Berlin
│       ├── email_notify.yml        # commit comment after data commits
│       ├── source_discovery.yml    # weekly maintenance, Sundays 12:00 UTC
│       └── vocabulary_review.yml   # review of the fixed lists, first day of every month
├── config/
│   └── vocabularies.toml           # fixed lists of values with their history
├── data/
│   ├── YYYY/MM/fashion_analytics_YYYY-MM-DD.json   # records of one UTC day
│   └── state/                      # sources.json, posts.json, images.json, run_log.jsonl
├── scripts/
│   └── try_extraction.py           # manual evaluation of the extraction
├── src/                            # pipeline modules
├── tests/                          # offline unit and integration tests, fixtures
├── pyproject.toml
├── uv.lock
└── README.md
```

---

## 2. Pipeline Run

`src/main.py` starts the run; `src/pipeline.py` executes it.

1. Load the source registry. If it is empty, seed it from the domains of the legacy records.
2. Fetch the feeds of the active and probation sources and update their feed statistics.
3. Select the posts: published within 30 days, not yet processed or due for a retry, not about clearly unrelated topics; at most 3 per source, 40 per run and 10 from sources on probation; a post in the feeds of two sources once. After each source's oldest post, sources with a higher recent yield come first, and sources whose recent yield is below 50% get no further post.
4. For each post:
   1. Take the content from the feed if it includes images, else render the page with crawl4ai.
   2. Select the article element and extract text, image candidates, links and the canonical URL.
   3. Skip the post if it was already processed under its canonical URL, or if it is republished. Leave out images that were uploaded more than 12 months before the publish date.
   4. Download the image candidates, filter them by size and shape, and remove duplicates by dHash.
   5. Send all images and the post text to Gemini in one request.
   6. Build the records, without outfits of minors, and merge them into the day file.
   7. Save the post state, the image state and the source registry.
5. Give up pending posts older than 30 days, apply the source lifecycle rules (including one source per feed), save, and append a line to the run log.
6. The workflow updates the README overview and commits `data/` and `README.md`.

---

## 3. Weekly Run

`src/discovery.py` maintains the registry:

1. Fetch the feeds of dormant and broken sources and apply the lifecycle rules, so that sources that publish again return.
2. Ask Gemini with Google Search for the country and language of sources whose country was so far inferred only from the domain or the feed language (20 domains per request).
3. Ask Gemini with Google Search for new personal style blogs, in up to 4 searches with successive focuses, starting with the focus of the week. A search without results does not end the discovery. Evaluate each candidate with the admission rules and store it with its status; at most 10 are admitted per week, and the searches end once that number is reached.

The requests with Google Search use `gemini-3.5-flash-lite` (`GEMINI_SEARCH_MODEL`), not the extraction model: in November 2026, `gemini-3.8-flash` took two to five minutes per grounded request and often rejected requests for high demand, while `gemini-3.5-flash-lite` answered in 20 to 60 seconds. The thinking level is set to `MEDIUM`, as lower levels can end the searches early.

A request ends at the latest at the server deadline of the Gemini API (five minutes). An overloaded model (503) or a gateway error is retried after about 10 and 20 seconds (`SEARCH_RETRY_ATTEMPTS`, `SEARCH_RETRY_STATUS_CODES`); a request that ran into the server deadline (504) is not retried, as the retry would take as long again. The client timeout of 5.5 minutes lies above the server deadline, because the SDK retries client timeouts in any case. After 20 minutes (`MAINTENANCE_DEADLINE_MINUTES`) no further request is started; the run stops with `stopped_early` in the run log and keeps what it found. The run log records the model (`gemini_model`) and the seconds of every request (`gemini_seconds`, and `seconds` per search).

The workflow commits `data/state/`; its timeout of 45 minutes leaves room for a request that started just before the time budget ran out.

---

## 4. Monthly Vocabulary Review

`src/vocabulary_review.py` checks whether the fixed lists in `config/vocabularies.toml` are up to date (see the README, section Vocabularies):

1. Read the schema 2.x records of the last 90 days and count, per reviewed list, the observations of each value and the terms that Gemini named as missing (`unlisted_values`, `aesthetic_other`, descriptions of garments of the type "Other"), per outfit and blog.
2. Ask Gemini with Google Search, in one request per group of lists, for missing established or emerging terms and for values that are no longer in use, with the data as hints. Check each proposal: known list and action, no existing or retired value, an active parent, a garment category for garment types, sources from at least two domains, at most three proposals per list.
3. Append the valid additions to their lists (`added` = day of the review) and to the change log in the README, and write the report: additions, proposed retirements, frequent unlisted terms that were not added, dominant and unused values, shares of the catch-all values, and the rejected proposals.

The research uses the search model and the retry rules of the weekly run (section 3). After 20 minutes (`REVIEW_DEADLINE_MINUTES`) no further request is started; the report names the model and the seconds of every request.

The workflow opens or updates a pull request on the branch `vocabulary-review`, which is rebuilt every month, and starts the CI workflow on it. A quota or API error or the time budget ends the research; the pull request is opened with what was found, and the workflow fails visibly. Its timeout of 45 minutes leaves room for a request that started just before the time budget ran out.

---

## 5. Failure Handling

- **One post fails:** the post stays pending and is retried in later runs. Failures that concern the post itself (missing page, unusable model response) count as attempts; after 3 attempts the post is given up. Server errors, rate limits and quota errors do not count.
- **Quota or call budget reached:** extraction stops; all processed posts are saved.
- **Gemini rejects the request** (for example an invalid API key): the run stops, saves its progress and exits with code 1, so that the workflow fails visibly.
- **Run interrupted** between writing records and writing state: the next run processes the post again and replaces its earlier records.
- **Blocked or invalid model response:** the images are split into two requests; images of a failed half are not marked as analyzed.
- **Concurrent pushes:** both data workflows share a concurrency group, pull with rebase and retry the push up to three times.

---

## 6. Setup Steps

1. Add the `GEMINI_API_KEY` repository secret under **Settings > Secrets and variables > Actions**. For local runs, set it in a `.env` file.
2. Allow workflows to push to the repository under **Settings > Actions > General > Workflow permissions**, and allow GitHub Actions to create and approve pull requests (vocabulary review).
3. For local runs, install the browser once: `uv run playwright install chromium`.
