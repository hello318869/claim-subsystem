# 校园失物招领 · 失物认领子系统（后端 V1.0.1）

Python + FastAPI + SQLAlchemy + PyMySQL + **真实 MySQL** 的课程项目后端。只实现三块：
**认领管理、匿名沟通、可解释规则匹配**，外加双向交接码。

> 边界：**未对接**其他成员的真实发布/身份服务；**无真实校园数据**（演示数据 `origin=demo`）；
> **非公网部署**；不实现账号注册、发布、争议裁决、管理后台。
> V1.0.1 已在本机真实 HTTP + 隔离 MySQL 上测过：集成 118 passed、性能 900 请求 0 个 5xx、
> 匹配 40 正例召回 39/40、12 负例 0 推荐。这些数字**不外推**到真实校园准确率或公网性能，
> 详见 [`docs/baseline-v1.0.1.md`](docs/baseline-v1.0.1.md)。

## 1. 环境要求

| 项 | 版本 |
| --- | --- |
| Windows | 10/11 + PowerShell 7 |
| Python | 3.11+ |
| MySQL | 8.0（由 `scripts/local_mysql.ps1` 在 WSL 内起独立实例，端口 **33307**） |
| WSL | Ubuntu（仅用于跑隔离 MySQL，不用于跑应用） |

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

演示数据：`finder` 发布 5 条拾获记录（F-1001…F-1005），`alice` 有 2 条、`bob` 有 1 条失物记录（L-2001…L-2003），用于匹配、竞争与交接演示。

## 5. 启动

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- 接口文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>
- 若 `web/` 由前端协作者放入，`/` 返回 `web/index.html`，`/static/*` 提供静态资源（无需改后端，重启即可）

## 6. 三角色演示（PowerShell）

```powershell
$base = 'http://127.0.0.1:8000'
function Token($actor) {
  (Invoke-RestMethod "$base/v1/demo/token" -Method Post -ContentType 'application/json' `
    -Body (@{actor=$actor} | ConvertTo-Json)).token
}
$a = Token alice; $f = Token finder; $o = Token outsider
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

聊天：`POST /v1/claims/{id}/messages {"text":"..."}`；含手机号/邮箱/身份证号会被 **422** 拦截（编号请放 `item_number`）。

## 7. 接口一览

| 方法 | 路径 | 角色 |
| --- | --- | --- |
| POST | `/v1/demo/token` | 仅 `DEMO_MODE=true` |
| GET | `/v1/listings`、`/v1/listings/{id}` | 认证用户 |
| POST | `/v1/claims` | 申请人 |
| GET | `/v1/claims`、`/v1/claims/{id}` | 双方 |
| POST | `/v1/claims/{id}/withdraw` | 申请人 |
| POST | `/v1/claims/{id}/approve`、`/reject` | 拾获方 |
| POST | `/v1/claims/{id}/dispute` | 双方 |
| GET | `/v1/claims/{id}/dispute-export` | 双方（无身份映射） |
| GET/POST | `/v1/claims/{id}/messages` | 双方 |
| GET | `/v1/claims/{id}/code` | 双方（仅本方码） |
| POST | `/v1/claims/{id}/handover/confirm`、`/reset` | 双方 |
| GET | `/v1/matches` | 申请人（本人失物） |

字段、错误码与状态机见 [`docs/api-contract.md`](docs/api-contract.md)。

## 8. 测试

```powershell
python -m pytest tests/unit -q                          # 纯函数与 DTO 用例
$env:RUN_DB_TESTS='1'; python -m pytest tests/unit -q   # 追加真实 MySQL 契约用例
python -m pytest tests/integration -q                   # 真实 HTTP + MySQL（测试协作者维护）
```

V1.0.1 实测：`tests/unit` **49 passed**（含 16 个 DB 用例）、`tests/integration`
**118 passed / 0 failed / 0 skipped**、`tests/performance` **11 passed**。
DB 用例只使用 `T-F-900x` / `T-F-91xx` 临时记录，跑前跑后自行清理，不动演示数据。

## 9. 已知限制

1. 交接码靠"服务端密钥 + nonce"重新派生，**恢复依赖密钥**；密钥轮换未实现。
2. 聊天限流是**单进程内存**，多进程部署会失效。
3. 手机号过滤会误伤以 `1[3-9]` 开头的 11 位物品编号（已接受，改用 `item_number`）。
4. 匹配为可解释规则，评测集是合成数据且 `regression` 为已见回归集；0.975 不代表真实校园准确率。
5. 性能数据限本机、单进程、20 并发；不能外推公网或更高并发。
6. 别名不阻止用户主动自报身份；平台侧仍可按内部 `user_id` 关联。
7. 未实现证据自动删除、争议裁决、推送。
8. 重置交接码的 `reason` 为**可选**；驳回与争议的 `reason` 必填且去空白后非空。

## 10. 文档

- [`docs/baseline-v1.0.1.md`](docs/baseline-v1.0.1.md) 当前基线：版本、规则、环境、证据哈希
- [`docs/api-contract.md`](docs/api-contract.md) 接口与 DTO 契约（冻结）
- [`docs/srs-v1.0.md`](docs/srs-v1.0.md) 需求基线
- [`docs/architecture-v1.0.md`](docs/architecture-v1.0.md) 架构与决策
- [`docs/data-design.md`](docs/data-design.md) 表、索引、约束
- [`docs/process-design.md`](docs/process-design.md) 三个核心时序
- [`docs/defect-fixes-v1.0.1.md`](docs/defect-fixes-v1.0.1.md) 缺陷根因与修复对照
- [`docs/rtm-v1.0.csv`](docs/rtm-v1.0.csv) 需求追踪矩阵（含证据列）
