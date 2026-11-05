# V1.0 测试工作流自审表

审计日期：2026-11-05。范围：`tests/integration/`、`tests/performance/`、`tests/fixtures/`、
`tests/conftest.py`、`pytest.ini`、`scripts/evaluate_matching.py`、`scripts/benchmark.py`、`evidence/`。

| # | 检查项 | 结果 | 证据/说明 |
| --- | --- | --- | --- |
| 1 | 只改自己拥有的路径 | 通过 | 写操作仅涉及 `tests/`、`pytest.ini`、两个脚本、`evidence/`；未对 `app/`、`web/`、`.env`、`.env.test`、数据库脚本执行写操作（`git status` 中的既有未跟踪项不代表本工作流改动） |
| 2 | 未读取父目录/课程要求 | 通过 | 仅访问 `D:\软工大作业\claim-subsystem` 与本对话；未枚举父目录 |
| 3 | 只读 `.env.test` 取连接 | 通过 | `claimtest/env.py` 只解析 `.env.test`，校验两个 URL 均为 `claim_test`，不打印凭据 |
| 4 | 拒绝 SQLite/内存库/claim_dev | 通过 | `test_environment_guard.py` 3 passed；seed 与 benchmark 运行前实际 `SELECT DATABASE()` |
| 5 | 只对 `claim_test` 造数/清理 | 通过 | seed 只删 `T-IT-`/`T-M-`；benchmark 只删 `T-PERF-<run>-`；未清 `claim_dev` |
| 6 | 保留 demo 数据 | 通过 | 运行后 `listing_snapshots` 仍有 `origin=demo` 5 found + 3 lost |
| 7 | 真实 MySQL | 通过 | 8.0.46，33307，`claim_test`；schema 7 表；未用 SQLite |
| 8 | 真实 HTTP（非 TestClient） | 通过 | 集成测试连接 `127.0.0.1:18080` 的 uvicorn 子进程；benchmark 走同一真实 HTTP；匹配评测走 HTTP |
| 9 | 只管理自己启动的进程 | 通过 | pytest session 启动/终止自己的 uvicorn（失败时读取自身日志）；benchmark 不启动/不杀外部服务 |
| 10 | 时间测试不睡 60 秒 | 通过 | `claimtest/dbtools.py` 固定 UPDATE：码过期、24h 期限、冷却结束；未 sleep 冷却 |
| 11 | token 篡改/过期真实测试 | 通过 | `v1` 格式重签过期/未来 token；未来 token 200 作为密钥对照，过期 401 |
| 12 | 幂等：同键同 body / 不同 body | 通过 | 同键重放同一 claim；不同 body 409；消息同样覆盖 |
| 13 | 并发批准仅一个成功 | 通过 | 3 轮双线程，均为 1×200 + 1×409，状态一 APPROVED 一 CLOSED_OTHER |
| 14 | 同键并发创建 | **未通过（后端缺陷）** | 一个请求 500；见 D2 |
| 15 | 终态只读（REJECTED/WITHDRAWN/CLOSED_OTHER/COMPLETED/EXPIRED） | 通过 | 状态操作/消息均在终态 409；COMPLETED 重复 confirm 为幂等 200 |
| 16 | DISPUTED 只读 | **未通过（后端缺陷）** | 消息 POST 201；测试保持 409 期望；见 D1 |
| 17 | 隐私字段 | 通过 | 公开 listing/claim/message/export 无 `user_id`/`publisher_id`/真实身份；alias 可解释 |
| 18 | PII 硬拦且不落库 | 通过 | 手机号、邮箱、15/18 位证件号均 422；GET 会话确认未写入 |
| 19 | 24h 期限、码过期、重置 2 次、nonce | 通过 | 真实 DB 时间接缝 + HTTP 断言；旧码失效、新码完成 |
| 20 | 匹配集规模/切分 | 通过 | 40 正例、12 负例、15 干扰；dev 24/7，reg 16/5；无真实 PII |
| 21 | 匹配标签不可变 | 通过 | 评估前后 SHA-256 均为 `443e7e...ef99`；脚本只读 |
| 22 | 匹配正例 Top3 召回 | 通过 | 40/40 = 1.0（≥0.8） |
| 23 | 匹配负例误推荐 | **未通过（规则缺陷）** | 12/12 = 1.0（要求 ≤0.2）；见 D3 |
| 24 | 性能数据规模 | 通过 | 实测 1002 listings + 1 claim + 20 messages = 1023，≥1000 |
| 25 | 性能并发/轮次/次数 | 通过 | 20 并发、预热 10、3 轮、每端点每轮 100，共 900 请求 |
| 26 | 性能门槛 | 通过 | P95 512.3 / 232.7 / 659.2 ms，0 5xx，0 未捕获异常 |
| 27 | 性能数据清理 | 通过 | `T-PERF-467f2994-` 清理后 listing 0 行；`origin LIKE 'perf-%'` 0 |
| 28 | 不使用 mock 延迟 | 通过 | loadgen 发真实 HTTP；benchmark 无 mock/fallback，setup 失败退出 2 |
| 29 | 失败不伪装成通过 | 通过 | 2 failed、3 xfailed、匹配 gate failed 均原样记录；未改期望迎合实现 |
| 30 | 证据可复核 | 通过 | `evidence/test-run-v1.0.md`、`performance-benchmark.json`、`matching-evaluation.json`、本表、缺陷清单 |

## 复核命令

```powershell
# 环境
& '.\scripts\local_mysql.ps1' -Action Status

# 重新 seed
python tests/fixtures/seed_test_world.py

# 启动专属后端
$env:APP_ENV='test'
python -m uvicorn app.main:app --host 127.0.0.1 --port 18080

# 集成（另开终端）
$env:CLAIM_TEST_BASE_URL='http://127.0.0.1:18080'
python -m pytest tests/integration -q

# 离线
python -m pytest tests/integration/test_dataset_integrity.py tests/performance/test_loadgen_policy.py tests/integration/test_harness_contract.py -q
python -m pytest tests/integration/test_environment_guard.py -q

# 匹配与性能
python scripts/evaluate_matching.py --manifest tests/fixtures/seed-world.json --base-url http://127.0.0.1:18080
python scripts/benchmark.py --base-url http://127.0.0.1:18080
```

## 已知限制

- 匹配集为合成、小规模、单标注者构造；不能外推真实召回率。负例口径偏严格（任何非空 Top3）。
- 性能为本机 Windows + WSL MySQL，64 MiB buffer pool；不是生产容量结论。
- 3 个空白输入 xfail 是后端校验限制，不计通过；2 个失败是后端/规则缺陷，见 `backend-defects-v1.0.md`。
- 集成测试会改变 `claim_test` 状态；重跑前必须重新 seed，否则场景 found 已被批准/关闭。
