# autoresearch-aw

Run [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) on your Mac or any cloud GPU — one command, no infrastructure knowledge needed.

| Platform | GPU | Cost | Status |
|----------|-----|------|--------|
| Mac | Apple Silicon MPS | Free | Verified |
| AWS | A10G 24GB | $1.01/hr on-demand | Verified |
| GCP | T4 16GB | $0.35/hr | Ready to test |
| Azure | T4 16GB | $0.35/hr | Ready to test |
| Oracle OCI | A10 24GB | $0.50/hr | Ready to test |

## Get Running (Mac — 2 minutes)

```bash
git clone https://github.com/<org>/autoresearch-aw.git
cd autoresearch-aw
uv sync
autoresearch-aw init mac
autoresearch-aw run
```

That's it. Training starts immediately on your Mac. No cloud account. No API keys. No configuration.

> Don't have `uv`? Install it: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Monitor Your Run

Everything streams to your terminal AND to a log file. Open a second terminal to watch:

```bash
tail -f logs/run_latest.log
```

What you'll see:

```
[12:01:00] Platform:    Mac
[12:01:00] Experiments: 2 (~10 min)
[12:01:00] Est. cost:   $0.036 (GPU: $0.00, API: $0.036)
[12:01:05] [setup] Installing workspace dependencies...
[12:02:30] [prepare] Downloading data and training tokenizer...
[12:03:45] ── Experiment 1/2 ──
[12:03:45] [warmup 1/10] First 10 steps are warmup, training starts after...
[12:04:10] [training 30/60s] step 00050 | loss 3.812 | remaining: 30s
[12:04:50] Evaluating val_bpb...
[12:05:10] val_bpb: 2.124254
[12:05:10]   Cost: $0.02 / $5.00 (GPU: $0.00, API: $0.02)
[12:05:10] ── Experiment 2/2 ──
...
══════════════════════════════════════════════════
RUN SUMMARY
══════════════════════════════════════════════════
Experiments:  2
Total time:   535s (8.9 min)

 Exp     val_bpb      Time    Status
 ────  ──────────  ────────  ────────
   1    2.124254      208s        ok
   2    2.201822      327s        ok

Best val_bpb: 2.124254 (experiment 1)
GPU compute:  $0.00 (0.00/hr)
LLM API:      $0.04 (8,000 in + 4,000 out tokens, claude-sonnet)
Total cost:   $0.04 / $5.00 budget
══════════════════════════════════════════════════
```

Results are saved to `./results/<timestamp>/train.py`.

## Get Results

```bash
ls results/
```

Each run saves the final `train.py` (with all improvements the AI made) to a timestamped folder.

## Configure Your Research

Edit the included `research.yaml`:

```yaml
research:
  topic: "Improve training loss on TinyShakespeare"
  program: "program.md"
  max_experiments: 1       # set very low for quick demo. Upstream default: 100

platform: mac              # or: aws, gcp, azure, oci

budget:
  max_cost_usd: 5.00       # Cloud + API combined. Auto-stops if exceeded. For overnight cloud runs: 10-50
```

**Included defaults are set very low for a quick demo (~10 min).** For real research:
- `max_experiments: 100` — upstream default, runs overnight (12 experiments per hour, 5 min each)
- `budget: 10–50` — overnight cloud runs cost $5–25 depending on provider
- Training time per experiment is 60s (upstream default: 300s). This is configurable in the platform scripts.

## Run on Cloud GPUs

When you're ready for faster GPUs, change `platform:` in `research.yaml` and provide cloud credentials. The tool handles everything else — launching the VM, installing dependencies, running training, collecting results, and shutting down the VM.

### AWS (no CLI install needed)

1. [Create an AWS access key](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html) and download the CSV
2. Move the CSV to `~/.aws/credentials/` (create the folder if needed: `mkdir -p ~/.aws/credentials`)
3. Set `platform: aws` in `research.yaml`
4. Run:

```bash
autoresearch-aw init aws
autoresearch-aw run
```

`init aws` reads credentials from `~/.aws/credentials/` by default and verifies them. To use a different location: `autoresearch-aw init aws --credentials /path/to/accessKeys.csv`

A GPU VM launches automatically, trains, collects results, and shuts down. Estimated cloud cost: $0.13 for 1 experiment on an A10G GPU.

### GCP

1. Install Google Cloud CLI: `brew install google-cloud-sdk`
2. Authenticate: `gcloud auth application-default login` (opens browser)
3. Run `autoresearch-aw init gcp` and provide your project ID

### Azure

1. Install Azure CLI: `brew install azure-cli`
2. Authenticate: `az login` (opens browser)
3. Run `autoresearch-aw init azure` and provide your subscription ID

### Oracle OCI

1. Install OCI CLI: `brew install oci-cli`
2. Configure: `oci setup config` (follow prompts)
3. Run `autoresearch-aw init oci` and provide your compartment OCID

### Switching Platforms

Change one line in `research.yaml`:

```yaml
platform: gcp    # or: mac, aws, azure, oci
```

Same command. Different platform. Same results format.

## Cost Tracking

Cloud cost and API cost are tracked and reported separately:

- **Cloud cost**: estimated from public on-demand pricing × elapsed time. Sources: AWS/GCP/Azure/OCI pricing pages.
- **API cost**: estimated from token usage per experiment × published per-token rates. Each experiment sends train.py + git log + program.md to the LLM (4,000 input tokens) and gets back modified code (2,000 output tokens). If you have a subscription (Claude Pro, ChatGPT Plus) or free credits, your actual API cost may be $0.

After each experiment:
```
  Cloud cost: $0.08  |  API cost (est): $0.04  |  Budget: $5.00
```

Run summary:
```
Cloud cost:   $0.25 (on-demand rate: $1.01/hr)
API cost:     $0.07 estimated (8,000 in + 4,000 out tokens × claude-sonnet pay-per-token rate)
              Note: API cost may be $0 if you have a subscription or free credits
Total (est):  $0.32 / $5.00 budget
```

If combined cost hits your budget, the run stops automatically and results are collected.

## GPU Quota

Cloud providers limit GPU access by default. If your first cloud run fails with a capacity or quota error, you need to request GPU access (free, usually approved within hours):

| Provider | Where to request |
|----------|-----------------|
| AWS | [Service Quotas](https://console.aws.amazon.com/servicequotas/) → EC2 → search "G and VT" |
| GCP | [Quotas](https://console.cloud.google.com/iam-admin/quotas) → search "NVIDIA T4" |
| Azure | [Usage + quotas](https://portal.azure.com/) → search "NCasT4" |
| OCI | [Limits](https://cloud.oracle.com/limits) → search your GPU shape |

## Security

- Credentials never stored in the project — they live in standard locations on your machine (`~/.aws/`, `~/.config/gcloud/`, etc.)
- API keys reach cloud VMs via SSH environment variables at runtime, never written to disk
- VMs are destroyed after each run — no lingering resources

## Acknowledgments

- [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — the upstream project
- [miolini/autoresearch-macos](https://github.com/miolini/autoresearch-macos) — Mac MPS adaptation
- [trevin-creator/autoresearch-mlx](https://github.com/trevin-creator/autoresearch-mlx) — MLX adaptation

## License

MIT
