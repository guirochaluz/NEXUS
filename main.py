from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from database.db import init_db
from auth.oauth import get_auth_url, exchange_code

app = FastAPI()
init_db()

@app.get("/")
def home():
    url = get_auth_url()
    return HTMLResponse(f'<a href="{url}">Login com Mercado Livre</a>')

@app.get("/callback")
def callback(code: str):
    success = exchange_code(code)
    return {"status": "ok" if success else "erro"}
