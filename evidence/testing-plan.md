# V1.0 测试计划与证据索引

执行日期：2026-11-05。后端已冻结；权威契约 `docs/api-contract.md`；入口 `app.main:app`。
本计划覆盖三个核心功能：认领全流程、匿名沟通、可解释规则匹配；不实现/不改动注册、发布、管理员。
**所有结果以实际执行为准；已知失败和 xfail 未被改写为通过。**

## 1. 所有权与环境边界

本工作流只维护：

```text
tests/integration/  tests/performance/  tests/fixtures/  tests/conftest.py
pytest.ini  scripts/evaluate_matching.py  scripts/benchmark.py  evidence/
```

未修改 `app/`、`web/`、`.env`、`.env.test` 或数据库环境脚本。测试通过 HTTP 访问真实后端；
除时间接缝外不导入业务代码。连接只来自 `.env.test`，两个 URL 均强制 `claim_test`；拒绝 SQLite、
内存库、`claim_dev`。seed/benchmark 只删除自己的前缀，不全局 truncate。

| 项目 | 实测 |
| --- | --- |
| MySQL | 8.0.46，127.0.0.1:33307，`claim_test`，7 表 |
| 后端 | uvicorn `app.main:app`，`APP_ENV=test`，`127.0.0.1:18080` |
| demo 数据 | 保留 5 found + 3 lost |
| 测试数据 | 80 场景（240 listing）+ 匹配 55 found/52 lost，共 347 测试 listing |
| 清理 | 性能前缀 `T-PERF-467f2994-` 清理为 0；demo/seed 保留 |

## 2. 测试架构

```text
tests/conftest.py                 # 环境、后端进程、seed、scenario、db_tools fixtures
tests/fixtures/claimtest/         # harness（不导入 app）
  env.py                          # .env.test + claim_test 硬守卫，APP_ENV=test
  api.py                          # HTTP 客户端、统一错误、DTO/分页访问器
  seed.py                         # manifest/module/command 适配器
  dbtools.py                      # claim_test-only 固定 SQL 时间接缝
  privacy.py                      # 身份字段/PII 断言
  jwt_tools.py                    # v1 签名 token 重签（过期/未来）
  matching.py                     # 匹配集加载与完整性校验
tests/fixtures/seed_test_world.py # 真实行 seeder（80 场景 + 匹配集）
```

- 未设置 `CLAIM_TEST_BASE_URL` 时，pytest 在 18080 启动自己的 uvicorn，结束后终止；只管理该子进程。
- 设置 `CLAIM_TEST_BASE_URL` 时连接外部后端；本次全量运行连接自己启动的 18080。
- seed 缺失时依赖测试 skip；本次已生成 80 场景 manifest，因此主要业务测试实际执行，未跳过。
- 响应契约集中适配：`token`、`PENDING/CLOSED_OTHER/EXPIRED`、`candidates`、`next_after`、
  `my_role`、`sender_alias` 等均按 V1.0 契约。

## 3. 覆盖矩阵与实际结果

| 需求 | 测试 | 结果 |
| --- | --- | --- |
| demo token、Bearer、401/403 | `test_auth.py` | 13 passed；v1 token 篡改/过期 401，未来签名对照 200 |
| 健康/环境/MySQL | `test_environment_guard.py` | 3 passed |
| 公开 DTO、mine、分页、404/422 | `test_listings.py` | 7 passed |
| 创建/双方可见/私有证据/角色 | `test_claims.py` | 13 passed, 2 xfailed（空白 evidence） |
| 状态机/越权/CLOSED_OTHER | `test_claim_state_machine.py` | 11 passed |
| 双方完成/码/nonce/冷却/重置/24h | `test_handover_flow.py` | 14 passed |
| 匿名沟通/游标/PII/终态 | `test_messages.py` | 8 passed, 1 xfailed（空白消息） |
| 争议、导出 | `test_dispute.py` | 5 passed, **1 failed（DISPUTED 消息）** |
| 幂等重放/冲突/并发 | `test_idempotency.py`, `test_concurrency.py` | 7 passed, **1 failed（同键并发 500）** |
| 匹配 API Top3/score/reasons/rule_version | `test_matching.py` | 4 passed |
| 匹配集完整性 | `test_dataset_integrity.py` | 5 passed |
| 隐私 | `test_privacy.py` | 2 passed |
| harness 自检 | `test_harness_contract.py` | 3 passed |
| benchmark 数学/门禁 | `test_loadgen_policy.py` | 9 passed |

**全量集成：95 passed, 2 failed, 3 xfailed（15.69s）。**
失败与 xfail 的逐项原因见 `test-run-v1.0.md` 与 `backend-defects-v1.0.md`。

## 4. Seed 与时间接缝

### 4.1 Seed

`python tests/fixtures/seed_test_world.py`：

- 只连接/校验 `claim_test`；
- 删除旧的 `T-IT-` / `T-M-` 认领、消息、码、审批、审计、listing；
- 清理四个 demo actor 的幂等记录（claim_test）；
- 写入 80 个独立场景：1 finder found + alice/bob 各 1 lost；`claimants.*.item_id` 指向 found；
- 写入 matching-v1 的 40 目标 found、15 干扰 found、52 lost；
- 写 `tests/fixtures/seed-world.json`；
- 重跑完整测试前必须重新执行；否则场景 found 已被批准/关闭。

### 4.2 时间接缝

不 sleep 60 秒。`claimtest/dbtools.py` 只执行固定参数化 UPDATE，连接先校验 `claim_test`：

| 方法 | 用途 |
| --- | --- |
| `expire_code` | 码 410、到期后 reset |
| `expire_handover_deadline` | 批准后 24h 绝对期限 -> 410/EXPIRED |
| `end_cooldown` | 连续 5 次错误后的 60s 冷却结束 -> 允许 reset/继续 |

token 过期用 `v1` 格式 + `.env.test` 的 AUTH_SECRET 重签，不使用 sleep。

## 5. 匹配评测

`tests/fixtures/matching-v1.json`（SHA-256 `443e7e59...ef99`）：

| 项 | 数量 |
| --- | --- |
| 正例 | 40（development 24 / regression 16） |
| 无对应物负例 | 12（development 7 / regression 5） |
| 目标 found | 40 |
| 干扰 found | 15 |

- 生成/标注规则、切分规则、局限均写在 fixture 的 `provenance` 与 `metric_definitions` 中。
- 评估脚本只读 fixture，前后 SHA-256 一致；不改标签、不删失败 case。
- 实际调用 HTTP `GET /v1/matches`（alice，rule_version `rules-v1.0`）。

| 指标 | 实测 | 门槛 | 结果 |
| --- | --- | --- | --- |
| 正例 Top3 召回 | 1.000（40/40） | ≥0.8 | 通过 |
| 负例有推荐比例 | 1.000（12/12） | ≤0.2 | **失败** |
| 负例 score>0 比例 | 1.000 | 参考 | 失败 |
| 执行错误 | 0 | 0 | 通过 |

失败根因：类别 35 + 时间 15 = 50，单独超过阈值 40；负例均为“无对应物但同类别/近时间”，
因此全部被推荐。详见 D3。未通过修改负例标签或提高推荐口径来刷分。

证据：`evidence/matching-evaluation.json`（`status=failed`，gate reasons，全部失败 case）。

## 6. 性能基准

`scripts/benchmark.py` 自建并清理专属前缀：

- 1000 条 `T-PERF-<run>-F*` found + 1 lost + 1 target found（origin `perf-<run>`）；
- 1 条 APPROVED claim + 20 条 messages；
- 预热 10 次/端点；3 轮；每轮每端点 100 次；20 并发；
- 真实 HTTP 18080 + 真实 MySQL；0 mock；
- 门槛：分端点/逐轮 P95 ≤1000 ms、5xx=0、未捕获异常=0；
- 报告：状态码、P50/P95/P99、数据规模、硬件、服务端/客户端连接池、轮次、清理结果。

**实际 PASS**：

| 端点 | 请求数 | P50 | P95 | P99 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 认领列表 | 300 | 311.0 ms | **512.3 ms** | 615.5 ms | 200×300 |
| 会话读取 | 300 | 137.1 ms | **232.7 ms** | 269.6 ms | 200×300 |
| 规则匹配 | 300 | 508.0 ms | **659.2 ms** | 741.8 ms | 200×300 |

- 总计 900 请求；0 5xx；0 未捕获异常。
- 实测 1023 样本（1002 listings + 1 claim + 20 messages）。
- 硬件：Windows 10.0.26300 / Intel64 Family 6 Model 183 / 32 vCPU / 32 GB。
- 数据库：MySQL 8.0.46 / max_connections 30 / buffer pool 64 MiB。
- 连接池：客户端 20；后端 pool_size 5 + overflow 5 = 10/进程；服务端上限 30。
- 清理：`T-PERF-467f2994-` -> 0 行；`origin LIKE 'perf-%'` -> 0。
- 证据：`evidence/performance-benchmark.json`。

## 7. 后端缺陷（集中转达）

| ID | 严重度 | 问题 | 证据 |
| --- | --- | --- | --- |
| D1 | 高 | DISPUTED 仍可 POST 消息（201），违反冻结只读策略 | `test_dispute.py` 失败 |
| D2 | 高 | 同 Idempotency-Key 并发创建一个请求 500 | `test_concurrency.py` 失败 |
| D3 | 高（规则） | 负例推荐率 1.0，超过 ≤0.2 | `matching-evaluation.json` |
| D4 | 低 | 空白 evidence/message 被接受 | 3 xfailed |

详见 `evidence/backend-defects-v1.0.md`（含根因与修复建议）。测试期望未修改迎合实现。

## 8. 复核命令

```powershell
# 环境（隔离实例）
& '.\scripts\local_mysql.ps1' -Action Status

# 重新 seed（完整集成前必须）
python tests/fixtures/seed_test_world.py

# 方式 A：pytest 自己启动 18080（无 CLAIM_TEST_BASE_URL）
python -m pytest tests/integration -q

# 方式 B：外部启动 18080 后连接
$env:APP_ENV='test'
python -m uvicorn app.main:app --host 127.0.0.1 --port 18080 --log-level warning
$env:CLAIM_TEST_BASE_URL='http://127.0.0.1:18080'
python -m pytest tests/integration -q

# 离线
python -m pytest tests/integration/test_dataset_integrity.py tests/performance/test_loadgen_policy.py tests/integration/test_harness_contract.py -q
python -m pytest tests/integration/test_environment_guard.py -q

# 匹配与性能
python scripts/evaluate_matching.py --manifest tests/fixtures/seed-world.json --base-url http://127.0.0.1:18080
python scripts/benchmark.py --base-url http://127.0.0.1:18080
```

注意：全量集成会消耗 80 个场景中的大部分；失败后重跑前必须重新 seed，不能用旧场景状态判断代码。

## 9. 证据索引

| 证据 | 内容 |
| --- | --- |
| `evidence/test-run-v1.0.md` | 实际命令、95/2/3 结果、匹配 1.0/1.0、性能 PASS |
| `evidence/performance-benchmark.json` | 900 请求逐轮统计、硬件、连接池、清理 |
| `evidence/matching-evaluation.json` | 40/12 指标、失败 case、fixture hash、gate |
| `evidence/backend-defects-v1.0.md` | D1-D4 根因与修复建议 |
| `evidence/self-audit-v1.0.md` | 30 项自审表与复核命令 |
| `evidence/mysql-environment.md` | 隔离 MySQL 环境既有记录 |

## 10. 局限与剩余工作

0. V1.0.1 修复后的补充回归与测量脚本见 `evidence/regression-plan-v1.0.1.md`；本轮未执行，
   原 v1.0 JSON 与本文件结果均保留，不覆盖。
1. 修复 D1/D2/D3/D4 后重新 seed 并重跑全量集成、匹配评测、性能基准；当前结果不代表修复后状态。
2. 匹配集为合成、小规模、单标注者；Top3 召回 1.0 不代表真实用户分布。负例口径为“任何非空 Top3”，
   同时报告 score>0 口径，二者均失败。
3. 性能为本机 Windows + WSL MySQL（64 MiB buffer pool）结果；P95 最高 659 ms，生产/冷缓存需复测。
4. 3 个 xfail 是后端空白输入校验限制，不计通过；2 个 failed 是后端/规则缺陷。
5. `POST /handover/confirm` 对 COMPLETED 的幂等 200 被接受；若产品要求终态 POST 一律 409，需要补充
   契约与测试。
6. 测试数据保留在 `claim_test`（347 条测试 listing + 运行产生的 claims/messages）；仅性能前缀被清理。
   如需清空，只能针对 `claim_test` 并由环境协作者执行。
