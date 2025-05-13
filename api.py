# api.py

import os
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from auth.oauth import get_auth_url, exchange_code, renovar_access_token

# Carrega variáveis de ambiente
load_dotenv()
FRONTEND_URL = os.getenv("FRONTEND_URL")
if not FRONTEND_URL:
    raise RuntimeError("❌ FRONTEND_URL deve estar definido no .env")

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "Nexus API rodando perfeitamente!"}

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/ml-login")
def mercado_livre_login():
    return RedirectResponse(get_auth_url())

# POST para Streamlit
@app.post("/auth/callback")
def auth_callback_post(payload: dict = Body(...)):
    code = payload.get("code")
    if not code:
        raise HTTPException(400, "Authorization code not provided")
    data = exchange_code(code)
    return data

# GET para navegador/redirect
@app.get("/auth/callback")
def auth_callback_get(code: str = None):
    if not code:
        raise HTTPException(400, "Authorization code not provided")
    data = exchange_code(code)
    response = RedirectResponse(f"{FRONTEND_URL}?nexus_auth=true")
    response.set_cookie(
        key="nexus_auth",
        value="true",
        httponly=True,
        max_age=3600,
        secure=True,
        samesite="lax",
    )
    return response

@app.post("/auth/refresh")
def auth_refresh(payload: dict = Body(...)):
    ml_user_id = payload.get("user_id")
    if not ml_user_id:
        raise HTTPException(400, "user_id not provided")
    token = renovar_access_token(int(ml_user_id))
    if not token:
        raise HTTPException(404, "Token renewal failed")
    return {"access_token": token}
