"""Orchestrator: provision → setup → run → collect → teardown."""

import os
import shutil
import subprocess
import sys
import threading
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
        print("Error: No config found. Run 'autoresearch-anywhere init <platform>' first.")
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
        elif platform == "aws":
            _run_cloud(config, research, max_experiments, verbose, log, "aws")
        elif platform == "gcp":
            _run_cloud(config, research, max_experiments, verbose, log, "gcp")
        elif platform == "azure":
            _run_cloud(config, research, max_experiments, verbose, log, "azure")
        elif platform == "oci":
            _run_cloud(config, research, max_experiments, verbose, log, "oci")
        else:
            log.error(f"Unknown platform '{platform}'. Use: mac, aws, gcp, azure, oci")
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

    from autoresearch_aw.cost import CostTracker, estimate_run_cost

    cost = estimate_run_cost("mac", "mac", max_experiments)
    budget = research.get("budget", {}).get("max_cost_usd", 5.0)
    tracker = CostTracker(gpu_hourly_rate=0.0, budget_usd=budget, log=log)

    log.log(f"Platform:    Mac")
    log.log(f"Experiments: {max_experiments} (~{max_experiments * 5} min)")
    log.log(f"Est. cost:   ${cost['total_cost_usd']:.3f} (GPU: $0.00, API: ${cost['llm_cost_usd']:.3f})")
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
        tracker.record_experiment()
        tracker.log_status()

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
    mac_device = config.get('platforms', {}).get('mac', {}).get('apple_silicon', False) and 'Apple Silicon MPS' or 'CPU'
    _print_summary(log, f"Mac ({mac_device})", config, max_experiments, total_elapsed, results, results_dir, tracker)


# GPU tuning: upstream train.py hardcodes for H100 80GB.
# We sed the constants to fit the actual GPU. No upstream code changes.
GPU_TUNING = {
    "g5.xlarge": {  # AWS A10G 24GB
        "gpu_name": "A10G 24GB",
        "patches": [
            ("DEVICE_BATCH_SIZE = 128", "DEVICE_BATCH_SIZE = 32"),
            ("TOTAL_BATCH_SIZE = 2\\*\\*19", "TOTAL_BATCH_SIZE = 2**17"),
        ],
    },
    "g2-standard-4": {  # GCP L4 24GB
        "gpu_name": "L4 24GB",
        "patches": [
            ("DEVICE_BATCH_SIZE = 128", "DEVICE_BATCH_SIZE = 32"),
            ("TOTAL_BATCH_SIZE = 2\\*\\*19", "TOTAL_BATCH_SIZE = 2**17"),
        ],
    },
    "Standard_NV36ads_A10_v5": {  # Azure A10 24GB
        "gpu_name": "A10 24GB",
        "patches": [
            ("DEVICE_BATCH_SIZE = 128", "DEVICE_BATCH_SIZE = 32"),
            ("TOTAL_BATCH_SIZE = 2\\*\\*19", "TOTAL_BATCH_SIZE = 2**17"),
        ],
    },
    "VM.GPU.A10.1": {  # OCI A10 24GB
        "gpu_name": "A10 24GB",
        "patches": [
            ("DEVICE_BATCH_SIZE = 128", "DEVICE_BATCH_SIZE = 32"),
            ("TOTAL_BATCH_SIZE = 2\\*\\*19", "TOTAL_BATCH_SIZE = 2**17"),
        ],
    },
}


def _get_gpu_tuning(platform: str, config: dict) -> dict | None:
    """Return GPU-specific patches for the target instance type."""
    instance_type = config.get("platforms", {}).get(platform, {}).get("instance_type", "")
    return GPU_TUNING.get(instance_type)


EXPERIMENT_TIMEOUT_OVERHEAD = 300  # seconds added to TIME_BUDGET for warmup, CUDA compile, eval
EXPERIMENT_TIMEOUT_DEFAULT = 600   # fallback if TIME_BUDGET can't be read (300s + 300s)


class BudgetWatchdog:
    """Background thread that checks cost every 30s and signals abort if over budget."""

    def __init__(self, tracker, abort_event: threading.Event, log=None, interval: int = 30):
        self.tracker = tracker
        self.abort_event = abort_event
        self.log = log
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        while not self._stop.wait(self.interval):
            if self.tracker.is_over_budget():
                if self.log:
                    self.log.log(f"  [watchdog] Budget exceeded (${self.tracker.total_cost_usd:.2f} / ${self.tracker.budget_usd:.2f}). Aborting experiment.")
                self.abort_event.set()
                return


def _get_experiment_timeout(project_root: Path, platform: str) -> int:
    """Derive experiment timeout from TIME_BUDGET in prepare.py.

    Returns TIME_BUDGET * multiplier to allow for CUDA compile, eval, and overhead.
    Falls back to a safe default if TIME_BUDGET can't be read.
    """
    import re as _re

    # Cloud uses upstream prepare.py; Mac uses platform-adapted one
    if platform == "mac":
        prepare_path = project_root / "platforms" / "mac" / "prepare.py"
    else:
        prepare_path = project_root / "upstream" / "autoresearch" / "prepare.py"

    if prepare_path.exists():
        for line in prepare_path.read_text().splitlines():
            match = _re.match(r'^TIME_BUDGET\s*=\s*(\d+)', line)
            if match:
                time_budget = int(match.group(1))
                return time_budget + EXPERIMENT_TIMEOUT_OVERHEAD

    return EXPERIMENT_TIMEOUT_DEFAULT


def _load_provider(platform: str):
    """Import and return the provider module for a given platform."""
    if platform == "aws":
        from autoresearch_aw.providers import aws as provider
    elif platform == "gcp":
        from autoresearch_aw.providers import gcp as provider
    elif platform == "azure":
        from autoresearch_aw.providers import azure as provider
    elif platform == "oci":
        from autoresearch_aw.providers import oci as provider
    else:
        raise ValueError(f"Unknown cloud platform: {platform}")
    return provider


def _run_cloud(config, research, max_experiments, verbose, log: Logger, platform: str):
    """Run autoresearch on any cloud platform (AWS/GCP/Azure/OCI).

    All cloud providers share the same flow:
    provision → SSH → upload scripts → prepare data → train → collect → teardown
    """
    from autoresearch_aw.providers.ssh import RemoteRunner

    provider = _load_provider(platform)
    project_root = Path(__file__).parent.parent
    platform_upper = platform.upper()

    # SSH user varies by provider
    ssh_user = {"aws": "ubuntu", "gcp": "ubuntu", "azure": "azureuser", "oci": "ubuntu"}.get(platform, "ubuntu")

    from autoresearch_aw.cost import CostTracker, estimate_run_cost

    # Cost estimate upfront
    instance_type = config.get("platforms", {}).get(platform, {}).get("instance_type", "unknown")
    budget = research.get("budget", {}).get("max_cost_usd", 5.0)
    cost = estimate_run_cost(platform, instance_type, max_experiments)

    log.log(f"Platform:    {platform_upper} ({instance_type})")
    log.log(f"Experiments: {max_experiments}")
    log.log(f"Est. cost:   ${cost['total_cost_usd']:.2f} (GPU: ${cost['gpu_cost_usd']:.2f} + API: ${cost['llm_cost_usd']:.3f})")
    log.log(f"Budget:      ${budget:.2f}")
    log.log()

    if cost["total_cost_usd"] > budget:
        log.error(f"Estimated cost ${cost['total_cost_usd']:.2f} exceeds budget ${budget:.2f}. Aborting.")
        sys.exit(1)

    tracker = CostTracker(
        gpu_hourly_rate=cost["gpu_hourly_rate"],
        llm_model=cost["llm_model"],
        budget_usd=budget,
        log=log,
        use_spot=config.get("platforms", {}).get(platform, {}).get("use_spot", False),
    )

    instance_info = None
    try:
        # Step 0: Provision
        log.log(f"[provision] Launching {platform_upper} instance...")
        instance_info = provider.provision(config, log)
        public_ip = instance_info["public_ip"]
        key_path = instance_info["key_path"]
        tracker.start_gpu()
        log.log()

        # Step 1: Connect and setup
        with RemoteRunner(public_ip, user=ssh_user, key_path=key_path, log=log) as ssh:
            remote_dir = f"/home/{ssh_user}/autoresearch"
            ssh.run(f"mkdir -p {remote_dir}")

            # Upload upstream autoresearch project (scripts + dependency manifest)
            upstream_dir = project_root / "upstream" / "autoresearch"
            if (upstream_dir / "train.py").exists():
                for fname in ["train.py", "prepare.py", "pyproject.toml", "uv.lock"]:
                    fpath = upstream_dir / fname
                    if fpath.exists():
                        ssh.upload(str(fpath), f"{remote_dir}/{fname}")
            else:
                # Fallback: upload platform-adapted scripts
                platforms_dir = project_root / "platforms" / "mac"
                ssh.upload(str(platforms_dir / "train.py"), f"{remote_dir}/train.py")
                ssh.upload(str(platforms_dir / "prepare.py"), f"{remote_dir}/prepare.py")
                log.log("[warn] Using Mac-adapted scripts (upstream not found). CUDA path preferred.")

            # Upload program.md if exists
            program_file = research.get("research", {}).get("program", "program.md")
            program_path = project_root / program_file
            if program_path.exists():
                ssh.upload(str(program_path), f"{remote_dir}/program.md")

            log.log()

            # Tune upstream defaults for the target GPU (upstream hardcodes for H100 80GB)
            gpu_tuning = _get_gpu_tuning(platform, config)
            if gpu_tuning:
                log.log(f"[setup] Tuning train.py for {gpu_tuning['gpu_name']}...")
                for old, new in gpu_tuning["patches"]:
                    ssh.run(f"sed -i 's/{old}/{new}/' {remote_dir}/train.py")

            # Build env prefix for forwarding tokens to remote commands
            # (passed inline, never written to disk — see CLAUDE.md security policy)
            env_prefix = ""
            for token_var in ("HF_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
                token_val = os.environ.get(token_var)
                if token_val:
                    env_prefix += f"{token_var}={token_val} "

            # Install uv and sync upstream dependencies on remote
            log.log("[setup] Installing uv and dependencies on remote...")
            ssh.run("curl -LsSf https://astral.sh/uv/install.sh | sh")
            ssh.run(f"cd {remote_dir} && ~/.local/bin/uv sync")
            log.log("[setup] Done.")
            log.log()

            # Step 2: Data preparation
            log.log("[prepare] Downloading data and training tokenizer...")
            exit_code, _ = ssh.run(f"cd {remote_dir} && {env_prefix}~/.local/bin/uv run prepare.py --num-shards 2")
            if exit_code != 0:
                log.error("Data preparation failed on remote. Cannot continue.")
                return
            log.log("[prepare] Done.")
            log.log()

            # Step 3: Run training experiments
            results = []
            run_start = time.time()
            experiment_timeout = _get_experiment_timeout(project_root, platform)
            log.log(f"[config] Experiment timeout: {experiment_timeout}s")

            # Budget watchdog: checks cost every 30s, aborts if over budget
            # TODO(backlog): validate end-to-end on a real cloud run — see BACKLOG.md
            abort_event = threading.Event()
            watchdog = BudgetWatchdog(tracker, abort_event, log=log)
            watchdog.start()

            try:
                for i in range(1, max_experiments + 1):
                    log.log(f"── Experiment {i}/{max_experiments} ──")
                    if i == 1:
                        log.log("  Note: first experiment includes one-time CUDA kernel compilation (~2 min).")
                        log.log("  The log will be silent during compilation — this is expected.")
                    t0 = time.time()

                    abort_event.clear()
                    exit_code, output = ssh.run(
                        f"cd {remote_dir} && {env_prefix}~/.local/bin/uv run train.py",
                        timeout=experiment_timeout,
                        abort_event=abort_event,
                    )

                    elapsed = time.time() - t0
                    ok = exit_code == 0

                    if abort_event.is_set():
                        log.log(f"  Experiment {i} aborted (budget exceeded) after {elapsed:.0f}s")
                        results.append((i, None, elapsed, False))
                        break
                    elif exit_code == -1:
                        log.log(f"  Experiment {i} timed out after {elapsed:.0f}s (limit: {experiment_timeout}s)")
                        results.append((i, None, elapsed, False))
                        break
                    elif ok:
                        log.log(f"  Completed in {elapsed:.0f}s")
                    else:
                        log.error(f"  Experiment {i} failed after {elapsed:.0f}s")

                    # Extract val_bpb from output
                    val_bpb = None
                    for line in output.splitlines():
                        if "val_bpb:" in line:
                            try:
                                val_bpb = float(line.split("val_bpb:")[1].strip().split()[0])
                            except (ValueError, IndexError):
                                pass

                    results.append((i, val_bpb, elapsed, ok))
                    tracker.record_experiment()
                    tracker.log_status()

                    # Budget check between experiments
                    if tracker.is_over_budget() and i < max_experiments:
                        log.log(f"  Budget limit reached (${tracker.total_cost_usd:.2f} / ${budget:.2f}). Stopping.")
                        break

                    log.log()
            finally:
                watchdog.stop()

            total_elapsed = time.time() - run_start

            # Step 4: Collect results
            log.log("[results] Collecting results from remote...")
            timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
            results_dir = project_root / "results" / timestamp
            results_dir.mkdir(parents=True, exist_ok=True)

            try:
                ssh.download(f"{remote_dir}/train.py", str(results_dir / "train.py"))
            except Exception as e:
                log.log(f"[results] Could not download train.py: {e}")

            log.log(f"[results] Saved to {results_dir}")
            log.log()

        # Summary
        _print_summary(log, platform_upper, config, max_experiments, total_elapsed, results, results_dir, tracker)

    except Exception as e:
        log.error(f"Run failed: {e}")
    finally:
        # Always teardown
        if instance_info:
            log.log()
            log.log(f"[teardown] Cleaning up {platform_upper} resources...")
            try:
                provider.teardown(instance_info, log)
            except Exception as e:
                log.error(f"Teardown failed: {e}")
                log.error(f"MANUAL CLEANUP NEEDED: check {platform_upper} console for orphaned resources")


def _print_summary(log, platform_name, config, max_experiments, total_elapsed, results, results_dir, cost_tracker=None):
    """Print run summary table — shared across all platforms."""
    log.log("═" * 50)
    log.log("RUN SUMMARY")
    log.log("═" * 50)
    log.log(f"Platform:     {platform_name}")
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

    # Cost summary
    if cost_tracker:
        log.log()
        cost_tracker.log_summary()

    log.log()
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
