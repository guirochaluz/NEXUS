import os
import requests
from dateutil import parser
from database.db import SessionLocal
from database.models import Sale
from sqlalchemy import func, text
from typing import Optional
from dotenv import load_dotenv
from dateutil import parser
from dateutil.tz import tzutc

# Carrega variáveis de ambiente
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL")

API_BASE = "https://api.mercadolibre.com/orders/search"
FULL_PAGE_SIZE = 50


def get_full_sales(ml_user_id: str, access_token: str) -> int:
    """
    Coleta **todas** as vendas paginadas do Mercado Livre e salva no banco,
    evitando duplicação pelo order_id. Usado para importar histórico completo.
    """
    db = SessionLocal()
    offset = 0
    total_saved = 0

    try:
        while True:
            params = {
                "seller": ml_user_id,
                "order.status": "paid",
                "offset": offset,
                "limit": FULL_PAGE_SIZE,
                "sort": "date_desc",  # garante ordem cronológica
            }
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.get(API_BASE, params=params, headers=headers)
            resp.raise_for_status()

            orders = resp.json().get("results", [])
            if not orders:
                break

            for order in orders:
                order_id = str(order["id"])
                # evita duplicar pelo order_id
                if db.query(Sale).filter_by(order_id=order_id).first():
                    continue
                sale = _order_to_sale(order, ml_user_id)
                db.add(sale)
                total_saved += 1

            db.commit()
            if len(orders) < FULL_PAGE_SIZE:
                break
            offset += FULL_PAGE_SIZE

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return total_saved


def get_incremental_sales(ml_user_id: str, access_token: str) -> int:
    db = SessionLocal()
    total_saved = 0

    try:
        # … refresh do token …

        # 1) Último date_created no banco (as aware UTC)
        last_db_date = (
            db.query(func.max(Sale.date_created))
              .filter(Sale.ml_user_id == int(ml_user_id))
              .scalar()
        )
        if last_db_date and last_db_date.tzinfo is None:
            last_db_date = last_db_date.replace(tzinfo=tzutc())
        print(f">>> DEBUG last_db_date (aware UTC): {last_db_date}")

        # 2) Busca a primeira página
        resp = requests.get(
            f"{API_BASE}?seller={ml_user_id}&order.status=paid&offset=0&limit={FULL_PAGE_SIZE}",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        resp.raise_for_status()
        orders = resp.json().get("results", [])
        if not orders:
            return 0

        # 3) Filtra novass por date_created
        novas = []
        for o in orders:
            order_dt = parser.isoparse(o["date_created"])
            # todos aware, comparação segura
            if last_db_date and order_dt <= last_db_date:
                continue
            novas.append(o)

        if not novas:
            return 0

        # 4) Persiste os novos
        for order in novas:
            sale = _order_to_sale(order, ml_user_id)
            db.add(sale)
            total_saved += 1

        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return total_saved

def sync_all_accounts() -> int:
    """
    Roda o incremental (get_incremental_sales) para todas as contas
    cadastradas em user_tokens, retorna o total de vendas importadas.
    """
    db = SessionLocal()
    total = 0
    try:
        rows = db.execute(text("SELECT ml_user_id, access_token FROM user_tokens")).fetchall()
        for ml_user_id, access_token in rows:
            total += get_incremental_sales(str(ml_user_id), access_token)
    finally:
        db.close()

    print(f"🗂️ Sincronização completa. Total de vendas importadas: {total}")
    return total


def _order_to_sale(order: dict, ml_user_id: str) -> Sale:
    """
    Converte o JSON de uma order ML num objeto database.models.Sale.
    """
    buyer    = order.get("buyer", {}) or {}
    item     = (order.get("order_items") or [{}])[0]
    item_inf = item.get("item", {}) or {}
    ship     = order.get("shipping") or {}
    addr     = ship.get("receiver_address") or {}

    return Sale(
        order_id        = str(order["id"]),
        ml_user_id      = int(ml_user_id),
        buyer_id        = buyer.get("id"),
        buyer_nickname  = buyer.get("nickname"),
        buyer_email     = buyer.get("email"),
        buyer_first_name= buyer.get("first_name"),
        buyer_last_name = buyer.get("last_name"),
        total_amount    = order.get("total_amount"),
        status          = order.get("status"),
        status_detail   = order.get("status_detail"),
        date_created    = parser.isoparse(order.get("date_created")),
        item_id         = item_inf.get("id"),
        item_title      = item_inf.get("title"),
        quantity        = item.get("quantity"),
        unit_price      = item.get("unit_price"),
        shipping_id     = ship.get("id"),
        shipping_status = ship.get("status"),
        city            = addr.get("city", {}).get("name"),
        state           = addr.get("state", {}).get("name"),
        country         = addr.get("country", {}).get("id"),
        zip_code        = addr.get("zip_code"),
        street_name     = addr.get("street_name"),
        street_number   = addr.get("street_number"),
    )
