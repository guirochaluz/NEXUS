from decimal import Decimal
import sys
from pathlib import Path
from types import ModuleType

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

# Evita dependências de banco e credenciais durante a importação de reconcile.py
fake_db = ModuleType("db")
fake_db.SessionLocal = None
sys.modules["db"] = fake_db

fake_oauth = ModuleType("oauth")
fake_oauth.renovar_access_token = lambda *_args, **_kwargs: None
sys.modules["oauth"] = fake_oauth

fake_sales = ModuleType("sales")
fake_sales._order_to_sale = lambda *_args, **_kwargs: None
sys.modules["sales"] = fake_sales

from reconcile import _is_different


def test_is_different_normalizes_strings():
    assert not _is_different("  valor ", "valor")
    assert _is_different("valor", "outro")


def test_is_different_respects_numeric_tolerance():
    assert not _is_different(Decimal("10.00"), Decimal("10.005"))
    assert _is_different(10.0, 10.02)


def test_is_different_handles_none_values():
    assert not _is_different(None, None)
    assert _is_different(None, "algo")
    assert _is_different("algo", None)
