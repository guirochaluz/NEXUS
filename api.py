import os
from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from oauth import get_auth_url, exchange_code, renovar_access_token
from sales import get_full_sales as get_sales

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
    """
    Redireciona o usuário para a página de login do Mercado Livre.
    """
    return RedirectResponse(get_auth_url())

@app.get("/auth/callback")
def auth_callback(code: str = Query(None)):
    """
    Recebe o callback de autorização do Mercado Livre, realiza a troca do code pelo access token
    e persiste as vendas no banco de dados.
    """
    # 1️⃣ valida o code
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code não fornecido")

    # 2️⃣ troca o code pelo token e persiste no banco de tokens
    try:
        token_payload = exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao trocar code: {e}")

    # 3️⃣ busca e persiste todo o histórico de vendas via get_sales
    try:
        ml_user_id    = str(token_payload["user_id"])
        access_token  = token_payload["access_token"]

        # 🔄 Aqui chamamos a versão paginada que criamos
        vendas_coletadas = get_sales(ml_user_id, access_token)

        # 🔍 Log para saber quantas foram coletadas
        print(f"✅ Vendas salvas com sucesso: {vendas_coletadas}")
    except Exception as e:
        # Loga o erro mas não impede o redirect
        print(f"⚠️ Erro ao buscar e persistir vendas históricas: {e}")

    # 4️⃣ redireciona de volta ao dashboard autenticado
    return RedirectResponse(f"{FRONTEND_URL}/?nexus_auth=success")

@app.post("/auth/refresh")
def auth_refresh(payload: dict = Body(...)):
    """
    Recebe uma requisição para renovação do access token.
    """
    ml_user_id = payload.get("user_id")
    if not ml_user_id:
        raise HTTPException(status_code=400, detail="user_id não fornecido")
    token = renovar_access_token(int(ml_user_id))
    if not token:
        raise HTTPException(status_code=404, detail="Falha na renovação do token")
    return {"access_token": token}
