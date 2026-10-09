import os, hmac, hashlib, secrets
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .database import get_db
from .models import User

SECRET = os.environ.get("JWT_SECRET", "dev-secret-ozgartiring")
bearer = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${h}"

def verify_password(password: str, stored: str) -> bool:
    salt, h = stored.split("$")
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(check, h)

def create_token(user: User) -> str:
    payload = {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return jwt.encode(payload, SECRET, algorithm="HS256")

def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(401, "Token kerak")
    try:
        data = jwt.decode(cred.credentials, SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Token yaroqsiz yoki muddati tugagan")
    user = db.get(User, int(data["sub"]))
    if not user:
        raise HTTPException(401, "Foydalanuvchi topilmadi")
    return user

def super_admin(user: User = Depends(current_user)) -> User:
    if user.role != "super":
        raise HTTPException(403, "Faqat Super Admin uchun")
    return user
