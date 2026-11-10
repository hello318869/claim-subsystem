# 校园失物招领 · 失物认领子系统（v2.0.0 · Django）

## 小组联调版

按《共同字段与接口约定-02》v0.3 实现 **C：失物认领子系统** 的 `/api/v1` 接口：

- 认领申请：`POST /claims`、`GET /claims/{id}`、`GET /users/me/claims`
- 审核与交接：`accept`、`reject`、`cancel`、`confirm-handover`
- 申请内站内消息：`POST/GET /claims/{id}/messages`
- 可解释规则匹配：`GET /posts/{id}/matches`

技术栈为 **Django 5.2 + Django REST Framework + MySQL 8**。A（账号与校园身份）和 B（信息
发布）仍是本地演示适配器，只提供契约要求的 `UserSummary` / `Post` 结构；接入组员的真实模块
时替换 `identity/services.py` 与 `posts/services.py` 即可，认领代码不变。

浏览器打开 <http://127.0.0.1:8000/team> 使用联调工作台；健康检查 `/health`。
旧版 FastAPI 的 `/v1` 课程演示接口已随本次改造移除（历史说明见第 10 节）。

## 1. 环境要求

| 项 | 版本 |
| --- | --- |
| Windows | 10/11 + PowerShell 7 |
| Python | 3.11+ |
| MySQL | 8.0（由 `scripts/local_mysql.ps1` 在 WSL 内起独立实例，端口 **33307**） |
| Node.js + Edge/Chrome | 仅浏览器联调验证需要（可选） |

## 2. 一键启动

双击项目根目录的 `start-demo.cmd`。脚本会：

1. 复用/启动项目专用 MySQL（`127.0.0.1:33307`，库 `claim_dev`、`claim_test`）；
2. 缺失依赖时在 `.venv` 中安装 `requirements.txt`；
3. 执行 `manage.py migrate` 建表并补齐演示数据；
4. 启动 Django 开发服务器并打开 <http://127.0.0.1:8000/team>。

只启动服务、不打开浏览器：`.\start-demo.cmd -NoBrowser`。隔离 MySQL 可用
`& '.\scripts\local_mysql.ps1' -Action Stop` 停止；状态用 `-Action Status` 查看。

## 3. 手动安装与启动

```powershell
cd 'D:\软工大作业\claim-subsystem'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

& '.\scripts\local_mysql.ps1' -Action Start   # 生成 .env / .env.test，创建 claim_dev / claim_test
python manage.py migrate                       # 建表（不会删除旧数据）
python manage.py seed_team_demo                # /team 演示样例信息（幂等）
python manage.py runserver 127.0.0.1:8000
```

- 页面：<http://127.0.0.1:8000/team>；健康检查：<http://127.0.0.1:8000/health>
- 生产部署：`gunicorn config.wsgi` 或 `uvicorn config.asgi:application`（需另配静态资源）。
- `.env`、`.env.test` 由脚本生成且被 `.gitignore` 排除；**不要打印或提交**。

## 4. 演示身份

`/api/v1/demo/token` 仅在 `DEMO_MODE=true` 时可用，签发 24 小时、服务端可撤销的随机令牌
（数据库只保存摘要）。演示账号：

| 账号 | 昵称 | 校园身份 | 用途 |
| --- | --- | --- | --- |
| `alice` | 小林 | 已绑定（`demo`） | 申请认领、确认交接 |
| `bob` | 小周 | 已绑定（`demo`） | 竞争申请 |
| `finder` | 小陈 | 已绑定（`demo`） | 发布招领、审核 |
| `outsider` | 访客 | 未绑定 | 验证 `403 IDENTITY_REQUIRED` |

演示数据（`seed_team_demo`）：`TEAM-DEMO-L01/L02` 失物、`TEAM-DEMO-F01/F02` 招领，覆盖匹配与
竞争场景。认证状态在页面上标注为「演示认证」，不声称真实校园认证。

## 5. 接口

所有路径前缀 `/api/v1`，不带结尾 `/`；成功响应 `{"code":"OK","message":"...","data":...}`，
失败响应 `{"code":"...","message":"...","data":null,"errors":{...}}`；时间统一 UTC、以 `Z` 结尾。

| 方法 | 路径 | 权限 | 契约 |
| --- | --- | --- | --- |
| POST | `/claims` | 登录且已绑定校园身份，非发布者 | §6.1，201 |
| GET | `/claims/{id}` | 申请者或对应发布者，否则 404 | §6.1 |
| GET | `/users/me/claims` | 登录；`role=applicant\|publisher`，`status`、`post_id` 筛选 | §6.1 |
| POST | `/claims/{id}/accept` | 对应发布者，可选 `decision_note` | §6.1 |
| POST | `/claims/{id}/reject` | 对应发布者，`decision_note` 必填 | §6.1 |
| POST | `/claims/{id}/cancel` | 待审核仅申请者；交接前双方可取消 | §6.1、§7.2 |
| POST | `/claims/{id}/confirm-handover` | 申请者或发布者，服务端识别确认方 | §6.1、§7.1 |
| POST | `/claims/{id}/messages` | 认领双方且申请为 `pending/accepted` | §6.2，201 |
| GET | `/claims/{id}/messages` | 认领双方（含终态），`after_id`、`limit` 增量读取 | §6.2 |
| GET | `/posts/{id}/matches` | 源信息发布者且信息为 `open` | §6.3 |
| POST | `/demo/token`、`/demo/logout` | 仅 `DEMO_MODE=true` | 本地演示 |
| GET | `/demo/posts` | 仅 `DEMO_MODE=true`，公开分页 | 本地演示 |

实现细节：

- 未知字段、只读字段、非法枚举、越界分页统一 `400 VALIDATION_ERROR`，`errors` 给到字段；
- 非 JSON 请求 `415`，格式错误的 JSON `400`，未知路径仍是 JSON `404`；
- 消息中手机号、邮箱、身份证号会被 `400` 拦截（编号请放到私有证明里）；
- 双方确认前只有一方确认时，状态保持 `accepted`/`in_handover`，取消返回 `409`。

## 6. 项目结构

```
manage.py
config/                 Django 项目：settings / urls / wsgi / asgi / test_settings
common/                 契约信封、DRF 异常处理、Bearer 认证、严格序列化、分页、时间、隐私过滤
identity/               演示 A 适配器：DemoUser、AuthToken、签发/校验/撤销、/demo/token|logout
posts/                  演示 B 适配器：校区/类别/地点/信息模型、get_post_for_claim、set_handover_state
claims/                 C：Claim/ClaimMessage、状态机、消息、匹配、DRF 视图与路由
tests/                  pytest-django 契约测试（含 MySQL 并发用例）
scripts/                local_mysql.ps1（隔离库）、start_demo.ps1（一键启动）
web/                    /team 联调工作台（team.html/team.js/team.css）
docs/ evidence/ baseline/   历史和交付记录（v1.x 对应已移除的 FastAPI 基线）
```

事务与锁：写操作在视图的 `transaction.atomic()` 内完成；先锁信息行，再按 ID 升序锁该信息的
申请，最后处理从属记录（契约 §7.3）。`accept` 关闭竞争申请并把信息置为 `in_handover`，双方
确认后同事务完成信息与申请；任一步失败全部回滚（有专门用例注入 B 适配器故障验证）。

数据库另有兜底约束：`claims_claim.active_key`（同一用户对同一信息的有效申请唯一）与
`accepted_key`（同一信息最多一条 accepted 申请），用可空唯一键实现 MySQL 的部分唯一语义。

## 7. 测试

```powershell
& '.\scripts\local_mysql.ps1' -Action Start   # 首次或 MySQL 停止后
python -m pytest                              # 133 项：单元 + HTTP 契约 + MySQL 并发
python -m pytest tests/test_concurrency.py    # 只跑行级锁/回滚用例
python manage.py check                        # Django 系统检查
```

- `pytest.ini` 使用 `config.test_settings`（读取 `.env.test`，库 `claim_test`）并加 `--reuse-db`；
  需要重建测试库时执行 `python -m pytest --create-db`。
- 并发用例使用 `transaction=True` 与真实行锁，非 MySQL 环境自动跳过。
- 测试覆盖：信封/认证/内容类型/分页、认领创建与权限、状态机全分支与幂等、消息游标与隐私、
  匹配规则与排序、并发创建/同意/确认、故障回滚、数据库唯一约束。

## 8. 已知限制

1. A 的真实注册、登录、校园身份绑定未接入；`/auth/*`、`/users/me`、绑定接口仍属 A。
2. B 的真实发布、`PATCH /posts`、`/meta/*`、图片上传与受控读取未接入；`cover_image` 恒为
   `null`，`/demo/posts` 仅服务演示页面。
3. 未实现契约中 A/B 的限流、图片校验、`withdraw/restore/resolve/reopen` 等 B 侧状态操作；
   C 通过 `close_pending_claims`、`has_completed_claim` 预留协作函数。
4. 旧 FastAPI `/v1` 接口与其 178 项测试、基准脚本已移除；`docs/`、`evidence/` 中对应记录为
   历史材料。
5. 演示令牌接口不是真实登录，不能用于生产；`DEMO_MODE=false` 时全部 `/demo/*` 返回 404。

## 9. 从 FastAPI 迁移

- 目录：`app/`（FastAPI + SQLAlchemy）→ `config/` + `identity/` + `posts/` + `claims/`。
- 建表：`scripts/init_db.py`（SQLAlchemy `create_all`）→ `manage.py migrate`（Django migrations，
  含演示账号与字典的初始数据迁移）。
- 种子：`scripts/seed_team_demo.py` → `manage.py seed_team_demo`。
- 启动：`uvicorn app.main:app` → `manage.py runserver` / `config.wsgi`。
- 测试：`tests/{unit,integration,performance}`（pytest + httpx + uvicorn）→ `tests/`（pytest-django）。
- 旧库中的 `claims`、`team_claims`、`listing_snapshots` 等表保持原样不再使用；新表使用
  Django 默认的 `claims_*`、`posts_*`、`identity_*` 前缀，因此可以直接在既有隔离库上迁移。

详细映射、事务设计与替换适配器的方法见 [`docs/django-migration-v2.md`](docs/django-migration-v2.md)。

## 10. 历史文档

以下文档与证据对应 v1.0–v1.2 的 FastAPI 基线，保留用于课程交付与追溯，不再描述当前实现：

- [`docs/api-contract.md`](docs/api-contract.md) 旧 `/v1` 接口契约（历史）
- [`docs/architecture-v1.0.md`](docs/architecture-v1.0.md)、[`docs/data-design.md`](docs/data-design.md)
- [`docs/srs-v1.1.md`](docs/srs-v1.1.md)、[`docs/rtm-v1.1.csv`](docs/rtm-v1.1.csv)
- [`evidence/test-run-v1.0.1.md`](evidence/test-run-v1.0.1.md)、`evidence/` 其余记录

## 11. 个人信息与最终裁决（由本人填写）

- 姓名 / 学号：____________
- 学生最终裁决（CR-01 / CR-02 / CR-03）：____________
- 课程反思：____________

> 以上留空，不代填。
