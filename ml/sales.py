import requests
from database.db import SessionLocal
from database.models import Sale
from dateutil import parser
from datetime import datetime

def get_sales(ml_user_id, access_token):
    offset = 0
    limit = 50
    total_saved = 0

    print(f"📥 Coletando vendas para o usuário {ml_user_id}...")

    while True:
        url = f"https://api.mercadolibre.com/orders/search?seller={ml_user_id}&order.status=paid&offset={offset}&limit={limit}"
        headers = {"Authorization": f"Bearer {access_token}"}
        res = requests.get(url, headers=headers)

        if res.status_code != 200:
            print(f"❌ Erro ao buscar vendas: {res.text}")
            break

        data = res.json()
        results = data.get("results", [])
        if not results:
            print("🚫 Nenhuma nova venda encontrada.")
            break

        db = SessionLocal()
        for order in results:
            try:
                db.add(Sale(
                    order_id=str(order["id"]),
                    ml_user_id=ml_user_id,

                    # Dados do comprador
                    buyer_id=str(order["buyer"]["id"]),
                    buyer_nickname=order["buyer"]["nickname"],
                    buyer_email=order["buyer"].get("email", ""),
                    buyer_first_name=order["buyer"].get("first_name", ""),
                    buyer_last_name=order["buyer"].get("last_name", ""),

                    # Informações do pedido
                    total_amount=str(order["total_amount"]),
                    status=order["status"],
                    status_detail=order.get("status_detail", ""),
                    date_created=parser.isoparse(order["date_created"]),

                    # Produto principal (assumindo 1 item por venda)
                    item_id=order["order_items"][0]["item"]["id"] if order["order_items"] else None,
                    item_title=order["order_items"][0]["item"]["title"] if order["order_items"] else None,
                    quantity=order["order_items"][0]["quantity"] if order["order_items"] else None,
                    unit_price=str(order["order_items"][0]["unit_price"]) if order["order_items"] else None,

                    # Dados de envio
                    shipping_id=str(order["shipping"]["id"]) if "shipping" in order else None,
                    shipping_status=order["shipping"].get("status") if "shipping" in order else None,
                    city=order["shipping"]["receiver_address"]["city"].get("name") if "shipping" in order and order["shipping"].get("receiver_address") else None,
                    state=order["shipping"]["receiver_address"]["state"].get("name") if "shipping" in order and order["shipping"].get("receiver_address") else None,
                    country=order["shipping"]["receiver_address"]["country"].get("name") if "shipping" in order and order["shipping"].get("receiver_address") else None,
                    zip_code=order["shipping"]["receiver_address"].get("zip_code") if "shipping" in order and order["shipping"].get("receiver_address") else None,
                    street_name=order["shipping"]["receiver_address"].get("street_name") if "shipping" in order and order["shipping"].get("receiver_address") else None,
                    street_number=order["shipping"]["receiver_address"].get("street_number") if "shipping" in order and order["shipping"].get("receiver_address") else None,
                ))
                total_saved += 1
            except Exception as e:
                print(f"⚠️ Erro ao salvar pedido {order['id']}: {e}")
        db.commit()
        db.close()

        offset += limit

    print(f"✅ Vendas salvas com sucesso: {total_saved}")