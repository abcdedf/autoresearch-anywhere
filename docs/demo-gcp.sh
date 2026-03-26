#!/bin/bash
# =============================================================================
# asciinema demo: GCP (L4 GPU)
#
# Recording:
#   asciinema rec docs/demo-gcp.cast -c "bash docs/demo-gcp.sh"
# Convert to GIF:
#   agg docs/demo-gcp.cast docs/demo-gcp.gif --cols 100 --rows 30 --speed 2
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
echo "# autoresearch-anycloud — GCP demo"
echo "# L4 24GB GPU, 1 experiment, 60s time budget"
echo ""
pause 2

type_cmd "cat research.yaml"
cat <<'LOG'
research:
  topic: "Improve training loss on TinyShakespeare"
  program: "program.md"
  max_experiments: 1
  time_budget: 60
platform: gcp
budget:
  max_cost_usd: 5.00
LOG
pause 2

type_cmd "autoresearch-anycloud run --preflight"
cat <<'LOG'
[16:19:09] PREFLIGHT — validating infrastructure for gcp

[16:19:12]   [PASS] Credentials: project autoresearch-491200
[16:19:12]   [PASS] Machine type: g2-standard-4 in asia-northeast1-b (1 NVIDIA L4 GPU, 4 vCPUs, 16GB RAM)
[16:19:12]   [PASS] Image: pytorch-2-7-cu128-ubuntu-2204-nvidia-570-v20260320
[16:19:12]   [PASS] GPU quota: NVIDIA_L4_GPUS: 1 available (limit 1)

[16:19:12] All checks passed. Ready to run.
LOG
pause 2

type_cmd "autoresearch-anycloud run"
cat <<'LOG'
[16:48:00] Log file: logs/2026-03-25T164800.log

[16:48:01] Platform:    GCP (g2-standard-4)
[16:48:01] Experiments: 1
[16:48:01] Est. cost:   $0.16 (GPU: $0.12 + API: $0.042)
[16:48:01] Budget:      $5.00

[16:48:01] [provision] Launching GCP instance...
[16:48:01] [gcp] Project: autoresearch-491200, Zone: asia-northeast1-b
[16:48:08] [gcp] Image: pytorch-2-7-cu128-ubuntu-2204-nvidia-570-v20260320
[16:48:08] [gcp] Launching g2-standard-4 + nvidia-l4 x1 on-demand instance...
[16:48:20] [gcp] Instance running at 34.153.215.153
[16:48:30] [gcp] SSH ready after 20s
LOG
pause 1

cat <<'LOG'
[16:48:30] [setup] Uploading autoresearch to remote...
[16:48:31] [setup] Tuning train.py for L4 24GB...
[16:48:31]   DEVICE_BATCH_SIZE = 32 (upstream: 128)
[16:48:31]   TIME_BUDGET = 60s
[16:49:45] [setup] Installing uv and dependencies on remote...
[16:50:30] [setup] Done.

[16:50:30] [prepare] Downloading data and training tokenizer...
[16:50:45] [prepare] Done.
LOG
pause 1

cat <<'LOG'
[16:50:45] ── Experiment 1/1 ──
[16:50:45]   Note: first experiment includes one-time CUDA kernel compilation (~2 min).
[16:50:45] Vocab size: 8,192 | 50M parameters
[16:50:45] Time budget: 60s
LOG
pause 0.5

cat <<'LOG'
[16:51:33] step 00000 | loss: 9.011 | dt: 47596ms | tok/sec: 2,753    (CUDA compile)
[16:51:34] step 00001 | loss: 8.877 | dt: 1018ms  | tok/sec: 128,810
[16:51:35] step 00005 | loss: 7.419 | dt: 1080ms  | tok/sec: 121,418
[16:51:47] step 00010 | loss: 6.580 | dt: 1101ms  | tok/sec: 119,023
LOG
pause 0.5

cat <<'LOG'
[16:52:10] step 00025 | loss: 5.788 | tok/sec: 121,100 | remaining: 45s
[16:52:30] step 00040 | loss: 5.471 | tok/sec: 121,400 | remaining: 27s
[16:52:50] step 00055 | loss: 5.135 | tok/sec: 123,587 | remaining: 10s
[16:53:05] step 00065 | loss: 4.981 | tok/sec: 123,773 | remaining: 0s
LOG
pause 0.5

cat <<'LOG'
[16:53:05] Evaluating val_bpb...
[16:54:20] Evaluation complete.
LOG
pause 1

cat <<'LOG'

[16:54:21] ══════════════════════════════════════════════════
[16:54:21] RUN SUMMARY
[16:54:21] ══════════════════════════════════════════════════
[16:54:21] Platform:     GCP (g2-standard-4 — L4 24GB)
[16:54:21] Experiments:  1
[16:54:21] Total time:   214s (3.6 min)

[16:54:21]  Exp     val_bpb      Time    Status
[16:54:21] ────  ──────────  ────────  ────────
[16:54:21]    1    1.732940     214s        ok

[16:54:21] Best val_bpb: 1.732940 (experiment 1)

[16:54:21] Cloud cost:   $0.07 (on-demand rate: $0.72/hr)
[16:54:21] API cost:     $0.04 estimated
[16:54:21] Total (est):  $0.11 / $5.00 budget
[16:54:21] ══════════════════════════════════════════════════

[16:54:21] [teardown] Cleaning up GCP resources...
[16:54:35] [gcp] Instance deleted.
[16:54:40] [gcp] Firewall rule deleted.
[16:54:40] Done.
LOG
pause 2

echo ""
echo "# Done. $0.11 total. Cheapest cloud GPU option."
pause 3
