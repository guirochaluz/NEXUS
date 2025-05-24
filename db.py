# database/db.py (otimizado)
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from dotenv import load_dotenv
from database.models import Base

# Carrega variáveis de ambiente
load_dotenv()
DATABASE_URL = os.getenv("DB_URL")
if not DATABASE_URL:
    raise RuntimeError("❌ A variável de ambiente DB_URL não está definida.")

# Criação do engine com otimização de pool
engine = create_engine(
    DATABASE_URL,
    pool_size=20,            # Número máximo de conexões abertas
    max_overflow=0,          # Número de conexões extras permitidas
    pool_pre_ping=True,      # Verifica se a conexão está ativa antes de usá-la
    pool_timeout=30          # Tempo máximo de espera por uma conexão (segundos)
)

# SessionLocal agora é uma sessão "scoped" para melhor gerenciamento em multithreading
SessionLocal = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
)

def init_db():
    """Cria as tabelas no banco de dados."""
    Base.metadata.create_all(bind=engine)

# Inicializa as tabelas ao importar
init_db()
