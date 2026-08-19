from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_auth import get_current_user, require_role
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.schemas.auth import LoginRequest, Token, UserCreate, UserRead

router = APIRouter()


@router.post("/auth/login", response_model=Token)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_db)) -> Token:
    result = await session.execute(select(User).where(User.email == payload.email))
    user = result.scalars().first()
    if user is None or not user.is_active or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="incorrect email or password")
    return Token(access_token=create_access_token(subject=str(user.id), role=user.role))


@router.get("/auth/me", response_model=UserRead)
async def read_current_user(user: User = Depends(get_current_user)) -> User:
    return user


@router.post(
    "/auth/users",
    response_model=UserRead,
    status_code=201,
    dependencies=[Depends(require_role("admin"))],
)
async def create_user(payload: UserCreate, session: AsyncSession = Depends(get_db)) -> User:
    existing = await session.execute(select(User).where(User.email == payload.email))
    if existing.scalars().first() is not None:
        raise HTTPException(status_code=409, detail=f"a user with email {payload.email!r} already exists")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.get(
    "/auth/users",
    response_model=list[UserRead],
    dependencies=[Depends(require_role("admin"))],
)
async def list_users(session: AsyncSession = Depends(get_db)) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())
