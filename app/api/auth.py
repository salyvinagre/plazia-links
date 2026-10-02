from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dependencies import get_db
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.services.auth_service import (
    authenticate_user,
    create_password_reset_token,
    create_tokens,
    refresh_user_token,
    register_user,
    reset_password_with_token,
)
from app.services.workspace_service import create_workspace

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def api_register(
    data: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        user = await register_user(db, data)
        ws_count = await db.execute(
            select(func.count()).select_from(Workspace).where(Workspace.owner_id == user.id)
        )
        if (ws_count.scalar() or 0) == 0:
            from app.schemas.workspace import WorkspaceCreate

            await create_workspace(
                db, WorkspaceCreate(name=f"{user.email.split('@')[0]}'s Workspace"), user.id
            )
        logger.info("User registered", extra={"user_id": user.id, "email": user.email})
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")
        access, refresh = await create_tokens(user, ip=ip, user_agent=ua)
        response.set_cookie(
            key="zly_token",
            value=access,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            max_age=settings.jwt_expire_minutes * 60,
            path="/",
        )
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post("/login", response_model=TokenResponse)
async def api_login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await authenticate_user(db, data.email, data.password)
    if not user:
        logger.warning("Login failed", extra={"email": data.email})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    logger.info("User logged in", extra={"user_id": user.id, "email": user.email})
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    access, refresh = await create_tokens(user, ip=ip, user_agent=ua)
    token_data = TokenResponse(access_token=access, refresh_token=refresh)
    response.set_cookie(
        key="zly_token",
        value=token_data.access_token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )
    return token_data


@router.post("/refresh", response_model=TokenResponse)
async def api_refresh(
    data: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    result = await refresh_user_token(data.refresh_token, db=db)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    access, refresh = result
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.get("/me", response_model=UserResponse)
async def api_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/forgot-password")
async def api_forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    from app.core.rate_limiter import ZONES, _check_rate_limit

    zone = "_forgot_pw"
    if zone not in ZONES:
        ZONES[zone] = {"max": 3, "window": 300}
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    allowed, _, _ = await _check_rate_limit(f"rl:forgot:{client_ip}:{data.email}", zone)
    if not allowed:
        return {"status": "ok"}
    user = await create_password_reset_token(db, data.email)
    if not user or user.password_reset_expires_at is None:
        return {"status": "ok"}
    email_data = {
        "user_id": user.id,
        "to_email": user.email,
        ("reset_url"): (
            f"{settings.base_url}"
            "/auth/reset-password?token="
            f"{getattr(user, '_plain_reset_token', '')}"
        ),
        "expires_at": user.password_reset_expires_at.strftime("%Y-%m-%d %H:%M UTC"),
    }
    try:
        from app.core.arq_pool import get_arq_pool

        pool = await get_arq_pool()
        await pool.enqueue_job(
            "send_password_reset_email_job",
            user_id=email_data["user_id"],
            to_email=email_data["to_email"],
            reset_url=email_data["reset_url"],
            expires_at=email_data["expires_at"],
        )
    except Exception as exc:
        logger.warning(
            "Failed to enqueue password reset email, skipping",
            extra={"user_id": user.id, "error": str(exc)},
        )
    return {"status": "ok"}


@router.post("/reset-password")
async def api_reset_password(
    data: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    from app.core.rate_limiter import ZONES, _check_rate_limit

    zone = "_reset_pw"
    if zone not in ZONES:
        ZONES[zone] = {"max": 5, "window": 300}
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    allowed, _, _ = await _check_rate_limit(f"rl:reset:{client_ip}", zone)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many reset attempts"
        )
    user = await reset_password_with_token(db, data.token, data.new_password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token"
        )
    logger.info("Password reset successful", extra={"user_id": user.id})
    return {"status": "ok"}
