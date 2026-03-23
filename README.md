# autoresearch-aw

**Autoresearch from Anywhere** — run [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) on your Mac or any cloud platform with a single command. You don't need any infrastructure expertise to get started, and built-in cost guardrails let you experiment with confidence instead of anxiety.

## What It Does

- Provisions infrastructure, runs autoresearch, collects results, tears down — automatically
- Estimates cost before starting, tracks it during execution, pauses if you exceed your budget
- One unified log for progress, results, cost, and troubleshooting
- Same CLI across all platforms

## Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) package manager
- [Terraform](https://www.terraform.io/) (for cloud platforms only)
- API keys set as environment variables in your shell profile (see [API Keys](#api-keys))

## Installation

```bash
git clone https://github.com/<org>/autoresearch-aw.git
cd autoresearch-aw
uv sync
```

## API Keys

autoresearch-aw does not store any API keys or credentials. It relies on standard environment variables and cloud CLI authentication that you configure once in your shell profile.

### AI Provider Keys

Add to your `~/.zshrc` (or `~/.bash_profile`):

```bash
# Anthropic (Claude)
export ANTHROPIC_API_KEY=your-key-here

# OpenAI (if using OpenAI models)
export OPENAI_API_KEY=your-key-here
```

Get your keys from:
- **Anthropic:** [console.anthropic.com](https://console.anthropic.com) → API Keys
- **OpenAI:** [platform.openai.com](https://platform.openai.com) → API Keys

### Cloud Credentials

Cloud providers use their own CLI tools to manage authentication. Set these up once and autoresearch-aw (and Terraform) will use them automatically:

| Provider | Auth Command | Credentials Stored In |
|----------|-------------|----------------------|
| GCP | `gcloud auth login && gcloud auth application-default login` | `~/.config/gcloud/` |
| AWS | `aws configure` | `~/.aws/credentials` |
| Azure | `az login` | `~/.azure/` |

### How Keys Reach Cloud VMs

When running on cloud platforms, API keys are passed to the VM as environment variables over SSH at runtime. They are never written to disk on the VM and are destroyed when the VM is torn down after the run.

## One-Time Setup

Run `init` once per platform. This stores platform preferences in `./config.yaml` so you never pass them again.

### Mac

```bash
autoresearch-aw init mac
```

No credentials needed. Detects Apple Silicon and verifies PyTorch MPS support.

### GCP

Before running init, complete the [GCP prerequisites](#gcp-prerequisites).

```bash
autoresearch-aw init gcp
```

Prompts for:
```
GCP project:  my-project
Region:       us-central1
Zone:         us-central1-a
Use spot instances? [Y/n]: Y
```

### AWS

Before running init, complete the [AWS prerequisites](#aws-prerequisites).

```bash
autoresearch-aw init aws
```

Prompts for:
```
AWS profile:  default
Region:       us-east-1
Use spot instances? [Y/n]: Y
```

### Azure

Before running init, complete the [Azure prerequisites](#azure-prerequisites).

```bash
autoresearch-aw init azure
```

Prompts for:
```
Subscription ID:  xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Region:           eastus
Use spot instances? [Y/n]: Y
```

### General Settings

The first time you run any `init`, it also prompts for general settings:

```
Log directory [./logs]:
```

All commands (run, estimate, dry-run, teardown) write to this log directory. Each invocation creates a timestamped log file. Output always goes to both terminal and log file. The default `./logs/` directory is git-ignored.

### Stored Config

`init` writes `./config.yaml` (committed to repo):

```yaml
log_dir: "./logs"

platforms:
  mac:
    enabled: true
  gcp:
    project: "my-project"
    region: "us-central1"
    zone: "us-central1-a"
    instance_type: "n1-standard-4"
    gpu_type: "nvidia-tesla-t4"
    use_spot: true
  aws:
    profile: "default"
    region: "us-east-1"
    instance_type: "g5.xlarge"
    use_spot: true
  azure:
    subscription: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    region: "eastus"
    instance_type: "Standard_NC4as_T4_v3"
    use_spot: true
```

No credentials or API keys are stored in this file. You can edit it directly or re-run `autoresearch-aw init <platform>` anytime.

## Quick Start

### 1. Create a Research File

Create `research.yaml`:

```yaml
research:
  topic: "Improve training loss on TinyShakespeare"
  program: "program.md"
  max_experiments: 12

platform: mac          # mac | gcp | aws | azure

budget:
  max_cost_usd: 5.00
```

The research file is **only about your research intent** — what to run, where, and your budget. No infrastructure details.

### 2. Estimate Cost

```bash
autoresearch-aw estimate
```

```
Platform:       Mac (local, Apple Silicon MPS)
Experiments:    12 (~60 min)
Estimated cost: $0.00 (local compute)
```

### 3. Run

```bash
autoresearch-aw run
```

That's it. Results appear in `./results/` when done.

### Custom Config

By default, commands look for `research.yaml` in the current directory. To use a different file:

```bash
autoresearch-aw run my-experiment.yaml
```

### Switch Platforms

Change one line in `research.yaml`:

```yaml
platform: gcp    # mac | gcp | aws | azure
```

```bash
autoresearch-aw run
```

Same command. Different platform.

## CLI Reference

### Commands

| Command | Description |
|---------|-------------|
| `autoresearch-aw init <platform>` | One-time platform setup (mac/gcp/aws/azure) |
| `autoresearch-aw config` | Show current configuration (init settings + research file) |
| `autoresearch-aw run [config]` | Run autoresearch end to end |
| `autoresearch-aw estimate [config]` | Show cost estimate without running |
| `autoresearch-aw status` | Show status of a running session |
| `autoresearch-aw stop` | Gracefully stop, collect results, tear down |
| `autoresearch-aw teardown` | Force destroy cloud resources |

`[config]` is optional. Defaults to `research.yaml` in the current directory.

### Options

```bash
autoresearch-aw run --dry-run    # terraform plan only, no provisioning
autoresearch-aw run --verbose    # detailed logging
```

No platform flags. No log path. All configuration comes from `init`.

### Viewing Current Configuration

```bash
autoresearch-aw config
```

```
── Init Settings ──────────────────────────
Log directory:    ./logs

Platforms configured:
  mac:    enabled (Apple Silicon MPS)
  gcp:    my-project / us-central1-a / T4 spot
  aws:    default profile / us-east-1 / g5.xlarge spot
  azure:  not configured

── Research File (research.yaml) ──────────
Topic:            Improve training loss on TinyShakespeare
Program:          program.md
Max experiments:  12
Platform:         mac
Budget:           $5.00

── Credentials ────────────────────────────
ANTHROPIC_API_KEY:  set
GCP (gcloud):       authenticated
AWS (aws cli):      configured (profile: default)
Azure (az cli):     not logged in
```

## Research Config Reference

```yaml
# What to research
research:
  topic: "Improve training loss on TinyShakespeare"
  program: "program.md"           # your autoresearch program.md
  max_experiments: 12              # number of 5-min cycles

# Where to run
platform: mac                      # mac | gcp | aws | azure

# Cost controls
budget:
  max_cost_usd: 5.00               # pause and ask before exceeding
```

That's the entire config. Platform details are handled by `init`.

## Platform Prerequisites

### Mac Prerequisites

No cloud setup needed.

1. Apple Silicon Mac (M1 or later)
2. Python 3.10+ and uv installed

```bash
python3 --version
uv --version
```

### GCP Prerequisites

1. **Create a GCP account** at [cloud.google.com](https://cloud.google.com)
2. **Create a project** in the GCP Console
3. **Enable the Compute Engine API** for your project
4. **Install gcloud CLI**:
   ```bash
   brew install google-cloud-sdk
   ```
5. **Authenticate**:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   ```
6. **Request GPU quota** — request T4 GPU quota in your desired region via GCP Console → IAM & Admin → Quotas

### AWS Prerequisites

1. **Create an AWS account** at [aws.amazon.com](https://aws.amazon.com)
2. **Install AWS CLI**:
   ```bash
   brew install awscli
   ```
3. **Configure credentials**:
   ```bash
   aws configure
   ```
   You'll need your Access Key ID and Secret Access Key. Generate these in AWS Console → IAM → Users → Security Credentials.
4. **Request GPU quota** — request G5 instance quota in your desired region via AWS Console → Service Quotas → EC2

### Azure Prerequisites

1. **Create an Azure account** at [azure.microsoft.com](https://azure.microsoft.com)
2. **Install Azure CLI**:
   ```bash
   brew install azure-cli
   ```
3. **Authenticate**:
   ```bash
   az login
   ```
4. **Request GPU quota** — request NCasT4_v3 series quota in your desired region via Azure Portal → Subscriptions → Usage + Quotas

## Unified Log

All commands write to both terminal and a timestamped log file in your configured log directory:

```
[12:01:00] Platform: GCP (us-central1, T4 spot)
[12:01:00] Estimated cost: $0.22 for 12 experiments
[12:01:05] Provisioning infrastructure...
[12:02:30] VM ready: 34.56.78.90
[12:02:35] Installing dependencies...
[12:03:45] Starting autoresearch (12 experiments, ~60 min)
[12:03:45] ── Experiment 1/12 ──
[12:08:50] val_bpb: 1.234 (baseline)
[12:08:51] Cost so far: $0.02
[12:08:51] ── Experiment 2/12 ──
[12:13:55] val_bpb: 1.198 (improved, keeping)
[12:13:56] Cost so far: $0.04
...
[13:05:00] ── Complete ──
[13:05:00] Best val_bpb: 1.087 (experiment 9)
[13:05:00] Total cost: $0.22
[13:05:01] Collecting results...
[13:05:10] Results saved to ./results/
[13:05:11] Tearing down infrastructure...
[13:05:30] Done. Resources destroyed.
```

## Cost Tracking

Before each run, you see an estimate. During the run, cost is tracked. If you approach your budget, the tool pauses:

```
[13:30:00] Cost: $4.85 / $5.00 budget
[13:30:00] Approaching budget limit. Pausing after current experiment.
[13:35:00] Budget threshold reached ($5.02 / $5.00).
           [c]ontinue with $5 more | [s]top and collect results | [t]eardown immediately
           >
```

## Results

After a run, results are saved to `./results/<timestamp>/`:

```
results/
  2026-03-23T120100/
    train.py              # final version of training code
    experiments.log       # full experiment history
    best_model/           # best checkpoint
    cost_report.txt       # cost breakdown
```

## Security

- **No credentials stored in the project.** API keys live in your shell profile. Cloud credentials are managed by their respective CLIs.
- **API keys reach cloud VMs via SSH environment variables** at runtime. They exist only in process memory on the VM and are never written to disk.
- **VMs are destroyed after each run.** No persistent infrastructure, no lingering secrets.
- **Future improvement:** Cloud secret managers (GCP Secret Manager, AWS Secrets Manager, Azure Key Vault) for enhanced key delivery.

## License

MIT
