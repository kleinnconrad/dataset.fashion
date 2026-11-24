# Fashion Analytics Scraper
[![CI](https://github.com/kleinnconrad/dataset.fashion/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/kleinnconrad/dataset.fashion/actions/workflows/ci.yml)

A fashion analytics pipeline that runs twice a week (Tuesdays and Fridays) in GitHub Actions. It reads the RSS feeds of personal style blogs, renders new posts with `crawl4ai`, describes the outfits in their photos with Google Gemini (`gemini-3.8-flash`) and stores one record per outfit in this repository. A weekly job finds new blogs and maintains the list of sources without manual curation.

## Table of Contents
- [Dataset Overview](#dataset-overview)
- [Pipeline Architecture](#pipeline-architecture)
- [Sources and Post Selection](#sources-and-post-selection)
- [Source Lifecycle](#source-lifecycle)
- [Record Schema 2.0](#record-schema-20)
- [Vocabularies](#vocabularies)
- [Data and State Files](#data-and-state-files)
- [Workflows](#workflows)
- [Configuration](#configuration)
- [Running Locally](#running-locally)
- [Dependency Management](#dependency-management)
- [Continuous Integration](#continuous-integration)
- [Setup](#setup)

## Dataset Overview
<!-- DATASET_OVERVIEW_START -->
**Last updated:** 2026-11-24 11:07 UTC

- **Schema 2.0 records:** 1,468 outfits from 381 posts of 49 sources, published 2026-09-11 to 2026-11-24
- **Images reused across posts:** 0
- **Legacy records (schema 1.x):** 1,457 records in 119 files (2026-06-14 to 2026-10-10); collected without deduplication and without publish dates, and not included in the tables below
- **Sources:** 44 active, 4 probation, 73 dormant, 10 broken, 56 rejected, 2 retired

**Active sources** (posts processed since admission; posts skipped as republished are not included in Posts)

| Source | Country | Posts | Posts with outfits | Skipped as republished | Last post |
|---|---|---|---|---|---|
| pumpsandpushups.com | US | 35 | 97.1% (34) | 1 | 2026-11-22 |
| russh.com | AU | 29 | 69.0% (20) | 1 | 2026-11-18 |
| fashionshouldbefun.com | US | 27 | 66.7% (18) | 0 | 2026-11-20 |
| thefashiontag.com | GB | 25 | 60.0% (15) | 0 | 2026-11-19 |
| shelbeeontheedge.com | US | 23 | 78.3% (18) | 0 | 2026-11-23 |
| awellstyledlife.com | US | 22 | 95.5% (21) | 1 | 2026-11-23 |
| loverlygrey.com | US | 20 | 100.0% (20) | 0 | 2026-11-21 |
| unefemme.net | US | 20 | 85.0% (17) | 1 | 2026-11-24 |
| thewelldressedlife.com | US | 18 | 55.6% (10) | 3 | 2026-11-19 |
| caphillstyle.com | US | 17 | 52.9% (9) | 13 | 2026-11-23 |
| permanentstyle.com | GB | 15 | 93.3% (14) | 0 | 2026-11-23 |
| mummabstylish.com | GB | 14 | 100.0% (14) | 0 | 2026-11-23 |
| thecurvyfashionista.com | US | 14 | 100.0% (14) | 6 | 2026-11-23 |
| reneeruin.com | AU | 13 | 100.0% (13) | 0 | 2026-10-15 |
| style-splash.com | GB | 13 | 69.2% (9) | 0 | 2026-11-19 |
| 9to5chic.com | US | 12 | 91.7% (11) | 0 | 2026-11-24 |
| midlifechic.com | GB | 12 | 66.7% (8) | 3 | 2026-11-23 |
| vintagevixon.blogspot.com | GB | 12 | 100.0% (12) | 0 | 2026-11-23 |
| fashion-note.me | US | 10 | 100.0% (10) | 0 | 2026-10-06 |
| nofearoffashion.com | NL | 10 | 100.0% (10) | 0 | 2026-11-21 |
| merricksart.com | US | 8 | 62.5% (5) | 0 | 2026-11-19 |
| sewliberated.com | US | 8 | 75.0% (6) | 1 | 2026-11-05 |
| invitadaperfecta.es | ES | 7 | 100.0% (7) | 0 | 2026-11-22 |
| marissawearsanoutfit.com | US | 7 | 100.0% (7) | 0 | 2026-11-18 |
| bluecollarredlipstick.com | US | 6 | 50.0% (3) | 0 | 2026-11-17 |
| isthismutton.com | GB | 6 | 83.3% (5) | 0 | 2026-11-17 |
| retrocat.de | DE | 6 | 50.0% (3) | 0 | 2026-11-22 |
| cellajane.com | US | 5 | 100.0% (5) | 0 | 2026-10-28 |
| clairejustineoxox.com | GB | 5 | 80.0% (4) | 2 | 2026-11-16 |
| livinginyellow.com | US | 5 | 60.0% (3) | 0 | 2026-11-19 |
| ... 14 more | | | | | |

**Fields (schema 2.0)**

| Field | Description | Known values | Distinct values |
|---|---|---|---|
| `framing` | Widest view of the person among the images of this outfit. | 100.0% (1,468) | 4 |
| `photo_context` | Who is shown: the blogger or another private person, models in a brand campaign or catalog image, or an editorial or street-style photo. | 97.3% (1,429) | 3 |
| `gender` | Perceived gender presentation of the person. | 99.4% (1,459) | 2 |
| `age_group` | Visually estimated age bracket of the person. | 99.9% (1,466) | 3 |
| `style_category` | Primary style of the outfit. | 100.0% (1,468) | 14 |
| `style_detail` | Refinement of the style in a few words, e.g. 'Relaxed weekend minimalism'. Null if not needed. | 78.7% (1,156) | 982 |
| `aesthetic_tags` | Named aesthetics or micro-trends that the outfit clearly represents. Empty list if none. | 18.4% (270) | 15 |
| `aesthetic_other` | A clearly represented aesthetic that is not in the list, in one to three words. Null if none. | 10.0% (147) | 75 |
| `focal_garment_index` | Position (starting at 1) in the garments list of the piece that draws the eye most. Null if no piece stands out. | 92.8% (1,362) | 6 |
| `layering_complexity` | Number of visible clothing layers on the upper body, from 1 (single layer) to 5 (heavy layering). | 100.0% (1,468) | 4 |
| `overall_fit` | Overall fit of the outfit. | 99.8% (1,465) | 4 |
| `silhouette` | Overall outline of the outfit. | 94.3% (1,385) | 7 |
| `color_palette_type` | Overall color character of the outfit. | 99.7% (1,464) | 5 |
| `color_contrast_strategy` | How the colors of the outfit are combined. | 99.6% (1,462) | 6 |
| `occasion` | Most likely occasion the outfit is meant for. 'Unclear' if the images and text give no indication. | 96.9% (1,423) | 6 |
| `setting` | Setting or background of the photos. | 99.3% (1,457) | 5 |
| `season` | Season suggested by the clothing and the surroundings. 'Unclear' if they give no indication. | 76.2% (1,119) | 4 |
| `weather` | Weather visible in the photos. 'Not visible' for indoor photos and whenever sky or conditions cannot be seen. | 25.6% (376) | 3 |
| `hair_length` | Hair length of the person. | 94.0% (1,380) | 4 |
| `hair_texture` | Hair texture of the person. | 92.4% (1,356) | 4 |
| `hair_style_type` | How the hair is worn. | 94.3% (1,384) | 7 |
| `hair_color` | Hair color of the person. | 93.2% (1,368) | 7 |
| `hair_parting` | How the hair is parted. | 90.1% (1,323) | 4 |
| `hair_finish` | Styling finish of the hair. | 92.6% (1,359) | 5 |
| `makeup_style` | Makeup style of the person. | 87.5% (1,285) | 4 |
| `brand_mentions` | Brands of this outfit that are named in the post title, text, tags, image captions or link texts. Do not infer brands from appearance. Empty list if none. | 51.7% (759) | 412 |
| `price_segment` | Price segment suggested by the named brands or the text. 'Unknown' without such evidence. | 38.8% (570) | 3 |
| `record_id` | Stable id derived from the post URL, the image hashes and the position of the outfit in the post. | 100.0% (1,468) | 1,468 |
| `schema_version` | Version of the record schema. | 100.0% (1,468) | 1 |
| `model` | Gemini model that produced the record. | 100.0% (1,468) | 3 |
| `extraction_hash` | Hash of the prompt, response schema, model settings and image preprocessing. Records with the same hash were extracted under the same conditions. | 100.0% (1,468) | 8 |
| `date_scraped` | UTC date of the extraction (YYYY-MM-DD). | 100.0% (1,468) | 14 |
| `published_date` | Publish date of the post from its feed (YYYY-MM-DD). | 100.0% (1,468) | 71 |
| `source_id` | Domain of the blog, without www. | 100.0% (1,468) | 49 |
| `source_country` | ISO 3166-1 alpha-2 country of the blog. Null if unknown. | 98.8% (1,450) | 8 |
| `source_country_basis` | How the country was determined: model (Gemini with web search), domain (country-code top-level domain), feed_language (region of the RSS language tag) or unknown. | 100.0% (1,468) | 3 |
| `source_region` | Region derived from source_country. | 98.8% (1,450) | 4 |
| `source_language` | Language of the blog from its feed (ISO 639-1). | 100.0% (1,468) | 3 |
| `post_url` | URL of the post. | 100.0% (1,468) | 381 |
| `canonical_url` | Canonical URL declared by the post page. | 56.4% (828) | 196 |
| `post_title` | Title of the post. | 100.0% (1,468) | 380 |
| `post_tags` | Categories and tags of the post from its feed. | 99.4% (1,459) | 891 |
| `shopping_link_count` | Number of links to shops or affiliate networks in the post. | 100.0% (1,468) | 45 |
| `outfit_colors` | Primary colors of the clothing and footwear, in the order of the garments list. | 98.8% (1,450) | 21 |

**Garments**

| Category | Items | Outfits with this category |
|---|---|---|
| Top | 1,217 | 74.0% (1,087) |
| Bottom | 1,045 | 70.9% (1,041) |
| Dress/One-piece | 249 | 17.0% (249) |
| Outerwear | 524 | 34.6% (508) |
| Footwear | 951 | 64.8% (951) |
| Bag | 468 | 31.5% (463) |
| Headwear | 99 | 6.7% (99) |
| Eyewear | 317 | 21.5% (316) |
| Jewelry | 1,068 | 43.8% (643) |
| Belt | 184 | 12.5% (183) |
| Scarf/Neckwear | 144 | 9.7% (143) |
| Hair accessory | 26 | 1.8% (26) |
| Hosiery | 87 | 5.7% (84) |
| Other | 135 | 7.6% (111) |

Most frequent garment types: Trousers (428), Jeans (328), Earrings (298), Necklace (279), T-shirt (262), Sweater (261), Dress (244), Button-up shirt (244), Heels/Pumps (205), Bracelet (192), Skirt (184), Belt (184), Ankle boots (180), Ring (172), Sunglasses (167).
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
- **Selection.** At most 3 posts per source and 40 posts per run, of which at most 10 come from sources on probation. The sources take turns: in the first round each source contributes its oldest post, oldest posts first. In the second and third rounds the sources with the higher recent yield (share of the last 6 processed posts that produced an outfit) come first; a source below 50% contributes no further post, and a source with fewer than 4 processed posts ranks as 50%. A post that appears in the feeds of two sources is selected once.
- **Content.** If the feed contains the full post with images, it is used directly; otherwise `crawl4ai` renders the post page. The article element is selected from the page, so that header, sidebar, related posts, share buttons and shop widgets are left out. Generic selectors are tried first, then the post containers of the Showit and Elementor site builders; if none matches, the whole page is used.
- **Old images and republished posts.** Images uploaded more than 12 months before the publish date (WordPress upload paths) are not analyzed, because their outfits would be dated wrongly. If most dated images of an article are that old, the post is skipped as republished. If the whole page had to be used, old header and sidebar images are common, so such a post is skipped only if no other image remains.
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
| Same feed | A source whose feed is the feed of another source, for example a second domain of the same blog, is `rejected`, at admission and after every run. Of the sources already in the registry, the one on the feed's own domain is kept. |

Further rules:
- Known domains are never proposed again, so `rejected` and `retired` sources stay out.
- At most 60 sources are `active` or on `probation` at the same time, and at most 10 new sources are admitted per week.
- The country of a source comes from Gemini with Google Search where available, otherwise from a country-code domain or from the region of the feed's language tag. The field `source_country_basis` records which.

## Record Schema 2.0

Each record describes one outfit of one person in one post. The models are defined in [src/schema.py](src/schema.py); the field table in the [Dataset Overview](#dataset-overview) lists every field with its description.

- **Outfit attributes:** framing, photo context (blogger or private person, brand campaign, editorial), gender, age group, style category and aesthetic tags, overall fit, silhouette, color palette and contrast, occasion, setting, season, weather, hair and makeup.
- **Garments:** one entry per garment, shoe and accessory with type and derived category, description, primary and secondary color, pattern, material, fit, length, neckline, rise, leg shape, finish and design details.
- **Fixed vocabularies:** all attributes except the free-text details use fixed lists of values. Absence is explicit: "Not visible" for attributes of the photo, "Not applicable" for garment attributes that do not apply to the item. The lists and their history are kept in [config/vocabularies.toml](config/vocabularies.toml) (see [Vocabularies](#vocabularies)).
- **Provenance:** record id, schema version, model, extraction hash (prompt, schema and model settings), scrape and publish dates, source domain, country and language, post URL, title and tags, and the dHash and size of each image. Image URLs are not stored.
- **Unlisted values (schema 2.1):** where no listed value describes an attribute well, Gemini still uses the closest value and names the term it would use (`unlisted_values`, field and term). Each record states the version of the lists it was extracted with (`vocabulary_version`, the day of the latest change of the lists). Records of schema 2.0 have neither field; the switch to schema 2.1 changed the extraction hash.

**Legacy records.** The records collected before the switch to schema 2.0 use schema 1.x. They were taken from blog homepages without deduplication and without publish dates, and many describe the same photos repeatedly. They remain unchanged in `data/` and are reported separately in the overview.

**Model changes.** Until 2026-11-03 the records were extracted by `gemini-2.5-flash` (thinking budget 2048 tokens, temperature 0.2), which Google retires in the Gemini API on 2026-12-01. The records of 2026-11-06 were extracted by `gemini-3.5-flash-lite`, which was replaced after this one run. Later records are extracted by `gemini-3.8-flash` (thinking level `LOW`; Gemini 3 and later models ignore custom temperatures). The fields `model` and `extraction_hash` separate the records of the three models. The requests with Google Search of the source discovery and the vocabulary review write no records; from 2026-11-24 they use `gemini-3.5-flash-lite` (`GEMINI_SEARCH_MODEL`), as `gemini-3.8-flash` took two to five minutes per request.

## Vocabularies

The fixed lists of values are kept in [config/vocabularies.toml](config/vocabularies.toml), one list per attribute group (35 lists, 352 values on 2026-10-11). They are slowly changing dimensions: every value has the day from which it is offered to Gemini (`added`), and a value that is no longer offered keeps its entry with the day of its retirement (`retired`), so the file shows which values were valid at any time. `src/schema.py` builds the response schema from the active values; a change of the file therefore changes the extraction hash of the following records.

- **Values are permanent.** A value is never renamed and never reused for another meaning; a changed meaning needs a new value.
- **Splits keep the series comparable.** A value that refines an existing value names it as `parent`, so that series can be summed up to the earlier values.
- **Every change is logged** in the table below with its date.

**Monthly review.** On the first day of every month, `vocabulary_review.yml` runs [src/vocabulary_review.py](src/vocabulary_review.py), which checks whether 26 of the lists are up to date. Framing, photo context, gender, age group, season, weather, price segment, the rejection reasons and the garment categories are classification frames and are changed by hand only. Gemini classifies every outfit with the closest listed value, so a term that a list lacks does not show up in the data by itself; the review therefore uses two sources:

1. **Research:** Gemini with Google Search checks the lists in five requests (garment types; colors, patterns, materials and surface details; cut and fit; styles, aesthetics, color strategies, occasions and settings; hair and makeup). It proposes terms that are established in fashion writing of the last 24 months or clearly emerging in the last 12 months and identifiable in outfit photos, and values that are no longer in use. A proposal needs sources from at least two websites, must not duplicate or reuse a value, and names the value it refines as `parent`; at most three proposals per list. Proposed additions with fewer sources are searched once more for further sources (one request per group).
2. **Data:** the records of the last 90 days. The terms that Gemini named as missing (`unlisted_values`), the aesthetics outside the list (`aesthetic_other`) and the descriptions of garments of the type "Other" are counted per outfit and blog and given to the research as hints; terms with at least 10 outfits from 3 blogs that the research does not add are listed in the report. The report also names values with at least 60 % of the observations of their list (candidates for a split), values without observations in the window, and the shares of "Other" and "Unclear".

The valid additions are written to `config/vocabularies.toml` (with the day of the review as `added`) and to the change log, and the workflow opens or updates a pull request with the report as its description; nothing changes until it is merged. Retirements and splits are reported only and carried out by hand. Without proposed changes, the report is in the job summary of the workflow run. The review sends five to ten requests with Google Search per month.

A change of the lists changes the response schema, but not `SCHEMA_VERSION`: the records state the version of the lists in `vocabulary_version`, and the schema snapshot test names the lists of the fields, not their values.

| Date | List | Change |
|---|---|---|
| 2026-10-11 | all | Lists of schema 2.0 (35 lists, 352 values). |
| 2026-11-24 | `aesthetic_tag` | Added "Boho chic": Boho chic has experienced a prominent high-fashion revival and widespread adoption in recent trend cycles. |

## Data and State Files

| Path | Content |
|---|---|
| `data/YYYY/MM/fashion_analytics_YYYY-MM-DD.json` | Records of one UTC day |
| `data/state/sources.json` | Source registry |
| `data/state/posts.json` | Processed posts with status and attempts |
| `data/state/images.json` | dHashes of all analyzed images |
| `data/state/run_log.jsonl` | One line per pipeline run or weekly maintenance run, with counters and token usage. Pipeline runs also record the posts that were due before the selection caps (`posts_due`, `sources_with_due_posts`); maintenance runs record each discovery search with its focus, candidates and admitted sources, and the beginning of the answer if it named no blog (`searches`). |

The state files have a version key and one entry per line, and they are written atomically after every post.

## Workflows

| Workflow | Schedule | Purpose |
|---|---|---|
| `daily_scraper.yml` | Tuesdays and Fridays, 02:07 Europe/Berlin | Runs the pipeline, updates the overview and commits `data/` and `README.md` |
| `source_discovery.yml` | Sundays, 12:00 UTC | Re-checks dormant and broken sources, looks up countries, discovers new blogs and commits `data/state/` |
| `vocabulary_review.yml` | First day of every month, 12:17 UTC | Checks whether the fixed lists are up to date and opens a pull request with the proposed additions (see [Vocabularies](#vocabularies)) |
| `email_notify.yml` | After data commits | Posts a commit comment that mentions the repository owner |
| `ci.yml` | Pull requests, pushes to `main` | Lint, tests and commit message checks |

The two data workflows share a concurrency group, so they never push at the same time, and they pull with rebase and retry before pushing. Processed posts are committed even if a later step of the run fails.

Manual runs (`workflow_dispatch`) accept a `mode`:
- `normal`: same as the scheduled run.
- `shadow`: runs on a copy of the state in a temporary folder and uploads it as an artifact; nothing is committed. Shadow runs use the same API key and quota as the scheduled runs.
- `dry-run` (`daily_scraper.yml` only): no model calls; uploads a report of the selected posts and images.

`vocabulary_review.yml` also accepts `research`: turned off, the review evaluates the data only, without Gemini. Its `shadow` mode uploads the report and the proposed changes instead of opening a pull request.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | none | API key for Gemini (required) |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Model for extraction; stored in every record. A Gemini 3 or later model: the requests set a thinking level, which Gemini 2.5 models reject |
| `GEMINI_SEARCH_MODEL` | `gemini-3.5-flash-lite` | Model for the requests with Google Search (source discovery, vocabulary review). A Gemini 3 or later model that supports Grounding with Google Search |
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
2. Allow workflows to push to the repository under **Settings > Actions > General > Workflow permissions**, and allow GitHub Actions to create and approve pull requests, so that the vocabulary review can open its pull request.
3. The first pipeline run seeds the source registry from the legacy records, which takes about a minute.

Copyright (c) 2026 Conrad Kleinn. All rights reserved.
