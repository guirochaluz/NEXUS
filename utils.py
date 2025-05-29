import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from datetime import datetime
import requests

# Carregar variáveis de ambiente
load_dotenv()
DB_URL = os.getenv("DB_URL")

# Criar engine do banco de dados com parâmetros personalizados
engine = create_engine(
    DB_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30
)

# Data de corte para busca de vendas ou taxas
DATA_INICIO = datetime(2024, 5, 16)

# Função para buscar taxa de comissão no Mercado Livre
def buscar_ml_fee(order_id: str, access_token: str):
    url = f"https://api.mercadolibre.com/orders/{order_id}?access_token={access_token}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.ok:
            full_order = resp.json()
            payments = full_order.get("payments", [])
            if payments:
                fee = payments[0].get("marketplace_fee")
                return (order_id, fee)
    except Exception as e:
        print(f"[erro buscar_ml_fee] {order_id}: {e}")
    return (order_id, None)

