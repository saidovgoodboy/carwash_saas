import sys
from app.database import SessionLocal, engine
from app.models import Base, User
from app.auth import hash_password

Base.metadata.create_all(engine)
cmd, email, password = sys.argv[1:4]
db = SessionLocal()
if cmd == "superadmin":
    u = User(email=email.lower(), password_hash=hash_password(password), role="super")
elif cmd == "tenantadmin":
    u = User(email=email.lower(), password_hash=hash_password(password),
             role="tenant", tenant_id=int(sys.argv[4]))
else:
    sys.exit("Buyruq: superadmin yoki tenantadmin")
db.add(u)
db.commit()
print("Yaratildi:", u.email, u.role)
