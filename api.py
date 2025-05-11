# api.py
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
import os

# Carregar variáveis de ambiente
load_dotenv()
CLIENT_ID = os.getenv("ML_CLIENT_ID")
REDIRECT_URI = os.getenv("FRONTEND_URL") + "/ml-callback"

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Nexus API rodando perfeitamente!"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/ml-login")
def mercado_livre_login():
    """
    Redireciona o usuário para a autenticação no Mercado Livre.
    """
    authorization_url = (
        f"https://auth.mercadolivre.com.br/authorization"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
    )
    return RedirectResponse(url=authorization_url)
