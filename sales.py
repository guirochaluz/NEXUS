import os
import sys
import requests
from dateutil import parser
from db import SessionLocal
from models import Sale
from sqlalchemy import func, text, create_engine
from typing import Optional, Tuple, List
from dotenv import load_dotenv
from dateutil.tz import tzutc
from requests.exceptions import HTTPError
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import time

# Carrega variáveis de ambiente
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL")

API_BASE = "https://api.mercadolibre.com/orders/search"
FULL_PAGE_SIZE = 50

def _order_to_sale(order: dict, ml_user_id: str, access_token: str, db: Optional[SessionLocal] = None) -> Sale:
    internal_session = False
    if db is None:
        db = SessionLocal()
        internal_session = True

    try:
        order_id = order.get("id")

        try:
            resp = requests.get(f"https://api.mercadolibre.com/orders/{order_id}?access_token={access_token}")
            resp.raise_for_status()
            order = resp.json()
            print(f"✅ Order {order_id} complementada com dados completos")
        except Exception as e:
            print(f"⚠️ Erro ao complementar order {order_id}: {e}")

        payments = order.get("payments")
        if not payments:
            try:
                pay_resp = requests.get(f"https://api.mercadolibre.com/orders/{order_id}/payments?access_token={access_token}")
                pay_resp.raise_for_status()
                payments = pay_resp.json()
                if isinstance(payments, list) and payments:
                    print(f"✅ Payments recuperados separadamente para {order_id}")
                    order["payments"] = payments
            except Exception as e:
                print(f"❌ Erro ao buscar payments separadamente: {e}")

        buyer = order.get("buyer", {}) or {}
        item = (order.get("order_items") or [{}])[0]
        item_inf = item.get("item", {}) or {}
        ship = order.get("shipping") or {}

        seller_sku = item_inf.get("seller_sku")
        quantity_sku = custo_unitario = level1 = level2 = None

        if seller_sku:
            sku_info = db.execute(text("""
                SELECT quantity, custo_unitario, level1, level2
                FROM sku
                WHERE sku = :sku
                ORDER BY date_created DESC
                LIMIT 1
            """), {"sku": seller_sku}).fetchone()

            if sku_info:
                quantity_sku, custo_unitario, level1, level2 = sku_info

        payment_info = (order.get("payments") or [{}])[0]
        payment_id = payment_info.get("id")
        marketplace_fee = payment_info.get("marketplace_fee")

        print(f"📦 Finalizando order {order_id} | ml_fee: {marketplace_fee}")

        return Sale(
            order_id=str(order.get("id")),
            ml_user_id=int(ml_user_id),
            buyer_id=buyer.get("id"),
            buyer_nickname=buyer.get("nickname"),
            total_amount=order.get("total_amount"),
            status=order.get("status"),
            date_closed=parser.isoparse(order.get("date_closed")),
            item_id=item_inf.get("id"),
            item_title=item_inf.get("title"),
            quantity=item.get("quantity"),
            unit_price=item.get("unit_price"),
            shipping_id=ship.get("id"),
            seller_sku=seller_sku,
            quantity_sku=quantity_sku,
            custo_unitario=custo_unitario,
            level1=level1,
            level2=level2,
            ml_fee=marketplace_fee,
            payment_id=payment_id,
        )

    finally:
        if internal_session:
            db.close()

def get_incremental_sales(ml_user_id: str, access_token: str) -> int:
    from db import SessionLocal
    from models import Sale
    from sqlalchemy import func, text
    from sales import get_full_sales, _order_to_sale
    from dateutil.tz import tzutc
    import requests
    from requests.exceptions import HTTPError
    import os
    from concurrent.futures import ThreadPoolExecutor
    from main import buscar_ml_fee, engine, DATA_INICIO  # ajuste conforme onde estão definidos

    API_BASE = "https://api.mercadolibre.com/orders/search"
    FULL_PAGE_SIZE = 50
    BACKEND_URL = os.getenv("BACKEND_URL")

    db = SessionLocal()
    total_saved = 0

    try:
        # 🔁 Tenta renovar token inicialmente
        try:
            r = requests.post(f"{BACKEND_URL}/auth/refresh", json={"user_id": ml_user_id})
            r.raise_for_status()
            new_token = db.execute(
                text("SELECT access_token FROM user_tokens WHERE ml_user_id = :uid"),
                {"uid": ml_user_id}
            ).scalar()
            if new_token:
                access_token = new_token
        except Exception as e:
            print(f"⚠️ Falha ao renovar token ({ml_user_id}): {e}")

        # Busca a data da última venda registrada
        last_db_date = db.query(func.max(Sale.date_closed)).filter(Sale.ml_user_id == int(ml_user_id)).scalar()
        if last_db_date is None:
            return get_full_sales(ml_user_id, access_token)

        if last_db_date.tzinfo is None:
            last_db_date = last_db_date.replace(tzinfo=tzutc())

        # Requisição inicial
        params = {
            "seller": ml_user_id,
            "limit": FULL_PAGE_SIZE,
            "sort": "date_desc",
            "order.date_closed.from": last_db_date.isoformat(),
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            resp = requests.get(API_BASE, params=params, headers=headers)
            resp.raise_for_status()
        except HTTPError as http_err:
            if resp.status_code == 401:
                print(f"🔐 Token expirado para {ml_user_id}, tentando renovar...")
                r2 = requests.post(f"{BACKEND_URL}/auth/refresh", json={"user_id": ml_user_id})
                r2.raise_for_status()
                new_token = db.execute(
                    text("SELECT access_token FROM user_tokens WHERE ml_user_id = :uid"),
                    {"uid": ml_user_id}
                ).scalar()
                if not new_token:
                    raise RuntimeError("Falha ao obter novo access_token após refresh")
                access_token = new_token
                headers["Authorization"] = f"Bearer {access_token}"
                resp = requests.get(API_BASE, params=params, headers=headers)
                resp.raise_for_status()
            else:
                raise

        orders = resp.json().get("results", [])
        if not orders:
            return 0

        for o in orders:
            oid = str(o["id"])
            existing_sale = db.query(Sale).filter_by(order_id=oid).first()

            full_resp = requests.get(f"https://api.mercadolibre.com/orders/{oid}?access_token={access_token}")
            if not full_resp.ok:
                print(f"⚠️ Falha ao buscar ordem completa {oid}: {full_resp.status_code}")
                continue

            full_order = full_resp.json()
            nova_venda = _order_to_sale(full_order, ml_user_id, access_token, db)
            print(f"📦 Incremental - ordem {oid} processada | ml_fee: {nova_venda.ml_fee}")

            if not existing_sale:
                db.add(nova_venda)
            else:
                for attr, value in nova_venda.__dict__.items():
                    if attr != "_sa_instance_state":
                        setattr(existing_sale, attr, value)

            total_saved += 1

        db.commit()

        # ✅ Atualização complementar das taxas
        print(f"\n📊 Iniciando atualização de taxas pendentes para usuário {ml_user_id}...")

        with engine.begin() as conn:
            pedidos = conn.execute(text("""
                SELECT order_id FROM sales
                WHERE ml_user_id = :uid AND ml_fee IS NULL AND date_closed >= :inicio
            """), {"uid": ml_user_id, "inicio": DATA_INICIO}).fetchall()

        pedidos_ids = [row[0] for row in pedidos]
        if not pedidos_ids:
            print(f"📭 Nenhuma venda pendente para atualizar fees de {ml_user_id}.")
        else:
            print(f"📦 {len(pedidos_ids)} vendas sem fee. Atualizando com até 10 threads...")
            with ThreadPoolExecutor(max_workers=10) as executor:
                resultados = list(executor.map(lambda oid: buscar_ml_fee(oid, access_token), pedidos_ids))

            with engine.begin() as conn:
                atualizadas = 0
                for i, (order_id, fee) in enumerate(resultados, 1):
                    if fee is not None:
                        conn.execute(text("""
                            UPDATE sales SET ml_fee = :fee WHERE order_id = :oid
                        """), {"fee": fee, "oid": order_id})
                        atualizadas += 1
                        print(f"💾 Atualizado {i}/{len(pedidos_ids)} | Pedido {order_id} | Fee R${fee}")
                    else:
                        print(f"⏭️ Pulado {i}/{len(pedidos_ids)} | Pedido {order_id} sem fee.")

            print(f"✅ Atualização de fees concluída: {atualizadas}/{len(pedidos_ids)} vendas.")

    except Exception as e:
        db.rollback()
        raise RuntimeError(f"❌ Erro no incremental: {e}")
    finally:
        db.close()

    return total_saved


def _order_to_sale(order: dict, ml_user_id: str, access_token: str, db: Optional[SessionLocal] = None) -> Sale:
    from models import Sale
    from db import SessionLocal
    from sqlalchemy import text
    from dateutil import parser
    import requests

    internal_session = False
    if db is None:
        db = SessionLocal()
        internal_session = True

    try:
        order_id = order.get("id")

        # 🔄 Garante dados completos da ordem
        try:
            resp = requests.get(
                f"https://api.mercadolibre.com/orders/{order_id}?access_token={access_token}"
            )
            resp.raise_for_status()
            order = resp.json()
            print(f"📦 Order {order_id} complementada com dados completos")
        except Exception as e:
            print(f"⚠️ Erro ao complementar order {order_id}: {e}")

        # 🔍 Fallback para buscar payments, se necessário
        payments = order.get("payments")
        if not payments:
            try:
                pay_resp = requests.get(
                    f"https://api.mercadolibre.com/orders/{order_id}/payments?access_token={access_token}"
                )
                pay_resp.raise_for_status()
                payments = pay_resp.json()
                if isinstance(payments, list) and payments:
                    order["payments"] = payments
                    print(f"💳 Payments recuperados separadamente para {order_id}")
                else:
                    print(f"⚠️ Nenhum payment encontrado para {order_id}")
            except Exception as e:
                print(f"❌ Erro ao buscar payments em fallback: {e}")

        # Dados principais da venda
        buyer = order.get("buyer", {}) or {}
        item = (order.get("order_items") or [{}])[0]
        item_inf = item.get("item", {}) or {}
        ship = order.get("shipping") or {}

        # SKU e metadados complementares
        seller_sku = item_inf.get("seller_sku")
        quantity_sku = custo_unitario = level1 = level2 = None

        if seller_sku:
            sku_info = db.execute(text("""
                SELECT quantity, custo_unitario, level1, level2
                FROM sku
                WHERE sku = :sku
                ORDER BY date_created DESC
                LIMIT 1
            """), {"sku": seller_sku}).fetchone()

            if sku_info:
                quantity_sku, custo_unitario, level1, level2 = sku_info

        # Taxas
        payment_info = (order.get("payments") or [{}])[0]
        payment_id = payment_info.get("id")
        marketplace_fee = payment_info.get("marketplace_fee")

        print(f"✅ Finalizando order {order_id} | ml_fee: {marketplace_fee}")

        return Sale(
            order_id         = str(order_id),
            ml_user_id       = int(ml_user_id),
            buyer_id         = buyer.get("id"),
            buyer_nickname   = buyer.get("nickname"),
            total_amount     = order.get("total_amount"),
            status           = order.get("status"),
            date_closed      = parser.isoparse(order.get("date_closed")),
            item_id          = item_inf.get("id"),
            item_title       = item_inf.get("title"),
            quantity         = item.get("quantity"),
            unit_price       = item.get("unit_price"),
            shipping_id      = ship.get("id"),
            seller_sku       = seller_sku,
            quantity_sku     = quantity_sku,
            custo_unitario   = custo_unitario,
            level1           = level1,
            level2           = level2,
            ml_fee           = marketplace_fee,
            payment_id       = payment_id,
        )

    finally:
        if internal_session:
            db.close()

def revisar_status_historico(ml_user_id: str, access_token: str, return_changes: bool = False) -> Tuple[int, List[Tuple[str, str, str]]]:
    from datetime import datetime, timedelta
    from dateutil.relativedelta import relativedelta
    from dateutil.tz import tzutc
    from db import SessionLocal
    from models import Sale
    from sales import _order_to_sale
    from sqlalchemy import func
    import requests

    print(f"🔁 Iniciando revisão histórica para usuário {ml_user_id}")

    db = SessionLocal()
    atualizadas = 0
    alteracoes = []

    try:
        data_min = db.query(func.min(Sale.date_closed)).filter(Sale.ml_user_id == int(ml_user_id)).scalar()
        data_max = db.query(func.max(Sale.date_closed)).filter(Sale.ml_user_id == int(ml_user_id)).scalar()

        if not data_min or not data_max:
            print("⚠️ Nenhuma venda encontrada no histórico para revisar.")
            return atualizadas, alteracoes

        if data_min.tzinfo is None:
            data_min = data_min.replace(tzinfo=tzutc())
        if data_max.tzinfo is None:
            data_max = data_max.replace(tzinfo=tzutc())

        current_start = data_min.replace(day=1)

        while current_start <= data_max:
            current_end = (current_start + relativedelta(months=1)) - timedelta(seconds=1)
            print(f"📅 Revisando intervalo: {current_start.date()} → {current_end.date()}")
            offset = 0

            while offset < 10000:
                params = {
                    "seller": ml_user_id,
                    "offset": offset,
                    "limit": 50,
                    "sort": "date_desc",
                    "order.date_closed.from": current_start.isoformat(),
                    "order.date_closed.to": current_end.isoformat()
                }
                headers = {"Authorization": f"Bearer {access_token}"}
                resp = requests.get("https://api.mercadolibre.com/orders/search", headers=headers, params=params)

                if not resp.ok:
                    print(f"❌ Falha ao buscar lista de orders (offset {offset}): {resp.status_code}")
                    break

                orders = resp.json().get("results", [])
                if not orders:
                    print("⛔ Nenhuma venda nesse intervalo.")
                    break

                for order in orders:
                    oid = str(order["id"])
                    existing_sale = db.query(Sale).filter_by(order_id=oid).first()

                    if not existing_sale:
                        print(f"🟨 Venda {oid} não encontrada no banco. Pulando...")
                        continue

                    old_status = existing_sale.status
                    full_resp = requests.get(f"https://api.mercadolibre.com/orders/{oid}?access_token={access_token}")

                    if not full_resp.ok:
                        print(f"⚠️ Falha ao buscar dados completos da venda {oid}: {full_resp.status_code}")
                        continue

                    full_order = full_resp.json()
                    nova_venda = _order_to_sale(full_order, ml_user_id, access_token, db)
                    print(f"🔄 Atualizando venda {oid} | status: {old_status} → {nova_venda.status} | ml_fee: {nova_venda.ml_fee}")

                    for attr, value in nova_venda.__dict__.items():
                        if attr != "_sa_instance_state":
                            setattr(existing_sale, attr, value)

                    if return_changes and old_status != nova_venda.status:
                        alteracoes.append((oid, old_status, nova_venda.status))

                    atualizadas += 1

                db.commit()

                if len(orders) < 50:
                    break
                offset += 50

            current_start += relativedelta(months=1)

    except Exception as e:
        db.rollback()
        raise RuntimeError(f"❌ Erro ao revisar histórico: {e}")

    finally:
        db.close()

    print(f"✅ Revisão finalizada. Total de vendas atualizadas: {atualizadas}")
    return (atualizadas, alteracoes) if return_changes else (atualizadas, [])



def padronizar_status_sales(engine):
    """
    Padroniza os status da tabela 'sales':
    - Converte todas as variações de 'paid' para 'Pago'
    - Todos os demais status serão definidos como 'Cancelado'
    """
    from sqlalchemy import text

    print("🔧 Iniciando padronização dos status de vendas...")

    try:
        with engine.begin() as conn:
            # Atualiza para 'Pago' onde for 'paid' (ignorando maiúsculas/minúsculas)
            result_pago = conn.execute(text("""
                UPDATE sales
                SET status = 'Pago'
                WHERE LOWER(status) = 'paid'
            """))
            print(f"✅ Linhas atualizadas para 'Pago': {result_pago.rowcount}")

            # Define como 'Cancelado' tudo que não for 'Pago'
            result_cancelado = conn.execute(text("""
                UPDATE sales
                SET status = 'Cancelado'
                WHERE status != 'Pago'
            """))
            print(f"✅ Linhas atualizadas para 'Cancelado': {result_cancelado.rowcount}")

        print("🎯 Padronização finalizada com sucesso.")

    except Exception as e:
        print(f"❌ Erro ao padronizar status: {e}")
        raise


def sync_all_accounts() -> int:
    """
    Sincroniza todas as contas cadastradas na tabela user_tokens,
    utilizando a função incremental para buscar novas vendas.
    """
    from db import SessionLocal
    from sqlalchemy import text
    from sales import get_incremental_sales

    db = SessionLocal()
    total = 0

    try:
        print("🔁 Iniciando sincronização de todas as contas...")

        rows = db.execute(text("SELECT ml_user_id, access_token FROM user_tokens")).fetchall()

        for ml_user_id, access_token in rows:
            try:
                print(f"➡️ Sincronizando conta {ml_user_id}...")
                novas_vendas = get_incremental_sales(str(ml_user_id), access_token)
                total += novas_vendas
                print(f"✅ Conta {ml_user_id} sincronizada: {novas_vendas} novas vendas.")
            except Exception as e:
                print(f"❌ Erro ao sincronizar conta {ml_user_id}: {e}")

        print(f"📦 Sincronização concluída. Total de vendas importadas/atualizadas: {total}")

    finally:
        db.close()

    return total

def get_full_sales(ml_user_id: str, access_token: str) -> int:
    from datetime import datetime, timedelta
    from dateutil.relativedelta import relativedelta
    from dateutil.tz import tzutc
    from sales import _order_to_sale
    from db import SessionLocal
    from models import Sale
    from sqlalchemy import func
    import requests

    API_BASE = "https://api.mercadolibre.com/orders/search"
    FULL_PAGE_SIZE = 50

    db = SessionLocal()
    total_saved = 0

    try:
        # Determina o intervalo de datas com base nas vendas registradas
        data_min = db.query(func.min(Sale.date_closed)).filter(Sale.ml_user_id == int(ml_user_id)).scalar()
        data_max = db.query(func.max(Sale.date_closed)).filter(Sale.ml_user_id == int(ml_user_id)).scalar()

        if not data_min or not data_max:
            data_max = datetime.utcnow().replace(tzinfo=tzutc())
            data_min = data_max - relativedelta(years=1)

        if data_min.tzinfo is None:
            data_min = data_min.replace(tzinfo=tzutc())
        if data_max.tzinfo is None:
            data_max = data_max.replace(tzinfo=tzutc())

        current_start = data_min.replace(day=1)

        while current_start <= data_max:
            current_end = (current_start + relativedelta(months=1)) - timedelta(seconds=1)
            offset = 0

            while True:
                params = {
                    "seller": ml_user_id,
                    "offset": offset,
                    "limit": FULL_PAGE_SIZE,
                    "sort": "date_asc",
                    "order.date_closed.from": current_start.isoformat(),
                    "order.date_closed.to": current_end.isoformat()
                }
                headers = {"Authorization": f"Bearer {access_token}"}

                resp = requests.get(API_BASE, params=params, headers=headers)
                if not resp.ok:
                    print(f"❌ Falha ao buscar pedidos no intervalo {current_start.date()} - {current_end.date()} (offset {offset}): {resp.status_code}")
                    break

                orders = resp.json().get("results", [])
                if not orders:
                    break

                for order in orders:
                    order_id = str(order["id"])
                    try:
                        full_resp = requests.get(f"https://api.mercadolibre.com/orders/{order_id}?access_token={access_token}")
                        if not full_resp.ok:
                            print(f"⚠️ Falha ao buscar ordem completa {order_id}: {full_resp.status_code}")
                            continue

                        full_order = full_resp.json()
                        nova_venda = _order_to_sale(full_order, ml_user_id, access_token, db)
                        print(f"📦 FULL - ordem {order_id} processada | ml_fee: {nova_venda.ml_fee}")

                        existing_sale = db.query(Sale).filter_by(order_id=order_id).first()
                        if not existing_sale:
                            db.add(nova_venda)
                        else:
                            for attr, value in nova_venda.__dict__.items():
                                if attr != "_sa_instance_state":
                                    setattr(existing_sale, attr, value)

                        total_saved += 1

                    except Exception as e:
                        print(f"❌ Erro ao processar venda {order_id}: {e}")

                db.commit()

                if len(orders) < FULL_PAGE_SIZE:
                    break

                offset += FULL_PAGE_SIZE

            current_start += relativedelta(months=1)

    except Exception as e:
        db.rollback()
        raise RuntimeError(f"Erro ao importar vendas por intervalo: {e}")
    finally:
        db.close()

    return total_saved

