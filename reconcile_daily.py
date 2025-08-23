# reconcile_daily.py
from datetime import datetime, timezone, timedelta
import logging
from db import SessionLocal
from models import UserToken
from sales_reconcile import reconciliar_vendas  # importa a função que te enviei

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

def run_all_users(days:int = 15):
    ate = datetime.now(timezone.utc)
    desde = ate - timedelta(days=days)

    with SessionLocal() as db:
        # pegue todas as contas com token (ajuste filtro se tiver flag "ativo")
        users = db.query(UserToken.ml_user_id).distinct().all()

    total_ok = total_err = 0
    for (ml_user_id,) in users:
        try:
            logging.info(f"▶️ {ml_user_id} — reconciliando {days}d")
            res = reconciliar_vendas(str(ml_user_id), desde=desde, ate=ate, max_workers=8)
            logging.info(f"✅ {ml_user_id} — {res}")
            total_ok += res.get("atualizadas", 0)
            total_err += res.get("erros", 0)
        except Exception as e:
            logging.exception(f"❌ {ml_user_id} — erro: {e}")

    logging.info(f"Resumo: atualizadas={total_ok} erros={total_err}")

if __name__ == "__main__":
    run_all_users(15)
