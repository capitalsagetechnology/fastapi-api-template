import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field

from src.core.security import uuid7
from src.models.base import TimestampModel


class UserBase(TimestampModel):
    email: str = Field(unique=True, index=True, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    is_verified: bool = Field(default=False, nullable=False)
    profile_image: Optional[str] = Field(default=None, nullable=True)


class User(UserBase, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(
        default_factory=uuid7, primary_key=True, index=True, nullable=False
    )
    hashed_password: Optional[str] = Field(default=None, nullable=True)
    roles: List[str] = Field(
        default=[], sa_column=Column(JSON, nullable=False, server_default="[]")
    )
    last_login: Optional[datetime] = Field(default=None, nullable=True)


class Token(TimestampModel, table=True):
    __tablename__ = "invite_tokens"

    id: uuid.UUID = Field(
        default_factory=uuid7, primary_key=True, index=True, nullable=False
    )
    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)
    token: str = Field(unique=True, index=True, nullable=False)
    expires_at: datetime = Field(nullable=False)
