import os
from pathlib import Path
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from database.db import init_db, salvar_nova_venda, criar_usuario_default_senha
from auth.oauth import exchange_code, renovar_access_token

# ---------------------------
# Carrega variáveis de ambiente
# ---------------------------
dotenv_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path)

# ---------------------------
# Configuração de URLs
# ---------------------------
BACKEND_URL  = os.getenv("BACKEND_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL")
SITE_URL     = os.getenv("SITE_URL") or FRONTEND_URL

# ---------------------------
# Credenciais OAuth ML
# ---------------------------
CLIENT_ID = os.getenv("ML_CLIENT_ID")

# ---------------------------
# Validações mínimas
# ---------------------------
if not BACKEND_URL:
    raise RuntimeError("Variável BACKEND_URL não definida no ambiente")
if not FRONTEND_URL:
    raise RuntimeError("Variável FRONTEND_URL não definida no ambiente")
if not CLIENT_ID:
    raise RuntimeError("Variável ML_CLIENT_ID não definida no ambiente")

# ---------------------------
# Inicializa FastAPI e Banco
# ---------------------------
app = FastAPI()
init_db()

# ---------------------------
# Rota Unificada ML OAuth
# ---------------------------
@app.get("/ml-login")
def ml_login(code: str | None = Query(None)):
    """
    Se não receber 'code': inicia OAuth (redireciona para ML).
    Se receber 'code': troca por token, cria usuário e redireciona ao front.
    """
    # inicie o fluxo OAuth
    if not code:
        redirect_uri = quote_plus(f"{BACKEND_URL}/ml-login")
        auth_url = (
            f"https://auth.mercadolibre.com.br/authorization"
            f"?response_type=code"
            f"&client_id={CLIENT_ID}"
            f"&redirect_uri={redirect_uri}"
        )
        return RedirectResponse(auth_url, status_code=302)

    # callback: troca código por token
    ml_user_id = exchange_code(code)
    if not ml_user_id:
        return HTMLResponse("<h1>Erro no OAuth do Mercado Livre</h1>", status_code=400)

    criar_usuario_default_senha(ml_user_id, password="Giguisa*")
    # redireciona para o frontend com flag de sucesso
    return RedirectResponse(f"{SITE_URL}/dashboard?registered={ml_user_id}", status_code=302)

# ---------------------------
# Rotas de Registro Manual
# ---------------------------
@app.get("/register", response_class=HTMLResponse)
def show_register(redirect_url: str = SITE_URL):
    html_content = f"""
    <html>
      <body>
        <h2>Cadastro ContaZoom</h2>
        <form action="/register" method="post">
          <label>Email: <input type="email" name="email" required></label><br/>
          <label>Senha: <input type="password" name="password" required></label><br/>
          <input type="hidden" name="redirect_url" value="{redirect_url}" />
          <button type="submit">Registrar</button>
        </form>
      </body>
    </html>
    """
    return HTMLResponse(html_content)

@app.post("/register")
async def do_register(
    email: str = Form(...),
    password: str = Form(...),
    redirect_url: str = Form(...)
):
    # TODO: implementar lógica de criação de usuário
    return RedirectResponse(url=redirect_url, status_code=302)

# ---------------------------
# Webhook de Pagamentos ML
# ---------------------------
@app.post("/webhook/payments")
async def webhook_payments(request: Request):
    payload = await request.json()
    payment_id = payload.get("resource", "").split("/")[-1]
    ml_user_id = str(payload.get("user_id", ""))

    if not payment_id or not ml_user_id:
        return {"status": "erro", "message": "Dados incompletos no webhook"}

    access_token = renovar_access_token(ml_user_id)
    if not access_token:
        return {"status": "erro", "message": "Falha ao renovar token"}

    # consulta pagamento
    r = requests.get(
        f"https://api.mercadolibre.com/collections/{payment_id}",
        params={"access_token": access_token}
    )
    if r.status_code != 200:
        return {"status": "erro", "details": r.json()}

    ext_ref = r.json().get("external_reference")
    if not ext_ref:
        return {"status": "erro", "message": "external_reference ausente"}

    # consulta pedido completo
    order = requests.get(
        f"https://api.mercadolibre.com/orders/{ext_ref}",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    if order.status_code != 200:
        return {"status": "erro", "details": order.json()}

    try:
        salvar_nova_venda(order.json())
        return {"status": "ok", "message": "Venda salva com sucesso"}
    except Exception as e:
        return {"status": "erro", "message": str(e)}
