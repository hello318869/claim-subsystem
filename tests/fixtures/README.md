# 测试数据与适配接缝（V1.0）

后端已冻结，测试按 `docs/api-contract.md` 和 `app/` 实际结构对接。

## 文件

| 文件 | 用途 |
| --- | --- |
| `matching-v1.json` | 冻结的合成匹配集：40 正例、12 负例、15 干扰招领；dev/reg 固定切分。 |
| `seed_test_world.py` | 生成 120 个独立认领场景、55 条匹配记录，并写入 `seed-world.json`；只清理 `T-IT-`/`T-M-` 前缀。 |
| `seed-world.json` | 实际的 claim_test 行 id 映射（本次运行生成；重跑测试前重新生成）。 |
| `seed-world.example.json` | manifest 形状示意（占位符，不能直接用于测试）。 |
| `claimtest/` | harness：环境守卫、HTTP 客户端、seed 加载、claim_test-only SQL 时间接缝、隐私断言、匹配集校验。 |

## 真实 seed 契约

`seed_test_world.py` 会：

- 校验数据库必须是 `claim_test`（PyMySQL 实际连接与 `SELECT DATABASE()`）；
- 删除旧的 `T-IT-` / `T-M-` 认领、消息、码、审批、审计和 listing；
- 清理 alice/bob/finder/outsider 的幂等记录（仅 claim_test）；
- 写入 120 个场景：每个场景 1 条 finder 的 found、alice/bob 各 1 条 lost；
- 写入匹配集的 40 条目标 found、15 条干扰 found、52 条 lost 查询；
- 写出 `seed-world.json`，其中 `claimants.*.item_id` 指向 found，`lost_item_id` 用于匹配；
- 不动 demo 数据，不动 `claim_dev`。

每个改变状态的测试独占一个场景。完整运行后重新执行：

```powershell
python tests/fixtures/seed_test_world.py
```

## 时间接缝

`claimtest/dbtools.py` 只执行固定、参数化的 `UPDATE`，连接先校验 `claim_test`：

- `expire_code(claim_id)`：把 `handover_codes.expires_at` 推到过去；
- `expire_handover_deadline(claim_id)`：把 24 小时绝对期限推到过去；
- `end_cooldown(claim_id, role)`：把 60 秒冷却结束时间推到过去。

用于 410、reset、24 小时期限和冷却恢复测试，不 sleep 60 秒。

## 安全边界

- 只连接 `.env.test` 的 `claim_test`；拒绝 `claim_dev` 和其他库名。
- 不执行全局 truncate；seed 与 benchmark 都只删除自己的前缀/origin。
- 时间接缝不暴露任意 SQL。
