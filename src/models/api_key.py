import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship

from src.models.base import TimestampModel
from src.models.user import User


class APIKey(TimestampModel, table=True):
    __tablename__ = "api_keys"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4, primary_key=True, index=True, nullable=False
    )
    name: str = Field(nullable=False)
    prefix: str = Field(nullable=False, index=True)
    hashed_key: str = Field(nullable=False, index=True)
    scopes: List[str] = Field(
        default=[], sa_column=Column(JSON, nullable=False, server_default="[]")
    )
    is_active: bool = Field(default=True, nullable=False)
    expires_at: Optional[datetime] = Field(default=None, nullable=True)

    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)

    # Relationships
    user: User = Relationship()
