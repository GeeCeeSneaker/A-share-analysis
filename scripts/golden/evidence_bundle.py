"""CLI for creating or inspecting deterministic GT-H3B evidence bundles."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ashare_state.spike.evidence_bundle import (  # noqa: E402
    EvidenceBundleError,
    read_evidence_bundle,
    write_evidence_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="GT-H3B evidence bundle utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="create a deterministic raw-byte bundle")
    create.add_argument("--input", type=Path, required=True, help="JSON list of source entries")
    create.add_argument("--output", type=Path, required=True, help="output .zip path")

    inspect = subparsers.add_parser("inspect", help="validate and print a bundle inventory")
    inspect.add_argument("--bundle", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "create":
            entries = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                raise EvidenceBundleError("input must contain a JSON list")
            write_evidence_bundle(args.output, entries)
            print(f"created deterministic evidence bundle: {args.output}")
        else:
            entries = read_evidence_bundle(args.bundle)
            print(json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, indent=2))
    except (EvidenceBundleError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"evidence bundle error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
