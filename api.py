# api.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
import os

from auth.oauth import get_auth_url, exchange_code, renovar_access_token

# Carregar variáveis de ambiente
dotenv_loaded = load_dotenv()

app = FastAPI()

@app.get("/")
def home():
    """Health check básico"""
    return {"message": "Nexus API rodando perfeitamente!"}

@app.get("/health")
def health_check():
    """Verifica o status da API"""
    return {"status": "ok"}

@app.get("/ml-login")
def mercado_livre_login():
    """
    Redireciona o usuário para a autenticação no Mercado Livre.
    """
    return RedirectResponse(get_auth_url())

@app.post("/auth/callback")
def auth_callback(payload: dict):
    """
    Processa o callback do Mercado Livre após login.
    Espera um JSON: {"code": "authorization_code"}.
    """
    code = payload.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code not provided")
    try:
        exchange_code(code)
        return {"message": "Tokens gerados e salvos com sucesso."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/refresh")
def auth_refresh(payload: dict):
    """
    Renova o access token usando refresh_token no banco.
    Espera um JSON: {"user_id": "<ml_user_id>"}.
    """
    ml_user_id = payload.get("user_id")
    if not ml_user_id:
        raise HTTPException(status_code=400, detail="user_id not provided")
    token = renovar_access_token(ml_user_id)
    if not token:
        raise HTTPException(status_code=404, detail="Token renewal failed")
    return {"access_token": token}
