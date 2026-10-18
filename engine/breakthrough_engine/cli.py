"""Command line: `bte <command>`. Run `bte --help` for the list."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import report
from .config import Config
from .llm import LLM, LLMError
from .stages import design, ideate, judge, needs, ownership, scout, triage
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bte", description="Breakthrough Engine: research and ideas in, products out.")
    parser.add_argument("--config", help="JSON file overriding default settings")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="Full discovery run: scout, triage, ownership, judge, needs, design")
    p.add_argument("--days", type=int, help="look back this many days (default from config)")
    p.add_argument("--sources", help="comma-separated: europepmc,biorxiv,medrxiv,clinicaltrials,nih_reporter,web")
    p.add_argument("--max-triage", type=int, help="cap on items screened this run")

    p = sub.add_parser("scout", help="Fetch new research only (no Claude calls unless the web source is used)")
    p.add_argument("--days", type=int)
    p.add_argument("--sources")

    p = sub.add_parser("triage", help="Screen untriaged research")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("ownership", help="Check triage survivors for a spinout, license or company that owns them")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("judge", help="Research and score the best triage survivors")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("needs", help="Send studies that show an unmet need to idea mode")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("design", help="Write product briefs for the top scored opportunities")
    p.add_argument("--limit", type=int)

    p = sub.add_parser("idea", help="Idea mode: find the breakthrough an idea needs, then score and design it")
    p.add_argument("text", nargs="?", help="the idea (or use --file)")
    p.add_argument("--file", help="read the idea from a file")
    p.add_argument("--no-design", action="store_true")

    p = sub.add_parser("evaluate", help="Run one specific paper or finding through judge and design")
    p.add_argument("--title", required=True)
    p.add_argument("--text", help="abstract or description (or use --file)")
    p.add_argument("--file")
    p.add_argument("--url", default="")
    p.add_argument("--no-design", action="store_true")

    sub.add_parser("leaderboard", help="Write and print the ranked list of opportunities")
    p = sub.add_parser("show", help="Print one opportunity's brief")
    p.add_argument("id", type=int)
    sub.add_parser("config", help="Print the active settings")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    cfg = Config.load(args.config)
    if getattr(args, "days", None):
        cfg.lookback_days = args.days
    if getattr(args, "sources", None):
        cfg.sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    if args.command == "config":
        print(cfg.to_json())
        return 0

    Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
    store = Store(cfg.db_path)
    llm: LLM | None = None

    def get_llm() -> LLM:
        nonlocal llm
        if llm is None:
            llm = LLM(cfg.model)
        return llm

    try:
        if args.command == "scout":
            _print(scout.run(cfg, store, get_llm() if "web" in cfg.sources else None))
        elif args.command == "triage":
            _print(triage.run(cfg, store, get_llm(), args.limit))
        elif args.command == "ownership":
            _print(ownership.run(cfg, store, get_llm(), args.limit))
        elif args.command == "judge":
            _print(judge.run(cfg, store, get_llm(), args.limit))
        elif args.command == "needs":
            _print(needs.run(cfg, store, get_llm(), args.limit))
        elif args.command == "design":
            _print(design.run(cfg, store, get_llm(), args.limit))
        elif args.command == "discover":
            engine = get_llm()
            result = {"scout": scout.run(cfg, store, engine if "web" in cfg.sources else None)}
            result["triage"] = triage.run(cfg, store, engine, args.max_triage)
            if cfg.check_ownership:
                result["ownership"] = ownership.run(cfg, store, engine)
            result["judge"] = judge.run(cfg, store, engine)
            result["needs"] = needs.run(cfg, store, engine)
            result["design"] = design.run(cfg, store, engine)
            _print(result)
            _write_leaderboard(cfg, store)
        elif args.command == "idea":
            text = Path(args.file).read_text() if args.file else args.text
            if not text:
                parser.error("give the idea as text or with --file")
            opp_id = ideate.run(text.strip(), cfg, store, get_llm(), design_it=not args.no_design)
            _summarize(store, opp_id)
            _write_leaderboard(cfg, store)
        elif args.command == "evaluate":
            text = Path(args.file).read_text() if args.file else args.text
            if not text:
                parser.error("give the finding with --text or --file")
            opp_id = ideate.evaluate(args.title, text.strip(), args.url, cfg, store, get_llm(),
                                     design_it=not args.no_design)
            _summarize(store, opp_id)
            _write_leaderboard(cfg, store)
        elif args.command == "leaderboard":
            print(_write_leaderboard(cfg, store))
        elif args.command == "show":
            opp = store.get_opportunity(args.id)
            if not opp:
                print(f"No opportunity {args.id}", file=sys.stderr)
                return 1
            if opp.get("report_path") and Path(opp["report_path"]).exists():
                print(Path(opp["report_path"]).read_text())
            else:
                _print({k: v for k, v in opp.items() if k != "landscape"})
    except LLMError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
    finally:
        if llm is not None:
            cost = llm.usage.estimated_cost(cfg.model)
            print(f"\nClaude usage: {llm.usage.calls} calls, {llm.usage.input_tokens:,} input / "
                  f"{llm.usage.output_tokens:,} output tokens, {llm.usage.web_searches} web searches"
                  + (f", about ${cost:.2f}" if cost is not None else ""), file=sys.stderr)
        store.close()
    return 0


def _summarize(store: Store, opp_id: int) -> None:
    opp = store.get_opportunity(opp_id)
    print(f"Opportunity {opp_id}: status {opp['status']}"
          + (f", score {opp['composite']:.0f}/100, verdict {opp['verdict']}" if opp["composite"] is not None else ""))
    if opp.get("report_path"):
        print(f"Brief: {opp['report_path']}")
    if opp.get("error"):
        print(f"Error: {opp['error']}")


def _write_leaderboard(cfg: Config, store: Store) -> str:
    opps = store.opportunities()
    papers = {o["paper_key"]: store.get_paper(o["paper_key"]) for o in opps if o["paper_key"]}
    text = report.leaderboard(opps, papers, store.owned())
    (Path(cfg.output_dir) / "leaderboard.md").write_text(text)
    return text


def _print(data) -> None:
    print(json.dumps(data, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
