from sqlalchemy import Column, Integer, String, DateTime, Float, BigInteger, Numeric
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class UserToken(Base):
    __tablename__ = "user_tokens"
    id            = Column(BigInteger, primary_key=True, index=True)
    ml_user_id    = Column(BigInteger, unique=True, index=True)
    access_token  = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    expires_at    = Column(DateTime, nullable=False)

class Sale(Base):
    __tablename__ = "sales"

    id               = Column(BigInteger, primary_key=True, index=True)
    order_id         = Column(BigInteger, unique=True, index=True, nullable=False)
    ml_user_id       = Column(BigInteger, index=True, nullable=False)
    buyer_id         = Column(BigInteger, nullable=True)
    buyer_nickname   = Column(String, nullable=True)
    total_amount     = Column(Float, nullable=True)
    status           = Column(String, nullable=True)
    date_closed      = Column(DateTime, nullable=False)
    item_id          = Column(String, nullable=True)
    item_title       = Column(String, nullable=True)
    quantity         = Column(Integer, nullable=True)
    unit_price       = Column(Float, nullable=True)
    shipping_id      = Column(String, nullable=True)
    seller_sku       = Column(String, nullable=True)

    # 🔽 Campos de SKU (mantidos)
    quantity_sku     = Column(Integer, nullable=True)
    custo_unitario   = Column(Numeric(10, 2), nullable=True)
    level1           = Column(String, nullable=True)
    level2           = Column(String, nullable=True)

    # 🔽 Campos financeiros
    ads              = Column(Numeric(10, 2), nullable=True)
    ml_fee           = Column(Numeric(10, 2), nullable=True)
    payment_id       = Column(BigInteger, nullable=True)

    # 🔽 Campos de envio (shipment)
    shipment_status             = Column(String, nullable=True)
    shipment_substatus          = Column(String, nullable=True)
    shipment_last_updated       = Column(DateTime, nullable=True)
    shipment_first_printed      = Column(DateTime, nullable=True)
    shipment_mode               = Column(String, nullable=True)
    shipment_logistic_type      = Column(String, nullable=True)
    shipment_list_cost          = Column(Float, nullable=True)
    shipment_delivery_type      = Column(String, nullable=True)
    shipment_delivery_limit     = Column(DateTime, nullable=True)
    shipment_delivery_final     = Column(DateTime, nullable=True)
    shipment_receiver_name      = Column(String, nullable=True)
    shipment_buffering_date = Column(DateTime, nullable=True)

