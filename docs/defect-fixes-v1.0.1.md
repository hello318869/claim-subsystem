# V1.0.1 缺陷修复记录

日期：2026-11-05。范围：仅后端与后端文档（`app/`、`docs/`、`tests/unit/`）。
V1.0 的失败证据保留原样，未删除、未覆盖：
`evidence/backend-defects-v1.0.md`、`evidence/test-run-v1.0.md`、`evidence/matching-evaluation.json`。

## 总览

| # | 缺陷 | 根因 | 修复 | 回归点 |
| --- | --- | --- | --- | --- |
| F1 | 同 Idempotency-Key 并发创建返回 500 | `check()` 先读、`remember()` 后写；两事务都读到空，后写者撞主键未被转译 | 键在**业务事务内**用占位行预占；冲突时用 `SELECT ... FOR UPDATE`（当前读）取已提交行，按指纹重放或 409 | `test_same_idempotency_key_concurrent_create_never_500` |
| F2 | 同人不同键并发创建产生重复 PENDING | `find_pending_by` 是普通 SELECT；REPEATABLE READ 早快照看不到并发已提交行 | 去重查询改 `FOR UPDATE` 当前读；同时 `item_approvals` 查询也改为加锁读 | `test_different_keys_concurrent_create_yields_one_pending` |
| F3 | 幂等指纹可枚举 | 裸 SHA-256（8 位交接码仅 10^8 空间） | 改为域分离 HMAC：`HMAC(AUTH_SECRET, "idem-v1|actor|operation|canonical)"`；码不入幂等缓存 | `test_fingerprint_is_keyed_and_domain_separated` |
| F4 | 锁后仍用旧实体 | `_locked_claim` 先 `get` 再 `FOR UPDATE`，未 `populate_existing`，身份映射返回旧 `status` | 所有锁读（listing / claim / code）加 `populate_existing` | `test_locked_read_refreshes_stale_identity` |
| F5 | 撤销/争议与批准/确认互相覆盖 | 同 F4 | 同 F4；`approve` 的获批指针检查也改当前读 | 同上 + 既有 approve 用例 |
| F6 | DISPUTED 仍可发消息 | `CHAT_OPEN_STATES` 含 DISPUTED；状态检查与写入非原子 | 开放状态仅 PENDING/APPROVED；发送前 `SELECT claim FOR UPDATE` 串行化 | `test_disputed_claim_rejects_new_messages` |
| F7 | 纯空白 evidence/message/reason 入库 | Pydantic `min_length` 只校验原始长度 | 字段校验器先 `strip()` 再判非空；`item_number` 去空白后为空则转 `None` | `test_whitespace_only_bodies_are_422`、`test_blank_*` |
| F8 | 负例被推荐率 1.0 | 类别 35 + 时间 15 = 50 已过阈值 40 | 新增文本证据门槛：重合词元 ≥ 9；规则版本 `rules-v1.1` | `test_development_split_meets_both_gates`、`test_regression_split_is_reported_honestly` |
| F9 | 期限后 reset 的 EXPIRED 被回滚 | 设置状态后 `raise`，事务回滚 | 改为返回 `(410, error_body)`，先 flush 再由路由提交 | `test_reset_after_deadline_persists_expired` |
| F10 | 同秒消息被游标丢弃 | 只按 `created_at > anchor` | 键集游标 `(created_at, id)`；校验游标归属，异会话 422 | `test_cursor_keeps_messages_written_in_the_same_second`、`test_foreign_cursor_is_rejected` |
| F11 | 导出静默截断 500 条 | 固定 `limit=500` | 分页读到底，返回 `messages_total` / `messages_truncated` | `test_dispute_export_reports_message_totals` |
| F12 | 非 published 记录可认领 | 只校验 `kind=found` | 增加 `snapshot.status == "published"` 校验 | `test_unpublished_snapshot_is_not_claimable` |
| F13 | 终态确认标志语义不清 | DTO 无条件读 code 行 | `APPROVED` 实时、`COMPLETED` 保留历史、其余清零 | `test_completed_claim_keeps_confirmation_history_and_disputed_clears_it` |
| F14 | 文档与实现冲突 | 契约 §7/§8/§10 及处理设计旧版 | 契约改为 DISPUTED 只读、`rules-v1.1`、`/code` 例外；处理设计新增 UC-02 聊天，交接改 UC-03 | 文档评审 |

## 关键实现说明

**幂等预占**（`app/idempotency.py`）
占位行与业务结果在同一事务提交；失败回滚即释放键。冲突路径用加锁读绕开 RR 快照，
因此“业务已提交又报 500”不再可能。占位行 `response_status=0` 仅在同一事务内可见。

**锁读刷新**（`app/repos/*`）
`with_for_update()` + `execution_options(populate_existing=True)`。没有这一步，
先 `get()` 的 anchor 会让等待锁后的实体仍是旧值，正是撤销覆盖批准、争议后仍可确认的成因。

**规则 v1.1**（`app/rules.py`）
权重与阈值不变（类别 35 / 文本 30 / 地点 20 / 时间 15，阈值 40），新增
`MIN_TEXT_OVERLAP = 9` 的文本证据门槛。门槛只在 development 分区选择
（24/24 正例、0/7 负例），regression 作为**已见**回归集单独报告，不是独立未见测试。

## 实测（本机，`claim_test`，真实 MySQL）

```text
$env:RUN_DB_TESTS=1; python -m pytest tests/unit -q
49 passed in 1.62s
```

匹配规则离线复算（同一冻结 fixture，未改标签）：

| 分区 | Top-3 召回 | 负例被推荐 | 门槛 |
| --- | --- | --- | --- |
| development | 24/24 = 1.000 | 0/7 = 0.000 | 召回 ≥0.8，负例 ≤0.2 |
| regression（已见） | 15/16 = 0.9375 | 0/5 = 0.000 | 同上 |
| 合计 | 39/40 = 0.975 | 0/12 = 0.000 | — |

以上是**离线复算**，尚未经测试协作者的真实 HTTP 评测脚本重跑；`rule_version` 已改为
`rules-v1.1`，需由测试会话执行 `scripts/evaluate_matching.py` 生成新的
`matching-evaluation-v1.1.json`。v1.0 的 `matching-evaluation.json`（`status=failed`）保持原样。

## 未解决与移交

1. **性能未重测**：本次改动新增一次幂等占位 INSERT 与聊天行锁，P95 需由性能会话复测
   （v1.0 匹配端点 659 ms，余量本就有限）。
2. **匹配评测未重跑**：v1.1 是否过门槛以上表离线复算为准，正式结论待真实 HTTP 评测。
3. **集成用例未重跑**：`tests/integration/` 的 2 个失败用例与新 xfail 需由测试会话复跑确认。
4. **规则门槛的边界敏感性**：gate=10 时 development 召回降到 21/24，说明 9 是当前数据下的
   贴合值；真实数据分布不同需重新评估，不能把 0.975 当作真实校园准确率。
5. **聊天限流仍为单进程内存**；交接码密钥轮换仍未实现。
