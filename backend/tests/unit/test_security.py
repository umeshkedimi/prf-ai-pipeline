import time

import jwt
import pytest

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_hash_password_round_trips_with_verify_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_a_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_hash_password_never_stores_the_plaintext():
    password = "correct horse battery staple"
    assert password not in hash_password(password)


def test_create_access_token_round_trips_with_decode_access_token():
    token = create_access_token(subject="user-id-123", role="reviewer")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-id-123"
    assert payload["role"] == "reviewer"


def test_decode_access_token_rejects_a_tampered_token():
    token = create_access_token(subject="user-id-123", role="reviewer")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tampered)


def test_decode_access_token_rejects_an_expired_token(monkeypatch):
    monkeypatch.setattr(
        "app.core.security.get_settings",
        lambda: type(
            "S",
            (),
            {"jwt_secret_key": "test-secret", "jwt_algorithm": "HS256", "jwt_access_token_expire_minutes": -1},
        )(),
    )
    token = create_access_token(subject="user-id-123", role="reviewer")
    time.sleep(0.01)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)
