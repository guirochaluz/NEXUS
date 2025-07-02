# sales.py – nova rotina de reconciliação
from __future__ import annotations

import math
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any

import requests
from dateutil.relativedelta import relativedelta
from sqlalchemy import text, inspect
from concurrent.futures import ThreadPoolExecutor, as_completed

from db import SessionLocal
from models import Sale, UserToken
from oauth import renovar_access_token
from sales import _order_to_sale

# ---------------- Configurações --------------- #
MAX_WORKERS       = 12
CHUNK_SIZE        = 1_000
NUMERIC_TOLERANCE = 0.01
API_TIMEOUT       = 10
BACKOFF_SEC       = 2

API_ORDER      = "https://api.mercadolibre.com/orders/{}"
API_ORDER_FULL = API_ORDER + "?access_token={}"

# ------------ Utilidades internas ------------- #
def _is_different(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return False
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return abs(float(a) - float(b)) > NUMERIC_TOLERANCE
    return a != b

def _fetch_full_order(order_id: str, access_token: str) -> dict | None:
    url = API_ORDER_FULL.format(order_id, access_token)
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=API_TIMEOUT)
            if resp.ok:
                return resp.json()
            if resp.status_code in (429, 500, 502, 503):
                time.sleep(BACKOFF_SEC * (attempt + 1))
                continue
            logging.warning(f"⚠️ Falha {resp.status_code} para order {order_id}")
            return None
        except requests.RequestException as e:
            logging.warning(f"⚠️ Req error ({order_id}): {e}")
            time.sleep(BACKOFF_SEC * (attempt + 1))
    return None

# --------------- Função principal -------------- #
def reconciliar_vendas(
    ml_user_id: str,
    desde: datetime | None = None,
    ate: datetime | None = None,
    max_workers: int = MAX_WORKERS
) -> Dict[str, int]:
    """
    Verifica divergências entre DB e API e faz UPDATE em lote.
    Retorna {"atualizadas": X, "erros": Y}.
    """

    if desde is None:
        desde = datetime.utcnow() - relativedelta(months=6)

    db = SessionLocal()
    atualizadas = erros = 0

    try:
        token_row: UserToken | None = db.query(UserToken).filter_by(ml_user_id=int(ml_user_id)).first()
        if not token_row:
            raise RuntimeError(f"Usuário {ml_user_id} não possui token válido.")
        access_token = token_row.access_token or ""
        novo_token = renovar_access_token(int(ml_user_id))
        if novo_token:
            access_token = novo_token

        # ----- Query com intervalo opcional ----- #
        query = """
            SELECT order_id
            FROM sales
            WHERE ml_user_id = :uid
              AND date_closed >= :desde
        """
        params = {"uid": ml_user_id, "desde": desde}
        if ate:
            query += " AND date_closed <= :ate"
            params["ate"] = ate

        order_ids: List[str] = [r[0] for r in db.execute(text(query), params)]

        if not order_ids:
            logging.info("Nenhuma venda no período para reconciliar.")
            return {"atualizadas": 0, "erros": 0}

        mapper = inspect(Sale)
        cols_to_check = {
            c.key for c in mapper.attrs
            if c.key not in {"id", "order_id", "ml_user_id"}
        }

        for chunk_idx in range(0, len(order_ids), CHUNK_SIZE):
            batch = order_ids[chunk_idx:chunk_idx + CHUNK_SIZE]
            updates: List[Dict[str, Any]] = []

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                fut_to_oid = {
                    pool.submit(_fetch_full_order, oid, access_token): oid
                    for oid in batch
                }

                for fut in as_completed(fut_to_oid):
                    oid = fut_to_oid[fut]
                    full_order = fut.result()
                    if full_order is None:
                        erros += 1
                        continue

                    db_row: Sale | None = db.query(Sale).filter_by(order_id=oid).first()
                    if db_row is None:
                        continue

                    api_sale: Sale = _order_to_sale(full_order, ml_user_id, access_token, db)

                    diff_map = {}
                    for col in cols_to_check:
                        db_val  = getattr(db_row, col)
                        api_val = getattr(api_sale, col)
                        if _is_different(db_val, api_val):
                            diff_map[col] = api_val

                    if diff_map:
                        diff_map["id"] = db_row.id
                        updates.append(diff_map)
                        logging.info(f"🔄 Order {oid} divergente – será atualizada.")

            if updates:
                db.bulk_update_mappings(Sale, updates)
                db.commit()
                atualizadas += len(updates)

    except Exception as e:
        db.rollback()
        raise RuntimeError(f"❌ Erro na reconciliação: {e}") from e
    finally:
        db.close()

    return {"atualizadas": atualizadas, "erros": erros}
