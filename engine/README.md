# Breakthrough Engine

The core technology of the company: an AI pipeline that turns biomedical research and ideas into scored product opportunities with build plans.

It has two ways in:

- **Discovery mode** reads new papers, preprints and clinical trials, finds the breakthroughs that could become products, researches who else is working on them, scores them, and writes a product brief for the best ones.
- **Idea mode** takes an idea from a person, researches what has blocked it, proposes the breakthrough that would make it work (three approaches, each with a first experiment), then scores it and writes a product brief the same way.

```
 RESEARCH IN                                                    PRODUCTS OUT
 Europe PMC (journals + PubMed) ─┐
 bioRxiv / medRxiv preprints ────┤                                  product brief (.md)
 ClinicalTrials.gov ─────────────┼─► SCOUT ─► TRIAGE ─► JUDGE ─► DESIGN ─► leaderboard
 Claude web search (fallback) ───┘   store    cheap     web        build plan, parts,
                                     every    screen    research   FDA path, funding,
 IDEAS IN                            item     of every  + 8 scores  first 90 days
 "bte idea ..." ─► IDEATE: research the obstacle,          ▲
                   propose 3 breakthrough approaches ───────┘
```

## Stages

| Stage | What it does | Claude use |
| --- | --- | --- |
| Scout | Pulls the last N days of research on the configured topics into a local database. Never fetches or pays for the same item twice. | None, unless the `web` source is on |
| Triage | Screens every new item in batches of 15 for breakthrough strength and buildability. Most items are dropped here. | Low effort, one call per batch |
| Judge | For each survivor: web research on competitors, prior products, FDA precedent, market size, grants and patents; then scores 8 dimensions and gives a verdict. | High effort, web search |
| Design | For opportunities scoring 60+ that are not "drop": the product, prototype parts, phased build plan with costs, validation, regulatory path, IP, business model, team, risks, kill criteria, first 90 days. | High effort |
| Ideate | Idea mode: researches the idea, names the key obstacle, proposes three approaches, recommends one, then hands it to Judge and Design. | High effort, web search |

### How opportunities are scored

Each dimension is scored 0 to 10, then weighted into a 0 to 100 composite. Weights favor near-term products the company can win with; change them in a config file.

| Dimension | Weight | Meaning |
| --- | --- | --- |
| buildability | 20% | How soon a small team can build a working prototype |
| breakthrough | 15% | How new and large the advance is |
| evidence | 15% | Human data beats animal data beats bench data |
| impact | 15% | People helped times how much it matters |
| winnability | 10% | Whether a new company can beat whoever is already there |
| regulatory | 10% | How light the path to market is |
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
bte discover --days 7                 # full weekly run: scout, triage, judge, design
bte idea "A patch that warns elderly people before they get dehydrated"
bte idea --file my_idea.txt
bte evaluate --title "..." --file abstract.txt --url https://doi.org/...   # one specific paper
bte leaderboard                       # ranked opportunities -> output/leaderboard.md
bte show 12                           # print one brief

# Step by step
bte scout --days 7 --sources europepmc,biorxiv,medrxiv,clinicaltrials
bte triage --limit 300
bte judge --limit 5
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

## Cost

These are rough estimates, not measurements. A weekly discovery run that screens about 500 items, judges 10 and designs 3 should cost roughly $5 to $10 in Claude usage. One idea run is roughly $1 to $2. Lower `max_judged` and `max_designed` to spend less; the judge's web research is the largest cost.

## Network access

Scout needs to reach `www.ebi.ac.uk`, `api.biorxiv.org` and `clinicaltrials.gov`. Every other stage only needs `api.anthropic.com`. Where the research APIs are blocked, use `--sources web`, which finds recent research through Claude's own web search instead.

## Tests

```bash
pip install pytest
pytest -q
```

The tests run offline. They check parsing against synthetic records shaped like each API's responses, and run the whole pipeline with a stand-in for Claude. They test the plumbing, not the quality of the model's judgments.

## What comes next

- Patent search (Lens.org or PatentsView, both need an API key) for freedom-to-operate checks.
- A weekly schedule and an email digest of new top opportunities.
- A web dashboard over the database for the team.
- An evaluation set of past breakthroughs with known outcomes, to measure and tune the scoring.
