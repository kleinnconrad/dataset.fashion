# Fashion Analytics Scraper
[![CI](https://github.com/kleinnconrad/style_dataset/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/kleinnconrad/style_dataset/actions/workflows/ci.yml)

A fashion analytics pipeline that runs twice a week (Tuesdays and Fridays) in GitHub Actions. It reads the RSS feeds of personal style blogs, renders new posts with `crawl4ai`, describes the outfits in their photos with Google Gemini (`gemini-2.5-flash`) and stores one record per outfit in this repository. A weekly job finds new blogs and maintains the list of sources without manual curation.

## Table of Contents
- [Dataset Overview](#dataset-overview)
- [Pipeline Architecture](#pipeline-architecture)
- [Sources and Post Selection](#sources-and-post-selection)
- [Source Lifecycle](#source-lifecycle)
- [Record Schema 2.0](#record-schema-20)
- [Data and State Files](#data-and-state-files)
- [Workflows](#workflows)
- [Configuration](#configuration)
- [Running Locally](#running-locally)
- [Dependency Management](#dependency-management)
- [Continuous Integration](#continuous-integration)
- [Setup](#setup)

## Dataset Overview
<!-- DATASET_OVERVIEW_START -->
**Last updated:** 2026-10-13 07:03 UTC

- **Schema 2.0 records:** 281 outfits from 51 posts of 25 sources, published 2026-09-11 to 2026-10-07
- **Images reused across posts:** 0
- **Legacy records (schema 1.x):** 1,457 records in 119 files (2026-06-14 to 2026-10-10); collected without deduplication and without publish dates, and not included in the tables below
- **Sources:** 24 active, 18 probation, 74 dormant, 7 broken, 34 rejected, 0 retired

**Active sources** (posts processed since admission)

| Source | Country | Posts | Posts with outfits | Last post |
|---|---|---|---|---|
| reneeruin.com | AU | 5 | 100.0% (5) | 2026-10-10 |
| sewliberated.com | US | 5 | 80.0% (4) | 2026-10-04 |
| thefashiontag.com | GB | 5 | 80.0% (4) | 2026-10-12 |
| awellstyledlife.com | US | 4 | 100.0% (4) | 2026-10-12 |
| midlifechic.com | GB | 4 | 50.0% (2) | 2026-10-09 |
| pumpsandpushups.com | US | 4 | 100.0% (4) | 2026-10-09 |
| youlookfab.com | US | 4 | 25.0% (1) | 2026-10-12 |
| russh.com | AU | 3 | 100.0% (3) | 2026-10-07 |
| thewelldressedlife.com | US | 3 | 100.0% (3) | 2026-10-01 |
| cellajane.com | US | 2 | 100.0% (2) | 2026-09-30 |
| livinginyellow.com | US | 2 | 50.0% (1) | 2026-10-10 |
| loverlygrey.com | US | 2 | 100.0% (2) | 2026-10-07 |
| nofearoffashion.com | NL | 2 | 100.0% (2) | 2026-10-10 |
| theoutfitrepeater.com | US | 2 | 100.0% (2) | 2026-09-22 |
| unefemme.net | US | 2 | 100.0% (2) | 2026-10-08 |
| beauticurve.com | US | 1 | 100.0% (1) | 2026-10-01 |
| caphillstyle.com | US | 1 | 100.0% (1) | 2026-10-09 |
| capitolhillstyle.com | US | 1 | 100.0% (1) | 2026-10-09 |
| phyrra.net | NL | 1 | 0.0% (0) | 2026-10-06 |
| poplinstyle.com | US | 1 | 100.0% (1) | 2026-09-11 |
| fashionjackson.com | US | 0 | 0.0% (0) | 2026-09-17 |
| lemonstripes.com | US | 0 | 0.0% (0) | 2026-09-24 |
| lovemaegan.com | US | 0 | 0.0% (0) | 2026-09-27 |
| vstyleblog.com | US | 0 | 0.0% (0) | 2026-10-12 |

**Fields (schema 2.0)**

| Field | Description | Known values | Distinct values |
|---|---|---|---|
| `framing` | Widest view of the person among the images of this outfit. | 100.0% (281) | 4 |
| `photo_context` | Who is shown: the blogger or another private person, models in a brand campaign or catalog image, or an editorial or street-style photo. | 94.7% (266) | 3 |
| `gender` | Perceived gender presentation of the person. | 100.0% (281) | 2 |
| `age_group` | Visually estimated age bracket of the person. | 100.0% (281) | 2 |
| `style_category` | Primary style of the outfit. | 100.0% (281) | 12 |
| `style_detail` | Refinement of the style in a few words, e.g. 'Relaxed weekend minimalism'. Null if not needed. | 68.3% (192) | 155 |
| `aesthetic_tags` | Named aesthetics or micro-trends that the outfit clearly represents. Empty list if none. | 13.5% (38) | 13 |
| `aesthetic_other` | A clearly represented aesthetic that is not in the list, in one to three words. Null if none. | 12.5% (35) | 15 |
| `focal_garment_index` | Position (starting at 1) in the garments list of the piece that draws the eye most. Null if no piece stands out. | 92.9% (261) | 5 |
| `layering_complexity` | Number of visible clothing layers on the upper body, from 1 (single layer) to 5 (heavy layering). | 100.0% (281) | 3 |
| `overall_fit` | Overall fit of the outfit. | 100.0% (281) | 4 |
| `silhouette` | Overall outline of the outfit. | 90.4% (254) | 7 |
| `color_palette_type` | Overall color character of the outfit. | 98.9% (278) | 5 |
| `color_contrast_strategy` | How the colors of the outfit are combined. | 98.2% (276) | 5 |
| `occasion` | Most likely occasion the outfit is meant for. 'Unclear' if the images and text give no indication. | 86.5% (243) | 5 |
| `setting` | Setting or background of the photos. | 99.6% (280) | 3 |
| `season` | Season suggested by the clothing and the surroundings. 'Unclear' if they give no indication. | 69.0% (194) | 4 |
| `weather` | Weather visible in the photos. 'Not visible' for indoor photos and whenever sky or conditions cannot be seen. | 23.5% (66) | 2 |
| `hair_length` | Hair length of the person. | 92.2% (259) | 4 |
| `hair_texture` | Hair texture of the person. | 91.5% (257) | 4 |
| `hair_style_type` | How the hair is worn. | 93.6% (263) | 7 |
| `hair_color` | Hair color of the person. | 91.5% (257) | 7 |
| `hair_parting` | How the hair is parted. | 90.0% (253) | 4 |
| `hair_finish` | Styling finish of the hair. | 91.5% (257) | 4 |
| `makeup_style` | Makeup style of the person. | 92.2% (259) | 3 |
| `brand_mentions` | Brands of this outfit that are named in the post title, text, tags, image captions or link texts. Do not infer brands from appearance. Empty list if none. | 48.8% (137) | 63 |
| `price_segment` | Price segment suggested by the named brands or the text. 'Unknown' without such evidence. | 23.8% (67) | 3 |
| `record_id` | Stable id derived from the post URL, the image hashes and the position of the outfit in the post. | 100.0% (281) | 281 |
| `schema_version` | Version of the record schema. | 100.0% (281) | 1 |
| `model` | Gemini model that produced the record. | 100.0% (281) | 1 |
| `extraction_hash` | Hash of the prompt, response schema, model settings and image preprocessing. Records with the same hash were extracted under the same conditions. | 100.0% (281) | 1 |
| `date_scraped` | UTC date of the extraction (YYYY-MM-DD). | 100.0% (281) | 2 |
| `published_date` | Publish date of the post from its feed (YYYY-MM-DD). | 100.0% (281) | 22 |
| `source_id` | Domain of the blog, without www. | 100.0% (281) | 25 |
| `source_country` | ISO 3166-1 alpha-2 country of the blog. Null if unknown. | 97.2% (273) | 4 |
| `source_country_basis` | How the country was determined: model (Gemini with web search), domain (country-code top-level domain), feed_language (region of the RSS language tag) or unknown. | 100.0% (281) | 3 |
| `source_region` | Region derived from source_country. | 97.2% (273) | 3 |
| `source_language` | Language of the blog from its feed (ISO 639-1). | 100.0% (281) | 1 |
| `post_url` | URL of the post. | 100.0% (281) | 51 |
| `canonical_url` | Canonical URL declared by the post page. | 62.3% (175) | 26 |
| `post_title` | Title of the post. | 100.0% (281) | 51 |
| `post_tags` | Categories and tags of the post from its feed. | 98.2% (276) | 183 |
| `shopping_link_count` | Number of links to shops or affiliate networks in the post. | 100.0% (281) | 16 |
| `outfit_colors` | Primary colors of the clothing and footwear, in the order of the garments list. | 100.0% (281) | 21 |

**Garments**

| Category | Items | Outfits with this category |
|---|---|---|
| Top | 205 | 65.8% (185) |
| Bottom | 186 | 65.5% (184) |
| Dress/One-piece | 75 | 26.7% (75) |
| Outerwear | 71 | 24.9% (70) |
| Footwear | 199 | 70.8% (199) |
| Bag | 102 | 36.3% (102) |
| Headwear | 15 | 5.3% (15) |
| Eyewear | 36 | 12.8% (36) |
| Jewelry | 183 | 41.6% (117) |
| Belt | 38 | 13.5% (38) |
| Scarf/Neckwear | 18 | 6.4% (18) |
| Hair accessory | 10 | 3.6% (10) |
| Hosiery | 28 | 9.6% (27) |
| Other | 39 | 11.0% (31) |

Most frequent garment types: Dress (74), Trousers (66), Jeans (58), Earrings (57), Necklace (52), Skirt (42), Sandals (41), Button-up shirt (40), T-shirt (40), Other (39), Sweater (38), Belt (38), Heels/Pumps (38), Shoulder bag (38), Bracelet (34).
<!-- DATASET_OVERVIEW_END -->

## Pipeline Architecture

```mermaid
sequenceDiagram
    participant Action as GitHub Actions
    participant Run as main.py / pipeline.py
    participant Reg as sources.py
    participant Feeds as feeds.py
    participant Page as crawl.py / content.py
    participant Img as images.py
    participant Gemini as Gemini API
    participant Store as storage.py / state.py

    Action->>Run: Pipeline run (Tuesdays and Fridays, 02:07 Europe/Berlin)
    Run->>Reg: Load the source registry (seed it from the legacy records if empty)
    Run->>Feeds: Fetch the feeds of active and probation sources
    Feeds-->>Run: Selected posts (new posts and posts due for a retry)
    loop For each post
        Run->>Page: Article content (from the feed, or the page rendered by crawl4ai)
        Page-->>Run: Text, image candidates, links, canonical URL
        Run->>Img: Download, size filter, dHash deduplication
        Img-->>Run: Up to 8 new images
        Run->>Gemini: One request with all images and the post text
        Gemini-->>Run: Outfits grouped by person, rejected images
        Run->>Store: Records, post state, image state, registry
    end
    Run->>Reg: Apply the lifecycle rules
    Action->>Action: Update the README overview, commit data/
```

## Sources and Post Selection

- **Registry.** The blogs are listed in `data/state/sources.json`. Nothing is curated by hand: the registry is seeded once from the domains of the legacy records, extended weekly by discovery, and maintained by fixed rules (see [Source Lifecycle](#source-lifecycle)).
- **Feeds.** Each run fetches the RSS or Atom feeds of the active sources and of the sources on probation. Posts published within the last 30 days that have not been processed yet are candidates. Posts whose title or tags indicate other topics (books, recipes, podcasts, interiors, giveaways, skincare, gift guides) are skipped.
- **Selection.** At most 3 posts per source and 40 posts per run, of which at most 10 come from sources on probation. The sources take turns, oldest posts first.
- **Content.** If the feed contains the full post with images, it is used directly; otherwise `crawl4ai` renders the post page. The article element is selected from the page, so that header, sidebar, related posts, share buttons and shop widgets are left out.
- **Republished posts.** Posts whose images were uploaded more than 12 months before the publish date (WordPress upload paths) are skipped, because their outfits would be dated wrongly.
- **Images.** At most 15 candidates per post are downloaded. The pipeline corrects the EXIF orientation, discards images with a shorter side below 400 px or a banner shape, and removes duplicates with a perceptual hash (dHash), within the post and against all images analyzed before. At most 8 images go to the model.
- **Extraction.** One Gemini request per post contains all images and the post text. The model groups the images that show the same person in the same outfit and returns one outfit per person and outfit; images without an outfit are listed with a reason. Brand names are kept only if they appear in the post's text, captions or link texts. Outfits of children and teenagers are not stored.

## Source Lifecycle

| Transition | Rule |
|---|---|
| Admission | The feed is found and has at least 2 posts in the last 60 days. Legacy sources with at least 5 legacy records start as `active`, all others on `probation`. |
| Not admitted | A site that blocks automated requests (HTTP 401 or 403) or has no feed is `rejected`. An unreachable site is `broken`. A feed with fewer than 2 posts in 60 days is `dormant`. |
| `probation` to `active` | At least 2 of the first 4 processed posts produced an outfit. |
| `probation` to `rejected` | 3 of the first 4 processed posts produced no outfit. |
| `active` to `retired` | Fewer than 25% of the last 12 processed posts produced an outfit. |
| To `dormant` | No post for more than 90 days. |
| Back from `dormant` | At least 2 posts in the last 60 days, checked weekly. The source returns to its previous status. |
| To `broken` | The feed failed on 7 consecutive pipeline runs (about three and a half weeks). It is checked weekly and returns to its previous status when the feed works again. |

Further rules:
- Known domains are never proposed again, so `rejected` and `retired` sources stay out.
- At most 60 sources are `active` or on `probation` at the same time, and at most 10 new sources are admitted per week.
- The country of a source comes from Gemini with Google Search where available, otherwise from a country-code domain or from the region of the feed's language tag. The field `source_country_basis` records which.

## Record Schema 2.0

Each record describes one outfit of one person in one post. The models are defined in [src/schema.py](src/schema.py); the field table in the [Dataset Overview](#dataset-overview) lists every field with its description.

- **Outfit attributes:** framing, photo context (blogger or private person, brand campaign, editorial), gender, age group, style category and aesthetic tags, overall fit, silhouette, color palette and contrast, occasion, setting, season, weather, hair and makeup.
- **Garments:** one entry per garment, shoe and accessory with type and derived category, description, primary and secondary color, pattern, material, fit, length, neckline, rise, leg shape, finish and design details.
- **Fixed vocabularies:** all attributes except the free-text details use fixed lists of values. Absence is explicit: "Not visible" for attributes of the photo, "Not applicable" for garment attributes that do not apply to the item.
- **Provenance:** record id, schema version, model, extraction hash (prompt, schema and model settings), scrape and publish dates, source domain, country and language, post URL, title and tags, and the dHash and size of each image. Image URLs are not stored.

**Legacy records.** The records collected before the switch to schema 2.0 use schema 1.x. They were taken from blog homepages without deduplication and without publish dates, and many describe the same photos repeatedly. They remain unchanged in `data/` and are reported separately in the overview.

## Data and State Files

| Path | Content |
|---|---|
| `data/YYYY/MM/fashion_analytics_YYYY-MM-DD.json` | Records of one UTC day |
| `data/state/sources.json` | Source registry |
| `data/state/posts.json` | Processed posts with status and attempts |
| `data/state/images.json` | dHashes of all analyzed images |
| `data/state/run_log.jsonl` | One line per pipeline run or weekly maintenance run, with counters and token usage |

The state files have a version key and one entry per line, and they are written atomically after every post.

## Workflows

| Workflow | Schedule | Purpose |
|---|---|---|
| `daily_scraper.yml` | Tuesdays and Fridays, 02:07 Europe/Berlin | Runs the pipeline, updates the overview and commits `data/` and `README.md` |
| `source_discovery.yml` | Sundays, 12:00 UTC | Re-checks dormant and broken sources, looks up countries, discovers new blogs and commits `data/state/` |
| `email_notify.yml` | After data commits | Posts a commit comment that mentions the repository owner |
| `ci.yml` | Pull requests, pushes to `main` | Lint, tests and commit message checks |

The two data workflows share a concurrency group, so they never push at the same time, and they pull with rebase and retry before pushing. Processed posts are committed even if a later step of the run fails.

Manual runs (`workflow_dispatch`) accept a `mode`:
- `normal`: same as the scheduled run.
- `shadow`: runs on a copy of the state in a temporary folder and uploads it as an artifact; nothing is committed. Shadow runs use the same API key and quota as the scheduled runs.
- `dry-run` (`daily_scraper.yml` only): no model calls; uploads a report of the selected posts and images.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | none | API key for Gemini (required) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model for extraction and discovery; stored in every record |
| `MAX_POSTS_PER_RUN` | 40 | Posts per pipeline run |
| `MAX_POSTS_PER_SOURCE` | 3 | Posts per source and run |
| `MAX_PROBATION_POSTS_PER_RUN` | 10 | Posts from sources on probation per run |
| `MAX_IMAGES_PER_POST` | 8 | Images per Gemini request |
| `MAX_GEMINI_CALLS_PER_RUN` | 50 | Gemini requests per pipeline run, including retries |
| `FEED_LOOKBACK_DAYS` | 30 | Age limit of new posts; unfinished posts are given up after this period |

Fixed thresholds, such as the lifecycle rules, are constants in the modules that use them.

## Running Locally

```bash
uv sync
uv run playwright install chromium                    # browser for crawl4ai, once
uv run python src/main.py --dry-run --max-posts 20    # no model calls, writes a report
uv run python src/main.py --max-posts 5               # processes 5 posts
uv run python src/discovery.py                        # weekly maintenance
```

Local runs write to `~/Downloads/style_dataset/` unless `--output-dir` is given; in GitHub Actions they write to `data/`. `--source DOMAIN` restricts a pipeline run to one or more sources. `scripts/try_extraction.py` runs the extraction on a fixed set of posts and writes an HTML review sheet.

## Dependency Management

This project uses [uv](https://docs.astral.sh/uv/) with a lockfile for reproducible builds.

1. **Dependencies**: `pyproject.toml` declares the direct dependencies; development tools (pytest, ruff) are in the `dev` dependency group.
2. **Lockfile**: `uv.lock` pins the complete dependency tree. After changing `pyproject.toml`, run `uv lock` and commit both files.
3. **Automated Updates**: Dependabot (`.github/dependabot.yml`) checks weekly for updates of the Python dependencies (`uv` ecosystem, updating `pyproject.toml` and `uv.lock` together) and of the GitHub Actions, each grouped into a single pull request.

## Continuous Integration

The `CI` workflow (`.github/workflows/ci.yml`) runs on every pull request and on pushes to `main`:

| Job | Checks |
|---|---|
| `Lint` | `uv.lock` matches `pyproject.toml`; `ruff check`; `actionlint` (including `shellcheck`) on the workflow files |
| `Tests` | The tests in `tests/` on Python 3.11 and 3.14. They run offline, with fakes for the web, the browser and the Gemini API, and also check that every module in `src/` and `scripts/` imports with the locked dependencies. |
| `Conventional Commits` | Every commit of a pull request follows the Conventional Commits format (pull requests only) |
| `CI passed` | Succeeds only if all jobs above succeeded or were skipped; use it as the single required status check in the branch protection of `main` |

Run the Python checks locally before pushing:
```bash
uv lock --check
uv run ruff check .
uv run pytest
```

## Setup

1. Add the repository secret `GEMINI_API_KEY` under **Settings > Secrets and variables > Actions**. For local runs, put it into a `.env` file.
2. Allow workflows to push to the repository under **Settings > Actions > General > Workflow permissions**.
3. The first pipeline run seeds the source registry from the legacy records, which takes about a minute.

Copyright (c) 2026 Conrad Kleinn. All rights reserved.
