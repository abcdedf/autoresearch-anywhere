# autoresearch-anywhere

Run [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) on your Mac or any cloud GPU — one command, no infrastructure knowledge needed.

| Platform | GPU | Cost | Status |
|----------|-----|------|--------|
| Mac | Apple Silicon MPS | Free | Verified |
| AWS | A10G 24GB | $1.01/hr on-demand | Verified |
| GCP | T4 16GB | $0.35/hr | Coming soon |
| Azure | T4 16GB | $0.53/hr | Coming soon |
| Oracle OCI | A10 24GB | $0.50/hr | Coming soon |

## Get Running (Mac — 2 minutes)

1. Install uv (if you don't have it): `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Set your LLM API key (add to `~/.zshrc` so it persists):

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # if using Claude
export OPENAI_API_KEY=sk-...          # if using OpenAI
```

3. Run:

```bash
git clone https://github.com/abcdedf/autoresearch-anywhere.git
cd autoresearch-anywhere
uv sync
autoresearch-anywhere init mac
autoresearch-anywhere run
```

That's it. Training starts immediately on your Mac. No cloud account. No configuration.

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

**Included defaults are set very low for a quick demo (~5 min).** For real research:
- `max_experiments: 100` — upstream default, runs overnight (12 experiments per hour, 5 min each)
- `budget: 10–50` — overnight cloud runs cost $5–25 depending on provider
- Training time per experiment is 60s (upstream default: 300s).

## Run on Cloud GPUs

When you're ready for faster GPUs, change `platform:` in `research.yaml` and provide cloud credentials. The tool handles everything else — launching the VM, installing dependencies, running training, collecting results, and shutting down the VM.

> **GPU quota required**: All cloud providers limit GPU access by default (quota = 0). Your first run will likely fail with a quota error. Request GPU access **before** your first run — it's free to apply but approval can take hours to days for new accounts. See [GPU Quota](#gpu-quota) below for links.

> **Note on GPU compatibility**: Upstream autoresearch hardcodes batch sizes for H100 80GB GPUs. Cloud GPUs (A10G 24GB, T4 16GB) have less VRAM and will OOM with those defaults. As a workaround, this tool patches batch sizes via `sed` before training. We've submitted a [PR to upstream](https://github.com/karpathy/autoresearch/pull/402) to make these values configurable via environment variables.

### AWS (no CLI install needed)

1. [Create an AWS access key](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html) and download the CSV
2. Move the CSV to `~/.aws/credentials/` (create the folder if needed: `mkdir -p ~/.aws/credentials`)
3. Set `platform: aws` in `research.yaml`
4. Run:

```bash
autoresearch-anywhere init aws
autoresearch-anywhere run
```

`init aws` reads credentials from `~/.aws/credentials/` by default and verifies them. To use a different location: `autoresearch-anywhere init aws --credentials /path/to/accessKeys.csv`

A GPU VM launches automatically, trains, collects results, and shuts down. Estimated cloud cost: $0.13 for 1 experiment on an A10G GPU.

### GCP (no CLI install needed)

1. [Create a GCP project](https://console.cloud.google.com/projectcreate) (or select an existing one from the dropdown at the top of any GCP console page)
2. Create a service account with Compute Admin access:
   - Go to [IAM → Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts)
   - Click **+ Create Service Account**
   - Enter a name (e.g. `autoresearch`) → click **Create and Continue**
   - Click **Select a role** → type `Compute Admin` → select it → click **Continue** → click **Done**
   - (If you skipped the role: go to [IAM](https://console.cloud.google.com/iam-admin/iam) → **Grant Access** → paste the service account email → add **Compute Admin** role → **Save**)
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
autoresearch-anywhere init gcp
autoresearch-anywhere run
```

`init gcp` reads credentials from `~/.config/gcloud/` by default and verifies them. To use a different location: `autoresearch-anywhere init gcp --credentials /path/to/key.json`

A GPU VM launches automatically, trains, collects results, and shuts down. Estimated cloud cost: $0.04 for 1 experiment on a T4 GPU (on-demand $0.35/hr).

### Azure

The quickest way is with the Azure CLI (one command creates everything). You can also gather the credentials manually from the Azure Portal — see below.

**Option A: Azure CLI (recommended)**

1. Install Azure CLI: `brew install azure-cli`
2. Sign in: `az login` (opens browser)
3. Create a service principal with Contributor access (replace `<subscription-id>` with yours from `az account show`):

```bash
az ad sp create-for-rbac --name autoresearch --role Contributor \
  --scopes /subscriptions/<subscription-id>
```

This outputs `appId`, `password`, `tenant`. Map them into a JSON file.

**Option B: Azure Portal (no CLI needed)**

1. Go to [App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) → **New registration** → name it `autoresearch` → **Register**
2. From the app's **Overview** page, note the **Application (client) ID** and **Directory (tenant) ID**
3. Click **Add a certificate or secret** → **New client secret** → copy the **Value** (shown only once)
4. Go to [Subscriptions](https://portal.azure.com/#view/Microsoft_Azure_Billing/SubscriptionsListBlade) → click your subscription → copy the **Subscription ID**
5. Still in the subscription → **Access control (IAM)** → **Add role assignment** → **Contributor** → select your app → **Review + assign**

**Both options**: Save credentials at `~/.azure/service-principal.json` (`mkdir -p ~/.azure`):

```json
{
  "tenant_id": "<tenant>",
  "client_id": "<appId>",
  "client_secret": "<password>",
  "subscription_id": "<subscription-id>"
}
```

5. Set `platform: azure` in `research.yaml`
6. Run:

```bash
autoresearch-anywhere init azure
autoresearch-anywhere run
```

`init azure` reads credentials from `~/.azure/service-principal.json` by default and verifies them. To use a different file: `autoresearch-anywhere init azure --credentials /path/to/sp.json`

A GPU VM launches automatically, trains, collects results, and shuts down. Estimated cloud cost: $0.05 for 1 experiment on a T4 GPU (on-demand $0.53/hr).

### Oracle OCI

1. Install OCI CLI: `brew install oci-cli`
2. Generate an API signing key and config: `oci setup config` (follow prompts — it creates `~/.oci/config` with your tenancy, user, region, and PEM key)
3. Find your compartment OCID: OCI Console → Identity & Security → Compartments → copy the OCID
4. Add the compartment to your OCI config: add `compartment=ocid1.compartment.oc1..xxxxx` to the `[DEFAULT]` section of `~/.oci/config`
5. Set `platform: oci` in `research.yaml`
6. Run:

```bash
autoresearch-anywhere init oci
autoresearch-anywhere run
```

`init oci` reads credentials from `~/.oci/config` by default and verifies them. To use a different config file: `autoresearch-anywhere init oci --credentials /path/to/oci/config`. The compartment OCID can also be provided via the `OCI_COMPARTMENT_ID` environment variable instead of adding it to the config file.

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
Cloud cost:   $0.13 (on-demand rate: $1.01/hr)
API cost:     $0.02 estimated (4,000 in + 2,000 out tokens × claude-sonnet pay-per-token rate)
              Note: API cost may be $0 if you have a subscription or free credits
Total (est):  $0.15 / $5.00 budget
```

If combined cost hits your budget, the run stops automatically and results are collected.

## GPU Quota

Cloud providers set GPU quota to **0** by default. Your first cloud run will fail with a quota error until you request access. Request GPU quota **before** your first run — it's free to apply but approval takes hours to days for new accounts:

| Provider | Where to request |
|----------|-----------------|
| AWS | [Service Quotas](https://console.aws.amazon.com/servicequotas/) → EC2 → search "G and VT" |
| GCP | [Quotas](https://console.cloud.google.com/iam-admin/quotas) → search "NVIDIA T4" |
| Azure | [Quotas](https://portal.azure.com/#view/Microsoft_Azure_Capacity/QuotaMenuBlade/~/myQuotas) → search "NCASv3_T4", request 4 cores |
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
