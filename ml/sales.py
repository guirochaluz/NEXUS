import requests
from dateutil import parser
from database.db import SessionLocal
from database.models import Sale
from sqlalchemy import func
from typing import Optional

def get_sales(ml_user_id: str, access_token: str) -> int:
    """
    Sincroniza incrementalmente as vendas mais recentes do Mercado Livre
    (primeira página de até 50 resultados), salvando apenas os pedidos
    com order_id maior do que o último importado para o banco.

    Args:
        ml_user_id (str): ID do usuário do Mercado Livre.
        access_token (str): Token de acesso para autenticação.

    Returns:
        int: Quantidade de vendas novas salvas no banco de dados.
    """
    db = SessionLocal()
    total_saved = 0

    try:
        # 1) Identifica o último order_id já salvo para essa conta
        last_order_id = (
            db.query(func.max(Sale.order_id))
              .filter(Sale.ml_user_id == int(ml_user_id))
              .scalar()
        )
        last_order_id = str(last_order_id) if last_order_id is not None else None
        print(f"Último order_id importado para {ml_user_id}: {last_order_id}")

        # 2) Puxa a primeira página de até 50 pedidos mais recentes
        url = (
            f"https://api.mercadolibre.com/orders/search"
            f"?seller={ml_user_id}"
            f"&order.status=paid"
            f"&offset=0"
            f"&limit=50"
        )
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"❌ Erro HTTP ao buscar vendas: {e}")
            return 0

        orders = resp.json().get("results", [])
        if not orders:
            print("🔍 Nenhuma venda encontrada na primeira página.")
            return 0

        # 3) Filtra apenas as vendas com order_id maior que o último
        novas = []
        for order in orders:
            oid = str(order.get("id"))
            if last_order_id and oid <= last_order_id:
                # pedidos antigos ou já importados
                continue
            novas.append(order)

        if not novas:
            print("🔍 Não há vendas novas para importar.")
            return 0

        # 4) Constrói e persiste cada nova venda
        for order in novas:
            order_id = str(order.get("id"))
            buyer      = order.get("buyer", {}) or {}
            item       = (order.get("order_items") or [{}])[0]
            item_info  = item.get("item", {}) or {}
            shipping   = order.get("shipping") or {}
            addr       = shipping.get("receiver_address") or {}

            sale = Sale(
                order_id=order_id,
                ml_user_id=int(ml_user_id),
                buyer_id=buyer.get("id"),
                buyer_nickname=buyer.get("nickname"),
                buyer_email=buyer.get("email"),
                buyer_first_name=buyer.get("first_name"),
                buyer_last_name=buyer.get("last_name"),
                total_amount=order.get("total_amount"),
                status=order.get("status"),
                status_detail=order.get("status_detail"),
                date_created=parser.isoparse(order.get("date_created")),
                item_id=item_info.get("id"),
                item_title=item_info.get("title"),
                quantity=item.get("quantity"),
                unit_price=item.get("unit_price"),
                shipping_id=shipping.get("id"),
                shipping_status=shipping.get("status"),
                city=addr.get("city", {}).get("name"),
                state=addr.get("state", {}).get("name"),
                country=addr.get("country", {}).get("id"),
                zip_code=addr.get("zip_code"),
                street_name=addr.get("street_name"),
                street_number=addr.get("street_number"),
            )
            db.add(sale)
            total_saved += 1

        # 5) Commit das novas vendas
        try:
            db.commit()
            print(f"✅ Importadas {total_saved} vendas novas para {ml_user_id}.")
        except Exception as e:
            db.rollback()
            print(f"⚠️ Erro no commit: {e}")
            total_saved = 0

    finally:
        db.close()

    return total_saved


def sync_all_accounts() -> int:
    """
    Sincroniza vendas novas para todas as contas cadastradas em user_tokens.
    
    Retorna o total de vendas importadas no batch.
    """
    db = SessionLocal()
    total = 0

    try:
        rows = db.execute(text("SELECT ml_user_id, access_token FROM user_tokens")).fetchall()
        for ml_user_id, access_token in rows:
            saved = get_sales(str(ml_user_id), access_token)
            total += saved
    finally:
        db.close()

    print(f"🗂️ Sincronização completa. Total de vendas importadas: {total}")
    return total
