from __future__ import annotations

import time
import logging
from datetime import datetime
from typing import Any, Dict, List

import requests
from dateutil.relativedelta import relativedelta
from sqlalchemy import text, inspect
from concurrent.futures import ThreadPoolExecutor, as_completed

from db import SessionLocal
from models import Sale, UserToken
from oauth import renovar_access_token
from sales import _order_to_sale  # mantém a lógica já existente

# ---------------- Configurações ---------------- #
MAX_WORKERS       = 12
CHUNK_SIZE        = 1_000
NUMERIC_TOLERANCE = 0.01
API_TIMEOUT       = 10        # segundos
BACKOFF_SEC       = 2

API_ORDER      = "https://api.mercadolibre.com/orders/{}"
API_ORDER_FULL = API_ORDER + "?access_token={}"

# ------------ Utilidades internas ------------- #
def _is_different(a: Any, b: Any) -> bool:
    """Compara dois valores, aplicando tolerância p/ numéricos."""
    if a is None and b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) > NUMERIC_TOLERANCE
    return a != b


def _fetch_full_order(order_id: str, access_token: str) -> dict | None:
    """Baixa a order completa com até 3 tentativas + back-off exponencial leve."""
    url = API_ORDER_FULL.format(order_id, access_token)
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=API_TIMEOUT)
            if resp.ok:
                return resp.json()
            if resp.status_code in (429, 500, 502, 503):
                time.sleep(BACKOFF_SEC * (attempt + 1))
                continue
            logging.warning("⚠️ Falha %s para order %s", resp.status_code, order_id)
            return None
        except requests.RequestException as exc:
            logging.warning("⚠️ Req error (%s): %s", order_id, exc)
            time.sleep(BACKOFF_SEC * (attempt + 1))
    return None


# --------------- Função principal -------------- #
def reconciliar_vendas(
    ml_user_id: str,
    desde: datetime | None = None,
    ate: datetime | None = None,
    max_workers: int = MAX_WORKERS,
) -> Dict[str, int]:
    """
    Compara vendas já gravadas no banco com os dados atuais da API Mercado Livre.
    Atualiza divergências em lote e devolve: {"atualizadas": X, "erros": Y}.
    """
    if desde is None:
        desde = datetime.utcnow() - relativedelta(months=6)

    db          = SessionLocal()
    atualizadas = 0
    erros       = 0

    try:
        # ---------- Token ----------------------------------------------------
        token_row: UserToken | None = (
            db.query(UserToken).filter_by(ml_user_id=int(ml_user_id)).first()
        )
        if token_row is None:
            raise RuntimeError(f"Usuário {ml_user_id} não possui token salvo.")
        access_token = token_row.access_token or ""
        novo_token   = renovar_access_token(int(ml_user_id))
        if novo_token:
            access_token = novo_token

        # ---------- Seleção das vendas ---------------------------------------
        filtro_sql = """
            SELECT order_id
            FROM sales
            WHERE ml_user_id = :uid
              AND date_closed >= :desde
        """
        params = {"uid": ml_user_id, "desde": desde}
        if ate is not None:
            filtro_sql += " AND date_closed <= :ate"
            params["ate"] = ate

        order_ids: List[str] = [row[0] for row in db.execute(text(filtro_sql), params)]

        if not order_ids:
            logging.info(
                "Nenhuma venda de %s entre %s e %s.",
                ml_user_id,
                desde.date(),
                ate.date() if ate else "agora",
            )
            return {"atualizadas": 0, "erros": 0}

        # ---------- Colunas a auditar ----------------------------------------
        cols_to_check = {
            c.key
            for c in inspect(Sale).attrs
            if c.key not in {"id", "order_id", "ml_user_id"}
        }

        # ---------- Processamento em chunks ----------------------------------
        for start in range(0, len(order_ids), CHUNK_SIZE):
            batch   = order_ids[start : start + CHUNK_SIZE]
            updates: List[Dict[str, Any]] = []

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                fut_map = {
                    pool.submit(_fetch_full_order, oid, access_token): oid
                    for oid in batch
                }

                for fut in as_completed(fut_map):
                    oid = fut_map[fut]
                    full_order = fut.result()
                    if full_order is None:
                        erros += 1
                        continue

                    db_row: Sale | None = db.query(Sale).filter_by(order_id=oid).first()
                    if db_row is None:
                        continue

                    # Converte ordem da API → objeto Sale temporário
                    api_sale: Sale = _order_to_sale(
                        full_order, ml_user_id, access_token, db
                    )

                    diff: Dict[str, Any] = {}
                    for col in cols_to_check:
                        if _is_different(getattr(db_row, col), getattr(api_sale, col)):
                            diff[col] = getattr(api_sale, col)

                    if diff:
                        diff["id"] = db_row.id
                        updates.append(diff)
                        logging.info("🔄 Order %s divergente – marcada p/ update.", oid)

            # ---------- Commit em lote por chunk ------------------------------
            if updates:
                db.bulk_update_mappings(Sale, updates)
                db.commit()
                atualizadas += len(updates)

    except Exception as exc:
        db.rollback()
        raise RuntimeError(f"❌ Erro na reconciliação: {exc}") from exc
    finally:
        db.close()

    return {"atualizadas": atualizadas, "erros": erros}
