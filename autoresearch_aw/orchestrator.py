"""Orchestrator: provision → setup → run → collect → teardown."""

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from autoresearch_aw.config import load_config, load_research
from autoresearch_aw.log import Logger


def run_experiment(research_path: str = "research.yaml", verbose: bool = False):
    """Run autoresearch end to end on the configured platform."""
    config = load_config()
    research = load_research(Path(research_path))

    if not config:
        print("Error: No config found. Run 'autoresearch-aw init <platform>' first.")
        sys.exit(1)

    if not research:
        print(f"Error: No research config found at {research_path}")
        sys.exit(1)

    platform = research.get("platform", "mac")
    max_experiments = research.get("research", {}).get("max_experiments", 2)
    log_dir = config.get("log_dir", "./logs")

    with Logger(log_dir) as log:
        log.log(f"Log file: {log.log_path}")
        log.log()

        if platform == "mac":
            _run_mac(config, research, max_experiments, verbose, log)
        else:
            log.error(f"Platform '{platform}' not yet implemented.")
            sys.exit(1)


def _run_mac(config, research, max_experiments, verbose, log: Logger):
    """Run autoresearch on Mac (MPS/CPU)."""
    project_root = Path(__file__).parent.parent
    platforms_dir = project_root / "platforms" / "mac"

    # Create workspace
    timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    workspace = project_root / "workspace" / timestamp
    workspace.mkdir(parents=True, exist_ok=True)

    results_dir = project_root / "results" / timestamp
    results_dir.mkdir(parents=True, exist_ok=True)

    log.log(f"Platform:    Mac")
    log.log(f"Experiments: {max_experiments} (~{max_experiments * 5} min)")
    log.log(f"Workspace:   {workspace}")
    log.log(f"Results:     {results_dir}")
    log.log()

    # Copy platform-adapted scripts to workspace
    shutil.copy2(platforms_dir / "train.py", workspace / "train.py")
    shutil.copy2(platforms_dir / "prepare.py", workspace / "prepare.py")

    # Create a minimal pyproject.toml for uv run in workspace
    workspace_pyproject = workspace / "pyproject.toml"
    workspace_pyproject.write_text(
        '[project]\n'
        'name = "autoresearch-workspace"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.10"\n'
        'dependencies = [\n'
        '    "torch>=2.6.0",\n'
        '    "numpy>=2.0",\n'
        '    "pyarrow>=15.0",\n'
        '    "rustbpe>=0.1.0",\n'
        '    "tiktoken>=0.11.0",\n'
        '    "requests>=2.32.0",\n'
        ']\n'
    )

    # Copy program.md if specified
    program_file = research.get("research", {}).get("program", "program.md")
    program_path = Path(program_file)
    if program_path.exists():
        shutil.copy2(program_path, workspace / "program.md")

    # Step 0: Install workspace dependencies
    log.log("[setup] Installing workspace dependencies (uv sync)...")
    ok = _run_script(workspace, ["uv", "sync"], log)
    if not ok:
        log.error("Dependency installation failed. Cannot continue.")
        sys.exit(1)
    log.log("[setup] Done.")
    log.log()

    # Step 1: Data preparation
    log.log("[prepare] Downloading data and training tokenizer...")
    ok = _run_script(workspace, ["uv", "run", "prepare.py", "--num-shards", "2"], log)
    if not ok:
        log.error("Data preparation failed. Cannot continue.")
        sys.exit(1)
    log.log("[prepare] Done.")
    log.log()

    # Step 2: Run training experiments
    results = []  # (experiment_num, val_bpb, elapsed, ok)
    run_start = time.time()

    for i in range(1, max_experiments + 1):
        log.log(f"── Experiment {i}/{max_experiments} ──")
        t0 = time.time()

        ok = _run_script(workspace, ["uv", "run", "train.py"], log)

        elapsed = time.time() - t0
        if ok:
            log.log(f"  Completed in {elapsed:.0f}s")
        else:
            log.error(f"  Experiment {i} failed after {elapsed:.0f}s")

        # Extract val_bpb from subprocess output captured in log
        val_bpb = _extract_last_val_bpb(log.log_path)
        results.append((i, val_bpb, elapsed, ok))

        log.log()

    total_elapsed = time.time() - run_start

    # Step 3: Collect results
    log.log("[results] Collecting results...")
    train_py = workspace / "train.py"
    if train_py.exists():
        shutil.copy2(train_py, results_dir / "train.py")

    log.log(f"[results] Saved to {results_dir}")
    log.log()

    # Summary
    log.log("═" * 50)
    log.log("RUN SUMMARY")
    log.log("═" * 50)
    log.log(f"Platform:     Mac ({config.get('platforms', {}).get('mac', {}).get('apple_silicon', False) and 'Apple Silicon MPS' or 'CPU'})")
    log.log(f"Experiments:  {max_experiments}")
    log.log(f"Total time:   {int(total_elapsed)}s ({total_elapsed / 60:.1f} min)")
    log.log()

    succeeded = sum(1 for _, _, _, ok in results if ok)
    failed = max_experiments - succeeded
    log.log(f"Succeeded:    {succeeded}/{max_experiments}")
    if failed:
        log.log(f"Failed:       {failed}/{max_experiments}")
    log.log()

    log.log(f"{'Exp':>4}  {'val_bpb':>10}  {'Time':>8}  {'Status':>8}")
    log.log(f"{'─' * 4}  {'─' * 10}  {'─' * 8}  {'─' * 8}")
    best_bpb = None
    best_exp = None
    for exp_num, val_bpb, elapsed, ok in results:
        status = "ok" if ok else "FAILED"
        bpb_str = f"{val_bpb:.6f}" if val_bpb is not None else "n/a"
        log.log(f"{exp_num:>4}  {bpb_str:>10}  {int(elapsed):>6}s  {status:>8}")
        if ok and val_bpb is not None:
            if best_bpb is None or val_bpb < best_bpb:
                best_bpb = val_bpb
                best_exp = exp_num

    log.log()
    if best_bpb is not None:
        log.log(f"Best val_bpb: {best_bpb:.6f} (experiment {best_exp})")
    log.log(f"Results:      {results_dir}")
    log.log(f"Log:          {log.log_path}")
    log.log("═" * 50)


def _run_script(workspace, cmd, log: Logger) -> bool:
    """Run a script in the workspace directory. Streams output to logger. Returns True on success."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"  # Force unbuffered output so log updates in real time

    log.log(f"  $ {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        cwd=workspace,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Stream output line by line to both terminal and log
    for line in proc.stdout:
        line = line.rstrip("\n\r")
        if line:
            log.raw(line)

    proc.wait()

    if proc.returncode != 0:
        log.error(f"Command failed with exit code {proc.returncode}: {' '.join(cmd)}")
        return False

    return True


def _extract_last_val_bpb(log_path: Path):
    """Extract the most recent val_bpb value from the log file."""
    if not log_path.exists():
        return None
    val_bpb = None
    for line in log_path.read_text().splitlines():
        if "val_bpb:" in line:
            try:
                val_bpb = float(line.split("val_bpb:")[1].strip().split()[0])
            except (ValueError, IndexError):
                pass
    return val_bpb
