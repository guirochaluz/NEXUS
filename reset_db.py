# -*- coding: utf-8 -*-

from db import SessionLocal
from models import Sale

def reset_sales():
    db = SessionLocal()
    try:
        deleted = db.query(Sale).delete()
        db.commit()
        print(f"{deleted} sales deleted successfully.")
    except Exception as e:
        db.rollback()
        print("Error deleting sales:", e)
    finally:
        db.close()

if __name__ == "__main__":
    reset_sales()
