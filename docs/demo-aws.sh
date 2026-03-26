#!/bin/bash
# =============================================================================
# asciinema demo: AWS (A10G GPU)
#
# Recording:
#   asciinema rec docs/demo-aws.cast -c "bash docs/demo-aws.sh"
# Convert to GIF:
#   agg docs/demo-aws.cast docs/demo-aws.gif --cols 100 --rows 30 --speed 2
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
echo "# autoresearch-anycloud — AWS demo"
echo "# A10G 24GB GPU, 1 experiment, 60s time budget"
echo ""
pause 2

type_cmd "cat research.yaml"
cat <<'LOG'
research:
  topic: "Improve training loss on TinyShakespeare"
  program: "program.md"
  max_experiments: 1
  time_budget: 60
platform: aws
budget:
  max_cost_usd: 5.00
LOG
pause 2

type_cmd "autoresearch-anycloud run --preflight"
cat <<'LOG'
[16:33:13] PREFLIGHT — validating infrastructure for aws

[16:33:17]   [PASS] Credentials: account 535830716015
[16:33:17]   [PASS] Instance type: g5.xlarge available in us-east-1
[16:33:17]   [PASS] AMI: ami-05603a42e5254c4bb
[16:33:17]   [PASS] Launch (DryRun): permissions and limits OK

[16:33:17] All checks passed. Ready to run.
LOG
pause 2

type_cmd "autoresearch-anycloud run"
cat <<'LOG'
[16:42:10] Log file: logs/2026-03-25T164210.log

[16:42:11] Platform:    AWS (g5.xlarge)
[16:42:11] Experiments: 1
[16:42:11] Est. cost:   $0.21 (GPU: $0.17 + API: $0.042)
[16:42:11] Budget:      $5.00

[16:42:11] [provision] Launching AWS instance...
[16:42:13] [aws] Finding latest Deep Learning AMI...
[16:42:14] [aws] AMI: Deep Learning OSS Nvidia Driver AMI GPU PyTorch 2.7 (Ubuntu 22.04)
[16:42:15] [aws] Launching g5.xlarge on-demand instance...
[16:42:32] [aws] Instance running at 3.82.188.231
[16:42:42] [aws] SSH ready after 20s
LOG
pause 1

cat <<'LOG'
[16:42:42] [setup] Uploading autoresearch to remote...
[16:42:43] [setup] Tuning train.py for A10G 24GB...
[16:42:43]   DEVICE_BATCH_SIZE = 32 (upstream: 128)
[16:42:43]   TIME_BUDGET = 60s
[16:43:50] [setup] Installing uv and dependencies on remote...
[16:44:05] [setup] Done.

[16:44:05] [prepare] Downloading data and training tokenizer...
[16:44:39] [prepare] Done.
LOG
pause 1

cat <<'LOG'
[16:44:39] ── Experiment 1/1 ──
[16:44:39]   Note: first experiment includes one-time CUDA kernel compilation (~2 min).
[16:44:39] Vocab size: 8,192 | 50M parameters
[16:44:39] Time budget: 60s
LOG
pause 0.5

cat <<'LOG'
[16:45:17] step 00000 | loss: 9.011 | dt: 38197ms | tok/sec: 3,431    (CUDA compile)
[16:45:18] step 00001 | loss: 9.158 | dt: 669ms   | tok/sec: 195,865
[16:45:19] step 00005 | loss: 8.184 | dt: 669ms   | tok/sec: 195,971
[16:45:24] step 00010 | loss: 6.580 | dt: 669ms   | tok/sec: 195,798
LOG
pause 0.5

cat <<'LOG'
[16:45:50] step 00030 | loss: 5.643 | tok/sec: 195,890 | remaining: 40s
[16:46:10] step 00050 | loss: 5.237 | tok/sec: 195,743 | remaining: 20s
[16:46:30] step 00070 | loss: 4.963 | tok/sec: 195,766 | remaining: 10s
[16:46:40] step 00090 | loss: 4.661 | tok/sec: 195,885 | remaining: 3s
[16:46:47] step 00100 | loss: 4.545 | tok/sec: 195,798 | remaining: 0s
LOG
pause 0.5

cat <<'LOG'
[16:46:47] Evaluating val_bpb...
[16:47:38] Evaluation complete.
LOG
pause 1

cat <<'LOG'

[16:47:39] ══════════════════════════════════════════════════
[16:47:39] RUN SUMMARY
[16:47:39] ══════════════════════════════════════════════════
[16:47:39] Platform:     AWS (g5.xlarge — A10G 24GB)
[16:47:39] Experiments:  1
[16:47:39] Total time:   178s (3.0 min)

[16:47:39]  Exp     val_bpb      Time    Status
[16:47:39] ────  ──────────  ────────  ────────
[16:47:39]    1    1.595383     178s        ok

[16:47:39] Best val_bpb: 1.595383 (experiment 1)

[16:47:39] Cloud cost:   $0.08 (on-demand rate: $1.01/hr)
[16:47:39] API cost:     $0.04 estimated
[16:47:39] Total (est):  $0.12 / $5.00 budget
[16:47:39] ══════════════════════════════════════════════════

[16:47:39] [teardown] Cleaning up AWS resources...
[16:47:40] [aws] Instance terminated.
[16:47:40] Done.
LOG
pause 2

echo ""
echo "# Done. $0.12 total. VM provisioned, trained, and torn down automatically."
pause 3
