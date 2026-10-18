# Breakthrough Engine

The core technology of the company: an AI pipeline that turns biomedical research and ideas into scored product opportunities with build plans.

It has two ways in:

- **Discovery mode** reads new papers, preprints, clinical trials and NIH grants, finds the breakthroughs that could become products, drops the ones someone already owns, researches who else is working on the rest, scores them, and writes a product brief for the best ones. Studies that show an existing product failing patients go to idea mode as unmet needs.
- **Idea mode** takes an idea from a person, researches what has blocked it, proposes the breakthrough that would make it work (three approaches, each with a first experiment), then scores it and writes a product brief the same way.

```
 RESEARCH IN                                                              PRODUCTS OUT
 Europe PMC (journals + PubMed) ─┐
 bioRxiv / medRxiv preprints ────┤                                          product brief (.md)
 ClinicalTrials.gov ─────────────┼─► SCOUT ─► TRIAGE ─► OWNERSHIP ─► JUDGE ─► DESIGN ─► leaderboard
 NIH RePORTER grants ────────────┤   store    cheap     a few        web        build plan, parts,
 Claude web search (fallback) ───┘   every    screen    searches:    research   FDA path, funding,
                                     item     of every  owned ones   + 8 scores  first 90 days
                                              item      are dropped    ▲
                                                │                      │
                                       unmet needs (an existing        │
 IDEAS IN                              product fails patients)         │
 "bte idea ..." ─────────────────────► IDEATE: research the obstacle,  │
                                       propose 3 breakthrough approaches
```

## Stages

| Stage | What it does | Claude use |
| --- | --- | --- |
| Scout | Pulls the last N days of research on the configured topics into a local database. Never fetches or pays for the same item twice. | None, unless the `web` source is on |
| Triage | Screens every new item in batches of 15 for breakthrough strength, buildability, and evidence of an unmet need. Most items are dropped here. | Low effort, one call per batch |
| Ownership | For each survivor, best first: up to 3 web searches for a spinout from the authors' lab, a license, or a funded company already selling or filing the same product. Owned items are not judged and are listed on the leaderboard with the owner. | Medium effort, web search |
| Judge | For each survivor not already owned: web research on competitors, prior products, FDA precedent, market size, grants and patents, starting from the ownership check; then scores 8 dimensions and gives a verdict. | High effort, web search |
| Needs | For studies that show a widely used product or standard of care failing patients: sends the gap to idea mode, then judges the result. Design treats it like any other opportunity. | High effort, web search |
| Design | For opportunities scoring 60+ that are not "drop": the product, prototype parts, phased build plan with costs, validation, regulatory path, IP, business model, team, risks, kill criteria, first 90 days. | High effort |
| Ideate | Idea mode: researches the idea, names the key obstacle, proposes three approaches, recommends one, then hands it to Judge and Design. | High effort, web search |

### How opportunities are scored

Each dimension is scored 0 to 10, then weighted into a 0 to 100 composite. Weights favor products the company can win with; change them in a config file. Winnability carries the most weight because the first scan (October 2026) found that easy, lightly regulated products scored high even when the lab's own spinout already sold them.

| Dimension | Weight | Meaning |
| --- | --- | --- |
| winnability | 20% | Whether a new company can beat whoever is already there |
| buildability | 15% | How soon a small team can build a working prototype |
| breakthrough | 15% | How new and large the advance is |
| evidence | 15% | Human data beats animal data beats bench data |
| impact | 15% | People helped times how much it matters |
| regulatory | 5% | How light the path to market is |
| capital efficiency | 10% | Money needed to reach clinical proof or revenue |
| funding fit | 5% | Match to open grants |

## Setup

Requires Python 3.10+ and a Claude API key.

```bash
cd engine
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...      # or: ant auth login
```

The engine uses Claude Opus 5.5 (`claude-opus-5-5`) with server-side refusal fallbacks turned on (`fallbacks: "default"`), so a request one model declines is retried on Anthropic's recommended fallback model.

## Commands

```bash
bte discover --days 7                 # full weekly run: scout, triage, ownership, judge, needs, design
bte idea "A patch that warns elderly people before they get dehydrated"
bte idea --file my_idea.txt
bte evaluate --title "..." --file abstract.txt --url https://doi.org/...   # one specific paper
bte leaderboard                       # ranked opportunities -> output/leaderboard.md
bte show 12                           # print one brief

# Step by step
bte scout --days 7 --sources europepmc,biorxiv,medrxiv,clinicaltrials,nih_reporter
bte triage --limit 300
bte ownership --limit 30
bte judge --limit 5
bte needs --limit 2
bte design --limit 2
bte config                            # print settings
```

Briefs are written to `output/<date>/<id>-<name>.md`. Every run prints its Claude usage and an estimated cost.

## Settings

Pass `--config my.json` to override any default in `breakthrough_engine/config.py`, for example:

```json
{
  "topics": ["wearable sensor", "point-of-care diagnostic", "digital biomarker"],
  "lookback_days": 14,
  "max_judged": 5,
  "max_designed": 2,
  "allowed_types": ["device", "diagnostic", "software", "platform_tool", "drug"]
}
```

Settings added after the first scan: `check_ownership` (on by default), `max_ownership_checks` (30 a run), `ownership_searches` (3 per check), `need_threshold` (the unmet-need score, 0 to 10, that sends a study to idea mode; default 7) and `max_needs` (2 a run).

## Cost

These are rough estimates, not measurements. A weekly discovery run that screens about 500 items, checks ownership on up to 30, judges 10, explores 2 unmet needs and designs 3 should cost roughly $8 to $15 in Claude usage. One idea run is roughly $1 to $2. Lower `max_judged`, `max_needs` and `max_designed` to spend less; the judge's web research is the largest cost.

## Network access

Scout needs to reach `www.ebi.ac.uk`, `api.biorxiv.org`, `clinicaltrials.gov` and `api.reporter.nih.gov`. Every other stage only needs `api.anthropic.com`. Where the research APIs are blocked, use `--sources web`, which finds recent research, conference abstracts and grant news through Claude's own web search instead.

## Weekly schedule

`.github/workflows/weekly-scan.yml` runs `bte discover --days 7` every Monday on GitHub's runners, which can reach all the research APIs. It does nothing until an `ANTHROPIC_API_KEY` repository secret is added (Settings, then Secrets and variables, then Actions). Each run's leaderboard and briefs are attached to the run as a download, kept 90 days. The database is carried between runs in the Actions cache, so nothing is paid for twice. It can also be started by hand from the Actions tab.

## Tests

```bash
pip install pytest
pytest -q
```

The tests run offline. They check parsing against synthetic records shaped like each API's responses, and run the whole pipeline with a stand-in for Claude. They test the plumbing, not the quality of the model's judgments.

## What comes next

- Patent search (Lens.org or PatentsView, both need an API key) for freedom-to-operate checks.
- An email digest of each week's new top opportunities.
- A web dashboard over the database for the team.
- An evaluation set of past breakthroughs with known outcomes, to measure and tune the scoring.
