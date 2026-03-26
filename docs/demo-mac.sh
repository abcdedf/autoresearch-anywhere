#!/bin/bash
# =============================================================================
# asciinema demo: Mac (Apple Silicon MPS)
#
# Recording:
#   asciinema rec docs/demo-mac.cast -c "bash docs/demo-mac.sh"
# Convert to GIF:
#   agg docs/demo-mac.cast docs/demo-mac.gif --cols 100 --rows 30 --speed 2
# =============================================================================

type_cmd() {
    echo ""
    echo -n "$ "
    for ((i=0; i<${#1}; i++)); do
        printf '%s' "${1:$i:1}"
        sleep 0.04
    done
    echo ""
    sleep 0.3
}

pause() { sleep "${1:-1.5}"; }

clear
echo "# autoresearch-anycloud — Mac demo"
echo "# Apple Silicon MPS, 1 experiment, 60s time budget"
echo ""
pause 2

type_cmd "cat research.yaml"
cat <<'LOG'
research:
  topic: "Improve training loss on TinyShakespeare"
  program: "program.md"
  max_experiments: 1
  time_budget: 60
platform: mac
budget:
  max_cost_usd: 5.00
LOG
pause 2

type_cmd "autoresearch-anycloud init mac"
cat <<'LOG'
Detecting Mac environment...
  Apple Silicon detected (arm64)
  PyTorch 2.6.0, MPS available: True
  MPS acceleration: enabled

Mac platform configured. Config saved to config.yaml
LOG
pause 2

type_cmd "autoresearch-anycloud run"
cat <<'LOG'
[16:36:25] Log file: logs/2026-03-25T163625.log

[16:36:25] Platform:    Mac
[16:36:25] Experiments: 1 (~5 min)
[16:36:25] Est. cost:   $0.042 (GPU: $0.00, API: $0.042)

[16:36:25] [setup] Installing workspace dependencies (uv sync)...
[16:36:30] [setup] Done.

[16:36:30] [prepare] Downloading data and training tokenizer...
LOG
pause 1

cat <<'LOG'
[16:36:40] [prepare] Done.

[16:36:40] ── Experiment 1/1 ──
[16:36:40] Device: mps
[16:36:40] Vocab size: 8,192
[16:36:45] Time budget: 60s
[16:36:45] Warmup: first 10 steps (includes MPS compilation)
[16:36:45] Training starts after warmup, then runs for 60s
LOG
pause 1

cat <<'LOG'
[16:37:25] step 00000 [warmup 0/10]  | loss: 9.011 | tok/sec: 1,603
[16:38:20] step 00002 [warmup 2/10]  | loss: 9.027 | tok/sec: 8,362
[16:38:41] step 00005 [warmup 5/10]  | loss: 8.210 | tok/sec: 9,545
[16:39:13] step 00009 [warmup 9/10]  | loss: 7.539 | tok/sec: 8,686
[16:39:20] step 00010 [warmup 10/10] | loss: 7.383 | tok/sec: 9,405
LOG
pause 0.5

cat <<'LOG'
[16:39:29] step 00011 [training 8/60s]  | loss: 7.250 | tok/sec: 7,931
[16:39:43] step 00013 [training 22/60s] | loss: 7.017 | tok/sec: 8,382
[16:39:58] step 00015 [training 37/60s] | loss: 6.809 | tok/sec: 8,492
[16:40:12] step 00017 [training 52/60s] | loss: 6.641 | tok/sec: 9,692
[16:40:27] step 00019 [training 66/60s] | loss: 6.501 | tok/sec: 9,131
LOG
pause 0.5

cat <<'LOG'
[16:40:27] Evaluating val_bpb (3 * 524K tokens)...
[16:41:49] Evaluation complete.
LOG
pause 1

cat <<'LOG'

[16:41:49] ══════════════════════════════════════════════════
[16:41:49] RUN SUMMARY
[16:41:49] ══════════════════════════════════════════════════
[16:41:49] Platform:     Mac (Apple Silicon MPS)
[16:41:49] Experiments:  1
[16:41:49] Total time:   309s (5.2 min)

[16:41:49]  Exp     val_bpb      Time    Status
[16:41:49] ────  ──────────  ────────  ────────
[16:41:49]    1    2.119531     309s        ok

[16:41:49] Best val_bpb: 2.119531 (experiment 1)

[16:41:49] Cloud cost:   $0.00
[16:41:49] API cost:     $0.04 estimated
[16:41:49] Total (est):  $0.04 / $5.00 budget
[16:41:49] ══════════════════════════════════════════════════
LOG
pause 2

echo ""
echo "# Done. Free. No cloud account needed."
pause 3
