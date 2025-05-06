from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class UserToken(Base):
    __tablename__ = "user_tokens"
    id = Column(Integer, primary_key=True)
    ml_user_id = Column(String, unique=True, index=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)

class Sale(Base):
    __tablename__ = "sales"
    id = Column(Integer, primary_key=True)
    order_id = Column(String, unique=True, index=True)
    ml_user_id = Column(String, index=True)

    # Dados do comprador
    buyer_id = Column(String, nullable=True)
    buyer_nickname = Column(String, nullable=True)
    buyer_email = Column(String, nullable=True)
    buyer_first_name = Column(String, nullable=True)
    buyer_last_name = Column(String, nullable=True)

    # Informações do pedido
    total_amount = Column(String, nullable=True)
    status = Column(String, nullable=True)
    status_detail = Column(String, nullable=True)
    date_created = Column(DateTime, nullable=True)

    # Produto principal (assumindo 1 item por venda)
    item_id = Column(String, nullable=True)
    item_title = Column(String, nullable=True)
    quantity = Column(Integer, nullable=True)
    unit_price = Column(String, nullable=True)

    # Dados de envio
    shipping_id = Column(String, nullable=True)
    shipping_status = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    country = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)
    street_name = Column(String, nullable=True)
    street_number = Column(String, nullable=True)