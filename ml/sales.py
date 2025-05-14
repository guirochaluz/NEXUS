# sales.py

import requests
from dateutil import parser
from database.db import SessionLocal
from database.dbmodels import Sale
from typing import Optional

def get_sales(ml_user_id: str, access_token: str):
    """
    Coleta todas as vendas paginadas do Mercado Livre e salva no banco.
    Evita duplicação usando order_id (VARCHAR).
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
            resp = requests.get(url, headers=headers)
            if resp.status_code != 200:
                print(f"❌ Erro HTTP {resp.status_code} ao buscar vendas: {resp.text}")
                break

            orders = resp.json().get("results", [])
            if not orders:
                break

            for order in orders:
                order_id = str(order.get("id"))
                # Evita duplicação pelo order_id
                if db.query(Sale).filter_by(order_id=order_id).first():
                    continue

                # Dados do comprador (podem não existir em alguns endpoints)
                buyer = order.get("buyer", {}) or {}
                buyer_id         = buyer.get("id")
                buyer_nickname   = buyer.get("nickname")
                buyer_email      = buyer.get("email")
                buyer_first_name = buyer.get("first_name")
                buyer_last_name  = buyer.get("last_name")

                # Primeiro item do pedido (simplificação)
                item = (order.get("order_items") or [{}])[0]
                item_info = item.get("item", {}) or {}
                item_id    = item_info.get("id")
                item_title = item_info.get("title")
                quantity   = item.get("quantity")
                unit_price = item.get("unit_price")

                # Totais e status
                total_amount  = order.get("total_amount")
                status        = order.get("status")
                status_detail = order.get("status_detail")

                # Dados de envio
                shipping = order.get("shipping") or {}
                shipping_id     = shipping.get("id")
                shipping_status = shipping.get("status")
                addr = shipping.get("receiver_address") or {}
                city          = addr.get("city",{}).get("name")
                state         = addr.get("state",{}).get("name")
                country       = addr.get("country",{}).get("id")
                zip_code      = addr.get("zip_code")
                street_name   = addr.get("street_name")
                street_number = addr.get("street_number")

                # Cria o objeto Sale
                sale = Sale(
                    order_id         = order_id,
                    ml_user_id       = int(ml_user_id),
                    buyer_id         = buyer_id,
                    buyer_nickname   = buyer_nickname,
                    buyer_email      = buyer_email,
                    buyer_first_name = buyer_first_name,
                    buyer_last_name  = buyer_last_name,
                    total_amount     = total_amount,
                    status           = status,
                    status_detail    = status_detail,
                    date_created     = parser.isoparse(order.get("date_created")),
                    item_id          = item_id,
                    item_title       = item_title,
                    quantity         = quantity,
                    unit_price       = unit_price,
                    shipping_id      = shipping_id,
                    shipping_status  = shipping_status,
                    city             = city,
                    state            = state,
                    country          = country,
                    zip_code         = zip_code,
                    street_name      = street_name,
                    street_number    = street_number,
                )

                # Persiste
                try:
                    db.add(sale)
                    total_saved += 1
                except Exception as e:
                    db.rollback()
                    print(f"⚠️ Erro ao adicionar pedido {order_id}: {e}")
                    continue

            # Commit por página
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"⚠️ Erro no commit da página offset={offset}: {e}")

            offset += limit

    finally:
        db.close()

    print(f"✅ Vendas salvas com sucesso: {total_saved}")
