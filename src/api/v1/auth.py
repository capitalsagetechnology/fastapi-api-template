from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.security import OAuth2PasswordRequestForm
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


class InviteRequest(BaseModel):
    email: EmailStr
    roles: List[str]


class InviteResponse(BaseModel):
    id: str
    email: str
    roles: List[str]
    expires_at: str


class UserOut(BaseModel):
    id: str
    email: str
    roles: List[str]
    is_active: bool
    profile_image: Optional[str] = None


@router.post("/login", response_model=Token)
async def login(
    db: AsyncSession = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
):
    """Authenticate user and establish an active session in Redis."""
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
    response_model=InviteResponse,
    dependencies=[Depends(RoleChecker(allowed_roles=["ADMIN"]))],
)
async def invite_user(
    payload: InviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only endpoint to invite a new user with specific access roles."""
    try:
        invitation = await AuthService.create_user_invitation(
            db=db, admin_user=current_user, email=payload.email, roles=payload.roles
        )
        return InviteResponse(
            id=str(invitation.id),
            email=invitation.email,
            roles=invitation.roles,
            expires_at=invitation.expires_at.isoformat(),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create invitation: {str(e)}",
        )


@router.post("/register-invite", response_model=UserOut)
async def register_from_invite(
    token: str = Form(..., description="Unique invitation token"),
    password: str = Form(..., description="Desired user password"),
    profile_image: Optional[UploadFile] = File(
        None, description="Optional profile photo"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Complete account registration by consuming the admin invitation token."""
    profile_image_bytes = None
    profile_image_filename = None
    profile_image_content_type = None

    if profile_image:
        profile_image_bytes = await profile_image.read()
        profile_image_filename = profile_image.filename
        profile_image_content_type = profile_image.content_type

    try:
        user = await AuthService.register_from_invitation(
            db=db,
            token=token,
            password=password,
            profile_image_bytes=profile_image_bytes,
            profile_image_filename=profile_image_filename,
            profile_image_content_type=profile_image_content_type,
        )
        return UserOut(
            id=str(user.id),
            email=user.email,
            roles=user.roles,
            is_active=user.is_active,
            profile_image=user.profile_image,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
