import os
import requests
from ml.sales import get_sales
from dotenv import load_dotenv
from datetime import datetime, timedelta
from database.db import SessionLocal
from database.models import UserToken

load_dotenv()
CLIENT_ID = os.getenv("ML_CLIENT_ID")
CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

def get_auth_url():
    return (
        f"https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    )

def exchange_code(code):
    print("🔐 Iniciando troca de authorization code por access_token...")

    url = "https://api.mercadolibre.com/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }

    res = requests.post(url, data=payload)
    if res.status_code != 200:
        print(f"❌ Erro ao obter token: {res.text}")
        return False

    data = res.json()
    access_token = data["access_token"]
    refresh_token = data["refresh_token"]
    expires_in = data["expires_in"]
    print("✅ Token recebido com sucesso")

    # Descobre o user_id
    print("🔎 Buscando informações do usuário...")
    user_info = requests.get(
        "https://api.mercadolibre.com/users/me",
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    ml_user_id = str(user_info["id"])
    print(f"👤 ml_user_id identificado: {ml_user_id}")
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    # Salva no banco
    print("💾 Salvando tokens no banco...")
    db = SessionLocal()
    try:
        user = db.query(UserToken).filter_by(ml_user_id=ml_user_id).first()
        if user:
            user.access_token = access_token
            user.refresh_token = refresh_token
            user.expires_at = expires_at
            print("📝 Tokens atualizados para o usuário existente.")
        else:
            db.add(UserToken(
                ml_user_id=ml_user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at
            ))
            print("🆕 Tokens salvos para novo usuário.")
        db.commit()
    except Exception as e:
        print(f"❌ Erro ao salvar token no banco: {e}")
        db.rollback()
    finally:
        db.close()

    # Importa as vendas na primeira autenticação
    print("📦 Iniciando download de vendas...")
    get_sales(ml_user_id, access_token)
    print("✅ Processo completo com sucesso!")

    return True
def renovar_access_token(ml_user_id: str) -> str:
    print(f"🔄 Renovando token para o usuário {ml_user_id}...")

    db = SessionLocal()
    try:
        user = db.query(UserToken).filter_by(ml_user_id=ml_user_id).first()
        if not user:
            print("⚠️ Usuário não encontrado na base de tokens.")
            return None

        payload = {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": user.refresh_token
        }

        res = requests.post("https://api.mercadolivre.com/oauth/token", data=payload)
        if res.status_code != 200:
            print(f"❌ Erro ao renovar token: {res.text}")
            return None

        data = res.json()
        user.access_token = data["access_token"]
        user.refresh_token = data["refresh_token"]
        user.expires_at = datetime.utcnow() + timedelta(seconds=data["expires_in"])

        db.commit()
        print("✅ Token renovado e salvo com sucesso.")
        return user.access_token

    except Exception as e:
        print(f"❌ Erro no processo de renovação do token: {e}")
        db.rollback()
        return None
    finally:
        db.close()
