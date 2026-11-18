"""The kb sourcing procedure (design 06, 6.3.3).

    python -m apdt.knowledge.sourcing fetch [ids…]      download sources and lock their hashes
    python -m apdt.knowledge.sourcing sections [ids…]   build the section trees
    python -m apdt.knowledge.sourcing search ID REGEX   find lines in a source with page and section
    python -m apdt.knowledge.sourcing pages ID A [B]    print PDF pages A to B by section
    python -m apdt.knowledge.sourcing terms SYSTEM TEXT find codes (snomed, icd11, loinc, atc, …)
    python -m apdt.knowledge.sourcing verify-codes      look up every kb code, write kb/terminology
    python -m apdt.knowledge.sourcing check             second pass: every number in its source
    python -m apdt.knowledge.sourcing review            write docs/governance/kb_review.pdf
"""

from __future__ import annotations

import argparse
import sys
import time


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m apdt.knowledge.sourcing")
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("ids", nargs="*")
    f.add_argument("--refresh", action="store_true")
    s = sub.add_parser("sections")
    s.add_argument("ids", nargs="*")
    s.add_argument("--rebuild", action="store_true")
    q = sub.add_parser("search")
    q.add_argument("source")
    q.add_argument("pattern")
    q.add_argument("--limit", type=int, default=60)
    p = sub.add_parser("pages")
    p.add_argument("source")
    p.add_argument("first", type=int)
    p.add_argument("last", type=int, nargs="?")
    t = sub.add_parser("terms")
    t.add_argument("system")
    t.add_argument("text")
    t.add_argument("--count", type=int, default=12)
    sub.add_parser("verify-codes")
    c = sub.add_parser("check")
    c.add_argument("--promote", action="store_true",
                   help="set status verified on entries that pass, draft on entries that fail")
    sub.add_parser("review")
    sub.add_parser("code-map", help="regenerate kb/code_to_twin.csv")
    sub.add_parser("tenant-data", help="regenerate synthetic stock, prices and rotas")
    sub.add_parser("questionnaires", help="regenerate kb/questionnaires/*.json")
    sub.add_parser("pathways", help="regenerate kb/plandefinitions and kb/pathways")
    args = parser.parse_args(argv)

    if args.cmd == "fetch":
        from apdt.knowledge.fetch import fetch

        failed = 0
        for sid, outcome in fetch(args.ids or None, refresh=args.refresh).items():
            print(f"{sid}: {outcome}")
            failed += outcome.startswith("failed")
        return 1 if failed else 0

    if args.cmd == "sections":
        from apdt.knowledge.sections import build_tree, load_tree, save_tree, tree_path
        from apdt.knowledge.sources import load_lock, load_sources

        sources, lock = load_sources(), load_lock()
        for src in sources.values():
            if args.ids and src.id not in args.ids:
                continue
            if src.status != "located" or src.data_via or src.format == "json":
                continue
            if src.id not in lock or src.path is None:
                print(f"{src.id}: not fetched")
                continue
            if (not args.rebuild and tree_path(src.id).exists()
                    and load_tree(src.id).sha256 == lock[src.id].sha256):
                continue
            t0 = time.monotonic()
            tree = build_tree(src, src.path, lock[src.id])
            save_tree(tree)
            print(f"{src.id}: {tree.method}, {tree.pages} pages, {len(tree.sections)} sections, "
                  f"{time.monotonic() - t0:.0f} s", flush=True)
        return 0

    if args.cmd == "search":
        import re

        from apdt.knowledge.sections import load_tree

        rx = re.compile(args.pattern, re.I)
        shown = 0
        for sec in load_tree(args.source).sections:
            if rx.search(sec.title):
                print(f"[{sec.id}] heading: {sec.title} (p{sec.page_start})")
                shown += 1
            for line in sec.lines:
                if rx.search(line.text):
                    print(f"p{line.page} [{sec.id} {sec.title[:40]}]: {line.text[:160]}")
                    shown += 1
            if shown >= args.limit:
                break
        return 0

    if args.cmd == "pages":
        from apdt.knowledge.sections import load_tree

        last = args.last or args.first
        for sec in load_tree(args.source).sections:
            lines = [ln for ln in sec.lines if args.first <= ln.page <= last]
            if lines or (args.first <= sec.page_start <= last and not sec.lines):
                print(f"## [{sec.id}] {sec.title} (p{sec.page_start})")
                for line in lines:
                    print(f"  p{line.page}: {line.text}")
        return 0

    if args.cmd == "terms":
        from apdt.knowledge.terminology import Terminology

        term = Terminology()
        for code, display in term.search(args.system, args.text, args.count):
            print(f"{code}\t{display}")
        term.save()
        return 0

    if args.cmd == "verify-codes":
        from apdt.knowledge.terminology import verify

        unknown = verify()
        for system, codes in unknown.items():
            print(f"unknown {system} codes: {', '.join(codes)}")
        return 1 if unknown else 0

    if args.cmd == "check":
        from apdt.knowledge.numcheck import check_kb, promote

        report = check_kb()
        for summary in report.summary_lines():
            print(summary)
        if args.promote:
            promote(report)
        return 0 if report.ok else 1

    if args.cmd == "code-map":
        from apdt.knowledge.code_map import write

        print(f"{write()} codes mapped")
        return 0

    if args.cmd == "tenant-data":
        from apdt.knowledge.tenant_data import write as write_tenants

        for path in write_tenants():
            print(path)
        return 0

    if args.cmd == "questionnaires":
        from apdt.knowledge.questionnaires import write as write_questionnaires

        for path in write_questionnaires():
            print(path.name)
        return 0

    if args.cmd == "pathways":
        from apdt.knowledge.pathways import write as write_pathways

        for path in write_pathways():
            print(path.name)
        return 0

    if args.cmd == "review":
        from apdt.knowledge.review import write_review

        print(write_review())
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
