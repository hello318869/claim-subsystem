# Performance benchmark

`scripts/benchmark.py` drives the **real HTTP backend** and **real MySQL
`claim_test`**. It has no mock-latency fallback and does not use SQLite.

## Workload (v1.0 and v1.0.1 identical)

| Item | Value |
| --- | --- |
| Data | 1000 prefixed found listings + 1 lost + target, origin `perf-<run>` |
| Conversation | 1 approved claim + 20 messages |
| Concurrency | exactly 20 |
| Warm-up | 10 requests per endpoint |
| Rounds | exactly 3 (minimum enforced) |
| Requests | 100 per endpoint per round (minimum enforced) |
| Endpoints | claim list, conversation read, rule matching |
| Gate | per-endpoint/round P95 <= 1000 ms; 0 5xx; 0 client exceptions; **0 server tracebacks** |
| Cleanup | every row with `T-PERF-<run>-` removed in `finally` |

## v1.0.1 changes

- The script now **manages the dedicated uvicorn on port 18080** itself
  (`--manage-server`, default on), waits for `/health`, and verifies the port is
  released afterwards.
- It reads the uvicorn combined stdout/stderr log from an offset taken after
  startup and counts `Traceback`, `Exception in ASGI application`, and `500`
  lines. The report includes `server_exception_reading.method`; client status
  alone is not accepted.
- Default output is `evidence/performance-benchmark-v1.0.1.json`, preserving
  the v1.0 `evidence/performance-benchmark.json`.
- P95/P99 and status counts remain recorded per endpoint **and per round**.

## Command (after backend fixes)

```powershell
python scripts/benchmark.py
```

The script seeds/cleans only `T-PERF-<run>-` rows and starts/stops its own
`127.0.0.1:18080` process. It refuses to pass if the dataset is under 1000 rows,
preflight is non-200, a 5xx/exception appears, any round/endpoint P95 exceeds
1000 ms, the server log is unreadable/has a traceback, or cleanup/port release
fails.

## v1.0 result (historical, preserved)

900 requests, 1023 measured samples, 0 5xx, 0 client exceptions; P95 512.3 ms
(claim list), 232.7 ms (conversation), 659.2 ms (matching). See
`evidence/performance-benchmark.json`. v1.0.1 rerun is pending backend fixes.
