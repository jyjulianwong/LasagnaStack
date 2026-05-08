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
        "--yes", "-y", action="store_true", help="Auto-confirm all stage prompts."
    )
    make.add_argument(
        "--max-critique-retries",
        type=int,
        default=2,
        metavar="N",
        help="Maximum critique-loop iterations (default: 2).",
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
            auto_confirm=args.yes,
            max_critique_retries=args.max_critique_retries,
        )
