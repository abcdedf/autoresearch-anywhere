---
title: "Show HN: Run Karpathy's autoresearch on any cloud GPU with one command"
---

## Post body

When Karpathy released autoresearch, I wanted to try it immediately. First on my Mac, then on AWS to see how it performs on a real GPU. Each time, I spent more time wrestling with infrastructure — figuring out the right instance type, patching batch sizes for the GPU, setting up SSH, making sure the VM gets torn down — than thinking about the actual research.

I figured other researchers and enthusiasts were hitting the same wall. So I built autoresearch-anywhere: a CLI that lets you run autoresearch on Mac or any cloud GPU with minimal infrastructure knowledge, reducing the barrier to experimenting with this awesome capability.

One YAML file describes your research intent. One command provisions a GPU VM, runs the experiments, collects results, and tears everything down:

```
autoresearch-anywhere init gcp
autoresearch-anywhere run
```

What it handles for you:

- Provisions the right GPU instance (A10G on AWS, L4 on GCP, A10 on Azure/OCI)
- Patches upstream training parameters for the specific GPU (batch sizes, etc.)
- Forwards your API keys securely (never written to disk on the remote)
- Streams logs to terminal and file simultaneously
- Estimates cost upfront and enforces a budget ceiling
- Tears down the VM in a try/finally — no orphaned instances

Cost for a single experiment: $0.00 (Mac), $0.17 (AWS), $0.12 (GCP).

No Terraform, no Docker, no Kubernetes. Just Python SDKs (boto3, google-cloud-compute, etc.) talking directly to cloud APIs.

Mac/AWS/GCP are verified end-to-end. Azure and OCI are code-complete, blocked on GPU quota approvals.

GitHub: https://github.com/abcdedf/autoresearch-anywhere

---

## Notes for posting

- HN prefers text posts for Show HN (not just a link)
- Keep the title under 80 chars
- Post between 8-10am ET on a weekday (Tue-Thu are best)
- Respond to every comment in the first 2 hours
- Don't be defensive about limitations — acknowledge them openly
- Alternative titles if the first doesn't land:
  - "Show HN: One-command wrapper to run autoresearch on Mac or any cloud GPU"
  - "Show HN: autoresearch-anywhere — Karpathy's autoresearch on AWS/GCP/Mac in one command"

## Anticipated questions and answers

**Q: Why not just use SkyPilot?**
A: SkyPilot is great for general GPU workloads. This is purpose-built for autoresearch — it handles the upstream-specific patches (batch sizes, GPU tuning), cost estimation tuned to short experiment runs, and the full experiment lifecycle. It's also much simpler to set up for this specific use case.

**Q: Why not Terraform?**
A: These are ephemeral VMs that live for 10-20 minutes. Native SDK calls (boto3, google-cloud-compute) are faster to provision, easier to tear down, and don't require the user to install anything beyond pip packages. This follows the SkyPilot/Ray approach for ephemeral workloads.

**Q: Does it work with other training scripts?**
A: Not currently — it's specifically for Karpathy's autoresearch. The architecture (provider modules, orchestrator, cost engine) could be generalized, but that's not the goal today.

**Q: Why does it need Ampere+ GPUs?**
A: Upstream autoresearch uses FlashAttention 3 and bfloat16, which require compute capability 8.0+. That means T4 and V100 don't work. This is an upstream constraint, not ours — we pick the right GPU so the researcher doesn't have to figure this out.

**Q: What's the catch?**
A: You need cloud credentials set up (AWS keys, GCP service account, etc.). The tool doesn't provision cloud accounts — just VMs. And GPU quota on some providers (Azure, OCI) requires a manual request that can take days.
