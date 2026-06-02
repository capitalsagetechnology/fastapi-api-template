from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlmodel import Field, SQLModel, func


class TimestampModel(SQLModel):
    """Abstract model class providing created_at and updated_at timestamps."""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"nullable": False, "server_default": func.now()},
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={
            "nullable": False,
            "server_default": func.now(),
            "onupdate": func.now(),
        },
    )
