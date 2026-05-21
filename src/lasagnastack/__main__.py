import multiprocessing

# Required for PyInstaller --onefile binaries: when multiprocessing spawns
# worker processes it re-executes the frozen binary; freeze_support() detects
# that case and handles it before the CLI entry point is reached.
multiprocessing.freeze_support()

from lasagnastack.cli import main  # noqa: E402

main()
