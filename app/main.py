import secrets
from datetime import timedelta
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .database import engine, get_db
from .models import Base, Tenant, Box, WashSession, Pulse, now

Base.metadata.create_all(engine)
app = FastAPI(title="CarWash SaaS")

class KeyIn(BaseModel):
    device_key: str

class PulseIn(KeyIn):
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
    s = get_open_session(db, box.id)
    s.pulse_count += data.count
    s.total_amount += data.amount
    db.add(Pulse(session_id=s.id, box_id=box.id, count=data.count, amount=data.amount))
    db.commit()
    return {"session_id": s.id, "plate": s.plate, "total_amount": s.total_amount}

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

@app.get("/api/tenant/{tenant_id}/stats")
def stats(tenant_id: int, db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Tenant topilmadi")
    if t.paid_until < now():
        raise HTTPException(402, "Abonement muddati tugadi. Xizmatni davom ettirish uchun to'lov qiling")
    cars, revenue = db.execute(
        select(func.count(WashSession.id), func.coalesce(func.sum(WashSession.total_amount), 0))
        .join(Box, Box.id == WashSession.box_id).where(Box.tenant_id == tenant_id)).one()
    return {"tenant": t.name, "cars": cars, "revenue": revenue,
            "avg_check": round(revenue / cars) if cars else 0,
            "paid_until": t.paid_until.isoformat()}

@app.post("/api/admin/seed")
def seed(db: Session = Depends(get_db)):
    if db.scalar(select(Tenant)):
        raise HTTPException(400, "Demo ma'lumotlar allaqachon bor")
    t = Tenant(name="Demo Shoxobcha", paid_until=now() + timedelta(days=30))
    db.add(t)
    db.flush()
    keys = []
    for i in (1, 2):
        key = secrets.token_hex(8)
        db.add(Box(tenant_id=t.id, name=f"Boks {i}", device_key=key))
        keys.append(key)
    db.commit()
    return {"tenant_id": t.id, "device_keys": keys}

@app.post("/api/admin/tenant/{tenant_id}/extend")
def extend(tenant_id: int, days: int = 30, db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Tenant topilmadi")
    t.paid_until = max(t.paid_until, now()) + timedelta(days=days)
    db.commit()
    return {"paid_until": t.paid_until.isoformat()}

@app.post("/api/admin/tenant/{tenant_id}/expire")
def expire(tenant_id: int, db: Session = Depends(get_db)):
    t = db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(404, "Tenant topilmadi")
    t.paid_until = now() - timedelta(days=1)
    db.commit()
    return {"paid_until": t.paid_until.isoformat()}
