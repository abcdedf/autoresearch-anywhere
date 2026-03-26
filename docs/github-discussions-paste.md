Title: `autoresearch-anycloud: run autoresearch on Mac or any cloud GPU with one command`

Category: Show and Tell (or General)

---

I built a CLI tool that lets you run autoresearch on your Mac or any major cloud GPU without dealing with infrastructure.

**The problem I kept hitting:** every time I wanted to run autoresearch on a new platform, I spent more time figuring out the right instance type, patching batch sizes for the GPU, setting up SSH, and making sure the VM gets torn down than thinking about the actual research.

**autoresearch-anycloud** handles all of that. You write a short YAML describing your research intent, and one command does the rest:

```bash
autoresearch-anycloud init gcp
autoresearch-anycloud run
```

**What it handles for you:**

- Provisions the right GPU instance (A10G on AWS, L4 on GCP, A10 on Azure/OCI)
- Patches upstream training parameters for the specific GPU (batch sizes, etc.)
- Forwards your API keys securely (never written to disk on the remote)
- Streams logs to terminal and file simultaneously
- Estimates cost upfront and enforces a budget ceiling
- Tears down the VM in a `try/finally` — no orphaned instances

**Supported platforms:** Mac (Apple Silicon MPS), AWS (A10G), GCP (L4), Azure (A10), Oracle OCI (A10). Mac/AWS/GCP verified end-to-end.

**Cost per proof-of-concept experiment** (`max_experiments: 1`): $0.00 on Mac, $0.17 on AWS, $0.12 on GCP.

GitHub: https://github.com/abcdedf/autoresearch-anycloud

Happy to hear feedback or suggestions. If anyone wants to add support for other providers (Lambda Labs, CoreWeave, etc.), the provider interface is documented in the README.
