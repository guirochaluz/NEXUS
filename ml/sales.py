# sales.py

import sys
import requests
from dateutil import parser
from db import SessionLocal
from models import Sale, UserToken

def get_sales(ml_user_id: int):
    """
    Coleta vendas paginadas do Mercado Livre e salva no banco,
    evitando duplicação pelo campo ml_order_id.
    """
    db = SessionLocal()
    token_obj = db.query(UserToken).filter_by(ml_user_id=ml_user_id).first()
    if not token_obj:
        print(f"❌ Token não encontrado para o usuário {ml_user_id}")
        db.close()
        return

    access_token = token_obj.access_token
    offset, limit = 0, 50
    total_saved = 0

    try:
        while True:
            url = (
                "https://api.mercadolibre.com/orders/search"
                f"?seller={ml_user_id}&order.status=paid"
                f"&offset={offset}&limit={limit}"
            )
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.get(url, headers=headers)
            if resp.status_code != 200:
                print(f"❌ Erro HTTP {resp.status_code}: {resp.text}")
                break

            orders = resp.json().get("results", [])
            if not orders:
                break

            for order in orders:
                ml_order_id = order.get("id")
                # Evita duplicação
                if db.query(Sale).filter_by(ml_order_id=ml_order_id).first():
                    continue

                sale = Sale(
                    ml_order_id   = ml_order_id,
                    ml_user_id    = ml_user_id,
                    date_created  = parser.isoparse(order["date_created"]),
                    status        = order.get("status"),
                    item_id       = (order["order_items"][0]["item"]["id"]
                                     if order.get("order_items") else None),
                    item_title    = (order["order_items"][0]["item"]["title"]
                                     if order.get("order_items") else None),
                    quantity      = (order["order_items"][0]["quantity"]
                                     if order.get("order_items") else None),
                    unit_price    = (order["order_items"][0]["unit_price"]
                                     if order.get("order_items") else None),
                    total_amount  = order.get("total_amount"),
                    shipping_id      = order.get("shipping", {}).get("id"),
                    shipping_status  = order.get("shipping", {}).get("status"),
                    city             = order.get("shipping", {}) \
                                          .get("receiver_address", {}) \
                                          .get("city"),
                    state            = order.get("shipping", {}) \
                                          .get("receiver_address", {}) \
                                          .get("state"),
                    country          = order.get("shipping", {}) \
                                          .get("receiver_address", {}) \
                                          .get("country"),
                    zip_code         = order.get("shipping", {}) \
                                          .get("receiver_address", {}) \
                                          .get("zip_code"),
                    street_name      = order.get("shipping", {}) \
                                          .get("receiver_address", {}) \
                                          .get("street_name"),
                    street_number    = order.get("shipping", {}) \
                                          .get("receiver_address", {}) \
                                          .get("street_number"),
                )
                db.add(sale)
                total_saved += 1

            db.commit()
            offset += limit

    except Exception as e:
        db.rollback()
        print(f"⚠️ Erro ao processar vendas: {e}")
    finally:
        db.close()

    print(f"✅ {total_saved} novas vendas salvas para o usuário {ml_user_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python sales.py <ml_user_id>")
        sys.exit(1)

    try:
        user_id = int(sys.argv[1])
    except ValueError:
        print("Erro: <ml_user_id> deve ser um número inteiro.")
        sys.exit(1)

    get_sales(user_id)
