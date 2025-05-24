import os
import requests
from dateutil import parser
from database.db import SessionLocal
from database.models import Sale
from sqlalchemy import func, text
from typing import Optional, Tuple, List
from dotenv import load_dotenv
from dateutil import parser
from dateutil.tz import tzutc
from requests.exceptions import HTTPError




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
                "offset": offset,
                "limit": FULL_PAGE_SIZE,
                "sort": "date_asc",  # garante ordem cronológica
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
    """
    Coleta apenas as vendas criadas após o último import, com retry automático
    ao receber 401 Unauthorized.
    """
    db = SessionLocal()
    total_saved = 0

    try:
        # 0) Refresh inicial do access_token via backend
        try:
            r = requests.post(f"{BACKEND_URL}/auth/refresh", json={"user_id": ml_user_id})
            r.raise_for_status()
            # pega o token atualizado no banco
            new_token = db.execute(
                text("SELECT access_token FROM user_tokens WHERE ml_user_id = :uid"),
                {"uid": ml_user_id}
            ).scalar()
            if new_token:
                access_token = new_token
        except Exception as e:
            print(f"⚠️ Falha no refresh inicial de token ({ml_user_id}): {e}")

        # 1) Última data no banco
        last_db_date = (
            db.query(func.max(Sale.date_closed))
              .filter(Sale.ml_user_id == int(ml_user_id))
              .scalar()
        )
        if last_db_date is None:
            return get_full_sales(ml_user_id, access_token)

        if last_db_date.tzinfo is None:
            last_db_date = last_db_date.replace(tzinfo=tzutc())

        # 2) Parâmetros da chamada incremental
        params = {
            "seller": ml_user_id,
            "order.status": "paid",
            "limit": FULL_PAGE_SIZE,
            "sort": "date_desc",
            "order.date_closed.from": last_db_date.isoformat(),
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        # 3) Tenta a requisição, faz retry em caso de 401
        try:
            resp = requests.get(API_BASE, params=params, headers=headers)
            resp.raise_for_status()
        except HTTPError as http_err:
            if resp.status_code == 401:
                # renova token de novo
                print(f"🔄 Token expirado para {ml_user_id}, renovando e retry...")
                r2 = requests.post(f"{BACKEND_URL}/auth/refresh", json={"user_id": ml_user_id})
                r2.raise_for_status()
                # busca o novo token
                new_token = db.execute(
                    text("SELECT access_token FROM user_tokens WHERE ml_user_id = :uid"),
                    {"uid": ml_user_id}
                ).scalar()
                if not new_token:
                    raise RuntimeError("Falha ao obter novo access_token após refresh")
                access_token = new_token
                headers = {"Authorization": f"Bearer {access_token}"}

                # retry da chamada
                resp = requests.get(API_BASE, params=params, headers=headers)
                resp.raise_for_status()
            else:
                # se for outro HTTPError, repassa
                raise

        orders = resp.json().get("results", [])
        if not orders:
            return 0

        # 4) Persiste ou atualiza vendas
        for o in orders:
            oid = str(o["id"])
            existing_sale = db.query(Sale).filter_by(order_id=oid).first()
        
            if not existing_sale:
                # nova venda
                db.add(_order_to_sale(o, ml_user_id))
                total_saved += 1
            else:
                # venda já existe — atualiza o status se mudou
                novo_status = o.get("status", "").lower()
                if novo_status and existing_sale.status != novo_status:
                    existing_sale.status = novo_status

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


def _order_to_sale(order: dict, ml_user_id: str, db: Optional[SessionLocal] = None) -> Sale:
    """
    Transforma um dicionário de pedido do Mercado Livre em um objeto Sale.
    Se um objeto db (Session) não for passado, cria e fecha uma sessão local.
    """
    internal_session = False
    if db is None:
        from database.db import SessionLocal
        db = SessionLocal()
        internal_session = True

    buyer    = order.get("buyer", {}) or {}
    item     = (order.get("order_items") or [{}])[0]
    item_inf = item.get("item", {}) or {}
    ship     = order.get("shipping") or {}
    addr     = ship.get("receiver_address") or {}

    item_id = item_inf.get("id")
    sku = None
    quantity_sku = None
    custo_unitario = None
    level1 = None
    level2 = None

    try:
        sku_result = db.execute(text("""
            SELECT sku FROM skumlb WHERE mlb = :mlb LIMIT 1
        """), {"mlb": item_id}).scalar()

        if sku_result:
            sku = sku_result
            sku_info = db.execute(text("""
                SELECT quantity, custo_unitario, level1, level2
                FROM sku
                WHERE sku = :sku
                ORDER BY date_created DESC
                LIMIT 1
            """), {"sku": sku}).fetchone()

            if sku_info:
                quantity_sku, custo_unitario, level1, level2 = sku_info

    finally:
        if internal_session:
            db.close()

    return Sale(
        order_id         = str(order["id"]),
        ml_user_id       = int(ml_user_id),
        buyer_id         = buyer.get("id"),
        buyer_nickname   = buyer.get("nickname"),
        buyer_email      = buyer.get("email"),
        buyer_first_name = buyer.get("first_name"),
        buyer_last_name  = buyer.get("last_name"),
        total_amount     = order.get("total_amount"),
        status           = order.get("status"),
        status_detail    = order.get("status_detail"),
        date_closed      = parser.isoparse(order.get("date_closed")),
        item_id          = item_id,
        item_title       = item_inf.get("title"),
        quantity         = item.get("quantity"),
        unit_price       = item.get("unit_price"),
        shipping_id      = ship.get("id"),
        shipping_status  = ship.get("status"),
        city             = addr.get("city", {}).get("name"),
        state            = addr.get("state", {}).get("name"),
        country          = addr.get("country", {}).get("id"),
        zip_code         = addr.get("zip_code"),
        street_name      = addr.get("street_name"),
        street_number    = addr.get("street_number"),
        sku              = sku,
        quantity_sku     = quantity_sku,
        custo_unitario   = custo_unitario,
        level1           = level1,
        level2           = level2
    )

def revisar_status_historico(ml_user_id: str, access_token: str, return_changes: bool = False) -> Tuple[int, List[Tuple[str, str, str]]]:
    """
    Revarre todas as vendas da conta no Mercado Livre e atualiza os status na base local.
    Retorna o total de vendas que tiveram o status alterado e, se return_changes=True,
    também retorna a lista de alterações (order_id, status_antigo, status_novo).
    """
    db = SessionLocal()
    atualizadas = 0
    alteracoes = []

    # Tradução de status da API para padrão do sistema
    tradutor_status = {
        "paid": "Pago",
        "cancelled": "Cancelado",
        "payment_required": "Pagamento Pendente",
        "payment_in_process": "Pagamento em Processamento",
        "partially_paid": "Parcialmente Pago",
    }

    MAX_OFFSET = 10000  # Limite imposto pela API

    try:
        offset = 0
        headers = {"Authorization": f"Bearer {access_token}"}
        params_base = {
            "seller": ml_user_id,
            "sort": "date_desc",
            "limit": FULL_PAGE_SIZE,
        }

        while offset < MAX_OFFSET:
            params = params_base.copy()
            params["offset"] = offset

            resp = requests.get(API_BASE, headers=headers, params=params)
            resp.raise_for_status()
            orders = resp.json().get("results", [])

            if not orders:
                break

            for o in orders:
                oid = str(o["id"])
                status_api_raw = o.get("status", "").strip().lower()
                status_api_formatado = tradutor_status.get(status_api_raw, status_api_raw.capitalize())

                existing_sale = db.query(Sale).filter_by(order_id=oid).first()
                if existing_sale:
                    status_local = existing_sale.status.strip().capitalize() if existing_sale.status else ""

                    if status_local != status_api_formatado:
                        if return_changes:
                            alteracoes.append((oid, status_local, status_api_formatado))
                        existing_sale.status = status_api_formatado
                        atualizadas += 1

            db.commit()

            if len(orders) < FULL_PAGE_SIZE:
                break

            offset += FULL_PAGE_SIZE

    except Exception as e:
        db.rollback()
        raise RuntimeError(f"Erro ao revisar histórico: {e}")

    finally:
        db.close()

    return (atualizadas, alteracoes) if return_changes else (atualizadas, [])
