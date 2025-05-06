from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class UserToken(Base):
    __tablename__ = "user_tokens"
    id = Column(Integer, primary_key=True)
    ml_user_id = Column(String, unique=True)
    access_token = Column(Text)
    refresh_token = Column(Text)
    expires_at = Column(DateTime)

class Sale(Base):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True)
    order_id = Column(String, unique=True)
    ml_user_id = Column(String)

    # Dados do comprador
    buyer_id = Column(String)
    buyer_nickname = Column(String)
    buyer_email = Column(String)
    buyer_first_name = Column(String)
    buyer_last_name = Column(String)

    # Informações do pedido
    total_amount = Column(String)
    status = Column(String)
    status_detail = Column(String)
    date_created = Column(DateTime)

    # Produto principal (assumindo 1 item por venda)
    item_id = Column(String)
    item_title = Column(String)
    quantity = Column(Integer)
    unit_price = Column(String)

    # Dados de envio
    shipping_id = Column(String)
    shipping_status = Column(String)
    city = Column(String)
    state = Column(String)
    country = Column(String)
    zip_code = Column(String)
    street_name = Column(String)
    street_number = Column(String)
