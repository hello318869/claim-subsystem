# 变更回归记录 v1.1（CR-03 认领列表分组）

状态：**已完成**。RG-01~RG-08、RG-10 首轮通过；RG-09 首轮失败原样保留，修复后限定复测通过。
基线：后端 V1.0.1（`c62a0b2`）；前端三文件见 [change-implementation.md](change-implementation.md)。
本轮**不重跑**既有 178 项自动化（49 unit + 118 integration + 11 performance），也不重测性能。

## 1. 范围

| 纳入 | 理由 |
| --- | --- |
| FR-10 分组与计数 | 本次唯一新增行为 |
| FR-01 列表与分页 | 列表读取由“混合”改为“分组”，确认分页不串 |
| QR-02 身份切换与越权 | 分组不得让上一身份或他人数据出现 |

**不纳入**：后端状态机、唯一获批、双向码、幂等、匹配规则 `rules-v1.1`、性能全套压测。

## 2. 环境与数据

独立无头 Edge 156.0.4314.58；后端真实 HTTP 端口 **18082**；真实 MySQL 33307 的 **claim_dev**；
未触碰 claim_test 与性能端口 18080。每轮以唯一 `UI-QA-…` 前缀新建 26 条 listing，26 份申请
全部经真实 `POST /v1/claims` 创建，未手工插入/修改申请来凑计数；结束只清理自身前缀的记录、
申请、幂等与审计。脚本：`scripts/ui_cr03.cjs`（`CLAIM_UI_CASE=RG-09` 可只跑该项）、
`scripts/ui_fixture.py`。

## 3. 用例与结果

| 编号 | 场景 | 阶段 | 结果 | 证据 / 观察 |
| --- | --- | --- | --- | --- |
| RG-01 | 默认分组 | 首轮 | 通过 | `ui-cr03-validation-attempt1.json`；active_group=applicant，首屏 id 与接口一致 |
| RG-02 | 两组计数准确 | 首轮 | 通过 | 界面 23 / 2，接口 23 / 2，逐项相等 |
| RG-03 | 快速切组与迟到响应隔离 | 首轮 | 通过 | 3 次往返；迟到的 applicant 响应未覆盖 finder |
| RG-04 | 分页与切组重置 | 首轮 | 通过 | 第 2 页精确；切组回到第 1 页 |
| RG-05 | 空组说明 | 首轮 | 通过 | 接口 total=0 时显示空态；仅在成功取得 total 后才显示 0 |
| RG-06 | 身份变化清空 | 首轮 | 通过 | alice→bob→outsider；切换瞬间计数为“—”，私有内容隐藏 |
| RG-07 | 第三方无权限 | 首轮 | 通过 | 详情 403、消息 403；outsider 列表 total=0 |
| RG-08 | 无混合入口且 all 兼容 | 首轮 | 通过 | 界面仅 applicant/finder；`role=all` 仍 200 且只含相关 id |
| RG-09 | 计数失败占位与恢复 | 首轮 | **失败（保留）** | `ui-cr03-validation-attempt2-rg09-before-fix.json`：切组后仍显示旧 23/2，未标“不可用” |
| RG-09 | 同上（修复后限定复测） | 复测 | 通过 | `ui-cr03-rg09-final-run.json`：切组/手刷均为“—”；恢复后自动回 23/2 |
| RG-10 | 两组不重叠且并集等于 all | 首轮 | 通过 | applicant 23 + finder 2，交集 0，并集 25 = all 25 |

补充：首轮 9 项在 390px 视口无横向溢出。

## 4. RG-09 失败与修复记录

**失败现象（原样保留）**：阻断 `/v1/claims` 后切组，列表请求失败，但界面继续把上一次的 23/2
当作 ready 显示，没有标注“旧缓存”或“暂不可用”。同时误以为首次等待属性是
`data-count-state=error`，实际产品呈现为 `unavailable`——测试等待属性随之修正，但**产品侧
确实存在“失败后仍显示旧计数”的缺陷**，因此该失败不是纯测试问题。

**修复要点**：
1. 计数状态机 `loading / ready / unavailable`，失败一律 `unavailable`，界面显示“—”，绝不显示 0。
2. 恢复网络（`online` 事件）后自动重取，并对并发事件去重：5 次 online 只发出 3 个请求
   （两组计数 + 当前列表），无重复刷新。
3. 计数来源优先级：本组成功 `total` > 当前列表请求返回的真实 `total` > “—”。
   仅计数失败时，当前列表的真实 total（23）仍可作为该组有效来源；另一组无来源则显示“—”。
4. 成功恢复后回到真实 23 / 2（实测 35 ms 内完成）。

**仍保留的边界**：RG-09 首轮失败记录未删除、未覆盖；`evidence/ui/ui-validation.json` 中原有的
favicon 失败历史同样保留。

## 5. 证据与源码

- 首轮：`evidence/ui-cr03-validation-attempt1.json`
- RG-09 修复前：`evidence/ui-cr03-validation-attempt2-rg09-before-fix.json`、`ui-cr03-validation-before-rg09-fix.md`
- RG-09 修复后：`evidence/ui-cr03-rg09-final-run.json`
- 最终静态资源 / 干净首屏：`evidence/ui-cr03-validation.json`（favicon 请求 0、控制台错误 0、pageerror 0）
- 汇总：`evidence/ui-cr03-validation.md`
- 三文件 SHA-256 与回退：见 [change-implementation.md](change-implementation.md)；
  V1.0.1 前端备份在 `baseline/web-v1.0.1/`（含 `SHA256SUMS.txt`，哈希已核对一致）

## 6. 不宣称

- 不宣称本轮重跑了既有 178 项自动化或性能基准。
- 不宣称真实校园数据、真实身份服务或公网环境已验证。
- 不把 RG-09 首轮失败改写为通过。
