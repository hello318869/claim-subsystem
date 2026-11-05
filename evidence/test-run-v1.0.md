# V1.0 实际测试与评测记录

执行时间：2026-11-05（Asia/Shanghai）。
后端：`app.main:app`，`APP_ENV=test`，专用 HTTP 端口 `127.0.0.1:18080`（由测试工作流启动/管理，非 TestClient）。
数据库：隔离 MySQL `8.0.46`，`127.0.0.1:33307`，库 `claim_test`（`SELECT DATABASE()` 实测）。
本记录只陈述实际执行结果，不把已知失败改写成通过。

## 1. 环境与 seed

```powershell
& '.\scripts\local_mysql.ps1' -Action Start
python scripts/init_db.py --database test
python scripts/seed_demo.py --database test
python tests/fixtures/seed_test_world.py
```

- `init_db`：7 张表，create_all，未 drop。
- `seed_demo`：8 条 demo listing（5 found / 3 lost），未删除。
- `seed_test_world`：80 个独立场景（每个场景 1 found + alice/bob 各 1 lost，共 240 条 listing）+ 匹配集 55 条 found（40 目标 + 15 干扰）+ 52 条 lost，共 347 条测试 listing（另保留 8 条 demo）；manifest `tests/fixtures/seed-world.json`。
- seed 仅清理 `T-IT-` / `T-M-` 前缀与四个 demo actor 的幂等记录；demo 行保留。

## 2. 测试结果

### 2.1 全量集成（真实 HTTP + 真实 MySQL）

```powershell
$env:CLAIM_TEST_BASE_URL='http://127.0.0.1:18080'
python -m pytest tests/integration -q
```

```text
95 passed, 2 failed, 3 xfailed in 15.69s
```

失败（均为后端问题，测试期望未改）：

| 测试 | 实际 | 期望/规则 |
| --- | --- | --- |
| `test_concurrency.py::test_concurrent_same_key_claim_replay` | 一个请求 500 Internal Server Error | 同 Idempotency-Key 并发创建应复用一个 claim（200/201） |
| `test_dispute.py::test_disputed_claim_messages_are_read_only` | POST 消息 201 | DISPUTED 冻结后只读，POST 应 409 |

xfail（后端已接受但记录为限制，未计通过）：

| 测试 | 实际 |
| --- | --- |
| `test_claims.py::test_create_claim_rejects_empty_evidence[   ]` | 空白 evidence_text 被接受（201） |
| `test_claims.py::test_create_claim_rejects_empty_evidence[\n\t]` | 同上 |
| `test_messages.py::test_empty_message_is_422[\n\t]` | 空白消息被接受并写入空 body |

### 2.2 离线/环境检查

```powershell
python -m pytest tests/integration/test_dataset_integrity.py tests/performance/test_loadgen_policy.py tests/integration/test_harness_contract.py -q
python -m pytest tests/integration/test_environment_guard.py -q
```

- 匹配集/benchmark 数学/harness：17 passed。
- 环境/MySQL 守卫：3 passed。
- 匹配集固定 SHA-256：`443e7e59ed2e887314dc9528d1d2eed5dc7d1565bc92afa56939936047bcef99`，评估前后一致。

### 2.3 匹配评测（真实 HTTP 规则入口）

```powershell
python scripts/evaluate_matching.py --manifest tests/fixtures/seed-world.json ^
  --base-url http://127.0.0.1:18080 --output evidence/matching-evaluation.json
```

| 指标 | 结果 | 门槛 | 结论 |
| --- | --- | --- | --- |
| 正例 Top3 召回 | **1.000**（40/40） | ≥0.8 | 通过 |
| 负例有推荐比例 | **1.000**（12/12） | ≤0.2 | **未通过** |
| 负例 score>0 比例 | 1.000 | 参考 | 未通过 |
| rule_version | `rules-v1.0` | 必须返回 | 通过 |

- development：24/24 正例命中，7/7 负例被推荐。
- regression：16/16 正例命中，5/5 负例被推荐。
- 执行错误 0；fixture 前后 SHA-256 一致；未修改任何标签。
- 根因：类别 35 分 + 时间 15 分 = 50 分，单独就超过阈值 40；同类别且时间相近的“无对应物”查询必然得到候选。详见 `backend-defects-v1.0.md`。

### 2.4 性能基准（真实 HTTP + 真实 MySQL）

```powershell
python scripts/benchmark.py --base-url http://127.0.0.1:18080
```

```text
status=passed
900 requests = 3 rounds × 3 endpoints × 100, concurrency=20
measured samples: listings=1002, claims=1, messages=20, total=1023
0 5xx, 0 uncaught exceptions
P95: claim list 512.3 ms | conversation 232.7 ms | matching 659.2 ms
P99: 615.5 / 269.6 / 741.8 ms
cleanup: ok, T-PERF-467f2994- -> 0 rows
```

- 硬件：Windows 10.0.26300，Intel64 Family 6 Model 183，32 vCPU，32 GB RAM（探测 5.6 GB available）。
- 数据库：MySQL 8.0.46，33307，max_connections=30，buffer pool 64 MiB，REPEATABLE-READ。
- 连接池：客户端 20；后端 SQLAlchemy pool_size=5，max_overflow=5（每进程 10）；服务端上限 30。
- 每轮每端点 100 次、全部 200；逐轮 P95 均 <1000 ms（claim 494/536/512，会话 176/269/209，匹配 616/600/695）。
- 证据：`evidence/performance-benchmark.json`。
- 专属前缀已清理；`SELECT COUNT(*) ... origin LIKE 'perf-%'` 为 0。

## 3. 结论

- 认领全流程、双方完成、越权、幂等重放/冲突、token 篡改/过期、PII、冷却/重置/24h 期限、私有字段、终态（除 DISPUTED 消息）均通过真实 HTTP 测试。
- 两个后端缺陷和三项空白输入限制已如实记录，未修改断言迎合实现。
- 匹配正例达标；负例指标未达标，属于规则质量问题。
- 性能基准达标（本机、隔离 MySQL、专用 HTTP 端口）。
