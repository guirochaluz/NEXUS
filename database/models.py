from sqlalchemy import Column, Integer, String, DateTime, Text, Float, BigInteger
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class UserToken(Base):
    __tablename__ = "user_tokens"
    id            = Column(BigInteger, primary_key=True, index=True)
    ml_user_id    = Column(BigInteger, unique=True, index=True)   # agora um BIGINT
    access_token  = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    expires_at    = Column(DateTime, nullable=False)


class Sale(Base):
    __tablename__ = "sales"

    id                = Column(BigInteger, primary_key=True, index=True)
    order_id          = Column(BigInteger, unique=True, index=True, nullable=False)  # antes não existia
    ml_user_id        = Column(BigInteger, index=True, nullable=False)
    buyer_id          = Column(BigInteger, nullable=True)
    buyer_nickname    = Column(String, nullable=True)
    buyer_email       = Column(String, nullable=True)
    buyer_first_name  = Column(String, nullable=True)
    buyer_last_name   = Column(String, nullable=True)
    total_amount      = Column(Float,   nullable=True)
    status            = Column(String,  nullable=True)
    status_detail     = Column(String,  nullable=True)
    date_created      = Column(DateTime, nullable=False)
    item_id           = Column(String,  nullable=True)
    item_title        = Column(String,  nullable=True)
    quantity          = Column(Integer, nullable=True)
    unit_price        = Column(Float,   nullable=True)
    shipping_id       = Column(String, nullable=True)
    shipping_status   = Column(String, nullable=True)
    city              = Column(String, nullable=True)
    state             = Column(String, nullable=True)
    country           = Column(String, nullable=True)
    zip_code          = Column(String, nullable=True)
    street_name       = Column(String, nullable=True)
    street_number     = Column(String, nullable=True)
