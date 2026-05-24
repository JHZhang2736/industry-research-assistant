"""模型层共享类型与默认值常量。"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import mapped_column

UUIDPK = Annotated[
    UUID,
    mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    ),
]

CreatedAt = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    ),
]

UpdatedAt = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    ),
]
