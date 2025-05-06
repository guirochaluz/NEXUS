from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from database.db import init_db, salvar_nova_venda
from auth.oauth import get_auth_url, exchange_code, renovar_access_token
import requests

app = FastAPI()
init_db()

@app.get("/")
def home():
    url = get_auth_url()
    return HTMLResponse(f'<a href="{url}">Login com Mercado Livre</a>')

@app.get("/callback")
def callback(code: str):
    success = exchange_code(code)
    return {"status": "ok" if success else "erro"}

@app.post("/webhook/payments")
async def webhook_payments(request: Request):
    payload = await request.json()
    print(f"📩 Webhook recebido: {payload}")

    payment_id = payload.get("resource", "").split("/")[-1]
    ml_user_id = str(payload.get("user_id"))

    if not payment_id or not ml_user_id:
        return {"status": "erro", "message": "Dados incompletos na notificação"}

    # Renovar access_token usando refresh_token salvo no banco
    access_token = renovar_access_token(ml_user_id)
    if not access_token:
        return {"status": "erro", "message": "Não foi possível renovar o token"}

    # Buscar dados do pagamento
    r = requests.get(
        f"https://api.mercadopago.com/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    if r.status_code != 200:
        return {"status": "erro", "message": "Erro ao consultar payment", "details": r.json()}

    payment_data = r.json()
    external_reference = payment_data.get("external_reference")

    if not external_reference:
        return {"status": "erro", "message": "external_reference ausente no payment"}

    # Buscar dados da venda (order)
    order = requests.get(
        f"https://api.mercadolibre.com/orders/{external_reference}",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    if order.status_code != 200:
        return {"status": "erro", "message": "Erro ao consultar order", "details": order.json()}

    order_data = order.json()

    # Salvar a venda no banco
    try:
        salvar_nova_venda(order_data)
        return {"status": "ok", "message": "Venda salva com sucesso"}
    except Exception as e:
        print(f"❌ Erro ao salvar venda: {e}")
        return {"status": "erro", "message": "Falha ao salvar venda"}