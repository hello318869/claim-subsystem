# FastAPI → Django 迁移说明（v2.0.0）

日期：2026-11-09
范围：失物认领子系统（C）按《共同字段与接口约定-02》v0.3 从 FastAPI 迁到 Django。
A（账号/校园身份）与 B（信息发布）仍为本地演示适配器，不随本次迁移实现。

## 1. 为什么这样改

| 诉求 | 处理 |
| --- | --- |
| 后端框架改为 Django | Django 5.2 + DRF；`manage.py`、`config/` 项目包、三个应用 |
| 接口按共同契约 | `/api/v1` 下 C 的 10 个接口，信封、错误码、分页、状态语义逐条对齐 |
| 保留原有业务规则 | 状态机、锁顺序、幂等语义、匹配打分与旧实现等价（含并发与回滚用例） |
| A/B 未就绪 | `identity/`、`posts/` 作为演示适配器，暴露契约 §7.3 的内部函数 |
| 不丢旧库 | 新表用 Django 默认前缀，可在既有隔离库上直接 `migrate` |

## 2. 目录映射

| FastAPI（迁移前） | Django（迁移后） | 说明 |
| --- | --- | --- |
| `app/main.py` | `config/urls.py`、`config/settings.py` | 路由、信封、CORS、静态页 |
| `app/team/api.py` | `claims/views.py`、`claims/urls.py` | 契约 C 的 HTTP 层 |
| `app/team/claims.py` | `claims/services/claims.py` | 状态机与内部函数 |
| `app/team/messages.py` | `claims/services/messages.py` | 会话与游标 |
| `app/team/matching.py` | `claims/services/matching.py` | 规则匹配 |
| `app/team/contracts.py` | `common/contracts.py` | `UserSummary` / `Post` / `PostSummary` |
| `app/team/demo.py` | `identity/*`、`posts/*` | 演示 A/B 适配器（ORM + 服务） |
| `app/team/models.py`、`app/models.py` | `claims/models.py`、`posts/models.py`、`identity/models.py` | Django ORM |
| `app/errors.py` | `common/errors.py` | `AppError`、异常处理 |
| `app/clock.py` | `common/clock.py` | UTC / ISO 8601 |
| `app/rules.py`（联系方式部分） | `common/privacy.py` | 消息联系方式过滤 |
| `app/config.py` | `config/settings.py` | `.env` / `.env.test` 读取 |
| `scripts/init_db.py` | `manage.py migrate` + 数据迁移 | 建表与初始字典/演示账号 |
| `scripts/seed_team_demo.py` | `posts/management/commands/seed_team_demo.py` | 演示数据 |
| `tests/{unit,integration,performance}` | `tests/*.py`（pytest-django） | 契约测试 |

旧 FastAPI 的 `/v1` 课程演示接口（`listings`、`claims` 旧状态机、交接码、争议、幂等重放、
`/v1/matches`）属于 v1.x 交付物，未进入共享契约，随 `app/` 一并移除，git 历史可追溯。

## 3. 接口映射（契约 → 代码）

| 契约 | 方法/路径 | 视图 | 服务 |
| --- | --- | --- | --- |
| §6.1 | POST `/claims` | `claims.views.ClaimCreateView` | `services.claims.create_claim` |
| §6.1 | GET `/claims/{id}` | `ClaimDetailView` | `get_claim` |
| §6.1 | GET `/users/me/claims` | `MyClaimsView` | `list_claims` |
| §6.1 | POST `/claims/{id}/accept` | `ClaimAcceptView` | `accept_claim` |
| §6.1 | POST `/claims/{id}/reject` | `ClaimRejectView` | `reject_claim` |
| §6.1 | POST `/claims/{id}/cancel` | `ClaimCancelView` | `cancel_claim` |
| §6.1 | POST `/claims/{id}/confirm-handover` | `ClaimConfirmHandoverView` | `confirm_handover` |
| §6.2 | POST/GET `/claims/{id}/messages` | `ClaimMessagesView` | `send_message` / `list_messages` |
| §6.3 | GET `/posts/{id}/matches` | `PostMatchesView` | `matching.find_matches` |
| §7.3 | `close_pending_claims(post_id, reason, except_claim_id)` | — | `services.claims.close_pending_claims` |
| §7.3 | `has_completed_claim(post_id)` | — | `services.claims.has_completed_claim` |
| §7.3 | `get_post_for_claim(post_id, lock)` | — | `posts.services.get_post_for_claim` |
| §7.3 | `set_handover_state(post_id, transition)` | — | `posts.services.set_handover_state` |
| §7.3 | `require_user(token)` / `get_user_summaries(ids)` | — | `identity.services` |

本地演示接口（契约外）：`POST /api/v1/demo/token`、`POST /api/v1/demo/logout`、
`GET /api/v1/demo/posts`；`/health` 与 `/team` 为运维/演示页面。

## 4. 事务、锁与并发

- 每个写视图一个 `transaction.atomic()`；B 适配器调用在同一事务内，任一步失败整体回滚。
- 锁顺序固定：信息行 → 该信息的申请（按 ID 升序）→ 消息等从属记录（契约 §7.3）。
  `select_for_update()` 用于 `posts.services.get_post_for_claim(lock=True)`、
  `set_handover_state`、`claims.services.*` 的锁定读。
- `lock_claim_for_write` 会重新读取加锁后的申请行，避免 REPEATABLE READ 快照读到旧状态；
  写操作的响应再以加锁读刷新信息状态。
- 数据库兜底：`claims_claim.active_key` 与 `accepted_key` 为可空唯一键，分别保证
  “同一用户对同一信息最多一条有效申请”“同一信息最多一条 accepted 申请”。并发冲突由
  `IntegrityError` 转换为 `409 DUPLICATE_RESOURCE` / `409 STATE_CONFLICT`。
- 并发用例（`tests/test_concurrency.py`）用屏障让两个请求同时到达锁定读，验证：
  重复申请只成功一次、同时同意只选一名交接对象、双方同时确认仍完成、适配器故障全部回滚。

## 5. 数据模型与迁移

| Django 模型 | 表 | 说明 |
| --- | --- | --- |
| `identity.DemoUser` | `identity_demouser` | 演示账号（4 个，数据迁移写入） |
| `identity.AuthToken` | `identity_authtoken` | 令牌摘要、24h 过期、可撤销 |
| `posts.Campus/Category/Location` | `posts_campus` 等 | 契约 §3.4 字典（数据迁移写入） |
| `posts.Post` | `posts_post` | 契约 §3.5 子集：类型、标题、类别、地点、时间、状态、发布者 |
| `claims.Claim` | `claims_claim` | 契约 §3.7 全部字段 + `active_key`/`accepted_key` |
| `claims.ClaimMessage` | `claims_claimmessage` | 契约 §3.8 |

迁移文件：

- `identity/migrations/0001_initial.py`、`0002_seed_demo_users.py`
- `posts/migrations/0001_initial.py`、`0002_seed_dictionaries.py`
- `claims/migrations/0001_initial.py`

新表名带应用前缀，因此旧库里的 `claims`、`team_claims`、`team_demo_posts`、
`listing_snapshots` 等 FastAPI 表不会被覆盖，也不会阻止迁移。确认不再需要旧数据后，可自行
用 SQL 删除这些历史表；Django 不管理它们。

## 6. 接入组员真实模块

1. **A（账号与校园身份）**：替换 `common/authentication.py` 中的令牌解析，改造
   `identity/services.py` 的 `require_user`、`get_user_summaries` 返回 `UserSummary`
   （含 `is_campus_verified`、`verification_mode`）；演示 `/demo/*` 可保留并由 `DEMO_MODE` 关闭。
2. **B（信息发布）**：保持 `posts/services.py` 的三个函数签名，改查真实 `Post` 表；C 仍通过
   `PostSummary` 读取公开字段，通过 `set_handover_state` 请求状态流转。
3. 事务边界仍由 C 的视图负责；B 的内部函数不得自行提交事务（契约 §7.3）。
4. 若 B 的 `Post` 主键改为其他类型，只需保证 `post_id` 仍以字符串存入 `claims_claim`。

## 7. 测试对照

| 契约验收 | Django 用例 |
| --- | --- |
| T05 失物/招领均可申请、自领 403、类型错误 400 | `tests/test_claims.py` |
| T06 并发重复申请只成功一条 | `test_concurrency.py::test_concurrent_duplicate_claims_create_only_one_row` |
| T07 同时同意只选一名 | `test_concurrent_accepts_select_exactly_one_partner` |
| T08 单方确认→双方确认、重复确认不覆盖 | `tests/test_claim_state.py`、`test_concurrent_confirmations_complete_claim_and_post` |
| T09 交接前取消、单方确认后 409 | `test_claim_state.py` |
| T10 撤回关闭待审申请、恢复不恢复历史 | `test_claim_state.py::test_withdrawing_a_post_closes_pending_claims` |
| T11 非参与者 404、终态会话 409 | `tests/test_messages.py` |
| T12 匹配候选可见性与排序 | `tests/test_matching.py` |
| T13 无效/过期令牌 401、伪造身份字段 400 | `tests/test_contract_envelope.py`、`tests/test_claims.py` |
| T14 事务内故障全部回滚 | `test_concurrency.py::test_adapter_failure_rolls_back_claim_and_post_writes` |

运行：`python -m pytest`（需先启动隔离 MySQL；测试库 `claim_test`，`--reuse-db`）。
