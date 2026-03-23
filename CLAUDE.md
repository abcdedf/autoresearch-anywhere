# CLAUDE.md — autoresearch-aw

## Project Overview

**autoresearch-aw (Autoresearch from Anywhere)** — a Python CLI tool that wraps Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) to let researchers run autonomous AI experiments on Mac or any cloud platform with minimal infrastructure knowledge.

## Core Principle

The researcher thinks about the research problem. This tool thinks about the infrastructure.

## Outcomes

1. Researcher writes a declarative config file describing intent (topic, platform, budget)
2. One CLI command provisions infrastructure, runs autoresearch, collects results, tears down
3. Cost is estimated upfront and tracked during execution; pauses at user-defined threshold
4. Single unified log covers progress, results, cost, and troubleshooting
5. Works identically on Mac (local), GCP, AWS, and Azure

## Architecture Decisions

- **~90% common code** — only Terraform modules and a thin local-vs-remote execution layer are platform-specific
- **Device abstraction** — PyTorch device detection (`cuda` / `mps` / `cpu`) is the only training code difference across platforms
- **Terraform** for all cloud provisioning
- **Python CLI** (`click` or `argparse`) as the single entry point
- **`init` separates one-time setup from runtime** — platform preferences stored in `./config.yaml` (committed), no credentials stored in project
- **No credential storage** — API keys come from environment variables (`ANTHROPIC_API_KEY` in `~/.zshrc`), cloud credentials from CLI tools (`gcloud`, `aws`, `az`). Keys reach cloud VMs via SSH env vars at runtime, never written to disk.
- **uv** as the package manager (matching autoresearch upstream)

## Development Constraints

- **Total cloud testing budget: ~$5-7** across all platforms
- **Most development/testing happens on Mac (free)** — CLI, config, cost engine, logging, orchestration
- **Cloud runs only for Terraform validation** — ~5-8 real runs per cloud provider
- **Each test run costs ~$0.02** (GCP T4 spot, 12 min)
- **Use `terraform plan` (dry run)** to validate templates before `apply`

## Current Goal

Get `autoresearch-aw run` working end-to-end on Mac with clear feedback at every step.

### Milestones (in order)

1. **Logging works** — every command writes to terminal AND timestamped log file in `./logs/`
2. **`run` gives clear, real-time progress** — the researcher sees what phase they're in (data prep, training, eval), what step, and how long remains. Never silence.
3. **Errors are specific and actionable** — if something fails, the log says exactly what and why. No "command failed" without context.
4. **End-to-end Mac run succeeds** — `autoresearch-aw run` completes with val_bpb in results
5. **Push to GitHub**
6. Cloud platforms (later)

### Enforcement Rules

- **No feature ships without logging.** If a command runs, its output goes to terminal AND log file. Period.
- **No silent failures.** Every subprocess must capture and surface stdout+stderr on failure.
- **Test after every change.** Run the command, check the log file, confirm it has what a researcher needs.
- **2 experiments for testing.** Keep `max_experiments: 2` until Mac is validated.
- **Logs directory must exist.** `init` creates it. `run` verifies it. No command should fail because `./logs/` is missing.

### Run Monitoring Policy

When running `autoresearch-aw run` or any long-running command:

1. **Launch the run in background** using `run_in_background`.
2. **Monitor `logs/run_latest.log` every 20 seconds** — read the last ~20 lines to check progress.
3. **If you see an error, failure, or unexpected output** — abort the run immediately, diagnose the issue from the log, fix it, and rerun.
4. **If the log is silent for 2 consecutive monitoring intervals (40 sec)** — abort immediately. Silent log means the orchestrator is not streaming output properly. Fix the logging, then rerun.
5. **Only read the log file** — do not check workspace, results, or other files during monitoring. The log is the single source of truth.
6. **When the run completes** — read the full log to confirm success (look for `val_bpb` and `Done`).

## Upstream & Attribution

- [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — upstream project (git submodule at `upstream/autoresearch/`)
- [miolini/autoresearch-macos](https://github.com/miolini/autoresearch-macos) — Mac MPS adaptation our Mac platform is based on
- Platform-adapted scripts live in `platforms/mac/` with attribution headers

## Iteration Plan

- Iterations 1-5: All on Mac ($0) — CLI, config, cost engine, logging, orchestration, local training
- Iterations 6-8: Cloud validation (~$3-5) — Terraform apply per provider
- Iterations 9-10: Cross-platform polish (~$1-2) — final validation, docs

## Key Files

- `README.md` — user manual
- `config.yaml` — platform settings (committed, no credentials)
- `research.yaml` — research intent (committed)
- `autoresearch_aw/cli.py` — CLI entry point
- `autoresearch_aw/config.py` — declarative config parser
- `autoresearch_aw/orchestrator.py` — provision → setup → run → collect → teardown
- `platforms/mac/train.py` — Mac-adapted training script (based on miolini)
- `platforms/mac/prepare.py` — Mac-adapted data prep script (based on miolini)
- `upstream/autoresearch/` — Karpathy's original repo (git submodule)
- `terraform/gcp/` — GCP Terraform module
- `terraform/aws/` — AWS Terraform module
- `terraform/azure/` — Azure Terraform module

## Coding Conventions

- Python 3.10+
- Keep it simple — no over-engineering
- No unnecessary abstractions
- Real error messages over generic ones
- **Every command must produce a log file** — no exceptions
