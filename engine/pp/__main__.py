"""CLI.

  python -m pp run policies/subway.json [--n-rep 300 --n-aff 100 --workers 8 --force react]
  python -m pp export <run_id> [--allow-mock]
  python -m pp series series/housing.json [--n 200 --tag pilot --only <measure id> … --workers 24 --no-export]
  python -m pp peoplemap --run series-housing-ctx --bundle ../web/public/series/housing.json --geo <dir> --out <dir>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import config, export, pipeline


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pp")
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("validate-scenario", help="validate a test card locally, without model calls")
    check.add_argument("scenario", type=Path)
    run = sub.add_parser("run", help="run every stage for one policy file (resumes)")
    run.add_argument("policy", type=Path)
    run.add_argument("--n-rep", type=int, default=300)
    run.add_argument("--n-aff", type=int, default=100)
    run.add_argument("--n-jev", type=int, default=5000, help="Jev quantitative panel size")
    run.add_argument("--n-alt", type=int, default=1500, help="people in the paired amendment test")
    run.add_argument("--workers", type=int, default=8)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--force", nargs="*", default=[], choices=pipeline.STAGES)
    run.add_argument("--only", nargs="*", default=[], choices=pipeline.STAGES)
    run.add_argument("--allow-mock", action="store_true")
    ser = sub.add_parser("series", help="run a Jev-only policy series (resumes)")
    ser.add_argument("series", type=Path)
    ser.add_argument("--n", type=int, default=None, help="panel size (default: the series file's)")
    ser.add_argument("--tag", default="", help="suffix for a separate run folder, e.g. pilot")
    ser.add_argument("--only", nargs="*", default=[], help="measure ids to (re)ask")
    ser.add_argument("--workers", type=int, default=24)
    ser.add_argument("--no-export", action="store_true")
    ser.add_argument("--housing", action="store_true",
                     help="assign tenure from official statistics and add local housing-market facts to every question")
    ser.add_argument("--panel-from", default=None, help="run folder whose panel to subsample, e.g. series-housing")
    ser.add_argument("--export-id", default=None, help="bundle name (default: the series id)")
    pm = sub.add_parser("peoplemap", help="write the 100만 명 지도 bundle (every persona as a dot + a series panel)")
    pm.add_argument("--run", required=True, help="series run folder under runs/, e.g. series-housing-ctx")
    pm.add_argument("--bundle", type=Path, required=True, help="the exported series bundle (measures and favour means)")
    pm.add_argument("--geo", type=Path, required=True, help="folder with sigg-, emd- and sido-boundaries.geojson")
    pm.add_argument("--out", type=Path, required=True)
    again = sub.add_parser("export", help="re-export an existing run directory")
    again.add_argument("run_id")
    again.add_argument("--allow-mock", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "validate-scenario":
        from .scenario import validate_scenario

        try:
            result = validate_scenario(json.loads(args.scenario.read_text(encoding="utf-8")))
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "run":
        job = pipeline.Run(args.policy, n_rep=args.n_rep, n_aff=args.n_aff, n_jev=args.n_jev, n_alt=args.n_alt,
                           workers=args.workers,
                           seed=args.seed, allow_mock=args.allow_mock)
        dest = job.run(force=tuple(args.force), only=tuple(args.only))
        if dest:
            print(f"exported {dest}")
    elif args.cmd == "series":
        from . import series

        dest = series.SeriesRun(args.series, n=args.n, tag=args.tag, workers=args.workers, housing=args.housing,
                                panel_from=args.panel_from, export_id=args.export_id).run(
            only=tuple(args.only), export=not args.no_export)
        if dest:
            print(f"exported {dest}")
    elif args.cmd == "peoplemap":
        from . import peoplemap

        print(peoplemap.build(config.runs_dir() / args.run, args.bundle, args.geo, args.out))
    else:
        bundle = export.assemble(config.runs_dir() / args.run_id)
        print(f"exported {export.write(bundle, allow_mock=args.allow_mock)}")


if __name__ == "__main__":
    main()
