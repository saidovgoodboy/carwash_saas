from datetime import datetime, timezone
from sqlalchemy import String, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Base(DeclarativeBase):
    pass

class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    paid_until: Mapped[datetime] = mapped_column(DateTime)

class Box(Base):
    __tablename__ = "boxes"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(50))
    device_key: Mapped[str] = mapped_column(String(64), unique=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class WashSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    box_id: Mapped[int] = mapped_column(ForeignKey("boxes.id"))
    plate: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_amount: Mapped[int] = mapped_column(default=0)
    pulse_count: Mapped[int] = mapped_column(default=0)

class Pulse(Base):
    __tablename__ = "pulses"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    box_id: Mapped[int] = mapped_column(ForeignKey("boxes.id"))
    count: Mapped[int]
    amount: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
