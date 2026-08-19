import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: Literal["admin", "reviewer"]
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    email: str
    full_name: str
    password: str
    role: Literal["admin", "reviewer"] = "reviewer"
