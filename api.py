from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from dotenv import load_dotenv
import os

from auth.oauth import get_auth_url, exchange_code, salvar_tokens_no_banco  # mova a função de gravação pro oauth.py ou db.py

load_dotenv()
BACKEND_URL   = os.getenv("BACKEND_URL")
FRONTEND_URL  = os.getenv("FRONTEND_URL")  # onde quiser redirecionar ao final (ex: a raiz do Streamlit)

app = FastAPI()

@app.get("/ml-login")
def ml_login():
    # dispara o OAuth pro ML, com redirect_uri = BACKEND_URL/auth/callback
    return RedirectResponse(get_auth_url())

@app.get("/auth/callback")
def auth_callback(code: str = None):
    if not code:
        raise HTTPException(400, "Código de autorização não recebido")
    try:
        # troca code por tokens e grava no banco de dados
        data = exchange_code(code)  # já retorna {user_id, access_token, refresh_token}
        salvar_tokens_no_banco(data)  # faz o INSERT / UPDATE no seu user_tokens
    except Exception as e:
        raise HTTPException(500, f"Erro durante autenticação: {e}")

    # tudo ok, devolve um HTML simples ou redireciona pro front
    html = """
    <html>
      <body style="font-family:sans-serif; text-align:center; margin-top:3rem;">
        <h2>✅ Conta adicionada com sucesso!</h2>
        <p>Você pode voltar para a sua dashboard.</p>
        <a href="{frontend}">↩ Voltar</a>
      </body>
    </html>
    """.format(frontend=FRONTEND_URL)
    return HTMLResponse(html)
