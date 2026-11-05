# 基线 V1.0.1

冻结日期：2026-11-05。本文件记录**实际交付的代码、规则、环境与真实证据**；数值均来自
`evidence/` 中的原始文件，不重新解释、不外推。

## 1. 代码版本

| 项 | 值 |
| --- | --- |
| Git 提交 | `861e1c4`（父提交 `273a349` = V1.0） |
| 应用入口 | `app.main:app`（工厂 `create_app()`） |
| 运行时 | Python 3.11.9、FastAPI 0.136.3、SQLAlchemy 2.0.49、PyMySQL 1.2.0 |
| 数据库 | MySQL 8.0.46，仅 `127.0.0.1:33307`，库 `claim_dev` / `claim_test` |
| 变更范围 | 仅 `app/`、`docs/`、`tests/unit/`、README；未改 `web/`、`tests/integration`、`tests/performance`、`tests/fixtures` |

## 2. 规则版本

| 项 | 值 |
| --- | --- |
| 规则版本 | `rules-v1.1`（v1.0 失败证据保留：`evidence/matching-evaluation.json`） |
| 权重 | 类别 35、文本 30、地点 20、时间 15 |
| 入选条件 | 总分 ≥ 40 **且** 文本重合词元 ≥ 9 |
| 评测集 | `tests/fixtures/matching-v1.json`，SHA-256 `443e7e59…47bcef99`（前后一致，未改标签） |
| 分区 | development 用于门槛选择；regression 为**已见**合成回归集 |

## 3. 环境与容量

Windows 10.0.26300 / Intel64 Family 6 Model 183 / 32 vCPU / 32 GB（测前可用约 5.9 GB）；
MySQL 8.0.46，`max_connections=30`，buffer pool 64 MiB，REPEATABLE-READ；
后端 SQLAlchemy `pool_size=5 + max_overflow=5`（10/进程）；压测客户端并发 20。

## 4. 真实证据

### 4.1 测试

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| 单元（含真实 MySQL） | `$env:APP_ENV='test'; $env:RUN_DB_TESTS='1'; python -m pytest tests/unit -q` | **49 passed** |
| 集成（真实 HTTP + MySQL） | `python -m pytest tests/integration -q` | **118 passed / 0 failed / 0 skipped / 0 xfailed**（18.51 s） |
| 性能策略 | `python -m pytest tests/performance -q` | **11 passed** |

V1.0 的 3 个空白输入 xfail 已转为严格 422；历史失败仍保存在 `evidence/test-run-v1.0.md`。

### 4.2 匹配（真实 HTTP）

| 分区 | Top-3 召回 | 负例被推荐 |
| --- | --- | --- |
| development | 24/24 = 1.000 | 0/7 = 0.000 |
| regression（已见） | 15/16 = 0.9375 | 0/5 = 0.000 |
| 合计 | 39/40 = **0.975** | 0/12 = **0.000** |

唯一 miss：`P32`（regression，期望 `T-M-F32`，返回空）。门槛 `passed=true`。

### 4.3 性能（真实 HTTP + 真实 MySQL）

实测样本 1023（1002 listings + 1 claim + 20 messages）；20 并发 × 3 轮 × 每端点 100 = 900 请求；
全部 200、0 个 5xx、0 未捕获异常、服务端 tracebacks=0。

| 端点 | P95 | P99 | 逐轮 P95 |
| --- | --- | --- | --- |
| 认领列表 | 512.6 ms | 686.7 ms | 526.9 / 475.8 / 527.2 |
| 会话读取 | 217.7 ms | 240.0 ms | 208.8 / 213.4 / 235.2 |
| 规则匹配 | 670.8 ms | 763.7 ms | 633.1 / 653.7 / 703.8 |

每端点每轮 < 1000 ms；匹配单请求最大 955.2 ms，**余量有限**。

### 4.4 证据哈希（SHA-256）

| 文件 | SHA-256 |
| --- | --- |
| `evidence/test-run-v1.0.1.md` | `98A9D1643257BE69834AFA4F19C557AB356A3C432C8781AD1E52C9617C234217` |
| `evidence/matching-evaluation-v1.0.1.json` | `883AD0883934B2D9AD397C3084E321CB8AE7F2AD57775254F350BA97387AC05D` |
| `evidence/performance-benchmark-v1.0.1.json` | `1997DC60CB7EBC7E16FABD04DA566FF4CAF366C6B77C94B9B5F581E80E6AD19C` |

附带日志（可复核，未计算哈希）：`pytest-unit/integration/performance-v1.0.1.log`、
`test-server-v1.0.1.log`、`performance-server-v1.0.1.log`。

## 5. 接口澄清：重置理由口径

- `POST /v1/claims/{id}/handover/reset` 的 `reason` **可选**（默认空串，去除首尾空白后可为空）：
  用户已经在为交接失败付出成本，不再强制填写理由。
- `reject` 与 `dispute` 的 `reason` **必填**，`strip()` 后必须非空，否则 422。
- 这是 **V1.0.1 正式采用的接口口径**，不表示 V1.0 曾强制 reset reason 非空；也不追溯修改
  V1.0 的历史文档。
- 非空 reset reason 的规范化（去空白、长度上限）已生效；本轮不做进一步的语义校验。

## 6. 已知限制（不得外推）

1. **匹配**：全部为合成数据、规模小、单标注者；development 参与门槛选择，regression 是已见
   回归集。`0.975` 不是真实校园准确率，也不是未见数据的泛化估计。
2. **性能**：仅本机、隔离 MySQL、单进程、20 并发下的 900 次请求；**不能外推公网、真实并发、
   冷缓存或多副本部署**。匹配端点余量有限，新增索引/数据增长需重测。
3. 聊天限流为单进程内存；多进程部署会失效。
4. 交接码依赖服务端密钥重新派生；密钥轮换未实现。
5. 演示身份入口由 `DEMO_MODE` 控制，误开即可自取令牌。
6. 未接真实身份/发布服务；全部演示数据 `origin=demo`。

## 7. 变更控制

V1.0.1 为当前冻结基线。任何新功能、规则调整或交互变更需先出变更提案（CR），说明范围、
验收标准与对 QR-01/QR-04 的影响，再实施；不得直接修改标签或评测集来“达标”。
