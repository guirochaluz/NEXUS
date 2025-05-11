# db.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from models import Base, Sale, UserToken

# Carregar variáveis de ambiente
dotenv_loaded = load_dotenv()
DATABASE_URL = os.getenv("DB_URL")
if not DATABASE_URL:
    raise RuntimeError("Environment variable DB_URL is not set")

# Criar engine e session factory
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """
    Cria as tabelas no banco de dados definidas em models.py.
    """
    Base.metadata.create_all(bind=engine)

# Opcional: chamar init_db() automaticamente ao importar este módulo
init_db()
