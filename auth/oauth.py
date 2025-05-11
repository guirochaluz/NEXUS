# oauth.py
import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta

from db import SessionLocal
from models import UserToken

# Carregar variáveis de ambiente
dotenv_loaded = load_dotenv()
CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
# REDIRECT_URI deve ser a URL do seu front-end (onde o Streamlit captura ?code=)
REDIRECT_URI = os.getenv("REDIRECT_URI") or os.getenv("FRONTEND_URL")

# Endpoint de token do Mercado Livre
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


def get_auth_url() -> str:
    """
    Gera a URL para redirecionar o usuário ao OAuth do Mercado Livre.
    """
    return (
        f"https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
    )


def exchange_code(code: str) -> None:
    """
    Troca o authorization_code por access_token e refresh_token,
    e salva/atualiza no banco de dados.
    """
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    resp = requests.post(TOKEN_URL, data=payload)
    data = resp.json()
    if resp.status_code != 200:
        raise Exception(f"Erro ao trocar code por token: {data}")

    db = SessionLocal()
    try:
        # Verifica se já existe registro para este usuário
        token = db.query(UserToken).filter_by(ml_user_id=data["user_id"]).first()
        expires_at = datetime.utcnow() + timedelta(seconds=data["expires_in"])
        if token is None:
            token = UserToken(
                ml_user_id=data["user_id"],
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=expires_at
            )
            db.add(token)
        else:
            token.access_token = data["access_token"]
            token.refresh_token = data["refresh_token"]
            token.expires_at = expires_at
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def renovar_access_token(ml_user_id: str) -> str:
    """
    Usa o refresh_token salvo no banco para obter um novo access_token.
    Retorna o novo access_token em caso de sucesso, ou None.
    """
    db = SessionLocal()
    try:
        token = db.query(UserToken).filter_by(ml_user_id=ml_user_id).first()
        if not token:
            print(f"Usuário {ml_user_id} não encontrado no banco.")
            return None

        payload = {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": token.refresh_token,
        }
        resp = requests.post(TOKEN_URL, data=payload)
        data = resp.json()
        if resp.status_code != 200:
            print(f"Erro ao renovar token: {data}")
            return None

        token.access_token = data["access_token"]
        token.refresh_token = data["refresh_token"]
        token.expires_at = datetime.utcnow() + timedelta(seconds=data["expires_in"])
        db.commit()
        return token.access_token
    except Exception as e:
        db.rollback()
        print(f"❌ Erro no processo de renovação do token: {e}")
        return None
    finally:
        db.close()
