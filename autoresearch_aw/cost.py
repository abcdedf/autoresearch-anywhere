"""Cost tracking for autoresearch-anywhere — GPU compute + LLM API costs, reported separately.

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
    "g5.xlarge": 1.006,                # AWS A10G on-demand — https://instances.vantage.sh/aws/ec2/g5.xlarge
    "g2-standard-4": 0.72,             # GCP L4 on-demand — https://cloud.google.com/compute/vm-instance-pricing
    "Standard_NV36ads_A10_v5": 3.20,   # Azure A10 on-demand — https://instances.vantage.sh/azure/vm/nv36ads-v5
    "VM.GPU.A10.1": 0.50,              # OCI A10 — https://www.oracle.com/cloud/compute/pricing/
    "mac": 0.00,                        # Local, free
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
