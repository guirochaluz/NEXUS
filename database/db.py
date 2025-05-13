# database/db.py (corrigido)
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from database.models import Base, Sale, UserToken

# Carrega env
load_dotenv()
DATABASE_URL = os.getenv("DB_URL")
if not DATABASE_URL:
    raise RuntimeError("Environment variable DB_URL is not set")

# Definimos corretamente 'engine'
engine = create_engine(DATABASE_URL)
# SessionLocal agora usa o mesmo 'engine'
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Cria as tabelas no banco de dados."""
    Base.metadata.create_all(bind=engine)

# Inicializa as tabelas ao importar
init_db()
