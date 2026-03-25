#!/bin/bash
# =============================================================================
# asciinema demo script for autoresearch-anywhere
#
# Records a ~2 min demo showing the Mac flow end-to-end.
# The actual training takes ~15 min, so we fake the training output
# with pre-recorded log lines for a tight demo.
#
# Prerequisites:
#   brew install asciinema
#   pip install asciinema-agg   # for GIF conversion (optional)
#
# Recording:
#   asciinema rec demo.cast -c "bash docs/demo-script.sh"
#
# Convert to GIF:
#   agg demo.cast demo.gif --cols 80 --rows 24 --speed 1
#
# Or upload to asciinema.org:
#   asciinema upload demo.cast
# =============================================================================

# Simulated typing effect
type_cmd() {
    echo ""
    for ((i=0; i<${#1}; i++)); do
        printf '%s' "${1:$i:1}"
        sleep 0.04
    done
    echo ""
    sleep 0.3
}

pause() { sleep "${1:-1.5}"; }

clear
echo "# autoresearch-anywhere — demo"
echo "# Run Karpathy's autoresearch on Mac or any cloud GPU"
echo ""
pause 2

# --- Clone and setup ---
type_cmd "git clone https://github.com/abcdedf/autoresearch-anywhere.git"
echo "Cloning into 'autoresearch-anywhere'..."
echo "done."
pause 1

type_cmd "cd autoresearch-anywhere && uv sync"
echo "Resolved 42 packages in 1.2s"
echo "Installed 42 packages in 3.4s"
pause 1

# --- Init Mac ---
type_cmd "autoresearch-anywhere init mac"
cat <<'LOG'
Detecting Mac environment...
  Apple Silicon detected (arm64)
  Python 3.12.8
  PyTorch 2.6.0, MPS available: True
  MPS acceleration: enabled

Mac platform configured.
Config saved to config.yaml
LOG
pause 2

# --- Show config ---
type_cmd "cat research.yaml"
cat <<'LOG'
topic: "Improving tokenization for small language models"
platform: mac
max_experiments: 2
budget_usd: 5.00
LOG
pause 2

# --- Run ---
type_cmd "autoresearch-anywhere run"
cat <<'LOG'
[12:01:00] Log file: logs/2026-03-25T120100.log

[12:01:00] Platform:    Mac (Apple Silicon MPS)
[12:01:00] Experiments: 2
[12:01:00] Est. cost:   $0.04 (GPU: $0.00 + API: $0.04)
[12:01:00] Budget:      $5.00

[12:01:00] [setup] Installing workspace dependencies...
[12:01:05] [setup] Done.

[12:01:05] [prepare] Downloading data and training tokenizer...
LOG
pause 1

cat <<'LOG'
[12:01:30] [prepare] Done.

[12:01:30] -- Experiment 1/2 --
[12:01:30]   $ uv run train.py
[12:01:31] Device: mps
[12:01:31] Vocab size: 8,192
[12:01:35] Time budget: 60s
[12:01:35] Warmup: first 10 steps (includes MPS compilation)
LOG
pause 1

cat <<'LOG'
[12:03:10] step 00010 [warmup 10/10] | loss: 7.383 | dt: 11980ms | tok/sec: 5,470
[12:03:21] step 00011 [training 10/60s] | loss: 7.250 | dt: 10771ms | tok/sec: 6,084
[12:03:33] step 00012 [training 22/60s] | loss: 7.122 | dt: 11460ms | tok/sec: 5,718
[12:03:44] step 00013 [training 33/60s] | loss: 7.017 | dt: 11574ms | tok/sec: 5,662
[12:04:07] step 00014 [training 56/60s] | loss: 6.913 | dt: 22423ms | tok/sec: 2,922
LOG
pause 1

cat <<'LOG'
[12:04:30] Evaluating val_bpb (3 * 524K tokens)...
[12:05:00] Evaluation complete.
---
val_bpb:          2.169
training_seconds: 120.4
total_tokens_M:   1.0
num_steps:        16
LOG
pause 1

cat <<'LOG'
[12:05:02]   Completed in 212s

[12:05:02] -- Experiment 2/2 --
LOG
echo "  [... experiment 2 runs similarly ...]"
pause 1

cat <<'LOG'

[12:20:00] ==============================================
[12:20:00] RUN SUMMARY
[12:20:00] ==============================================
[12:20:00] Platform:     Mac (Apple Silicon MPS)
[12:20:00] Experiments:  2
[12:20:00] Total time:   1140s (19.0 min)

[12:20:00] Succeeded:    2/2

[12:20:00]  Exp     val_bpb      Time    Status
[12:20:00] ----  ----------  --------  --------
[12:20:00]    1    2.169433     212s        ok
[12:20:00]    2    2.041822     210s        ok

[12:20:00] Best val_bpb: 2.041822 (experiment 2)

[12:20:00] API cost:     $0.04 estimated
[12:20:00] Results:      results/2026-03-25T120100
[12:20:00] Log:          logs/2026-03-25T120100.log
[12:20:00] ==============================================
LOG
pause 2

echo ""
echo "# Done. Two experiments, zero infrastructure, one command."
echo "# Works the same way on AWS, GCP, Azure, and OCI."
echo "# https://github.com/abcdedf/autoresearch-anywhere"
pause 3
