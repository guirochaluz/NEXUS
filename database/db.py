import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from datetime import datetime
from database.models import Base, Sale, User, UserToken

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
        # ... resto da extração de campos ...
        venda = Sale(
            order_id=order_id,
            ml_user_id=ml_user_id,
            # demais campos...
        )
        session.add(venda)
        session.commit()
    except IntegrityError:
        session.rollback()  # já existe sale com esse ID
    finally:
        session.close()

# Cria um usuário com senha padrão "Giguisa*" (ou ignora se já existir)
def criar_usuario_default_senha(ml_user_id: str, password: str = "Giguisa*"):
    session: Session = SessionLocal()
    try:
        # tenta inserir; se já existir, IntegrityError será lançado
        novo = User(
            ml_user_id=ml_user_id,
            password=password  # aqui você pode criptografar, se tiver utilitário
        )
        session.add(novo)
        session.commit()
    except IntegrityError:
        session.rollback()  # usuário já existe, ignora
    finally:
        session.close()
