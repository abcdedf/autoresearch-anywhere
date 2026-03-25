# CLAUDE.md — autoresearch-anycloud

## Project Overview

**autoresearch-anycloud** — a Python CLI tool that wraps Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) to let researchers run autonomous AI experiments on Mac or any cloud platform with minimal infrastructure knowledge.

## Core Principle

The researcher thinks about the research problem. This tool thinks about the infrastructure.

## Outcomes

1. Researcher writes a declarative config file describing intent (topic, platform, budget)
2. One CLI command provisions infrastructure, runs autoresearch, collects results, tears down
3. Cost is estimated upfront and tracked during execution; pauses at user-defined threshold
4. Single unified log covers progress, results, cost, and troubleshooting
5. Works identically on Mac (local), AWS, GCP, Azure, and Oracle OCI

## Architecture Decisions

- **~90% common code** — only provider modules (thin SDK wrappers) are platform-specific
- **No Terraform** — all cloud provisioning uses native Python SDKs (boto3, google-cloud-compute, azure-mgmt-compute, oci). This follows SkyPilot/Ray best practices for ephemeral VM lifecycle.
- **Device abstraction** — PyTorch device detection (`cuda` / `mps` / `cpu`) is the only training code difference across platforms
- **Python CLI** (`click`) as the single entry point
- **`init` separates one-time setup from runtime** — platform preferences stored in `./config.yaml` (committed), no credentials stored in project
- **No credential storage** — API keys from env vars, cloud credentials from standard SDK auth (~/.aws/credentials, ~/.config/gcloud/, ~/.azure/, ~/.oci/config). Keys reach cloud VMs via SSH env vars at runtime, never written to disk.
- **uv** as the package manager (matching autoresearch upstream)
- **Optional dependencies** — `pip install autoresearch-anycloud[aws]` installs only what you need

## Development Constraints

- **Total cloud testing budget: ~$5-7** across all platforms
- **Most development/testing happens on Mac (free)** — CLI, config, cost engine, logging, orchestration
- **Cloud runs for validation** — ~2-3 real runs per cloud provider
- **Each test run costs ~$0.02-0.10** depending on provider

## Current Status

- Mac: verified, working end-to-end
- AWS: verified, working end-to-end
- GCP: verified, working end-to-end (L4 GPU, asia-northeast1-b)
- Azure: blocked on quota (A10, need 36 regional cores)
- OCI: code complete, not yet verified

## Enforcement Rules

- **No feature ships without logging.** If a command runs, its output goes to terminal AND log file. Period.
- **No silent failures.** Every subprocess must capture and surface stdout+stderr on failure.
- **Test after every change.** Run the command, check the log file, confirm it has what a researcher needs.
- **2 experiments for testing.** Keep `max_experiments: 2` until validated.
- **Logs directory must exist.** `init` creates it. `run` verifies it.
- **Always teardown.** Cloud runs use try/finally to guarantee resource cleanup.

### Run Monitoring Policy

When running `autoresearch-anycloud run` or any long-running command:

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

## Key Files

- `README.md` — user manual
- `config.yaml` — platform settings (committed, no credentials)
- `research.yaml` — research intent (committed)
- `autoresearch_ac/cli.py` — CLI entry point
- `autoresearch_ac/config.py` — declarative config parser
- `autoresearch_ac/orchestrator.py` — provision → setup → run → collect → teardown
- `autoresearch_ac/providers/aws.py` — AWS provider (boto3)
- `autoresearch_ac/providers/gcp.py` — GCP provider (google-cloud-compute)
- `autoresearch_ac/providers/azure.py` — Azure provider (azure-mgmt-compute)
- `autoresearch_ac/providers/oci.py` — Oracle OCI provider (oci SDK)
- `autoresearch_ac/providers/ssh.py` — shared SSH/SCP helper (paramiko)
- `platforms/mac/train.py` — Mac-adapted training script (based on miolini)
- `platforms/mac/prepare.py` — Mac-adapted data prep script (based on miolini)
- `upstream/autoresearch/` — Karpathy's original repo (git submodule)

## Coding Conventions

- Python 3.10+
- Keep it simple — no over-engineering
- No unnecessary abstractions
- Real error messages over generic ones
- **Every command must produce a log file** — no exceptions
