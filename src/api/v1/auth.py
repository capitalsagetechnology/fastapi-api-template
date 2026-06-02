import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlmodel.ext.asyncio.session import AsyncSession

from src.api.deps import RoleChecker, get_current_user
from src.core.database import get_db
from src.models.user import User
from src.services.auth import AuthService, session_manager

router = APIRouter()


# Schemas
class Token(BaseModel):
    access_token: str
    token_type: str


class LoginRequest(BaseModel):
    username: str
    password: str
    grant_type: Optional[str] = None
    scope: str = ""
    client_id: Optional[str] = None
    client_secret: Optional[str] = None


class InviteRequest(BaseModel):
    email: EmailStr
    roles: List[str]


class InviteResponseNew(BaseModel):
    id: uuid.UUID
    email: str


class ReInviteRequest(BaseModel):
    email: EmailStr


class ValidateTokenRequest(BaseModel):
    user_id: uuid.UUID
    token: str


class SetPasswordRequest(BaseModel):
    user_id: uuid.UUID
    token: str
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    roles: List[str]
    is_active: bool
    profile_image: Optional[str] = None


class OAuth2PasswordRequestFormCustom:
    """Custom request form to bypass strict grant_type validation during logins."""

    def __init__(
        self,
        username: str = Form(...),
        password: str = Form(...),
        grant_type: Optional[str] = Form(default=None),
        scope: str = Form(default=""),
        client_id: Optional[str] = Form(default=None),
        client_secret: Optional[str] = Form(default=None),
    ):
        self.username = username
        self.password = password
        self.grant_type = grant_type
        self.scope = scope
        self.client_id = client_id
        self.client_secret = client_secret


@router.post("/login", response_model=Token)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and establish an active session in Redis."""
    user = await AuthService.authenticate_user(
        db=db, email=payload.username, password=payload.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await AuthService.generate_user_token(user)


@router.post("/token", response_model=Token)
async def login_for_oauth_token(
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestFormCustom = Depends(),
):
    """Authenticate user via OAuth2 Form data for Swagger login compatibility."""
    user = await AuthService.authenticate_user(
        db=db, email=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await AuthService.generate_user_token(user)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(current_user: User = Depends(get_current_user)):
    """Terminate the user's current session and revoke their JWT token in Redis."""
    await session_manager.invalidate_session(
        user_id=current_user.id, jti=current_user._current_jti
    )
    return {"detail": "Successfully logged out."}


@router.post(
    "/invite",
    response_model=InviteResponseNew,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RoleChecker(allowed_roles=["ADMIN"]))],
)
async def invite_user(
    payload: InviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only endpoint to invite a new user and generate verification OTP."""
    try:
        user = await AuthService.create_user_invitation(
            db=db, admin_user=current_user, email=payload.email, roles=payload.roles
        )
        return InviteResponseNew(id=user.id, email=user.email)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create invitation: {str(e)}",
        )


@router.post(
    "/re-invite",
    response_model=InviteResponseNew,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(allowed_roles=["ADMIN"]))],
)
async def re_invite_user(
    payload: ReInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only endpoint to re-invite a user who hasn't verified their password yet."""
    try:
        user = await AuthService.re_invite_user(
            db=db, admin_user=current_user, email=payload.email
        )
        return InviteResponseNew(id=user.id, email=user.email)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to re-invite user: {str(e)}",
        )


@router.post("/validate-token")
async def validate_token(
    payload: ValidateTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Validate if the invitation verification OTP code is active and valid."""
    is_valid = await AuthService.validate_token(
        db=db, user_id=payload.user_id, token=payload.token
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token.",
        )
    return {"detail": "Token is valid"}


@router.post("/set-password")
async def set_password(
    payload: SetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Set the user's password using a valid invitation verification OTP code."""
    try:
        await AuthService.set_password_via_token(
            db=db,
            user_id=payload.user_id,
            token=payload.token,
            password=payload.password,
        )
        return {"detail": "Password set successfully"}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to set password: {str(e)}",
        )
