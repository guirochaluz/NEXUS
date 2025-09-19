# reconcile.py – rotina de reconciliação (ajustada)
from __future__ import annotations

import time
import logging
import random
from datetime import datetime, timezone
from typing import Dict, List, Any, Iterable
from decimal import Decimal

import requests
from dateutil.relativedelta import relativedelta
from sqlalchemy import text, select, inspect
from sqlalchemy.orm import Session
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from db import SessionLocal
from models import Sale, UserToken
from oauth import renovar_access_token
from sales import _order_to_sale

# ---- Config ----
MAX_WORKERS      = 12        # reduza p/ 6–8 se tiver muitos 429
CHUNK_SIZE       = 1_000
NUM_TOL          = 0.01
API_TIMEOUT      = 12
BASE_BACKOFF     = 1.5
MAX_RETRIES      = 5
POOL_MAXSIZE     = 100

API_ORDER = "https://api.mercadolibre.com/orders/{}"
EXCLUDE_COLS = {"id", "order_id", "ml_user_id", "seller_sku"}  # nunca atualiza

# ---- Comparação segura ----
def _is_different(a: Any, b: Any, tol: float = NUM_TOL) -> bool:
    if a is None and b is None:
        return False
    # normaliza strings
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() != b.strip()
    # decimais/numéricos com tolerância
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        return abs(float(a) - float(b)) > tol
    return a != b

# ---- HTTP session com retry/backoff ----
def _build_http_session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    retry = Retry(
        total=MAX_RETRIES,
        connect=2,
        read=2,
        backoff_factor=BASE_BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=POOL_MAXSIZE, pool_maxsize=POOL_MAXSIZE)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

def _respect_retry_after(resp: requests.Response) -> None:
    ra = resp.headers.get("Retry-After")
    if ra:
        try:
            sleep_s = int(ra)
        except ValueError:
            sleep_s = 5
    else:
        sleep_s = BASE_BACKOFF + random.random() * BASE_BACKOFF
    time.sleep(sleep_s)

def _fetch_full_order(order_id: str, http: requests.Session) -> dict | None:
    url = API_ORDER.format(order_id)
    for attempt in range(MAX_RETRIES):
        try:
            r = http.get(url, timeout=API_TIMEOUT)
            if r.ok:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                _respect_retry_after(r)
                continue
            logging.warning(f"Falha {r.status_code} order {order_id}: {r.text[:200]}")
            return None
        except requests.RequestException as e:
            logging.warning(f"Erro req ({order_id}) tent.{attempt+1}: {e}")
            time.sleep((BASE_BACKOFF * (2 ** attempt)) + random.random())
    return None

# ---- DB helpers ----
def _load_sales_batch(db: Session, order_ids: Iterable[str]) -> Dict[str, Sale]:
    rows: List[Sale] = db.execute(
        select(Sale).where(Sale.order_id.in_(list(order_ids)))
    ).scalars().all()
    return {row.order_id: row for row in rows}

# ---- Principal ----
def reconciliar_vendas(
    ml_user_id: str,
    desde: datetime | None = None,
    ate: datetime | None = None,
    max_workers: int = MAX_WORKERS
) -> Dict[str, int]:
    """
    Compara vendas no DB vs API ML e atualiza diferenças em lote.
    Retorna: {"atualizadas": X, "erros": Y}
    """
    if desde is None:
        desde = datetime.now(timezone.utc) - relativedelta(months=6)

    atualizadas = 0
    erros = 0

    with SessionLocal() as db:
        try:
            # token
            token_row: UserToken | None = db.query(UserToken).filter_by(ml_user_id=int(ml_user_id)).first()
            if not token_row:
                raise RuntimeError(f"Usuário {ml_user_id} sem token.")
            access_token = token_row.access_token or ""
            novo = renovar_access_token(int(ml_user_id))
            if novo:
                access_token = novo

            http = _build_http_session(access_token)

            # ids no período
            params = {"uid": ml_user_id, "desde": desde}
            q = """
                SELECT order_id
                FROM sales
                WHERE ml_user_id = :uid
                  AND date_closed >= :desde
            """
            if ate:
                q += " AND date_closed <= :ate"
                params["ate"] = ate

            order_ids: List[str] = [r[0] for r in db.execute(text(q), params)]
            if not order_ids:
                logging.info("Nenhuma venda para reconciliar.")
                return {"atualizadas": 0, "erros": 0}

            # somente colunas reais (evita relacionamentos)
            cols_real = {c.key for c in inspect(Sale).mapper.columns}
            cols_to_check = cols_real - EXCLUDE_COLS

            total = len(order_ids)
            logging.info(f"Reconciliando {total} pedidos (user={ml_user_id})")

            for start in range(0, total, CHUNK_SIZE):
                batch = order_ids[start:start + CHUNK_SIZE]
                t0 = time.time()

                sales_by_oid = _load_sales_batch(db, batch)
                if not sales_by_oid:
                    continue

                updates: List[Dict[str, Any]] = []

                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    fut_to_oid = {pool.submit(_fetch_full_order, oid, http): oid for oid in batch}

                    for fut in as_completed(fut_to_oid):
                        oid = fut_to_oid[fut]
                        data = fut.result()
                        if data is None:
                            erros += 1
                            continue

                        db_row = sales_by_oid.get(oid)
                        if db_row is None:
                            continue

                        api_sale: Sale = _order_to_sale(data, ml_user_id, access_token, db)

                        diff: Dict[str, Any] = {}
                        for col in cols_to_check:
                            if _is_different(getattr(db_row, col, None), getattr(api_sale, col, None)):
                                diff[col] = getattr(api_sale, col, None)

                        if diff:
                            diff["id"] = db_row.id
                            updates.append(diff)

                if updates:
                    db.bulk_update_mappings(Sale, updates)
                    db.commit()
                    atualizadas += len(updates)

                dt = time.time() - t0
                logging.info(
                    f"Lote {start//CHUNK_SIZE + 1}: {len(batch)} pedidos | "
                    f"{len(updates)} atualizadas | erros={erros} | {dt:.1f}s"
                )

        except Exception as e:
            db.rollback()
            raise RuntimeError(f"Erro na reconciliação: {e}") from e

    return {"atualizadas": atualizadas, "erros": erros}
