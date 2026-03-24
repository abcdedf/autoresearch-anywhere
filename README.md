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
[12:01:00] Experiments: 1 (~5 min)
[12:01:00] Est. cost:   $0.018 (GPU: $0.00, API: $0.018)
[12:01:05] [setup] Installing workspace dependencies...
[12:02:30] [prepare] Downloading data and training tokenizer...
[12:03:45] ── Experiment 1/1 ──
[12:03:45] [warmup 1/10] First 10 steps are warmup, training starts after...
[12:04:10] [training 30/60s] step 00050 | loss 3.812 | remaining: 30s
[12:04:50] Evaluating val_bpb...
[12:05:10] val_bpb: 2.124254
[12:05:10]   Cost: $0.02 / $5.00 (GPU: $0.00, API: $0.02)
══════════════════════════════════════════════════
RUN SUMMARY
══════════════════════════════════════════════════
Experiments:  1
Total time:   208s (3.5 min)

 Exp     val_bpb      Time    Status
 ────  ──────────  ────────  ────────
   1    2.124254      208s        ok

Best val_bpb: 2.124254 (experiment 1)
GPU compute:  $0.00 (0.00/hr)
LLM API:      $0.02 (4,000 in + 2,000 out tokens, claude-sonnet)
Total cost:   $0.02 / $5.00 budget
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
- Training time per experiment is 60s (upstream default: 300s).

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

### GCP (no CLI install needed)

1. [Create a GCP project](https://console.cloud.google.com/projectcreate) (or select an existing one from the dropdown at the top of any GCP console page)
2. Create a service account with Compute Admin access:
   - Go to [IAM → Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts)
   - Click **+ Create Service Account**
   - Enter a name (e.g. `autoresearch`) → click **Create and Continue**
   - Click **Select a role** → type `Compute Admin` → select it → click **Continue** → click **Done**
3. Download a JSON key for the service account:
   - You're back on the Service Accounts list. Click the service account you just created
   - Go to the **Keys** tab → click **Add Key** → **Create new key**
   - Select **JSON** → click **Create** — the key file downloads automatically (you can only download it once)
4. Move the JSON to `~/.config/gcloud/`:

```bash
mkdir -p ~/.config/gcloud
mv ~/Downloads/*.json ~/.config/gcloud/
```
5. Set `platform: gcp` in `research.yaml`
6. Run:

```bash
autoresearch-aw init gcp
autoresearch-aw run
```

`init gcp` reads credentials from `~/.config/gcloud/` by default and verifies them. To use a different location: `autoresearch-aw init gcp --credentials /path/to/key.json`

A GPU VM launches automatically, trains, collects results, and shuts down. Estimated cloud cost: $0.04 for 1 experiment on a T4 GPU (on-demand $0.35/hr).

### Azure (no CLI install needed)

1. [Create a service principal](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) in the Azure Portal:
   - Microsoft Entra ID → App registrations → New registration
   - Go to Certificates & secrets → New client secret → copy the **Value**
   - Note the **Application (client) ID** and **Directory (tenant) ID** from the Overview page
   - Go to Subscriptions → your subscription → copy the **Subscription ID**
   - In the subscription, go to Access control (IAM) → Add role assignment → **Contributor** → assign to your app
2. Save credentials as a JSON file at `~/.azure/service-principal.json` (create the folder if needed: `mkdir -p ~/.azure`):

```json
{
  "tenant_id": "your-tenant-id",
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "subscription_id": "your-subscription-id"
}
```

3. Set `platform: azure` in `research.yaml`
4. Run:

```bash
autoresearch-aw init azure
autoresearch-aw run
```

`init azure` reads credentials from `~/.azure/service-principal.json` by default and verifies them. It also checks the environment variables `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, and `AZURE_SUBSCRIPTION_ID`. To use a different file: `autoresearch-aw init azure --credentials /path/to/sp.json`

A GPU VM launches automatically, trains, collects results, and shuts down. Estimated cloud cost: $0.04 for 1 experiment on a T4 GPU (on-demand $0.35/hr).

### Oracle OCI

1. Install OCI CLI: `brew install oci-cli`
2. Generate an API signing key and config: `oci setup config` (follow prompts — it creates `~/.oci/config` with your tenancy, user, region, and PEM key)
3. Find your compartment OCID: OCI Console → Identity & Security → Compartments → copy the OCID
4. Add the compartment to your OCI config: add `compartment=ocid1.compartment.oc1..xxxxx` to the `[DEFAULT]` section of `~/.oci/config`
5. Set `platform: oci` in `research.yaml`
6. Run:

```bash
autoresearch-aw init oci
autoresearch-aw run
```

`init oci` reads credentials from `~/.oci/config` by default and verifies them. To use a different config file: `autoresearch-aw init oci --credentials /path/to/oci/config`. The compartment OCID can also be provided via the `OCI_COMPARTMENT_ID` environment variable instead of adding it to the config file.

Estimated cloud cost: $0.08 for 1 experiment on an A10 GPU (on-demand $0.50/hr).

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

- Credentials never stored in the project — they live in standard locations on your machine (`~/.aws/`, `~/.config/gcloud/`, `~/.azure/`, etc.)
- API keys reach cloud VMs via SSH environment variables at runtime, never written to disk
- VMs are destroyed after each run — no lingering resources

## Acknowledgments

- [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — the upstream project
- [miolini/autoresearch-macos](https://github.com/miolini/autoresearch-macos) — Mac MPS adaptation
- [trevin-creator/autoresearch-mlx](https://github.com/trevin-creator/autoresearch-mlx) — MLX adaptation

## License

MIT
