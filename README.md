# 校园失物招领系统 · 小组联调版

本项目按《共同字段与接口约定-02》v0.3 整合 A 用户管理、B 信息发布与浏览、C 失物认领三个模块。三个模块使用同一个 Django 5.2 + Django REST Framework 后端、MySQL 8 数据库和 Vue 3 + Vite 页面。

| 模块 | 功能 | 来源 |
| --- | --- | --- |
| A 用户管理 | 注册、登录、退出、个人资料、演示校园身份绑定、我的发布 | [Haohan1127/lost-and-found-system `8f2ac2ba`](https://github.com/Haohan1127/lost-and-found-system/tree/8f2ac2ba2ff10a7d01ff189168b93106d9cd7d25) |
| B 信息发布与浏览 | 失物和招领信息、公开列表与筛选、图片上传与访问、发布者状态管理 | [AutoWalkVoid/software-engine `1245922`](https://github.com/AutoWalkVoid/software-engine/tree/12459229dafcd4309c8b4b5c1030e87f57cca7f1) |
| C 失物认领 | 认领申请、审核、双向交接确认、站内消息、规则匹配 | 本仓库的 [Django 后端](backend/claims/) 和 [Vue 页面](frontend/spa/src/modules/claims/) |

启动后打开 [统一页面 `/team`](http://127.0.0.1:8000/team)。[C 接口诊断页 `/workbench`](http://127.0.0.1:8000/workbench) 保留预置身份和样例操作，[`/health`](http://127.0.0.1:8000/health) 显示后端与数据库状态。

## 1. 环境要求

| 项 | 版本 |
| --- | --- |
| Windows | 10/11 + PowerShell 7 |
| Python | 3.11+ |
| Ubuntu WSL + MySQL | Ubuntu WSL 内已有 MySQL 8.0 工具。`scripts/local_mysql.ps1` 使用独立实例，端口 **33307** |
| Node.js + npm | Node.js 20.19+（20.x）或 22.12+，用于安装依赖和构建 Vue 页面 |

## 2. 一键启动

双击项目根目录的 `start-demo.cmd`，脚本依次完成以下操作。

1. 检查 Python 和 npm，缺少 Python 依赖时使用项目虚拟环境安装 `backend/requirements.txt`。
2. 按 `frontend/package-lock.json` 安装缺少或待更新的前端依赖，构建 Vue 页面到 `frontend/dist/`。
3. 启动或复用 `127.0.0.1:33307` 的隔离 MySQL，执行数据库迁移和 `seed_team_demo`。
4. 启动 Django 开发服务器，健康检查通过后打开 <http://127.0.0.1:8000/team>。

只启动服务、不打开浏览器：`.\start-demo.cmd -NoBrowser`。隔离 MySQL 可用
`& '.\scripts\local_mysql.ps1' -Action Stop` 停止；状态用 `-Action Status` 查看。

## 3. 手动安装与启动

```powershell
cd 'D:\软工大作业\claim-subsystem'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build

& '.\scripts\local_mysql.ps1' -Action Start  # 生成 .env / .env.test，创建 claim_dev / claim_test
python backend/manage.py migrate
python backend/manage.py seed_team_demo      # 补齐 C 的演示样例
python backend/manage.py runserver 127.0.0.1:8000
```

- Django 从 `frontend/dist/` 读取页面和构建产物。前端源码变更后重新运行 `npm --prefix frontend run build`。
- `.env` 和 `.env.test` 由隔离 MySQL 脚本生成，分别用于开发和测试，并由 `.gitignore` 排除。

## 4. 演示完整流程

启动后，另开 PowerShell，在项目根目录运行以下命令。若后端依赖安装在虚拟环境，将命令中的 `python` 换成 `.\.venv\Scripts\python.exe`。

```powershell
python backend/manage.py seed_demo_users
```

命令要求 `DEMO_MODE=true`，为共用校区 `main` 创建预置测试身份，只显示本次签发且尚未使用的学号和一次性绑定码。需要为未使用的身份重新签发绑定码时，显式添加 `--reset-codes`。

1. 在 `/team` 注册并登录两个账户，分别在「校园身份认证」使用不同的预置测试身份进行绑定。可用两个浏览器配置分别保留登录状态，也可在同一窗口依次切换账户。
2. 用一个账户发布招领信息，可选上传图片。游客可以浏览公开信息。登录后可发布失物，发布招领和发起认领还需要完成校园身份绑定。
3. 另一个账户打开该招领详情，提交认领和私有核验说明。发布者从「收到的申请」同意认领，双方可在申请详情中沟通。
4. 申请者与发布者分别确认交接。第二次确认完成后，认领和信息同步进入完成状态。可在「我的认领」和「我的发布」查看结果。
5. 也可发布同类别的失物和招领，在本人仍为 `open` 的信息中查看规则匹配和匹配理由。

`/workbench` 的预置演示身份独立于注册账户。`seed_team_demo` 补齐失物和招领样例，覆盖认领竞争与匹配。诊断页通过 `/api/v1/demo/token` 在演示模式下申请随机令牌，服务端保存令牌摘要。

## 5. 接口

所有路径前缀 `/api/v1`，不带结尾 `/`；成功响应 `{"code":"OK","message":"...","data":...}`，
失败响应 `{"code":"...","message":"...","data":null,"errors":{...}}`；时间统一 UTC、以 `Z` 结尾。

| 方法 | 路径 | 权限 | 契约 |
| --- | --- | --- | --- |
| POST | `/auth/register`、`/auth/login` | 公开 | §4 |
| POST | `/auth/logout` | 登录 | §4 |
| GET / PATCH | `/users/me` | 登录，读写本人资料 | §4 |
| GET / POST | `/users/me/campus-binding` | 登录，查询或提交演示绑定 | §4 |
| GET | `/users/me/posts` | 登录，查询本人发布 | §4 |
| GET | `/meta/campuses`、`/meta/categories`、`/meta/locations` | 公开 | §5.1 |
| GET / POST | `/posts` | 公开浏览。发布需登录，发布招领需校园绑定 | §5.1–5.3 |
| GET / PATCH | `/posts/{id}` | 详情按可见性读取，修改仅发布者 | §5.1–5.2 |
| POST | `/posts/{id}/withdraw`、`restore`、`resolve`、`reopen` | 发布者，受信息及认领状态限制 | §5.4 |
| POST | `/post-images` | 登录，上传图片 | §5.1 |
| GET | `/post-images/{id}/content` | 按图片及关联信息的可见性读取 | §5.1 |
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

服务端执行以下校验和状态约束。

- 未知字段、只读字段、非法枚举或越界分页返回 `400 VALIDATION_ERROR`。可在 `errors` 中查看字段错误。
- 普通写接口接收 JSON，图片上传使用 `multipart/form-data`。未知 API 路径返回 JSON `404`。
- 消息中手机号、邮箱、身份证号会被 `400` 拦截，核验信息通过申请中的私有说明提交。
- 双方确认前只有一方确认时，状态保持 `accepted`/`in_handover`，取消返回 `409`。
- 已注销账号的占位摘要带有 `is_deleted: true`。公开信息仍可浏览，已有申请者可查看自己的认领记录，新申请返回 `409 STATE_CONFLICT`。

## 6. 项目结构

```
backend/
  manage.py
  config/               Django 项目（settings / urls / wsgi / asgi / test_settings）
  common/               API 信封、认证、序列化、分页和隐私规则
  users/                A 用户、会话、校园绑定、个人资料与我的发布
  identity/             统一用户摘要和 C 诊断页的预置身份
  posts/                B 信息发布、公开查询、图片和供 C 使用的信息服务
  catalog/              B 校区、分类、地点查询接口，复用 posts 中的字典模型
  claims/               C 认领状态机、交接确认、消息和匹配
  integration/          跨模块身份适配
  workflow/             B 信息状态转换与记录
  requirements.txt      Python 依赖
  pyproject.toml        后端项目配置
  pytest.ini            pytest-django 配置
  tests/                契约、MySQL 并发及 A/B/C 联调测试
frontend/
  spa/src/modules/      统一 Vue 页面的 users、posts、claims 模块
  dist/                 构建生成的页面与资源
  team.html, team.js, team.css    /workbench 诊断页
scripts/                local_mysql.ps1（隔离库）、start_demo.ps1（一键启动）
start-demo.cmd          根目录的一键启动入口
.env.example           根目录环境配置模板
.env, .env.test, .venv  根目录的本地环境文件和虚拟环境
docs/ evidence/ baseline/   历史和交付记录（v1.x 对应已移除的 FastAPI 基线）
```

跨模块状态更新使用 `transaction.atomic()`。C 先锁信息行，再按 ID 升序锁该信息的申请，最后处理从属记录（契约 §7.3）。同意申请时关闭竞争申请并把信息置为 `in_handover`，双方确认后在同一事务内完成信息与申请。B 撤回信息时也会关闭对应的待审核申请。

数据库另有兜底约束：`claims_claim.active_key`（同一用户对同一信息的有效申请唯一）与
`accepted_key`（同一信息最多一条 accepted 申请），用可空唯一键实现 MySQL 的部分唯一语义。

## 7. 测试

```powershell
& '.\scripts\local_mysql.ps1' -Action Start         # 首次或 MySQL 停止后
python -m pytest backend                           # 后端单元、契约、并发与联调测试
python -m pytest backend/tests/test_concurrency.py  # 只跑行级锁/回滚用例
python backend/manage.py check                     # Django 系统检查
npm --prefix frontend test                         # Vue 前端单元测试
```

- `backend/pytest.ini` 使用 `config.test_settings`（读取根目录的 `.env.test`，库 `claim_test`）并加
  `--reuse-db`。需要重建测试库时执行 `python -m pytest backend --create-db`。
- 并发用例使用 `transaction=True` 与真实行锁，非 MySQL 环境自动跳过。
- 联调用例覆盖注册登录、身份绑定、发帖、图片、匹配、认领、交接以及信息撤回和认领状态联动。后端并发用例另外检查行锁、回滚和唯一约束。

## 8. 已知限制

1. 校园认证使用预置测试身份和一次性绑定码，页面标记为「演示认证」。本期未接入学校统一身份认证。
2. 管理后台和争议处理属于本期范围之外。
3. `/api/v1/demo/*` 面向本地诊断，在 `DEMO_MODE=false` 时返回 `404`。统一页面的账户登录走 `/api/v1/auth/login`。
4. 旧 FastAPI `/v1`、其 178 项测试和基准脚本属于历史版本，对应材料见第 10 节。

## 9. 从 FastAPI 迁移

- 目录：`app/`（FastAPI + SQLAlchemy）→ `backend/` 下的 `config/`、`identity/`、`posts/` 和 `claims/`。
- 建表：`scripts/init_db.py`（SQLAlchemy `create_all`）→ `python backend/manage.py migrate`（Django migrations，
  含演示账号与字典的初始数据迁移）。
- 种子：`scripts/seed_team_demo.py` → `python backend/manage.py seed_team_demo`。
- 启动：`uvicorn app.main:app` → `python backend/manage.py runserver` / `backend/config/wsgi.py`。
- 测试：`tests/{unit,integration,performance}`（pytest + httpx + uvicorn）→ `backend/tests/`（pytest-django）。
- Django 使用独立的 `claims_*`、`posts_*`、`identity_*` 和 `users_*` 表。旧 FastAPI 的 `claims`、`team_claims`、`listing_snapshots` 等表保留供历史追溯。

C 首次迁移到 Django 时的文件映射和事务设计记录见 [`docs/django-migration-v2.md`](docs/django-migration-v2.md)。

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
