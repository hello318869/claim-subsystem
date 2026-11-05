"""Scoped UI-QA fixtures in claim_dev only; never prints credentials."""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['APP_ENV'] = 'dev'
os.environ.pop('DATABASE_URL', None)

from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from app.config import get_settings
from app.db import get_engine, session_scope
from app.models import Base, ListingSnapshot, Claim, ItemApproval, Message, HandoverCode, IdempotencyRecord, AuditEvent
from app.clock import utcnow, to_db

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['seed', 'seed-cr03', 'inspect', 'expire-code', 'expired-token', 'cleanup'])
parser.add_argument('--prefix', required=True)
parser.add_argument('--claim-id')
args = parser.parse_args()
if not re.fullmatch(r'UI-QA-[A-Za-z0-9-]{1,36}-', args.prefix) or len(args.prefix) > 42:
    raise SystemExit('Invalid task prefix')
settings = get_settings()
if make_url(settings.database_url).database != 'claim_dev':
    raise SystemExit('Refusing non-claim_dev database')
engine = get_engine()
with engine.connect() as conn:
    row = conn.execute(text('SELECT DATABASE(), @@port')).one()
    if row[0] != 'claim_dev' or int(row[1]) != 33307:
        raise SystemExit('Refusing unexpected database instance')

if args.action == 'expired-token':
    from app.security import issue_token
    import time
    token, _ = issue_token('alice', settings.auth_secret, ttl_minutes=1, now_epoch=int(time.time()) - 7200)
    print(token)
    raise SystemExit(0)

if args.action in ['seed', 'seed-cr03']:
    Base.metadata.create_all(engine)
    now = utcnow()
    rows = [
        ('F-HANDOVER', 'found', 'UI-QA 深蓝帆布包', 'bag', '实验图书馆', '深蓝帆布包，内袋有银色星形钥匙扣', 'finder'),
        ('L-ALICE', 'lost', 'UI-QA 深蓝帆布包', 'bag', '实验图书馆', '深蓝帆布包，内袋有银色星形钥匙扣', 'alice'),
        ('L-BOB', 'lost', 'UI-QA 深蓝帆布包', 'bag', '实验图书馆', '深蓝帆布包，内袋有银色星形钥匙扣', 'bob'),
        ('F-DISPUTE', 'found', 'UI-QA 蓝色电子阅读器', 'electronics', '实验教学楼', '蓝色电子阅读器，背面有月亮贴纸', 'finder'),
        ('L-DISPUTE', 'lost', 'UI-QA 蓝色电子阅读器', 'electronics', '实验教学楼', '蓝色电子阅读器，背面有月亮贴纸', 'alice'),
        ('F-EXPIRY', 'found', 'UI-QA 紫色保温杯', 'cup', '实验体育馆', '紫色保温杯，杯底有梅花图案', 'finder'),
        ('L-EXPIRY', 'lost', 'UI-QA 紫色保温杯', 'cup', '实验体育馆', '紫色保温杯，杯底有梅花图案', 'alice'),
    ]
    if args.action == 'seed-cr03':
        rows = [
            (f'F-PAGE-{i:02}', 'found', f'UI-QA 分页样本 {i:02}', 'bag', 'UI-QA实验服务台',
             f'仅用于前端分组和分页验证的合成物品 {i:02}', 'finder') for i in range(1, 24)
        ] + [
            ('F-OWN-01', 'found', 'UI-QA Alice收到的样本一', 'cup', 'UI-QA实验服务台', '只用于CR03角色分组', 'alice'),
            ('F-OWN-02', 'found', 'UI-QA Alice收到的样本二', 'cup', 'UI-QA实验服务台', '只用于CR03角色分组', 'alice'),
            ('F-BOB-EXTRA', 'found', 'UI-QA Bob申请样本', 'card', 'UI-QA实验服务台', '只用于CR03身份切换验证', 'finder'),
        ]
    with session_scope() as session:
        for suffix, kind, title, category, location, description, actor in rows:
            item_id = args.prefix + suffix
            if session.get(ListingSnapshot, item_id):
                raise SystemExit('Prefix already exists; choose a fresh run prefix')
            session.add(ListingSnapshot(item_id=item_id,kind=kind,title=title,category=category,
                occurred_at=to_db(now - timedelta(minutes=10)),location=location,description=description,
                status='published',publisher_user_id=actor,origin='ui-qa',synced_at=to_db(now)))
    print(json.dumps({'database':'claim_dev','port':33307,'created_listings':len(rows),'prefix':args.prefix}))
elif args.action in ['inspect', 'expire-code']:
    with session_scope() as session:
        claim = session.get(Claim, args.claim_id)
        if not claim or not claim.item_id.startswith(args.prefix):
            raise SystemExit('Claim is outside this UI-QA fixture')
        if args.action == 'expire-code':
            row = session.get(HandoverCode, claim.id)
            if not row:
                raise SystemExit('No handover row')
            row.expires_at = to_db(utcnow() - timedelta(seconds=10))
            print(json.dumps({'claim_id':claim.id,'code_expiry_forced_into_past':True,'scope':'own UI-QA fixture only'}))
        else:
            messages = session.execute(select(Message).where(Message.claim_id == claim.id)).scalars().all()
            print(json.dumps({'claim_id':claim.id,'status':claim.status,'message_count':len(messages),
                'blocked_phone_present':any('13800138000' in m.body for m in messages),
                'identity_fields_in_message_model':False}))
elif args.action == 'cleanup':
    counts = {}
    with session_scope() as session:
        claims = session.execute(select(Claim).where(Claim.item_id.startswith(args.prefix))).scalars().all()
        claim_ids = [c.id for c in claims]
        if claim_ids:
            own_message_ids = list(session.execute(select(Message.id).where(Message.claim_id.in_(claim_ids))).scalars())
            counts['message_idempotency_records'] = 0
            for message_id in own_message_ids:
                counts['message_idempotency_records'] += session.execute(delete(IdempotencyRecord).where(
                    IdempotencyRecord.response_body.contains(message_id))).rowcount
            for model in [Message, HandoverCode]:
                counts[model.__tablename__] = session.execute(delete(model).where(model.claim_id.in_(claim_ids))).rowcount
            counts['idempotency_records'] = 0
            for claim_id in claim_ids:
                counts['idempotency_records'] += session.execute(delete(IdempotencyRecord).where(
                    IdempotencyRecord.response_body.contains(claim_id))).rowcount
            counts['audit_events'] = session.execute(delete(AuditEvent).where(AuditEvent.claim_id.in_(claim_ids))).rowcount
        counts['item_approvals'] = session.execute(delete(ItemApproval).where(ItemApproval.item_id.startswith(args.prefix))).rowcount
        counts['claims'] = session.execute(delete(Claim).where(Claim.item_id.startswith(args.prefix))).rowcount
        counts['prefixed_idempotency_keys'] = session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.idem_key.contains(args.prefix))).rowcount
        counts['remaining_prefixed_audit'] = session.execute(delete(AuditEvent).where(AuditEvent.item_id.startswith(args.prefix))).rowcount
        counts['listing_snapshots'] = session.execute(delete(ListingSnapshot).where(ListingSnapshot.item_id.startswith(args.prefix))).rowcount
    print(json.dumps({'database':'claim_dev','prefix':args.prefix,'deleted_only_own_fixture':counts}))
