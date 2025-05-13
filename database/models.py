from sqlalchemy import Column, Integer, String, DateTime, Text, Float
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class UserToken(Base):
    __tablename__ = "user_tokens"

    id = Column(Integer, primary_key=True, index=True)
    ml_user_id = Column(Integer, unique=True, index=True, nullable=False)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)

class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)
    ml_user_id = Column(Integer, index=True, nullable=False)
    date_created = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)
    item_id = Column(String, nullable=True)
    item_title = Column(String, nullable=True)
    quantity = Column(Integer, nullable=True)
    unit_price = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)
    
    # Dados de envio
    shipping_id = Column(String, nullable=True)
    shipping_status = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    country = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)
    street_name = Column(String, nullable=True)
    street_number = Column(String, nullable=True)
