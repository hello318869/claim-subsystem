# 处理设计 v1.0.1

描述三个核心用例的时序与失败分支，字段以 `api-contract.md` 为准。
v1.0.1 变更：新增 UC-02 匿名沟通；交接确认改为 UC-03；消息发送与争议状态检查串行化。

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
  R->>DB: INSERT idempotency_records 占位（同事务）
  alt 主键冲突（并发同键）
    R->>DB: SELECT ... FOR UPDATE 读已提交行
    alt 请求指纹一致且已完成
      R-->>A: 200/201 原响应 + Idempotent-Replay
    else 指纹不同
      R-->>A: 409 idempotency_conflict
    end
  end
  R->>S: create(payload)
  S->>DB: SELECT listing_snapshots FOR UPDATE   %% 锁 1
  alt 不存在 / 非 found / status≠published / 自己发布
    S-->>A: 404 / 422 not_claimable
  end
  alt item_approvals 已有行（当前读）
    S-->>A: 409 already_approved
  end
  S->>DB: SELECT claims ... PENDING FOR UPDATE   %% 当前读，避免 RR 旧快照
  alt 已存在
    S-->>A: 200 已有申请（业务幂等）
  else
    S->>DB: INSERT claims(PENDING) + audit
    S-->>R: 201 ClaimDTO
  end
  R->>DB: UPDATE idempotency_records 写入脱敏响应
  R->>DB: COMMIT

  actor F as 拾获方 finder
  F->>R: POST /v1/claims/{id}/approve
  R->>DB: BEGIN
  R->>S: approve()
  S->>DB: SELECT listing_snapshots FOR UPDATE   %% 锁 1
  S->>DB: SELECT claims FOR UPDATE (populate_existing)  %% 锁 2，强制刷新实体
  alt 非拾获方 / 非 PENDING（可能刚被撤销/争议）
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

要点：锁序固定 `listing → claim → code`；加锁读一律 `populate_existing`；批准是记录级唯一操作。

## 2. UC-02 匿名沟通（含争议冻结）

```mermaid
sequenceDiagram
  autonumber
  actor U as 参与方（申请人/拾获方）
  participant S as chat_service
  participant DB as MySQL

  U->>S: GET /claims/{id}/messages?after=&limit=
  S->>DB: 校验成员关系；按 (created_at,id) 键集读取
  S-->>U: items + next_after

  U->>S: POST /claims/{id}/messages {text}
  S->>DB: BEGIN
  S->>DB: SELECT claims FOR UPDATE (populate_existing)
  alt 非本申请成员
    S-->>U: 403
  end
  alt 状态 ∈ {PENDING, APPROVED}
    S->>S: scan_contact_info(text)
    alt 命中手机号/邮箱/证件号
      S-->>U: 422 contact_info_blocked（不落库）
    else 通过
      S->>DB: INSERT messages(sender_role, body)
      S-->>U: 201 MessageDTO
    end
  else DISPUTED / COMPLETED / 其他终态
    S-->>U: 409 invalid_transition（只读）
  end

  actor P as 任一参与方
  P->>S: POST /claims/{id}/dispute
  S->>DB: BEGIN; SELECT listing FOR UPDATE; SELECT claims FOR UPDATE
  S->>DB: UPDATE claims → DISPUTED
  S->>DB: COMMIT
  Note over U,S: 发送方持 claim 行锁，争议方需等锁，因此不会出现“先写消息再冻结”的 TOCTOU
```

争议后消息只读；发送与冻结在同一行锁上串行化。

## 3. UC-03 交接确认与冷却/重置

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
  S-->>A: 本方码（仅经认证传输，不入库/日志）

  Note over A,F: 线下交换的是"对方的码"

  A->>S: POST /handover/confirm {finder_code}
  S->>DB: listing FOR UPDATE → claims FOR UPDATE → codes FOR UPDATE
  alt 非 APPROVED
    S-->>A: 409（COMPLETED 时按幂等返回 200）
  end
  alt 已过 24 小时绝对期限
    S->>DB: claims → EXPIRED（持久化）
    S-->>A: 410 code_expired
  end
  alt 本方冷却中
    S-->>A: 429 retry_after
  end
  alt 摘要匹配
    S->>DB: confirmed_<role> = true
    alt 双方均已确认
      S->>DB: claims → COMPLETED + audit
      S-->>A: 200 status=COMPLETED
    else
      S-->>A: 200 confirmed_by_me=true
    end
  else 码错误
    S->>DB: attempts_<role> += 1
    alt 达到 5 次
      S->>DB: cooldown_until=now+60s, triggered=true, attempts=0
      S-->>A: 422 invalid_code（剩余 0）→ 下次 429
    else
      S-->>A: 422 invalid_code（剩余次数）
    end
  end

  A->>S: POST /handover/reset
  S->>DB: 同一锁序；检查 reset_count<2 与 24h 期限
  alt 期限已过
    S->>DB: claims → EXPIRED（先 flush，再返回 410，事务提交）
    S-->>A: 410 code_expired（状态为 EXPIRED，不是回滚）
  end
  alt 码有效且未触发冷却
    S-->>A: 409 reset_not_allowed
  else 允许
    S->>DB: 换 nonce、清双方确认/计数/冷却、reset_count+1
    S-->>A: 200 counterparty_must_refetch=true
  end
```

## 4. 失败与一致性

| 场景 | 处理 |
| --- | --- |
| 客户端重试（弱网） | 同键在事务内预占：同请求重放原响应，不同内容 409；不再出现 5xx |
| 同人不同键并发创建 | 记录行锁 + `FOR UPDATE` 当前读去重，只留一条 PENDING |
| 并发批准 | `item_approvals` 主键冲突 → 409，事务回滚 |
| 加锁后读到旧值 | 所有锁读 `populate_existing`，撤销/争议不会与批准/确认互相覆盖 |
| 争议后发消息 | claim 行锁串行化，DISPUTED 返回 409 |
| 猜码 | 每方独立 5 次 + 60 秒冷却；码长 8 位且绑定申请/角色/nonce/到期 |
| 旧码重放 | 重置即换 nonce，旧码摘要失效 |
| 交接超时 | 条件 UPDATE 收敛为 EXPIRED；reset/confirm 的 EXPIRED 先写库再返回 410 |
| 同秒消息 | 游标为 `(created_at, id)`，不丢消息；异会话游标 422 |
| 越权读会话/证据 | 每次请求按 `applicant_id` / `finder_id` 判定成员关系 |
