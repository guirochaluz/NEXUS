import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from auth.oauth import get_auth_url, exchange_code, renovar_access_token
from sales import fetch_and_persist_sales

# Carrega variáveis de ambiente
load_dotenv()
FRONTEND_URL = os.getenv("FRONTEND_URL")
if not FRONTEND_URL:
    raise RuntimeError("❌ FRONTEND_URL deve estar definido no .env")

app = FastAPI()

# Configura CORS para permitir apenas o front-end
default_origins = [FRONTEND_URL]
app.add_middleware(
    CORSMiddleware,
    allow_origins=default_origins,
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
    """Redireciona o usuário para a URL de autorização do ML"""
    return RedirectResponse(get_auth_url())

@app.get("/auth/callback")
def auth_callback(code: str = Query(None)):
    """
    Handler de callback OAuth:
     1. Valida código
     2. Troca código por tokens e persiste em user_tokens
     3. Busca histórico de vendas e persiste em sales
     4. Redireciona de volta ao front-end com flag de sucesso
    """
    # 1️⃣ Valida o code
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code não fornecido")

    # 2️⃣ Troca o code pelo token e persiste no banco de tokens
    try:
        token_payload = exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao trocar code: {e}")

    # 3️⃣ Busca todo o histórico de vendas e persiste na tabela `sales`
    try:
        ml_user_id   = token_payload.get("user_id")
        access_token = token_payload.get("access_token")
        fetch_and_persist_sales(ml_user_id, access_token)
    except Exception as e:
        # se falhar aqui, ainda podemos redirecionar, mas logamos o erro
        print(f"⚠️ Erro ao buscar/vender vendas históricas: {e}")

    # 4️⃣ Redireciona de volta ao dashboard autenticado
    return RedirectResponse(f"{FRONTEND_URL}/?nexus_auth=success")

@app.post("/auth/refresh")
def auth_refresh(payload: dict = Body(...)):
    """Renova o token usando o refresh_token e retorna novo access_token"""
    ml_user_id = payload.get("user_id")
    if not ml_user_id:
        raise HTTPException(status_code=400, detail="user_id não fornecido")
    token = renovar_access_token(int(ml_user_id))
    if not token:
        raise HTTPException(status_code=404, detail="Falha na renovação do token")
    return {"access_token": token}
