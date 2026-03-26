"""Cost tracking for autoresearch-anycloud — GPU compute + LLM API costs, reported separately.

Cloud cost: estimated from public spot pricing × elapsed time. Source: AWS/GCP/Azure/OCI pricing pages.
API cost:   estimated from per-experiment token usage × published per-token rates.
            Each experiment sends the full train.py + git log + program.md to the LLM (~4K input tokens)
            and receives a modified code section back (~2K output tokens).
            Actual cost depends on your plan — subscriptions, enterprise agreements, or free credits
            may make API cost $0. These estimates assume pay-per-token pricing.
"""

import time


# LLM API pricing (per 1M tokens, pay-per-token rates as of March 2026)
# Source: https://www.anthropic.com/pricing, https://openai.com/pricing
LLM_PRICING = {
    "claude-sonnet": {"input": 3.00, "output": 15.00},
    "claude-opus": {"input": 15.00, "output": 75.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}

# Estimated LLM token usage per experiment (based on upstream autoresearch behavior):
#   Input:  train.py (~2K tokens) + git log (~1K) + program.md (~1K) = ~4K tokens
#   Output: modified code section + reasoning = ~2K tokens
ESTIMATED_INPUT_TOKENS_PER_EXPERIMENT = 4000
ESTIMATED_OUTPUT_TOKENS_PER_EXPERIMENT = 2000

# GPU on-demand pricing per hour (from public pricing pages, March 2026)
# Source: instances.vantage.sh, cloud provider pricing calculators
GPU_PRICING = {
    # AWS
    "g5.xlarge": 1.006,                # A10G 24GB
    "p4d.24xlarge": 32.77,             # A100 40GB ×8
    "p4de.24xlarge": 40.97,            # A100 80GB ×8
    "p5.48xlarge": 98.32,              # H100 80GB ×8
    # GCP
    "g2-standard-4": 0.72,             # L4 24GB
    "a2-highgpu-1g": 3.67,             # A100 40GB ×1
    "a2-ultragpu-1g": 5.00,            # A100 80GB ×1
    "a3-highgpu-8g": 98.26,            # H100 80GB ×8
    # Azure
    "Standard_NV36ads_A10_v5": 3.20,   # A10 24GB
    "Standard_NC24ads_A100_v4": 3.67,  # A100 80GB ×1
    "Standard_NC40ads_H100_v5": 7.35,  # H100 80GB ×1
    # OCI
    "VM.GPU.A10.1": 0.50,              # A10 24GB
    "BM.GPU.A100-v2.8": 26.00,         # A100 40GB ×8
    "BM.GPU.H100.8": 44.00,            # H100 80GB ×8
    # Local
    "mac": 0.00,
}

# GPU type → smallest single-GPU instance per provider
# Used by `init --gpu <type>` to resolve the right instance type.
# Only lists Ampere+ GPUs (upstream autoresearch requirement).
GPU_CATALOG = {
    "aws": {
        "a10g":     {"instance_type": "g5.xlarge",      "gpu": "A10G 24GB",  "note": "single GPU, cheapest"},
        "a100":     {"instance_type": "p4d.24xlarge",    "gpu": "A100 40GB",  "note": "8-GPU (no single-GPU A100 on AWS)"},
        "a100-80":  {"instance_type": "p4de.24xlarge",   "gpu": "A100 80GB",  "note": "8-GPU"},
        "h100":     {"instance_type": "p5.48xlarge",     "gpu": "H100 80GB",  "note": "8-GPU"},
    },
    "gcp": {
        "l4":       {"instance_type": "g2-standard-4",   "gpu": "L4 24GB",    "note": "single GPU, cheapest"},
        "a100":     {"instance_type": "a2-highgpu-1g",   "gpu": "A100 40GB",  "note": "single GPU"},
        "a100-80":  {"instance_type": "a2-ultragpu-1g",  "gpu": "A100 80GB",  "note": "single GPU"},
        "h100":     {"instance_type": "a3-highgpu-8g",   "gpu": "H100 80GB",  "note": "8-GPU"},
    },
    "azure": {
        "a10":      {"instance_type": "Standard_NV36ads_A10_v5",   "gpu": "A10 24GB",  "note": "single GPU"},
        "a100":     {"instance_type": "Standard_NC24ads_A100_v4",  "gpu": "A100 80GB",  "note": "single GPU"},
        "h100":     {"instance_type": "Standard_NC40ads_H100_v5",  "gpu": "H100 80GB",  "note": "single GPU, cheapest H100"},
    },
    "oci": {
        "a10":      {"instance_type": "VM.GPU.A10.1",      "gpu": "A10 24GB",  "note": "single GPU, cheapest"},
        "a100":     {"instance_type": "BM.GPU.A100-v2.8",  "gpu": "A100 40GB",  "note": "8-GPU bare metal"},
        "h100":     {"instance_type": "BM.GPU.H100.8",     "gpu": "H100 80GB",  "note": "8-GPU bare metal"},
    },
}

# Default GPU type per provider (used when neither --gpu nor --instance-type is given)
GPU_DEFAULTS = {
    "aws": "a10g",
    "gcp": "l4",
    "azure": "a10",
    "oci": "a10",
}


class CostTracker:
    """Track GPU compute + LLM API costs during a run, reported separately."""

    def __init__(self, gpu_hourly_rate: float = 0.0, llm_model: str = "claude-sonnet",
                 budget_usd: float = 5.0, log=None, use_spot: bool = False):
        self.gpu_hourly_rate = gpu_hourly_rate
        self.llm_model = llm_model
        self.budget_usd = budget_usd
        self.log = log
        self.use_spot = use_spot

        # LLM pricing
        pricing = LLM_PRICING.get(llm_model, LLM_PRICING["claude-sonnet"])
        self.input_price_per_token = pricing["input"] / 1_000_000
        self.output_price_per_token = pricing["output"] / 1_000_000

        # Running totals
        self.gpu_start_time = None
        self.gpu_cost_usd = 0.0
        self.llm_input_tokens = 0
        self.llm_output_tokens = 0
        self.llm_cost_usd = 0.0
        self.experiments_completed = 0

    def start_gpu(self):
        """Mark when GPU billing starts (instance running)."""
        self.gpu_start_time = time.time()

    def update_gpu_cost(self):
        """Update GPU cost based on elapsed time."""
        if self.gpu_start_time:
            elapsed_hours = (time.time() - self.gpu_start_time) / 3600
            self.gpu_cost_usd = elapsed_hours * self.gpu_hourly_rate

    def record_experiment(self, input_tokens: int = None, output_tokens: int = None):
        """Record one experiment's LLM usage. Uses estimates if actual counts not available."""
        in_tok = input_tokens or ESTIMATED_INPUT_TOKENS_PER_EXPERIMENT
        out_tok = output_tokens or ESTIMATED_OUTPUT_TOKENS_PER_EXPERIMENT

        self.llm_input_tokens += in_tok
        self.llm_output_tokens += out_tok
        self.llm_cost_usd += (in_tok * self.input_price_per_token +
                               out_tok * self.output_price_per_token)
        self.experiments_completed += 1
        self.update_gpu_cost()

    @property
    def total_cost_usd(self) -> float:
        self.update_gpu_cost()
        return self.gpu_cost_usd + self.llm_cost_usd

    @property
    def budget_remaining_usd(self) -> float:
        return self.budget_usd - self.total_cost_usd

    def is_over_budget(self) -> bool:
        return self.total_cost_usd >= self.budget_usd

    def log_status(self):
        """Log current cost status — cloud and API reported separately."""
        if not self.log:
            return
        self.update_gpu_cost()
        self.log.log(f"  Cloud cost: ${self.gpu_cost_usd:.2f}  |  API cost (est): ${self.llm_cost_usd:.2f}  |  Budget: ${self.budget_usd:.2f}")

    def log_summary(self):
        """Log final cost summary — cloud and API reported separately."""
        if not self.log:
            return
        self.update_gpu_cost()
        rate_label = "spot rate" if self.use_spot else "on-demand rate"
        self.log.log(f"Cloud cost:   ${self.gpu_cost_usd:.2f} ({rate_label}: ${self.gpu_hourly_rate:.2f}/hr)")
        self.log.log(f"API cost:     ${self.llm_cost_usd:.2f} estimated "
                     f"({self.llm_input_tokens:,} in + {self.llm_output_tokens:,} out tokens × "
                     f"{self.llm_model} pay-per-token rate)")
        self.log.log(f"              Note: API cost may be $0 if you have a subscription or free credits")
        self.log.log(f"Total (est):  ${self.total_cost_usd:.2f} / ${self.budget_usd:.2f} budget")


def estimate_run_cost(platform: str, instance_type: str, max_experiments: int,
                      llm_model: str = "claude-sonnet") -> dict:
    """Estimate total cost for a run before starting."""
    # GPU cost — from public spot pricing
    gpu_rate = GPU_PRICING.get(instance_type, 0.50)
    if platform == "mac":
        gpu_rate = 0.0
    estimated_hours = (max_experiments * 5 + 5) / 60  # 5 min/experiment + 5 min setup
    gpu_cost = gpu_rate * estimated_hours

    # LLM API cost — from per-token pricing × estimated tokens per experiment
    pricing = LLM_PRICING.get(llm_model, LLM_PRICING["claude-sonnet"])
    input_cost = (ESTIMATED_INPUT_TOKENS_PER_EXPERIMENT * max_experiments *
                  pricing["input"] / 1_000_000)
    output_cost = (ESTIMATED_OUTPUT_TOKENS_PER_EXPERIMENT * max_experiments *
                   pricing["output"] / 1_000_000)
    llm_cost = input_cost + output_cost

    return {
        "gpu_hourly_rate": gpu_rate,
        "gpu_hours": round(estimated_hours, 2),
        "gpu_cost_usd": round(gpu_cost, 2),
        "llm_model": llm_model,
        "llm_cost_usd": round(llm_cost, 3),
        "total_cost_usd": round(gpu_cost + llm_cost, 2),
    }
