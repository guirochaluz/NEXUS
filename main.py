from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from database.db import init_db, salvar_nova_venda
from auth.oauth import get_auth_url, exchange_code, renovar_access_token
import requests
import os

app = FastAPI()
init_db()

# ----------------- Home / ML Login -----------------
@app.get("/", response_class=HTMLResponse)
def home():
    url = get_auth_url()
    return HTMLResponse(f'<a href="{url}">Login com Mercado Livre</a>')

# ----------------- OAuth Callback -----------------
@app.get("/callback")
def callback(code: str):
    success = exchange_code(code)
    return {"status": "ok" if success else "erro"}

# ----------------- Registration Endpoints -----------------
@app.get("/register", response_class=HTMLResponse)
def show_register(redirect_url: str = "https://contazoom.com"):
    # Renderiza um formulário simples de cadastro
    html_content = f"""
    <html>
      <body>
        <h2>Cadastro ContaZoom</h2>
        <form action="/register" method="post">
          <label>Email: <input type=\"email\" name=\"email\" required></label><br/>
          <label>Senha: <input type=\"password\" name=\"password\" required></label><br/>
          <input type=\"hidden\" name=\"redirect_url\" value=\"{redirect_url}\" />
          <button type=\"submit\">Registrar</button>
        </form>
      </body>
    </html>
    """
    return HTMLResponse(html_content)

@app.post("/register")
async def do_register(
    email: str = Form(...),
    password: str = Form(...),
    redirect_url: str = Form("https://contazoom.com")
):
    # TODO: implemente sua lógica de criação de usuário aqui
    # Exemplo: salvar no banco, validações, envio de email, etc.

    # Após sucesso no cadastro, redireciona de volta
    return RedirectResponse(url=redirect_url, status_code=302)

# ----------------- Webhook de Pagamentos -----------------
@app.post("/webhook/payments")
async def webhook_payments(request: Request):
    payload = await request.json()
    print(f"📩 Webhook recebido: {payload}")

    payment_id = payload.get("resource", "").split("/")[-1]
    ml_user_id = str(payload.get("user_id"))

    if not payment_id or not ml_user_id:
        return {"status": "erro", "message": "Dados incompletos na notificação"}

    access_token = renovar_access_token(ml_user_id)
    if not access_token:
        return {"status": "erro", "message": "Não foi possível renovar o token"}

    r = requests.get(
        f"https://api.mercadolibre.com/collections/{payment_id}",
        params={"access_token": access_token}
    )
    if r.status_code != 200:
        return {"status": "erro", "message": "Erro ao consultar payment", "details": r.json()}

    payment_data = r.json()
    external_reference = payment_data.get("external_reference")
    if not external_reference:
        return {"status": "erro", "message": "external_reference ausente no payment"}

    order = requests.get(
        f"https://api.mercadolibre.com/orders/{external_reference}",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    if order.status_code != 200:
        return {"status": "erro", "message": "Erro ao consultar order", "details": order.json()}

    order_data = order.json()
    try:
        salvar_nova_venda(order_data)
        return {"status": "ok", "message": "Venda salva com sucesso"}
    except Exception as e:
        print(f"❌ Erro ao salvar venda: {e}")
        return {"status": "erro", "message": "Falha ao salvar venda"}