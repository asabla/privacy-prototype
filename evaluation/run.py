"""Run with python -m evaluation.run --engine heuristic (or --engine opf)."""

import argparse
import json
from pathlib import Path
import sys

from backend.detector import Detector
from evaluation.core import check_baseline, evaluate, load_cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("heuristic", "opf"), default="heuristic")
    parser.add_argument("--dataset", type=Path, default=Path(__file__).with_name("cases.json"))
    parser.add_argument("--baseline", type=Path, help="Fail if a case worsens against this reviewed baseline")
    parser.add_argument("--output", type=Path, help="Write the full JSON report here instead of stdout")
    args = parser.parse_args()
    try:
        cases, digest = load_cases(args.dataset)
        report = evaluate(cases, Detector(engine=args.engine), digest)
        failures = check_baseline(report, json.loads(args.baseline.read_text())) if args.baseline else []
        report["baseline_failures"] = failures
        rendered = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered)
        else:
            print(rendered, end="")
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1 if failures else 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
