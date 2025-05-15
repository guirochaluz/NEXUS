from fastapi import APIRouter, Request, HTTPException
from database.db import SessionLocal
from database.models import Sale
from dateutil import parser
import requests

router = APIRouter()

@router.post("/api/webhook/ml")
async def ml_webhook(request: Request):
    """
    Rota que recebe notificações do Mercado Livre em tempo real.
    """
    data = await request.json()
    
    if "resource" not in data:
        raise HTTPException(status_code=400, detail="Dados inválidos.")

    resource_url = data["resource"]

    # Coletar detalhes da venda com o access token do usuário
    access_token = "SEU_ACCESS_TOKEN_AQUI"  # Aqui vamos usar o token dinâmico mais tarde
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        response = requests.get(resource_url, headers=headers)
        response.raise_for_status()
        sale_data = response.json()
    except requests.RequestException as e:
        print(f"❌ Erro ao buscar detalhes da venda: {e}")
        raise HTTPException(status_code=500, detail="Erro ao buscar detalhes da venda.")

    # Gravar no banco de dados
    db = SessionLocal()
    try:
        order_id = sale_data.get("id")
        if db.query(Sale).filter_by(order_id=order_id).first():
            print(f"⚠️ Venda {order_id} já existe no banco, pulando...")
            return {"status": "Venda já existente"}

        sale = Sale(
            order_id=str(order_id),
            ml_user_id=sale_data["seller"]["id"],
            buyer_id=sale_data["buyer"]["id"],
            buyer_nickname=sale_data["buyer"]["nickname"],
            total_amount=sale_data["total_amount"],
            status=sale_data["status"],
            date_created=parser.isoparse(sale_data["date_created"]),
            item_id=sale_data["order_items"][0]["item"]["id"],
            item_title=sale_data["order_items"][0]["item"]["title"],
            quantity=sale_data["order_items"][0]["quantity"],
            unit_price=sale_data["order_items"][0]["unit_price"]
        )
        
        db.add(sale)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"⚠️ Erro ao salvar venda no banco: {e}")
        raise HTTPException(status_code=500, detail="Erro ao salvar venda.")
    finally:
        db.close()

    print(f"✅ Venda {order_id} recebida e salva com sucesso!")
    return {"status": "Venda recebida"}
