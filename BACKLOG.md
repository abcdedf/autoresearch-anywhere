# Backlog

## To verify

- [ ] **Cost budget enforcement end-to-end**: The budget watchdog (30s interval) and per-experiment timeout (TIME_BUDGET + 60s) are implemented but not yet validated on a real cloud run. Verify:
  - Watchdog aborts a running experiment when GPU cost exceeds budget mid-training
  - Experiment timeout kills a hung/slow experiment correctly
  - Teardown still runs after an abort (VM gets cleaned up, no orphaned resources)
  - Budget check between experiments stops the loop as expected
  - Edge case: budget exceeded during data preparation (before experiments start)

## To do

- [ ] **Upstream PR**: Submit PR to karpathy/autoresearch to make DEVICE_BATCH_SIZE and TOTAL_BATCH_SIZE configurable via environment variables (eliminates the sed workaround)
- [ ] **GCP end-to-end test**: Blocked on GPU quota (requested 2026-03-23, 48hr wait)
- [ ] **Azure end-to-end test**: Blocked on GPU quota (service request submitted 2026-03-23)
- [ ] **OCI provider test**: No account yet

## To improve

- [ ] **AWS teardown: clean up SG reliably**: Currently teardown fires `terminate_instances` and tries to delete the SG immediately (non-blocking). If the SG delete fails (instance still attached), it's reused on the next run. Consider a short async retry (e.g., 30s delay then retry SG delete in background) for cleaner cleanup without blocking the user for 5 minutes.
- [ ] **GCP/Azure/OCI teardown timing**: Verify teardown on other providers is also non-blocking and doesn't leave orphaned resources
