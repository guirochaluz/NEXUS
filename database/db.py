import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from datetime import datetime
from database.models import Base, Sale, UserToken

# Carrega variáveis de ambiente do .env
load_dotenv()
DATABASE_URL = os.getenv("DB_URL")

# Conexão com o banco
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# Inicializa as tabelas (executado no main.py)
def init_db():
    Base.metadata.create_all(bind=engine)

# Consulta o token de um user_id específico
def obter_token_por_user_id(user_id: str) -> str:
    session = SessionLocal()
    try:
        token = session.query(UserToken).filter_by(ml_user_id=str(user_id)).first()
        if token:
            return token.access_token
        return None
    finally:
        session.close()

# Salva uma nova venda no banco
def salvar_nova_venda(order_data: dict):
    session: Session = SessionLocal()
    try:
        order_id = str(order_data["id"])
        ml_user_id = str(order_data["seller"]["id"])

        # Dados do comprador
        buyer = order_data.get("buyer", {})
        buyer_id = str(buyer.get("id"))
        buyer_nickname = buyer.get("nickname")
        buyer_email = buyer.get("email")
        buyer_first_name = buyer.get("first_name")
        buyer_last_name = buyer.get("last_name")

        # Dados do item principal (assume 1 item)
        item = order_data.get("order_items", [{}])[0]
        item_id = item.get("item", {}).get("id")
        item_title = item.get("item", {}).get("title")
        quantity = item.get("quantity")
        unit_price = str(item.get("unit_price"))

        # Dados de envio
        shipping = order_data.get("shipping", {})
        receiver_address = shipping.get("receiver_address", {})
        shipping_id = str(shipping.get("id"))
        shipping_status = shipping.get("status")
        city = receiver_address.get("city", {}).get("name")
        state = receiver_address.get("state", {}).get("name")
        country = receiver_address.get("country", {}).get("name")
        zip_code = receiver_address.get("zip_code")
        street_name = receiver_address.get("street_name")
        street_number = receiver_address.get("street_number")

        # Cria objeto da venda
        venda = Sale(
            order_id=order_id,
            ml_user_id=ml_user_id,
            buyer_id=buyer_id,
            buyer_nickname=buyer_nickname,
            buyer_email=buyer_email,
            buyer_first_name=buyer_first_name,
            buyer_last_name=buyer_last_name,
            total_amount=str(order_data.get("total_amount")),
            status=order_data.get("status"),
            status_detail=order_data.get("status_detail"),
            date_created=datetime.strptime(order_data["date_created"], "%Y-%m-%dT%H:%M:%S.%fZ"),
            item_id=item_id,
            item_title=item_title,
            quantity=quantity,
            unit_price=unit_price,
            shipping_id=shipping_id,
            shipping_status=shipping_status,
            city=city,
            state=state,
            country=country,
            zip_code=zip_code,
            street_name=street_name,
            street_number=street_number
        )

        session.add(venda)
        session.commit()
    except IntegrityError:
        session.rollback()  # Evita erro se venda já estiver salva
    finally:
        session.close()