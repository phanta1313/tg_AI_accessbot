from sqlalchemy import Column, String, Date, Integer
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import BigInteger
import uuid



class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    first_name = Column(String())
    user_id = Column(BigInteger(), unique=True, index=True, nullable=False, primary_key=True)
    sub_expire_date = Column(Date())


