# 失物认领子系统 HTTP 数据契约 v1.0

状态：**冻结（2026-11-05）**。前后端与测试以本文为准；任何字段改名都必须同时改本文与 RTM。
代码入口：`app.main:app`（工厂 `app.main:create_app()`）。

- 基础路径：`/v1`（`/health`、`/`、`/static` 例外）
- 认证：`Authorization: Bearer <token>`，服务端校验 HMAC 签名与 `exp`，缺一即 401
- 时间：UTC，ISO-8601 带 `Z`
- 金额/枚举：`status` 使用大写枚举，见第 9 节

## 1. 权威 DTO

**PublicListingDTO**（任何公开接口都只出现这些字段，**永不出现 `publisher_id`**）

```json
{
  "id": "F-1001",
  "kind": "found",
  "title": "黑色双肩包",
  "category": "bag",
  "occurred_at": "2026-10-28T08:20:00Z",
  "location": "图书馆二楼",
  "description": "黑色双肩包，侧袋有一个蓝色水杯",
  "status": "published",
  "claimable": true
}
```

`kind`: `lost|found`；`status`: `published|claimed`；`claimable` 仅当 `found` 且未获批且外部状态为 `published`。

**ClaimDTO**

```json
{
  "id": "0f3c8f0e-6f0a-4d6e-9c1a-2b7d5e4a1c33",
  "item_id": "F-1001",
  "status": "PENDING",
  "my_role": "applicant",
  "evidence_text": "包内有蓝色水杯和借书卡",
  "item_number": "ASSET-2026-0042",
  "reason": null,
  "confirmed_by_me": false,
  "confirmed_by_counterpart": false,
  "created_at": "2026-11-05T08:10:00Z",
  "updated_at": "2026-11-05T08:10:00Z",
  "handover_deadline": null
}
```

- `my_role`: `applicant|finder`，随调用者变化
- `reason`: 驳回理由或争议理由
- 两个布尔值对应交接双确认；非 `APPROVED` 时均为 `false`

**MessageDTO**（**绝不出现 `sender_id`**）

```json
{"id": "6a1c...", "text": "好的，食堂门口见", "sender_alias": "申请人-0F3C8F", "is_mine": true, "created_at": "2026-11-05T08:20:00Z"}
```

**分页**：`{"items": [...], "total": 12, "page": 1, "page_size": 20}`，`page≥1`、`1≤page_size≤100`。
**消息分页**：`{"items": [...], "next_after": null}`；`next_after` 非空时作为下一次 `?after=` 传入。

## 2. 错误体

```json
{"code": "invalid_transition", "message": "只有待核验的申请可以批准", "field": null, "retry_after_seconds": null}
```

| HTTP | code | 场景 |
| --- | --- | --- |
| 401 | `unauthorized` | 缺失/签名错误/已过期令牌 |
| 403 | `forbidden` / `demo_disabled` | 非本申请成员；演示入口关闭 |
| 404 | `not_found` | 记录或申请不存在 |
| 409 | `invalid_transition` / `already_approved` / `idempotency_conflict` / `reset_not_allowed` / `conflict` | 状态与并发冲突 |
| 410 | `code_expired` | 交接码或交接期限已过 |
| 422 | `validation_error` / `not_claimable` / `contact_info_blocked` / `invalid_code` | 参数、业务校验、隐私过滤、码错误 |
| 429 | `cooldown_active` / `rate_limited` | 冷却/限流，带 `retry_after_seconds` |
| 500 | `internal_error` | 未捕获异常（缺陷计数） |

## 3. 健康检查

`GET /health` → `{"status":"ok","database":"ok","demo_mode":true,"time":"...Z","version":"1.0.0"}`；库不可用时 503 且 `database="unavailable"`。

## 4. 演示身份

`POST /v1/demo/token`，仅 `DEMO_MODE=true` 开放，否则 403 `demo_disabled`。

```json
{"actor": "alice"}
```

```json
{"token": "v1.eyJzdWIiOiJhbGljZSJ9...<sig>", "actor": "alice", "expires_at": "2026-11-05T09:00:00Z"}
```

允许的 actor：`alice`、`bob`、`finder`、`outsider`（422 其他值）。令牌 60 分钟，与真实令牌走同一校验路径。

## 5. 招领/失物

`GET /v1/listings?kind=lost|found&mine=false&q=&page=1&page_size=20`

- `mine=true` 只看自己发布的记录
- `q` 模糊匹配标题/描述/地点/类别
- 返回分页结构，元素为 PublicListingDTO

`GET /v1/listings/{item_id}` → PublicListingDTO；404 不存在。

## 6. 认领

### 6.1 发起

`POST /v1/claims`

```json
{"item_id": "F-1001", "evidence_text": "包内有蓝色水杯和借书卡", "item_number": "ASSET-2026-0042"}
```

- 201：ClaimDTO
- 同一人重复提交同一记录：200 + 已有 ClaimDTO
- 规则：仅 `found` 可认领；不可认领自己发布的记录；同一记录允许多份 PENDING

幂等：`Idempotency-Key` 相同且请求体相同 → 重放首次响应并带 `Idempotent-Replay: true`；请求体变化 → 409 `idempotency_conflict`。

### 6.2 查询

`GET /v1/claims?role=applicant|finder|all&page=1&page_size=20` → 分页 ClaimDTO（只含本人相关申请）

`GET /v1/claims/{claim_id}` → ClaimDTO；非双方 403

### 6.3 状态操作

| 方法与路径 | 角色 | 前置状态 | 后置状态 |
| --- | --- | --- | --- |
| `POST /v1/claims/{id}/withdraw` | 申请人 | PENDING | WITHDRAWN |
| `POST /v1/claims/{id}/approve` | 拾获方 | PENDING | APPROVED（记录级唯一获批指针；其余 PENDING → CLOSED_OTHER） |
| `POST /v1/claims/{id}/reject` | 拾获方 | PENDING | REJECTED（`{"reason": "..."}` 必填） |
| `POST /v1/claims/{id}/dispute` | 双方 | APPROVED | DISPUTED（冻结，不做裁决） |

响应均为 ClaimDTO；非法迁移 409，越权 403。

### 6.4 争议导出

`GET /v1/claims/{claim_id}/dispute-export` → 仅双方；**不含任何 `user_id` / `publisher_id` / 真实身份**

```json
{
  "claim_id": "0f3c...", "exported_at": "2026-11-05T09:00:00Z", "state": "DISPUTED",
  "item": {"id": "F-1001", "kind": "found", "title": "黑色双肩包", "category": "bag",
           "occurred_at": "2026-10-28T08:20:00Z", "location": "图书馆二楼",
           "description": "黑色双肩包，侧袋有一个蓝色水杯", "status": "published", "claimable": false},
  "timeline": [{"at": "2026-11-05T08:10:00Z", "event": "claim.create", "actor_alias": "申请人-0F3C8F"}],
  "evidence_text": "包内有蓝色水杯和借书卡",
  "item_number": "ASSET-2026-0042",
  "dispute_reason": "交接地点无法达成一致",
  "messages": [{"sender_alias": "申请人-0F3C8F", "text": "可以改到食堂门口吗", "created_at": "2026-11-05T08:20:00Z"}]
}
```

## 7. 匿名沟通

`GET /v1/claims/{claim_id}/messages?after=&limit=50` → `{"items":[MessageDTO],"next_after":null}`

`POST /v1/claims/{claim_id}/messages` `{"text": "..."}` → 201 MessageDTO

- 仅双方；非成员 403
- 仅 PENDING / APPROVED / DISPUTED 可发，其余 409
- 服务端硬拦截手机号、邮箱、15/18 位身份证号，命中 422 `contact_info_blocked`，文本**不落库**
- 已知误伤：以 `1[3-9]` 开头的 11 位纯数字物品编号会被拦；编号应走 `item_number` 私有字段
- 速率：每人每申请 20 条/分钟，超出 429

## 8. 规则匹配

`GET /v1/matches?item_id=L-2001`

- 仅本人 `lost` 记录：非本人 403，非 lost 422，不存在 404
- `{"item_id": ..., "rule_version": "rules-v1.0", "threshold": 40, "candidates": [{"item": PublicListingDTO, "score": 86, "reasons": ["类别一致：bag", "描述关键词重合 9 项", "地点一致", "时间接近"]}]}`
- 最多 3 条，`score ≥ 40`；**不自动批准、不推送**

## 9. 交接码

状态枚举：`PENDING|APPROVED|REJECTED|WITHDRAWN|CLOSED_OTHER|EXPIRED|DISPUTED|COMPLETED`

`GET /v1/claims/{id}/code` → `{"claim_id":"...","code":"48291375","expires_at":"...Z"}`

- 只返回**本方**码；对方码只能通过线下交换获得
- 非 APPROVED 409；已过期 410；本方冷却中 429

`POST /v1/claims/{id}/handover/confirm` `{"code":"73910528"}`（提交**对方**码）→ ClaimDTO

- 双方都确认后状态才变 COMPLETED
- 码错误 422 `invalid_code`（消息含剩余次数）；连续 5 次错误 → 60 秒冷却 → 429
- 单方提交永不完成

`POST /v1/claims/{id}/handover/reset` `{"reason":"..."}`

- 仅当本方触发过冷却且冷却已结束，或码已到期；每申请最多 2 次；未超批准后 24 小时
- 200：`{"claim_id","expires_at","reset_count":1,"counterparty_must_refetch":true,"reason":"..."}`
- 不满足条件 409 `reset_not_allowed`
- 重置换 nonce、清空双方确认，旧码立即失效

码有效期 30 分钟；令牌 60 分钟；交接绝对期限 = 批准后 24 小时。

## 10. 不变量

1. 一个 `item_id` 同时最多一条 APPROVED/COMPLETED 申请（`item_approvals.item_id` 主键）。
2. 事务锁序固定：`listing_snapshots` → `claims` → `handover_codes`。
3. 任何接口、日志、错误体、导出都不含身份映射与明文交接码。
4. 前端只做纯文本渲染；服务端不返回 HTML 片段。

## 11. 本地运行（测试协作者按此对接）

```powershell
# 1) 启动隔离 MySQL（33307），首启会生成 .env / .env.test，不覆盖已有文件
& '.\scripts\local_mysql.ps1' -Action Start

# 2) 建表（只建不删）
python scripts/init_db.py --database dev
python scripts/init_db.py --database test

# 3) 演示数据（幂等，origin=demo）
python scripts/seed_demo.py --database dev
python scripts/seed_demo.py --database test

# 4) 启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 配置：`.env`（dev/演示）、`.env.test`（测试，`APP_ENV=test` 时加载），两文件均被 `.gitignore` 排除
- 测试库：`TEST_DATABASE_URL` → `claim_test`；测试可用 `APP_ENV=test` 切换
- 测试运行：`python -m pytest tests/unit`（纯函数用例默认全跑；DB 契约用例需 `RUN_DB_TESTS=1`）
- 演示账号：alice、bob 各有失物记录；finder 有 5 条拾获记录；outsider 用于越权验证
