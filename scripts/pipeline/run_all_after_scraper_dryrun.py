"""
Run scraper dry-runs first, then execute the full pipeline only if all pass.
"""

from __future__ import annotations
from pathlib import Path
import argparse
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
src = root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from pink_tax.config import load_pipeline_definition

def _build_dryrun_command(
    step_command: list[str],
    limit: int,
    headful: bool,
    user_data_dir: str,
) -> list[str]:
    """
    Add dry-run flags to a scraper command.
    """

    cmd = list(step_command)

    if "--dry-run" not in cmd:
        cmd.append("--dry-run")

    if "--limit" not in cmd:
        cmd.extend(["--limit", str(limit)])

    uses_browser = "--browser-mode" in cmd
    if uses_browser and headful and "--headful" not in cmd:
        cmd.append("--headful")

    if uses_browser and user_data_dir and "--user-data-dir" not in cmd:
        cmd.extend(["--user-data-dir", user_data_dir])

    return [sys.executable, *cmd]

def main() -> None:
    """
    CLI entrypoint.
    """

    parser = argparse.ArgumentParser(
        description="Run all scraper dry-runs; if all succeed, run python run_all.py."
    )
    parser.add_argument(
        "--pipeline-config",
        default=str(root / "config" / "pipeline_build_steps.json"),
        help="Pipeline config used to discover scraper steps.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Pairs limit passed to each scraper dry-run.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Pass --headful to browser-mode scrapers during dry-run.",
    )
    parser.add_argument(
        "--user-data-dir",
        default="",
        help="Pass --user-data-dir to browser-mode scrapers during dry-run.",
    )
    parser.add_argument(
        "--run-mode",
        choices=["all", "build", "clean"],
        default="all",
        help="Mode passed to run_all.py if dry-runs pass.",
    )
    args = parser.parse_args()

    definition = load_pipeline_definition(Path(args.pipeline_config))
    steps = definition.get("steps", [])
    scraper_steps = [s for s in steps if str(s.get("key", "")).startswith("scrape_")]

    if not scraper_steps:
        raise SystemExit("No scraper steps found in pipeline config.")

    print(f"Dry-run gate: {len(scraper_steps)} scraper steps")
    for step in scraper_steps:
        command = _build_dryrun_command(
            step_command=list(step["command"]),
            limit=args.limit,
            headful=args.headful,
            user_data_dir=args.user_data_dir,
        )
        print(f"\n-- dryrun:{step['key']}")
        print("   $ " + " ".join(command))
        result = subprocess.run(command, cwd=root, check=False)
        if result.returncode != 0:
            print(f"   failed (exit {result.returncode})")
            raise SystemExit(result.returncode)
        print("   passed")

    run_all_cmd = [sys.executable, str(root / "run_all.py")]
    if args.run_mode != "all":
        run_all_cmd.extend(["--mode", args.run_mode])

    print("\nAll scraper dry-runs passed. Running full pipeline:")
    print("   $ " + " ".join(run_all_cmd))
    final = subprocess.run(run_all_cmd, cwd=root, check=False)
    raise SystemExit(final.returncode)

if __name__ == "__main__":
    main()
