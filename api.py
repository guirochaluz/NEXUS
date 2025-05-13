# api.py

import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

from auth.oauth import get_auth_url, exchange_code, renovar_access_token

# Carrega variáveis de ambiente
load_dotenv()
FRONTEND_URL = os.getenv("FRONTEND_URL")
if not FRONTEND_URL:
    raise RuntimeError("❌ FRONTEND_URL deve estar definido no .env")

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    Redireciona o usuário para a página de OAuth do Mercado Livre.
    """
    return RedirectResponse(get_auth_url())


@app.get("/auth/callback")
def auth_callback(code: str = None):
    """
    Processa o callback do Mercado Livre após login.
    Exemplo de chamada:
      GET /auth/callback?code=AUTH_CODE
    """
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code not provided")

    try:
        # 1) Troca code por tokens e salva no banco
        data = exchange_code(code)

        # 2) Redireciona ao front-end e seta cookie de sessão
        redirect_to = f"{FRONTEND_URL}?nexus_auth=true"
        response = RedirectResponse(url=redirect_to)
        # Cookie de exemplo; você pode ajustar nome/valor/tempo conforme necessidade
        response.set_cookie(
            key="nexus_auth",
            value="true",
            httponly=True,
            max_age=3600,
            secure=True,
            samesite="lax"
        )
        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro no callback: {e}")


@app.post("/auth/refresh")
def auth_refresh(payload: dict):
    """
    Renova o access token usando refresh_token no banco.
    Espera um JSON: {"user_id": <ml_user_id>}.
    """
    ml_user_id = payload.get("user_id")
    if not ml_user_id:
        raise HTTPException(status_code=400, detail="user_id not provided")

    token = renovar_access_token(int(ml_user_id))
    if not token:
        raise HTTPException(status_code=404, detail="Token renewal failed")
    return {"access_token": token}
