# 处理设计 v1.0

只描述两个核心用例的时序与失败分支，字段以 `api-contract.md` 为准。

## 1. UC-01 申请认领 → 核验 → 批准

```mermaid
sequenceDiagram
  autonumber
  actor A as 申请人 alice
  participant R as router /claims
  participant S as claim_service
  participant DB as MySQL

  A->>R: POST /v1/claims (Idempotency-Key)
  R->>DB: BEGIN
  R->>DB: SELECT idempotency_records (user+op+key)
  alt 命中且请求哈希相同
    R-->>A: 200 原响应 + Idempotent-Replay
  else 命中但内容不同
    R-->>A: 409 idempotency_conflict
  end
  R->>S: create(payload)
  S->>DB: SELECT listing_snapshots FOR UPDATE   %% 锁 1
  alt 记录不存在 / 非 found / 自己发布
    S-->>A: 404 / 422 not_claimable
  end
  alt item_approvals 已有行
    S-->>A: 409 already_approved
  end
  S->>DB: SELECT claims WHERE item+applicant+PENDING
  alt 已存在
    S-->>A: 200 已有申请（幂等）
  else
    S->>DB: INSERT claims(status=PENDING) + audit
    S-->>R: 201 ClaimDTO
  end
  R->>DB: INSERT idempotency_records(脱敏响应)
  R->>DB: COMMIT

  actor F as 拾获方 finder
  F->>R: POST /v1/claims/{id}/approve
  R->>DB: BEGIN
  R->>S: approve()
  S->>DB: SELECT listing_snapshots FOR UPDATE   %% 锁 1
  S->>DB: SELECT claims FOR UPDATE              %% 锁 2
  alt 非拾获方 / 非 PENDING
    S-->>F: 403 / 409 invalid_transition
  end
  S->>DB: INSERT item_approvals(item_id PK)
  alt 唯一键冲突（并发批准）
    S-->>F: 409 already_approved（事务回滚）
  end
  S->>DB: UPDATE claims → APPROVED, deadline=now+24h
  S->>DB: UPDATE 其余 PENDING → CLOSED_OTHER
  S->>DB: INSERT handover_codes(nonce, digests, expires)
  S-->>F: 200 ClaimDTO
  R->>DB: COMMIT
```

要点：锁序固定；批准是记录级唯一操作；其余申请被系统关闭而不是驳回；幂等表存的是脱敏响应。

## 2. UC-02 交接确认与冷却/重置

```mermaid
sequenceDiagram
  autonumber
  actor A as 申请人
  actor F as 拾获方
  participant S as handover_service
  participant DB as MySQL

  A->>S: GET /v1/claims/{id}/code
  S->>DB: SELECT handover_codes
  S->>S: code = HMAC(secret, claim|applicant|nonce|exp)
  S-->>A: 本方码（明文仅此一次传输，不入库）
  F->>S: GET /v1/claims/{id}/code
  S-->>F: 本方码（与申请人的码不同）

  Note over A,F: 线下交换的是"对方的码"

  A->>S: POST /handover/confirm {finder_code}
  S->>DB: SELECT listing FOR UPDATE → claims FOR UPDATE → handover_codes FOR UPDATE
  alt 非 APPROVED / 已过交接期限
    S-->>A: 409 / 410
  end
  alt 本方冷却中
    S-->>A: 429 retry_after
  end
  alt 摘要匹配
    S->>DB: confirmed_applicant = true
    alt 双方均已确认
      S->>DB: claims → COMPLETED + audit
      S-->>A: 200 status=COMPLETED
    else
      S-->>A: 200 confirmed_by_me=true
    end
  else 码错误
    S->>DB: attempts_applicant += 1
    alt 达到 5 次
      S->>DB: cooldown_until = now+60s, triggered=true, attempts=0
      S-->>A: 422 invalid_code（剩余 0）→ 下次 429
    else
      S-->>A: 422 invalid_code（剩余次数）
    end
  end
```

重置分支：

1. 仅当**本方**曾触发冷却且冷却已结束，或码已到期；
2. 每申请最多 2 次，且未超过批准后 24 小时；
3. 重置换 nonce、清空双方确认与计数，旧码立即失效，响应提示 `counterparty_must_refetch=true`；
4. 仍有效且未触发冷却时重置 → 409 `reset_not_allowed`。

## 3. 失败与一致性

| 场景 | 处理 |
| --- | --- |
| 客户端重试（弱网） | 同 Idempotency-Key 重放；无 Key 时按业务幂等（重复申请返回已有 PENDING） |
| 并发批准 | `item_approvals` 主键冲突 → 409，事务回滚 |
| 猜码 | 每方独立 5 次 + 60 秒冷却；码长 8 位且绑定申请/角色/nonce/到期 |
| 旧码重放 | 重置即换 nonce，旧码摘要失效 |
| 交接超时 | 条件 UPDATE 收敛为 EXPIRED，再取码 410 |
| 越权读会话/证据 | 每次请求按 `applicant_id` / `finder_id` 判定成员关系 |
