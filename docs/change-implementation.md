# CR-03 实施记录

变更：FR-10 认领列表分组。状态：**Implemented-Verified**。
范围：仅前端三文件；后端、数据库、接口 schema 均未改。

## 1. 实际改动（web 三文件）

| 文件 | 改动 |
| --- | --- |
| `web/index.html` | ① 认领区改为“我发起的 / 我收到的”两个分组与空态容器，移除混合视图入口；② 头部加入内联 SVG data-URI 图标，消除 `/favicon.ico` 404 |
| `web/styles.css` | 分组标签、计数“—/暂不可用”占位、空态与 390px 版式样式 |
| `web/app.js` | 分组状态与默认组；计数状态机（loading/ready/unavailable）；请求序列与身份纪元校验，丢弃迟到响应；`online` 恢复去重与自动刷新；计数来源优先级（本组 total > 当前列表 total > “—”） |

未新增/删除任何接口，未改 DTO，未改数据库；`GET /v1/claims?role=all` 保留兼容。

## 2. favicon 基线缺陷与修复

- **基线缺陷**：V1.0.1 页面未声明图标，浏览器自动请求 `/favicon.ico` 得到 404，产生一条非预期
  资源控制台错误。15 项浏览器业务检查本身通过，但该轮被如实记为“未完全通过”。
- **修复**：`index.html` 头部加入内联 `data:image/svg+xml` 图标，不新增静态路由、不改后端。
- **复核**：最终干净首屏 `favicon_requests=[]`、控制台错误 0、JavaScript pageerror 0
  （`evidence/ui-cr03-validation.json`）。旧的失败记录未被覆盖。

## 3. RG-09 修复

- 计数失败不再沿用旧值，切组/手刷均显示“—”，状态为 `unavailable`，绝不显示 0。
- 恢复网络后自动重取；5 次 `online` 事件只发出 3 个请求（两组计数 + 当前列表），无重复刷新。
- 来源优先级：本组成功 `total` > 当前列表真实 `total` > “—”。因此“仅计数失败、列表成功”时，
  该组仍可显示真实 23；另一组无来源时为“—”。
- 实测恢复：自动回到 23 / 2，耗时 35 ms。

## 4. 源码 SHA-256

`baseline` 列取自 `evidence/ui/validation-source-hashes.json`（导出时 git head `c62a0b2`，即 V1.0.1 前端），
并由 `baseline/web-v1.0.1/SHA256SUMS.txt` 与三文件实测哈希逐项核对一致。
`CR-03` 列为当前工作区实测哈希。

| 文件 | V1.0.1 基线 SHA-256 | CR-03 最终 SHA-256 |
| --- | --- | --- |
| `web/index.html` | `ad3a8561a3dcb514f49254a2e428fab10b1bb61b1e94cbe0f88c6be0edde13cd` | `13af85bf2f4222a5228c055e14701c0a55206c4d94edfd1e2669f461d7a8e7f9` |
| `web/app.js` | `e07436de863c269025bfe9f69e84e2c906df89d1c442df003f2875e827ca7b00` | `3b4f0527ae393df8b28adac1dc74c426f321402a67bfca95928209637c2deebc` |
| `web/styles.css` | `c2280513faa04c38871141a75a62bd9a316231dc1dab41fc92dd50c8bb669a93` | `02021b19855f28c388cd3e4465e5fac5c8e86166caee239e2fb5db05dc5fd4d0` |

## 5. 可回退步骤（不使用 Git 旧版本）

`web/` **未纳入本仓库版本控制**，因此不存在可 `git checkout` 的 V1.0.1 三文件；回退以内容复原为准。

1. **基线备份**：`baseline/web-v1.0.1/` 保存了 V1.0.1 的 `index.html`、`app.js`、`styles.css`
   与 `SHA256SUMS.txt`；三文件实测哈希与清单逐项一致。
2. **index.html**：本次对它的改动是两处（分组面板结构、内联图标）。实施过程中曾对这两处做
   **反向精确编辑**还原到 V1.0.1，并复核 `SHA-256 = ad3a8561…e13cd`；该复原方式可行，
   但不以“Git 旧版本”为依据。
3. **回退操作**：把 `baseline/web-v1.0.1/` 的三个文件覆盖回 `web/`（或按第 2 步反向编辑）。
4. **校验**：三文件 SHA-256 应分别等于上表 baseline 列，等价于 `SHA256SUMS.txt` 中的值；
   随后强刷页面，确认混合视图恢复、分组计数消失。后端与数据无需变动。
5. 回退不影响已产生的认领数据；`role=all` 兼容性始终存在。

## 6. 未实现与不宣称

- **CR-01 交接预约卡、【Rejected】**：未实现，仅列未来候选。
- **CR-02 驳回后 24 小时冷静期、【Rejected】**：未实现，未验证，不写成已确认需求。
- 本轮未重跑既有 178 项自动化（49 unit + 118 integration + 11 performance），也未重测性能；
  上述结果沿用 V1.0.1 证据。
- 浏览器验证为无头 Edge、真实 HTTP 18082、`claim_dev`，不代表真实校园数据或公网验收。
