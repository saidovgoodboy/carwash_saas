import secrets
from datetime import timedelta, datetime, timezone
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .database import engine, get_db
from .models import Base, Tenant, Box, WashSession, Pulse, User, now
from .auth import current_user, super_admin, verify_password, hash_password, create_token

Base.metadata.create_all(engine)
app = FastAPI(title="CarWash SaaS")

class KeyIn(BaseModel):
    device_key: str

class PulseIn(KeyIn):
    event_id: str
    ts: int | None = None
    count: int
    amount: int

class PlateIn(KeyIn):
    plate: str

def get_box(db: Session, key: str) -> Box:
    box = db.scalar(select(Box).where(Box.device_key == key))
    if not box:
        raise HTTPException(401, "Noto'g'ri device_key")
    box.last_seen = now()
    return box

def get_open_session(db: Session, box_id: int, plate: str | None = None) -> WashSession:
    s = db.scalar(select(WashSession).where(
        WashSession.box_id == box_id, WashSession.ended_at.is_(None)))
    if not s:
        s = WashSession(box_id=box_id, started_at=now(),
                        plate=plate or f"UNKNOWN-{secrets.token_hex(3).upper()}")
        db.add(s)
        db.flush()
    return s

@app.post("/api/device/heartbeat")
def heartbeat(data: KeyIn, db: Session = Depends(get_db)):
    box = get_box(db, data.device_key)
    db.commit()
    return {"ok": True, "box": box.name}

@app.post("/api/anpr/plate")
def plate(data: PlateIn, db: Session = Depends(get_db)):
    box = get_box(db, data.device_key)
    s = get_open_session(db, box.id, data.plate)
    if s.plate.startswith("UNKNOWN"):
        s.plate = data.plate
    db.commit()
    return {"session_id": s.id, "plate": s.plate}

@app.post("/api/device/pulse")
def pulse(data: PulseIn, db: Session = Depends(get_db)):
    box = get_box(db, data.device_key)
    if db.scalar(select(Pulse).where(Pulse.event_id == data.event_id)):
        db.commit()
        return {"duplicate": True}
    ev = now()
    if data.ts and abs(data.ts - datetime.now(timezone.utc).timestamp()) < 7 * 86400:
        ev = datetime.fromtimestamp(data.ts, timezone.utc).replace(tzinfo=None)
    s = get_open_session(db, box.id)
    s.pulse_count += data.count
    s.total_amount += data.amount
    db.add(Pulse(session_id=s.id, box_id=box.id, count=data.count, amount=data.amount,
                 event_id=data.event_id, event_time=ev))
    db.commit()
    return {"duplicate": False, "session_id": s.id, "plate": s.plate, "total_amount": s.total_amount}

@app.post("/api/device/exit")
def exit_box(data: KeyIn, db: Session = Depends(get_db)):
    box = get_box(db, data.device_key)
    s = db.scalar(select(WashSession).where(
        WashSession.box_id == box.id, WashSession.ended_at.is_(None)))
    if not s:
        db.commit()
        return {"closed": False}
    s.ended_at = now()
    db.commit()
    return {"closed": True, "session_id": s.id, "plate": s.plate,
            "duration_sec": int((s.ended_at - s.started_at).total_seconds()),
            "total_amount": s.total_amount}

class LoginIn(BaseModel):
    email: str
    password: str

class TenantIn(BaseModel):
    name: str
    owner_email: str
    owner_password: str
    boxes: int = 2
    days: int = 30

def tenant_stats(db: Session, t: Tenant):
    cars, revenue = db.execute(
        select(func.count(WashSession.id), func.coalesce(func.sum(WashSession.total_amount), 0))
        .join(Box, Box.id == WashSession.box_id).where(Box.tenant_id == t.id)).one()
    return {"tenant": t.name, "cars": cars, "revenue": revenue,
            "avg_check": round(revenue / cars) if cars else 0,
            "paid_until": t.paid_until.isoformat()}

@app.post("/api/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == data.email.lower()))
    if not u or not verify_password(data.password, u.password_hash):
        raise HTTPException(401, "Email yoki parol noto'g'ri")
    return {"token": create_token(u), "role": u.role, "tenant_id": u.tenant_id}

@app.get("/api/tenant/stats")
def my_stats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "tenant":
        raise HTTPException(400, "Bu endpoint shoxobcha egalari uchun")
    t = db.get(Tenant, user.tenant_id)
    if t.paid_until < now():
        raise HTTPException(402, "Abonement muddati tugadi. Xizmatni davom ettirish uchun to'lov qiling")
    return tenant_stats(db, t)

@app.get("/api/admin/tenants")
def list_tenants(_: User = Depends(super_admin), db: Session = Depends(get_db)):
    out = []
    for t in db.scalars(select(Tenant)):
        boxes = db.scalars(select(Box).where(Box.tenant_id == t.id)).all()
        online = sum(1 for b in boxes if b.last_seen and (now() - b.last_seen).total_seconds() < 120)
        out.append({"id": t.id, "name": t.name, "paid_until": t.paid_until.isoformat(),
                    "active": t.paid_until >= now(), "boxes": len(boxes), "boxes_online": online})
    return out

@app.post("/api/admin/tenants")
def create_tenant(data: TenantIn, _: User = Depends(super_admin), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == data.owner_email.lower())):
        raise HTTPException(400, "Bu email band")
    t = Tenant(name=data.name, paid_until=now() + timedelta(days=data.days))
    db.add(t)
    db.flush()
    db.add(User(email=data.owner_email.lower(), password_hash=hash_password(data.owner_password),
                role="tenant", tenant_id=t.id))
    keys = []
    for i in range(1, data.boxes + 1):
        key = secrets.token_hex(8)
        db.add(Box(tenant_id=t.id, name=f"Boks {i}", device_key=key))
        keys.append(key)
    db.commit()
    return {"tenant_id": t.id, "device_keys": keys}

@app.get("/api/admin/tenant/{tenant_id}/stats")
def admin_stats(tenant_id: int, _: User = Depends(super_admin), db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Tenant topilmadi")
    return tenant_stats(db, t)

@app.post("/api/admin/tenant/{tenant_id}/extend")
def extend(tenant_id: int, days: int = 30, _: User = Depends(super_admin), db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Tenant topilmadi")
    t.paid_until = max(t.paid_until, now()) + timedelta(days=days)
    db.commit()
    return {"paid_until": t.paid_until.isoformat()}

@app.post("/api/admin/tenant/{tenant_id}/expire")
def expire(tenant_id: int, _: User = Depends(super_admin), db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Tenant topilmadi")
    t.paid_until = now() - timedelta(days=1)
    db.commit()
    return {"paid_until": t.paid_until.isoformat()}

from collections import defaultdict
UZ = timedelta(hours=5)

def resolve_tenant(user: User, tenant_id: int | None, db: Session) -> Tenant:
    if user.role == "tenant":
        t = db.get(Tenant, user.tenant_id)
        if t.paid_until < now():
            raise HTTPException(402, "Abonement muddati tugadi. Xizmatni davom ettirish uchun to'lov qiling")
        return t
    if not tenant_id:
        raise HTTPException(400, "tenant_id kerak")
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Tenant topilmadi")
    return t

def closed_sessions(db: Session, t: Tenant):
    return db.execute(
        select(WashSession, Box.name)
        .join(Box, Box.id == WashSession.box_id)
        .where(Box.tenant_id == t.id, WashSession.ended_at.is_not(None))
        .order_by(WashSession.started_at.desc())).all()

@app.get("/api/analytics/revenue")
def an_revenue(period: str = "day", tenant_id: int | None = None,
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = resolve_tenant(user, tenant_id, db)
    buckets = defaultdict(lambda: {"cars": 0, "revenue": 0})
    for s, _ in closed_sessions(db, t):
        d = s.started_at + UZ
        if period == "month":
            key = d.strftime("%Y-%m")
        elif period == "week":
            iso = d.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        else:
            key = d.strftime("%Y-%m-%d")
        buckets[key]["cars"] += 1
        buckets[key]["revenue"] += s.total_amount
    return [{"period": k, **v, "avg_check": round(v["revenue"] / v["cars"])}
            for k, v in sorted(buckets.items())]

@app.get("/api/analytics/peak-hours")
def an_peak(tenant_id: int | None = None,
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = resolve_tenant(user, tenant_id, db)
    hours = [0] * 24
    for s, _ in closed_sessions(db, t):
        hours[(s.started_at + UZ).hour] += 1
    return [{"hour": h, "cars": c} for h, c in enumerate(hours)]

@app.get("/api/analytics/boxes")
def an_boxes(tenant_id: int | None = None,
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = resolve_tenant(user, tenant_id, db)
    boxes = defaultdict(lambda: {"cars": 0, "revenue": 0, "busy_min": 0.0})
    for s, name in closed_sessions(db, t):
        b = boxes[name]
        b["cars"] += 1
        b["revenue"] += s.total_amount
        b["busy_min"] += round((s.ended_at - s.started_at).total_seconds() / 60, 1)
    return [{"box": n, **v} for n, v in sorted(boxes.items())]

@app.get("/api/analytics/log")
def an_log(limit: int = 50, tenant_id: int | None = None,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = resolve_tenant(user, tenant_id, db)
    return [{"plate": s.plate, "box": name,
             "started_at": (s.started_at + UZ).isoformat(timespec="seconds"),
             "duration_sec": int((s.ended_at - s.started_at).total_seconds()),
             "amount": s.total_amount}
            for s, name in closed_sessions(db, t)[:limit]]
