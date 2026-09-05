"""
Cairo Deal-Finder pipeline entry point.

Called by GitHub Actions with --stage argument:
  python main.py --stage ingestion
  python main.py --stage scoring
  python main.py --stage reporting

The Africa/Cairo time guard is enforced inside each stage module.
This script just routes to the right stage and sets up logging.
"""
from __future__ import annotations
import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("main")


def main():
    parser = argparse.ArgumentParser(description="Cairo Deal-Finder pipeline")
    parser.add_argument(
        "--stage",
        required=True,
        choices=["ingestion", "scoring", "reporting"],
        help="Pipeline stage to run",
    )
    args = parser.parse_args()

    log.info("Starting stage: %s", args.stage)

    if args.stage == "ingestion":
        from pipeline.ingest import run
        run()
    elif args.stage == "scoring":
        from pipeline.score import run
        run()
    elif args.stage == "reporting":
        from pipeline.report import run
        run()
    else:
        log.error("Unknown stage: %s", args.stage)
        sys.exit(1)


if __name__ == "__main__":
    main()
