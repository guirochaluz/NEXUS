# oauth.py

import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta

from db import SessionLocal
from models import UserToken

# 1) Carregar .env e variáveis obrigatórias
load_dotenv()
CLIENT_ID     = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
BACKEND_URL   = os.getenv("BACKEND_URL")
if not all([CLIENT_ID, CLIENT_SECRET, BACKEND_URL]):
    raise RuntimeError("⚠️ ML_CLIENT_ID, ML_CLIENT_SECRET e BACKEND_URL devem estar definidos no .env")

# 2) Seu endpoint de callback no backend
REDIRECT_URI = f"{BACKEND_URL}/auth/callback"

# 3) URL para trocar code por token
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


def get_auth_url() -> str:
    """
    Gera a URL de autorização do Mercado Livre,
    com redirect_uri apontando ao /auth/callback do backend.
    """
    return (
        "https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
    )


def exchange_code(code: str) -> dict:
    """
    Troca o authorization_code por access_token e refresh_token,
    faz upsert em user_tokens e retorna o payload completo.
    """
    payload = {
        "grant_type":    "authorization_code",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
    }
    resp = requests.post(TOKEN_URL, data=payload)
    data = resp.json()
    if resp.status_code != 200:
        raise Exception(f"Erro ao trocar code por token: {data}")

    # Persiste no banco
    db = SessionLocal()
    try:
        expires_at = datetime.utcnow() + timedelta(seconds=data["expires_in"])
        token: UserToken = (
            db.query(UserToken)
              .filter_by(ml_user_id=data["user_id"])
              .first()
        )
        if token is None:
            token = UserToken(
                ml_user_id    = data["user_id"],
                access_token  = data["access_token"],
                refresh_token = data["refresh_token"],
                expires_at    = expires_at
            )
            db.add(token)
        else:
            token.access_token  = data["access_token"]
            token.refresh_token = data["refresh_token"]
            token.expires_at    = expires_at

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return data


def renovar_access_token(ml_user_id: int) -> str | None:
    """
    Renova o token usando o refresh_token gravado no banco.
    Retorna o novo access_token ou None em caso de falha.
    """
    db = SessionLocal()
    try:
        token = db.query(UserToken).filter_by(ml_user_id=ml_user_id).first()
        if not token:
            print(f"⚠️ Usuário {ml_user_id} não encontrado no banco.")
            return None

        payload = {
            "grant_type":    "refresh_token",
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": token.refresh_token,
        }
        resp = requests.post(TOKEN_URL, data=payload)
        data = resp.json()
        if resp.status_code != 200:
            print(f"⚠️ Erro ao renovar token: {data}")
            return None

        token.access_token  = data["access_token"]
        token.refresh_token = data["refresh_token"]
        token.expires_at    = datetime.utcnow() + timedelta(seconds=data["expires_in"])
        db.commit()
        return token.access_token

    except Exception as e:
        db.rollback()
        print(f"❌ Erro na renovação do token: {e}")
        return None

    finally:
        db.close()
