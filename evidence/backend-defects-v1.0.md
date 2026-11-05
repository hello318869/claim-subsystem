# V1.0 后端缺陷与规则风险清单

以下问题由真实 HTTP/真实 MySQL 测试或评测直接暴露。测试期望未为迎合实现而修改。
按影响排序，供后端/规则负责人集中修复后再回归。

## D1（高）DISPUTED 状态仍可发送消息，违反冻结的“终态只读”策略

- 位置：`app/services/chat_service.py` `CHAT_OPEN_STATES = {PENDING, APPROVED, DISPUTED}`。
- 复现：`tests/integration/test_dispute.py::test_disputed_claim_messages_are_read_only`
  - 先批准 claim，再 `POST /v1/claims/{id}/dispute` 得到 `DISPUTED`；
  - `POST /v1/claims/{id}/messages` 预期 409，实际 **201 Created**。
- 冲突：`docs/api-contract.md` 第 166 行把 DISPUTED 列为可发；但本项目冻结的终态策略是
  “DISPUTED 冻结后仅只读”。按冻结策略，消息写应 409。
- 影响：争议发生后仍可改写/增加会话证据，破坏冻结快照。
- 建议：POST 消息的开放状态仅保留 PENDING/APPROVED；GET 消息保持可读。同步修正
  `docs/api-contract.md` 的表述，避免再次冲突。
- 证据：`evidence/test-run-v1.0.md` 失败表；本次运行 95 passed / 2 failed。

## D2（高）相同 Idempotency-Key 的并发创建返回 500

- 复现：`tests/integration/test_concurrency.py::test_concurrent_same_key_claim_replay`
  - 两个线程同时以相同 `Idempotency-Key`、相同 body 向 `POST /v1/claims` 发请求；
  - 实际一个请求返回 **500 Internal Server Error**（无统一错误体）。
- 根因（代码审阅）：`app/idempotency.py` 的 `check()` 先读、`remember()` 后写；两个事务
  都先读到不存在，随后第二个事务插入相同 `idempotency_records.idem_key` 主键触发
  `IntegrityError`，未被转换为幂等重放/409。
- 影响：并发重试会产生 5xx，违反“并发写/重复请求幂等”和 5xx=0 的业务要求。
- 建议：在事务内先占位（`INSERT ... ON DUPLICATE KEY`/唯一冲突捕获），冲突时读取已存在
  记录并按 request_hash 返回重放或 409 `idempotency_conflict`；不要向客户端暴露 500。
- 证据：同上；另一个并发批准用例（不同 claim）3 轮均通过，说明 listing/claim 行锁有效。

## D3（高，规则质量）负例有推荐比例 1.0，远超 ≤0.2 门槛

- 复现：`python scripts/evaluate_matching.py --manifest tests/fixtures/seed-world.json --base-url http://127.0.0.1:18080`
  - 正例 Top3 召回 **1.000**（40/40）；
  - 负例有推荐 **12/12 = 1.000**；development 7/7、regression 5/5；score>0 同样 1.0。
- 根因（代码审阅 `app/rules.py`）：类别一致 **35** 分 + 时间接近（≤3 天）**15** 分 = **50**，
  已超过阈值 **40**；即使文本/地点完全不重合，也会返回同类别且时间相近的候选。
  例如 N01（绿色长柄伞）返回 D01/F17/F04 等同为“雨具”的记录。
- 影响：系统几乎对任何同类近期 found 都“推荐”，负例误报率 100%，可解释性也会给出
  误导性的类别/时间理由。
- 建议（不改标签、不重排）：
  1. 加“文本关键词或地点至少一项”作为进入候选的门槛；
  2. 或提高阈值/重新分配权重（例如类别 25、文本 35、地点 25、时间 15），并用同一冻结集回归；
  3. 负例口径已同时报告“任何非空 Top3”和“score>0”，两者均失败，不能用口径解释为通过。
- 证据：`evidence/matching-evaluation.json`（`status=failed`、`gate.reasons`、失败 case 列表）；
  fixture SHA-256 前后一致，未改任何标签。

## D4（低）仅空白字符的 evidence_text / 消息被接受

- 复现：
  - `test_create_claim_rejects_empty_evidence[   ]` / `[\n\t]`：201，空白 evidence 入库；
  - `test_empty_message_is_422[\n\t]`：201，body 被 `strip()` 成空字符串后入库。
- 原因：Pydantic `min_length=1` 只检查原始长度，未做 `strip()` 后非空校验；请求 schema 允许
  空白字符串。
- 影响：私有证据/会话出现空内容，影响可读性与争议导出质量。
- 建议：在 schema 或 service 中先 `strip()` 再校验非空；保持错误体 422、field 指向字段。
- 证据：3 个 xfail（未计通过），见 `evidence/test-run-v1.0.md`。

## 观察项（不列为失败）

- `POST /handover/confirm` 在 claim 已 `COMPLETED` 时返回 200（幂等重放），未改变状态；
  测试接受该幂等行为。若要求终态 POST 一律 409，需要产品明确。
- `POST /v1/claims` 无 `Idempotency-Key` 时仍可创建/去重（按人 + item 返回已有 200）；
  这与冻结契约“key 可选”一致，不属于缺陷。
- 性能基准本机达标，但 P95 最高为匹配 659.2 ms，距离 1000 ms 余量有限；生产数据/冷缓存
  下需复测。
