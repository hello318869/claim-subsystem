# V1.0.1 回归与测量清单（已执行）

状态：**已执行（2026-11-05，commit 861e1c4）**；实际结果见 `evidence/test-run-v1.0.1.md`。
v1.0 的失败与性能/匹配 JSON 保留原样，未覆盖。

- `evidence/performance-benchmark.json`
- `evidence/matching-evaluation.json`
- `evidence/test-run-v1.0.md`
- `evidence/backend-defects-v1.0.md`

新结果将在修复完成后写入 `evidence/*-v1.0.1.json`（以及新的 server log），不覆盖上述文件。

## 1. 新增严格回归（17 个）

| 编号 | 测试文件 | 断言要点 |
| --- | --- | --- |
| ① | `test_regression_concurrency_v1_0_1.py` | 同 actor、不同 Idempotency-Key 并发 create：两个响应均 2xx 且同一 claim id；DB 仅 1 条 PENDING、该 item 仅 1 条 claim |
| ② | 同上 | approve × withdraw、approve × reject 交叉并发：仅 1 个 200，另一个 409；终态只可能是 APPROVED/WITHDRAWN 或 APPROVED/REJECTED；ItemApproval 与终态一致，不被覆盖 |
| ③ | `test_regression_messages_v1_0_1.py` | 同秒直接插入 60 条消息（绕过限流），按 `limit=20` + `next_after` 翻页：不丢、不重、恰好 60；非法 UUID 游标和另一 claim 的游标不得泄漏对方消息 |
| ④ | `test_regression_validation_v1_0_1.py` | 24h 绝对期限过后 reset 返回 410 `code_expired`，且立即查 DB 状态为 EXPIRED（不是 rollback 回 APPROVED） |
| ⑤ | 同上 | 空白 evidence/message/reject reason/dispute reason 均 422 且不落库；reset reason 在冻结 V1.0.1 契约中仍可选，不强行要求 422；历史 xfail 记录保留在 v1.0 evidence，测试已改为严格断言 |
| ⑥ | `test_regression_snapshot_completion_v1_0_1.py` | found 状态 `withdrawn`/`claimed` 时 POST claim 422 `not_claimable` 且无 claim；恢复 `published` 后才 201 |
| ⑦ | 同上 | 完成后双方 `confirmed_by_me`/`confirmed_by_counterpart` 均为 true、status COMPLETED、deadline 不变、reason 不变、listing claimed/claimable=false、取码 409；单方确认后 dispute 会清零确认标志 |
| 匹配 | `test_dataset_integrity.py` | 固定 fixture SHA-256 `443e7e59...ef99`；40/12/15；dev 24/7、reg 16/5 |
| 性能 | `scripts/benchmark.py` | 自管 18080 服务、读取 uvicorn 日志中的服务端异常，不只依赖 client status；输出 v1.0.1 JSON |

### 场景数

新测试需要独立场景；seed 已提升到 **120** 个场景（原 v1.0 为 80，历史记录不改）。
修复后先执行：

```powershell
python tests/fixtures/seed_test_world.py
```

## 2. 匹配 v1.0.1

- fixture 不变：`tests/fixtures/matching-v1.json`，SHA 固定为
  `443e7e59ed2e887314dc9528d1d2eed5dc7d1565bc92afa56939936047bcef99`。
- development/regression 划分保持不变；新增离线测试锁定 SHA 与切分。
- 规则 v1.1 的文本门槛只在 development 分区选择；regression 是**已见合成回归集**，
  最终报告必须写“已见合成回归集”，不得声称未见数据的泛化准确率。
- 规则升级 v1.1 后运行：

```powershell
python scripts/evaluate_matching.py --manifest tests/fixtures/seed-world.json --base-url http://127.0.0.1:18080
```

默认输出改为 `evidence/matching-evaluation-v1.0.1.json`；原 v1.0 负例 100% 失败文件保留。
最终报告必须同时展示 v1.0 负例失败事实与 v1.1 新结果；若仍失败，如实记录。
报告中的 `rule_versions` 应显示 v1.1；不能把 v1.0 的失败覆盖掉。

## 3. 性能 v1.0.1

`scripts/benchmark.py` 新增：

- 默认自管 `127.0.0.1:18080` uvicorn，结束 terminate + wait + 端口释放检查；
- `--server-log` 读取 uvicorn stdout/stderr 日志，从启动后的 offset 统计
  `Traceback`、`Exception in ASGI application`、`500`；日志不可读则判失败；
- 默认输出 `evidence/performance-benchmark-v1.0.1.json`，不覆盖 v1.0；
- 保留逐端点逐轮 P95/P99/状态码计数、数据规模、硬件、客户端/后端连接池、清理结果；
- 门槛新增 `max_server_tracebacks=0`。

修复后命令：

```powershell
python -m pytest tests/integration -q   # 仅后端完成后；覆盖全部原测试 + 新回归
python scripts/evaluate_matching.py
python scripts/benchmark.py
```

本轮不执行以上命令，避免与后端修复竞争，也不轮询后端进度。

## 4. 已知失败的历史状态（不得掩盖）

| 项目 | v1.0 结果 | v1.0.1 要求 |
| --- | --- | --- |
| 同键并发 create | 500 | 新测试 ① 严格 2xx 同 id |
| DISPUTED 消息 | 201 | 原测试保持 409；不得改为 201 |
| 匹配负例 | 1.000 | v1.1 需 ≤0.2，否则如实失败 |
| 空白证据/消息 | 201（xfail） | 新测试严格 422，不落库 |
| reset 超 24h | 尚未单测持久化 | 新测试要求 410 + DB EXPIRED |
| 非 published snapshot | 尚未单测 | 新测试要求 422 |
| reset 空 reason | v1.0 测试曾按可选 reason 期望 200 | 冻结 V1.0.1 schema 仍将 reset reason 设为可选；旧测试改为验证非空 reason，未把 reset 空白列为本轮失败；v1.0 证据保留 |

## 5. 证据写入规则

- 只写新文件：`*-v1.0.1.json`、`performance-server-v1.0.1.log`。
- 不覆盖 `performance-benchmark.json`、`matching-evaluation.json`、`test-run-v1.0.md`、
  `backend-defects-v1.0.md`、`self-audit-v1.0.md`、`testing-plan.md` 中的历史结果。
- 若修复后仍有失败，新增失败记录追加到 v1.0.1 文档，不删除原失败。

## 6. 执行自检（2026-11-05）

| 检查 | 结果 |
| --- | --- |
| 全量集成 | **118 passed，0 failed/skipped/xfailed**（18.51s） |
| 18080 | 测试工作流启动/管理；集成后停止；性能脚本再自管；最终端口 free |
| 测试收集 | **129 collected**（集成 118 + 性能 11） |
| 新回归标记 | `pytest -m regression_v1_0_1`，17 个 |
| 新 seed | 120 场景，467 条测试 listing；重跑前需重新 seed |
| 匹配 fixture SHA | 未变：`443e7e59...ef99` |
| 匹配实测 | rules-v1.1：总 0.975，dev 1.0，reg 0.9375（已见），负例 0 |
| 性能实测 | 900 请求、1023 样本、0 5xx、0 server traceback、P95 均 <1s；prefix 清理 0 |
| 原 evidence JSON | 未覆盖，时间戳/内容保留 |
| 脚本语法/CLI | benchmark/evaluate `--help` 正常 |

重跑命令：

```powershell
python tests/fixtures/seed_test_world.py
python -m pytest tests/integration -m regression_v1_0_1 -q
```

完整结果见 `evidence/test-run-v1.0.1.md`。
