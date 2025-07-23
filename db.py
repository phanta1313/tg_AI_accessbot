from sqlalchemy import Column, String, Date
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.dialects.postgresql import UUID
import uuid



class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),  
        primary_key=True,
        default=uuid.uuid4
    )
    
    tg_username = Column(String(32), unique=True, index=True)
    sub_expire_date = Column(Date())


