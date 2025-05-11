# sales.py
import requests
from db import SessionLocal
from models import Sale
from dateutil import parser
from datetime import datetime


def get_sales(ml_user_id: str, access_token: str):
    """
    Coleta todas as vendas paginadas pelo Mercado Livre e salva no banco.
    """
    offset = 0
    limit = 50
    total_saved = 0
    print(f"📥 Coletando vendas para o usuário {ml_user_id}...")

    db = SessionLocal()
    try:
        while True:
            url = (
                f"https://api.mercadolibre.com/orders/search"
                f"?seller={ml_user_id}&order.status=paid"
                f"&offset={offset}&limit={limit}"
            )
            headers = {"Authorization": f"Bearer {access_token}"}
            try:
                resp = requests.get(url, headers=headers)
                resp.raise_for_status()
            except requests.HTTPError as http_err:
                print(f"❌ Erro na requisição de vendas: {http_err}")
                break

            data = resp.json()
            orders = data.get("results", [])
            if not orders:
                break

            for order in orders:
                try:
                    # Extrai dados da venda e envio
                    sale = Sale(
                        ml_user_id=ml_user_id,
                        date_created=parser.isoparse(order.get("date_created")),
                        status=order.get("status"),
                        item_id=(order["order_items"][0]["item"]["id"]
                                 if order.get("order_items") else None),
                        item_title=(order["order_items"][0]["item"]["title"]
                                    if order.get("order_items") else None),
                        quantity=(order["order_items"][0]["quantity"]
                                  if order.get("order_items") else None),
                        unit_price=(order["order_items"][0]["unit_price"]
                                    if order.get("order_items") else None),
                        total_amount=order.get("total_amount"),
                        shipping_id=(order.get("shipping", {}).get("id")),
                        shipping_status=(order.get("shipping", {}).get("status")),
                        city=(order.get("shipping", {}).get("receiver_address", {}).get("city")),
                        state=(order.get("shipping", {}).get("receiver_address", {}).get("state")),
                        country=(order.get("shipping", {}).get("receiver_address", {}).get("country")),
                        zip_code=(order.get("shipping", {}).get("receiver_address", {}).get("zip_code")),
                        street_name=(order.get("shipping", {}).get("receiver_address", {}).get("street_name")),
                        street_number=(order.get("shipping", {}).get("receiver_address", {}).get("street_number")),
                    )
                    db.add(sale)
                    total_saved += 1
                except Exception as e:
                    print(f"⚠️ Erro ao salvar pedido {order.get('id')}: {e}")

            db.commit()
            offset += limit

    finally:
        db.close()

    print(f"✅ Vendas salvas com sucesso: {total_saved}")
