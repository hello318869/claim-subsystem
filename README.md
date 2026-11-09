# 校园失物招领 · 失物认领子系统（v1.2.0）

## 小组联调版

按《共同字段与接口约定-02》v0.3 提供 `/api/v1` 下的认领、站内消息和双向匹配。浏览器打开
`/team`，接口文档在 `/api/v1/docs`。旧课程演示仍从 `/` 和 `/v1` 访问，使用原有数据。

使用下文的隔离 MySQL 启动步骤后，运行：

```powershell
python scripts/init_db.py --database dev
python scripts/seed_team_demo.py --database dev
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

在 `/team` 选择演示身份。可用小林（`alice`）申请小陈（`finder`）的招领，或用小陈申请访客
（`outsider`）的失物，查看交接提示。发布者审核后，两人分别确认即可完成。演示会话要求
`DEMO_MODE=true`，刷新页面需要重新登录。

### 接入组员的模块

调用 `app.team.api.create_team_app(identity=..., posts=..., session_dependency=...)` 后，
把 A、B 的路由加到返回的应用上，由主应用挂载在 `/api/v1`。适配器签名在
`app/team/contracts.py`。A 解析令牌并返回公开身份摘要，B 提供帖子读取、状态流转和匹配候选。
前端组内登录使用 A 的 `/auth/login`、`/auth/logout`，帖子列表使用 B 的 `/posts` 和 A 的 `/users/me/posts`。

双方使用同一个 SQLAlchemy Session 和数据库事务。B 的 `get_post_for_claim(lock=True)` 要锁定
真实帖子行，`set_handover_state` 在事务内更新。先锁帖子，再锁申请，然后处理消息。B 撤回时调用
`app.team.claims.close_pending_claims`，撤销完成前调用 `has_completed_claim`。内部调用由外层统一提交。
新申请和消息使用 `team_claims`、`team_claim_messages` 两张表，独立演示另使用 `team_demo_posts`。

约定正文 §6.1 和 §7.1 支持对失物及招领发起申请，因此实现保留两个方向。v0.3 验收表 T05
对失物类型返回 400 的旧描述需要和组员核对。

## V1.1 课程演示

Python + FastAPI + SQLAlchemy + PyMySQL + **真实 MySQL** 的后端，加上 `web/` 静态前端。
功能范围只有三块：**认领管理、匿名沟通、可解释规则匹配**，外加双向交接码。
历史基线：后端 **V1.0.1**，前端 **CR-03 分组（FR-10）**。

> 边界：**未对接**其他成员的真实发布/身份服务；**无真实校园数据**（演示数据 `origin=demo`）；
> **非公网部署**；不实现账号注册、发布、争议裁决、管理后台。

## 0. 交付状态

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| 后端基线 V1.0.1 | **178 项自动化通过**：49 unit + 118 integration + 11 performance | `evidence/test-run-v1.0.1.md` |
| 匹配规则 `rules-v1.1` | 40 正例 Top3 召回 39/40；12 负例 0 推荐 | `evidence/matching-evaluation-v1.0.1.json` |
| 性能（本机） | 20 并发 × 3 轮 × 900 请求，P95 认领 512.6 / 会话 217.7 / 匹配 670.8 ms，0 个 5xx | `evidence/performance-benchmark-v1.0.1.json` |
| CR-03 分组 FR-10 | **10 项跨阶段回归通过**（RG-01~RG-08、RG-10 首轮；RG-09 修复后限定复测） | `evidence/ui-cr03-validation-attempt1.json`、`ui-cr03-rg09-final-run.json` |
| 浏览器业务验证 | **15 项通过**；首轮因 `/favicon.ico` 404 记“未完全通过”，修复后干净首屏 0 资源错误 | `evidence/ui-validation.md`、`ui-cr03-validation.json` |

上表记录 V1.1 交付时的验证结果。性能与匹配数据对应当时的本机环境、隔离 MySQL 和样本。

## 1. 环境要求

| 项 | 版本 |
| --- | --- |
| Windows | 10/11 + PowerShell 7 |
| Python | 3.11+ |
| MySQL | 8.0（由 `scripts/local_mysql.ps1` 在 WSL 内起独立实例，端口 **33307**） |
| Node.js + Playwright | 仅浏览器验证需要（`scripts/ui_*.cjs`） |

## 2. 安装

```powershell
cd 'D:\软工大作业\claim-subsystem'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 3. 数据库（隔离实例，绝不碰 3306）

```powershell
# 首次启动：初始化独立 datadir、生成 .env / .env.test、创建 claim_dev / claim_test 与受限账号
& '.\scripts\local_mysql.ps1' -Action Start
& '.\scripts\local_mysql.ps1' -Action Status
```

- 监听仅 `127.0.0.1:33307`，账号 `claim_app` 只有两个库的权限。
- `.env`、`.env.test` 由脚本生成且被 `.gitignore` 排除；**不要打印或提交**。
- 实例在 `/tmp`，WSL 重启后需再次 `Start`。

## 4. 初始化与演示数据

```powershell
python scripts/init_db.py  --database dev      # 建表（只建不删）
python scripts/init_db.py  --database test
python scripts/seed_demo.py --database dev     # 幂等，origin=demo
python scripts/seed_demo.py --database test
```

演示数据：`finder` 发布 5 条拾获记录（F-1001…F-1005），`alice` 有 2 条、`bob` 有 1 条失物记录
（L-2001…L-2003），用于匹配、竞争与交接演示。

## 5. 启动

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 接口文档：<http://127.0.0.1:8000/docs>；健康检查：<http://127.0.0.1:8000/health>
- 页面：<http://127.0.0.1:8000/>（`web/index.html`；`/static/*` 提供同目录资源）

## 6. 三角色演示（PowerShell）

```powershell
$base = 'http://127.0.0.1:8000'
function Token($actor) {
  (Invoke-RestMethod "$base/v1/demo/token" -Method Post -ContentType 'application/json' `
    -Body (@{actor=$actor} | ConvertTo-Json)).token
}
$a = Token alice; $f = Token finder
$ha = @{ Authorization = "Bearer $a" }; $hf = @{ Authorization = "Bearer $f" }

# 1) alice 看自己的失物匹配推荐（不自动认领）
Invoke-RestMethod "$base/v1/matches?item_id=L-2001" -Headers $ha | ConvertTo-Json -Depth 6

# 2) alice 认领 F-1001，提交私有证据
$claim = Invoke-RestMethod "$base/v1/claims" -Method Post -Headers $ha -ContentType 'application/json' `
  -Body (@{ item_id='F-1001'; evidence_text='包里有蓝色水杯和借书卡'; item_number='ASSET-2026-0042' } | ConvertTo-Json)
$id = $claim.id

# 3) finder 核验并批准
Invoke-RestMethod "$base/v1/claims/$id/approve" -Method Post -Headers $hf | Out-Null

# 4) 双方各取本方码，线下交换后互填对方的码
$codeA = (Invoke-RestMethod "$base/v1/claims/$id/code" -Headers $ha).code
$codeF = (Invoke-RestMethod "$base/v1/claims/$id/code" -Headers $hf).code
Invoke-RestMethod "$base/v1/claims/$id/handover/confirm" -Method Post -Headers $ha -ContentType 'application/json' -Body (@{code=$codeF} | ConvertTo-Json)
Invoke-RestMethod "$base/v1/claims/$id/handover/confirm" -Method Post -Headers $hf -ContentType 'application/json' -Body (@{code=$codeA} | ConvertTo-Json)
```

页面上的“我的认领”默认显示**我发起的**，可切到**我收到的**；两组计数失败时显示“—/暂不可用”，
不会伪造成 0。聊天含手机号/邮箱/身份证号会被 **422** 拦截（编号请放 `item_number`）。

## 7. 接口一览

| 方法 | 路径 | 角色 |
| --- | --- | --- |
| POST | `/v1/demo/token` | 仅 `DEMO_MODE=true` |
| GET | `/v1/listings`、`/v1/listings/{id}` | 认证用户 |
| POST | `/v1/claims` | 申请人 |
| GET | `/v1/claims`（`role=applicant\|finder\|all`）、`/v1/claims/{id}` | 双方 |
| POST | `/v1/claims/{id}/withdraw` | 申请人 |
| POST | `/v1/claims/{id}/approve`、`/reject` | 拾获方 |
| POST | `/v1/claims/{id}/dispute` | 双方 |
| GET | `/v1/claims/{id}/dispute-export` | 双方（无身份映射） |
| GET/POST | `/v1/claims/{id}/messages` | 双方 |
| GET | `/v1/claims/{id}/code` | 双方（仅本方码） |
| POST | `/v1/claims/{id}/handover/confirm`、`/reset` | 双方 |
| GET | `/v1/matches` | 申请人（本人失物） |

字段、错误码与状态机见 [`docs/api-contract.md`](docs/api-contract.md)。

## 8. 测试与验证

**后端自动化**（当前状态，见第 0 节证据）：

```powershell
python -m pytest tests/unit -q                          # 纯函数与 DTO
$env:RUN_DB_TESTS='1'; python -m pytest tests/unit -q   # 追加真实 MySQL 契约
python -m pytest tests/integration -q                   # 真实 HTTP + MySQL
python -m pytest tests/performance -q                   # 性能策略
python scripts/benchmark.py                             # 真实基准（自管 18080）
```

**匹配评测**（固定评测集，标签不可改）：

```powershell
python scripts/evaluate_matching.py --manifest tests/fixtures/seed-world.json --base-url http://127.0.0.1:18080
```

**浏览器验证**（需本机 Edge/Playwright；CR-03 脚本自建 18082 后端并自清理）：

```powershell
node scripts/ui_cr03.cjs                              # RG-01 ~ RG-10
$env:CLAIM_UI_CASE='RG-09'; node scripts/ui_cr03.cjs   # 只复测 RG-09

# 15 项业务/权限/版面检查：先用唯一前缀 seed，再用同一前缀运行
python scripts/ui_fixture.py seed --prefix 'UI-QA-<唯一后缀>-'
$env:CLAIM_UI_PREFIX='UI-QA-<同一前缀>-'; node scripts/ui_smoke.cjs
```

## 9. 已知限制

1. 交接码靠“服务端密钥 + nonce”重新派生，**恢复依赖密钥**；密钥轮换未实现。
2. 聊天限流是**单进程内存**，多进程部署会失效。
3. 手机号过滤会误伤以 `1[3-9]` 开头的 11 位物品编号（已接受，改用 `item_number`）。
4. 匹配 0.975 来自合成数据，`regression` 为已见回归集，不代表真实校园准确率。
5. 性能数据限本机、单进程、20 并发；不能外推公网或更高并发。
6. 别名不阻止用户主动自报身份；平台侧仍可按内部 `user_id` 关联。
7. 未实现证据自动删除、争议裁决、推送；CR-01 交接预约卡与 CR-02 驳回冷静期均**未实现**。
8. 重置交接码的 `reason` 为**可选**；驳回与争议的 `reason` 必填且去空白后非空。

## 10. 文档

- [`docs/baseline-v1.0.1.md`](docs/baseline-v1.0.1.md) 后端基线：版本、规则、环境、证据哈希
- [`docs/change-assessment.md`](docs/change-assessment.md) 三项变更的评估与裁决
- [`docs/change-impact.md`](docs/change-impact.md) CR-03 影响分析（按 RTM 列）
- [`docs/change-implementation.md`](docs/change-implementation.md) 三文件改动、SHA 与回退步骤
- [`docs/change-regression-plan.md`](docs/change-regression-plan.md) RG-01~RG-10 执行记录
- [`docs/srs-v1.1.md`](docs/srs-v1.1.md) 需求规格 v1.1（含 FR-10）
- [`docs/srs-v1.0.md`](docs/srs-v1.0.md) 需求规格 v1.0（保留）
- [`docs/rtm-v1.1.csv`](docs/rtm-v1.1.csv) 需求追踪矩阵 v1.1
- [`docs/rtm-v1.0.csv`](docs/rtm-v1.0.csv) 需求追踪矩阵 v1.0（保留）
- [`docs/api-contract.md`](docs/api-contract.md) 接口与 DTO 契约
- [`docs/architecture-v1.0.md`](docs/architecture-v1.0.md) 架构与决策
- [`docs/data-design.md`](docs/data-design.md) 表、索引、约束
- [`docs/process-design.md`](docs/process-design.md) 三个核心时序
- [`docs/defect-fixes-v1.0.1.md`](docs/defect-fixes-v1.0.1.md) 缺陷根因与修复对照

## 11. 个人信息与最终裁决（由本人填写）

- 姓名 / 学号：____________
- 学生最终裁决（CR-01 / CR-02 / CR-03）：____________
- 课程反思：____________

> 以上留空，不代填。
