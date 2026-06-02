import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship

from src.models.base import TimestampModel


class UserBase(TimestampModel):
    email: str = Field(unique=True, index=True, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    profile_image: Optional[str] = Field(default=None, nullable=True)


class User(UserBase, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, primary_key=True, index=True, nullable=False
    )
    hashed_password: str = Field(nullable=False)
    roles: List[str] = Field(
        default=[], sa_column=Column(JSON, nullable=False, server_default="[]")
    )

    # Relationships
    sent_invitations: List["Invitation"] = Relationship(
        back_populates="created_by",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class Invitation(TimestampModel, table=True):
    __tablename__ = "invitations"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, primary_key=True, index=True, nullable=False
    )
    email: str = Field(index=True, nullable=False)
    token: str = Field(unique=True, index=True, nullable=False)
    roles: List[str] = Field(
        default=[], sa_column=Column(JSON, nullable=False, server_default="[]")
    )
    expires_at: datetime = Field(nullable=False)
    accepted_at: Optional[datetime] = Field(default=None, nullable=True)

    created_by_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)

    # Relationships
    created_by: User = Relationship(back_populates="sent_invitations")
