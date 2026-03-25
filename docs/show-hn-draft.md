---
title: "Show HN: Run Karpathy's autoresearch on any cloud GPU with one command"
---

## Post body

When Andrej Karpathy released autoresearch, I wanted to try it immediately. First on my Mac, then on AWS to see how it performs on a real GPU. Each time, I spent more time wrestling with infrastructure — figuring out the right instance type, patching batch sizes for the GPU, setting up SSH, making sure the VM gets torn down — than thinking about the actual research.

I figured other researchers and enthusiasts were hitting the same wall. So I built autoresearch-anywhere: a CLI that lets you run autoresearch on Mac or any cloud GPU with minimal infrastructure knowledge, reducing the barrier to experimenting with autoresearch.

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

## Prep notes

- Anticipated questions are pre-empted in the README FAQ section
