# V1.0.1 实际回归、匹配与性能报告

执行日期：2026-11-05（Asia/Shanghai）。代码基线：commit `861e1c4`。
后端：`app.main:app`，`APP_ENV=test`，测试工作流管理的 uvicorn `127.0.0.1:18080`。
数据库：隔离 MySQL `8.0.46`，`127.0.0.1:33307`，库 `claim_test`（实际 `SELECT DATABASE()` 校验）。
本轮只读 `.env.test`，未修改 `app/`、`web/`、`.env` 或环境脚本；匹配标签未改。

## 1. Seed 与数据规模

```powershell
python tests/fixtures/seed_test_world.py
```

- 120 个独立认领场景：每场景 1 found + alice/bob 各 1 lost = 360 条；
- 匹配集：55 found（40 目标 + 15 干扰）+ 52 lost；
- 测试 listing 合计 467 条；另有 8 条 demo（5 found + 3 lost），DB 总 listing 475；
- 运行后 claims 83、messages 83、handover_codes 36、item_approvals 36、audit_events 163；
- seed 仅清理 `T-IT-` / `T-M-` 与测试 actor 的幂等记录，未动 demo/其他 prefix。

## 2. 完整测试结果

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| 单元（含 DB） | `$env:APP_ENV='test'; $env:RUN_DB_TESTS='1'; python -m pytest tests/unit -q` | **49 passed** |
| 集成 | `python -m pytest tests/integration -q` | **118 passed, 0 failed, 0 skipped, 0 xfailed**（18.51s） |
| 性能测试集 | `python -m pytest tests/performance -q` | **11 passed** |

- 业务集成没有整组 skip；seed 120 足够，所有场景用例实际执行。
- v1.0 的 3 个空白输入 xfail 在后端 F7 修复后已走严格 422 分支，本轮 **0 xfailed**；
  历史失败仍保留在 `evidence/test-run-v1.0.md`。
- 严格 V1.0.1 回归 17 个（`-m regression_v1_0_1`）全部包含在 118 passed 中：
  同人不同 key 并发、approve×withdraw/reject、同秒消息分页、期限后 reset 持久化、
  空白 evidence/message/reject/dispute reason、非 published 不可申请、完成后确认历史。

## 3. 真实 HTTP 匹配评测（固定 40 正 / 12 负）

```powershell
python scripts/evaluate_matching.py --manifest tests/fixtures/seed-world.json --base-url http://127.0.0.1:18080
```

- 入口：真实 HTTP `GET /v1/matches`，actor alice；`rule_version = rules-v1.1`。
- fixture：`tests/fixtures/matching-v1.json`；SHA-256 前后均为
  `443e7e59ed2e887314dc9528d1d2eed5dc7d1565bc92afa56939936047bcef99`，标签未改。
- 结果 JSON：`evidence/matching-evaluation-v1.0.1.json`；原 v1.0 JSON 保留。

| 分区 | 正例 Top3 | 负例有推荐 | 结果 |
| --- | --- | --- | --- |
| development | 24/24 = **1.000** | 0/7 = **0.000** | 通过 |
| regression（**已见合成回归集**） | 15/16 = **0.9375** | 0/5 = **0.000** | 通过 |
| 合计 | 39/40 = **0.975** | 0/12 = **0.000** | gate passed |

- 唯一 miss：`P32`（regression，期望 `T-M-F32`，返回空）。
- 失败 case、`evaluation_scope` 与 `已见合成回归集` 说明已写入 JSON。
- **局限**：全部为合成数据、规模小、单标注者；development 用于规则门槛选择，regression 是
  已见回归集，不是未见数据，不能把 0.975 当成真实校园/未见数据泛化准确率。

## 4. 真实性能基准

```powershell
python scripts/benchmark.py
```

脚本自管 18080，自建 1000+ 数据并清理专属前缀；真实 HTTP + 真实 MySQL；无 mock。

| 数据 | 值 |
| --- | --- |
| 实测样本 | **1023**（1002 listings + 1 claim + 20 messages） |
| 并发/轮次/次数 | 20 / 3 轮 / 每端点每轮 100（共 900） |
| 状态码 | 全部 200；0 5xx；0 client 未捕获异常 |
| 服务端日志 | `bytes_read=85902`（非空）；tracebacks=0，ASGI exceptions=0，HTTP 500 行=0 |
| 服务端读取方式 | uvicorn stdout/stderr 合并日志，启动后 offset 读取，统计 Traceback / Exception in ASGI application / 500 |
| 端口释放 | managed=true，released=true，18080 已空闲 |
| 清理 | prefix `T-PERF-b16397dd-` 清理；`origin LIKE 'perf-%'` 与 `T-PERF-%` 均 0 |

### 端点 P95/P99 与逐轮 P95

| 端点 | 总数 | P50 | P95 | P99 | 轮1 P95 | 轮2 P95 | 轮3 P95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 认领列表 | 300 | 311.1 ms | **512.6 ms** | 686.7 ms | 526.9 | 475.8 | 527.2 |
| 会话读取 | 300 | 149.2 ms | **217.7 ms** | 240.0 ms | 208.8 | 213.4 | 235.2 |
| 规则匹配 | 300 | 506.0 ms | **670.8 ms** | 763.7 ms | 633.1 | 653.7 | 703.8 |

- 每端点、每轮 P95 均 <1000 ms；匹配单请求 max 955.2 ms，余量有限。
- 硬件：Windows 10.0.26300 / Intel64 Family 6 Model 183 / 32 vCPU / 32 GB
  （运行前 available 约 5.9 GB）。
- 数据库：MySQL 8.0.46 / max_connections 30 / buffer pool 64 MiB / REPEATABLE-READ。
- 连接池：客户端 20；后端 SQLAlchemy pool_size=5 + max_overflow=5 = 10/进程；服务端上限 30。
- JSON：`evidence/performance-benchmark-v1.0.1.json`；server log：
  `evidence/performance-server-v1.0.1.log`。

## 5. 与 v1.0 的差异

| 项 | v1.0 | V1.0.1 实际 |
| --- | --- | --- |
| 集成 | 95 passed / 2 failed / 3 xfailed | **118 passed / 0 failed / 0 skipped / 0 xfailed** |
| 同键并发 create | 一个 500 | 通过 |
| DISPUTED 消息 | 201 | 409，只读 |
| 空白 evidence/message | 接受 | 422，严格测试通过 |
| reset 超 24h | 未验证持久化 | 410 且 DB EXPIRED |
| 非 published 认领 | 未覆盖 | 422 `not_claimable` |
| 匹配 | 正例 1.0，负例 1.0（fail） | 正例 0.975，负例 0.0（pass，rules-v1.1） |
| 性能 | 900 请求，PASS | 900 请求，PASS；服务端日志 0 异常 |

原 `evidence/performance-benchmark.json`、`matching-evaluation.json`、`test-run-v1.0.md`、
`backend-defects-v1.0.md` 未被覆盖。

## 6. 测试适配说明（非后端缺陷）

- V1.0.1 契约要求 `after` 游标属于本会话；首屏不再发送 `after=0`，改为省略 `after`。
  这是测试客户端对最终契约的适配，不是放宽断言。
- `ResetRequest.reason` 在冻结 V1.0.1 schema 中仍为可选（默认空串）；空白严格校验适用于
  reject/dispute 的 `ReasonRequest`。因此未把 reset 空 reason 列为后端失败；原先的
  optional-reason 测试已改为验证非空 reason 的正常重置。若产品要求 reset 空白 reason 也必须
  422，这是当前冻结契约与需求之间的缺口（实际仍返回 200），需要先改契约/实现再回归。
- 除上述契约对齐外，没有为通过而修改任何业务期望；v1.0 历史失败保持原样。
