import sys
import requests
from dateutil import parser
from database.db import SessionLocal
from database.models import Sale, UserToken


def get_sales(ml_user_id: int):
    """
    Coleta vendas paginadas do Mercado Livre e salva no banco,
    evitando duplicação pelo campo order_id.
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
                order_id = order.get("id")

                # Evita duplicação pelo order_id
                if db.query(Sale).filter_by(order_id=order_id).first():
                    continue

                # Comprador
                buyer = order.get("buyer", {})
                buyer_id          = buyer.get("id")
                buyer_nickname    = buyer.get("nickname")
                buyer_email       = buyer.get("email")
                buyer_first_name  = buyer.get("first_name")
                buyer_last_name   = buyer.get("last_name")

                # Item
                item = order.get("order_items", [{}])[0]
                item_info = item.get("item", {})
                item_id    = item_info.get("id")
                item_title = item_info.get("title")
                quantity   = item.get("quantity")
                unit_price = item.get("unit_price")

                # Valores e status
                total_amount  = order.get("total_amount")
                status        = order.get("status")
                status_detail = order.get("status_detail")

                # Dados de envio
                shipping = order.get("shipping", {})
                shipping_id     = shipping.get("id")
                shipping_status = shipping.get("status")
                addr = shipping.get("receiver_address", {})
                city          = addr.get("city", {}).get("name")
                state         = addr.get("state", {}).get("name")
                country       = addr.get("country", {}).get("id")
                zip_code      = addr.get("zip_code")
                street_name   = addr.get("street_name")
                street_number = addr.get("street_number")

                sale = Sale(
                    order_id         = order_id,
                    ml_user_id       = ml_user_id,
                    buyer_id         = buyer_id,
                    buyer_nickname   = buyer_nickname,
                    buyer_email      = buyer_email,
                    buyer_first_name = buyer_first_name,
                    buyer_last_name  = buyer_last_name,
                    total_amount     = total_amount,
                    status           = status,
                    status_detail    = status_detail,
                    date_created     = parser.isoparse(order["date_created"]),
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

