from datetime import timedelta

import bcrypt
import jwt

from app.core.db import new_id, now
from app.core.errors import AppError


def hash_password(password, rounds):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()


def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())


def issue_token(user_id, token_type, settings, jti=None):
    lifetime = (
        timedelta(minutes=settings.access_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_days)
    )
    issued = now()
    payload = {
        "sub": user_id,
        "type": token_type,
        "jti": jti or new_id(),
        "iat": issued,
        "exp": issued + lifetime,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token, token_type, settings):
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "sub", "jti", "type", "iss", "aud"]},
        )
        if payload["type"] != token_type:
            raise jwt.InvalidTokenError("Wrong token type")
        return payload
    except jwt.InvalidTokenError as exc:
        raise AppError(401, "INVALID_TOKEN", "Token is invalid or expired") from exc
