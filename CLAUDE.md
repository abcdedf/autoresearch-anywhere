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
- `autoresearch_aw/cost.py` — cost estimation and tracking
- `autoresearch_aw/orchestrator.py` — provision → setup → run → collect → teardown
- `autoresearch_aw/logging.py` — unified logging
- `terraform/gcp/` — GCP Terraform module
- `terraform/aws/` — AWS Terraform module
- `terraform/azure/` — Azure Terraform module

## Coding Conventions

- Python 3.10+
- Keep it simple — no over-engineering
- No unnecessary abstractions
- Real error messages over generic ones
