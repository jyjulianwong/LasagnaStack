import argparse
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lasagnastack",
        description="Turn raw video clips into an editable CapCut draft for short-form video and reel editing.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    make = sub.add_parser("make", help="Run the full pipeline.")
    make.add_argument("input_dir", type=Path, metavar="INPUT_DIR")
    make.add_argument("--out", type=Path, required=True, metavar="OUTPUT_DIR")
    make.add_argument(
        "--skill",
        type=Path,
        default=None,
        metavar="SKILL_FILE",
        help="Path to a Markdown skill file injected into the direct, critique, and enhance prompts.",
    )
    make.add_argument(
        "--yes", "-y", action="store_true", help="Auto-confirm all stage prompts."
    )
    make.add_argument(
        "--critique-max-retries",
        type=int,
        default=2,
        metavar="N",
        help="Maximum critique-loop iterations (default: 2).",
    )
    make.add_argument(
        "--ingest-max-workers",
        type=int,
        default=2,
        metavar="N",
        help="Parallel worker processes for Stage 1 — ingest (default: 1).",
    )
    make.add_argument(
        "--analyse-max-workers",
        type=int,
        default=4,
        metavar="N",
        help="Concurrent LLM calls for Stage 2 — analyse (default: 4).",
    )

    return parser


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()  # no-op if .env absent; shell env vars take precedence

    from lasagnastack.logging_config import configure_logging

    configure_logging()

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "make":
        from lasagnastack.pipeline import run_pipeline

        run_pipeline(
            input_dir=args.input_dir,
            output_dir=args.out,
            skill_path=args.skill,
            auto_confirm=args.yes,
            critique_max_retries=args.critique_max_retries,
            ingest_max_workers=args.ingest_max_workers,
            analyse_max_workers=args.analyse_max_workers,
        )
