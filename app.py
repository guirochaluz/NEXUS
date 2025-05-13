import os
import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import locale

# ----------------- Configuração da Página (MUST be first!) -----------------
st.set_page_config(
    page_title="Dashboard de Vendas - NEXUS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ----------------- Estado Inicial -----------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "page" not in st.session_state:
    st.session_state["page"] = "Dashboard"

# ----------------- Bloco de Autenticação -----------------
# Lê query params
params = st.query_params

# Login automático via ?nexus_auth=success
if params.get("nexus_auth", [None])[0] == "success":
    st.session_state["authenticated"] = True
    # Limpa o param para não ficar preso nisso
    st.experimental_set_query_params()

if not st.session_state["authenticated"]:
    # Título na tela de login
    st.title("Sistema de Gestão - Grupo Nexus")
    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if username == "GRUPONEXUS" and password == "NEXU$2025":
            st.session_state["authenticated"] = True
            st.experimental_rerun()
        else:
            st.error("Credenciais inválidas")
    st.stop()

# ----------------- Título Principal -----------------
st.title("Nexus Dashboard")

# ----------------- Carregamento de variáveis -----------------
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL")
DB_URL       = os.getenv("DB_URL")
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID")

if not all([BACKEND_URL, FRONTEND_URL, DB_URL, ML_CLIENT_ID]):
    st.error("❌ Defina BACKEND_URL, FRONTEND_URL, DB_URL e ML_CLIENT_ID em seu .env")
    st.stop()

# ----------------- CSS Customizado -----------------
st.markdown("""
<style>
  html, body, [data-testid="stAppViewContainer"] {
    overflow: hidden !important;
    height: 100vh !important;
  }
  ::-webkit-scrollbar { display: none; }
  [data-testid="stSidebar"] {
    background-color: #161b22;
    overflow: hidden !important;
    height: 100vh !important;
  }
  [data-testid="stAppViewContainer"] {
    background-color: #0e1117;
    color: #fff;
  }
  .sidebar-title {
    font-size: 18px;
    font-weight: bold;
    color: #ffffff;
    margin-bottom: 10px;
  }
  .menu-button {
    width: 100%;
    padding: 10px;
    margin-bottom: 5px;
    background-color: #1d2b36;
    color: #fff;
    border: none;
    border-radius: 5px;
    text-align: left;
    cursor: pointer;
  }
  .menu-button:hover {
    background-color: #273947;
  }
</style>
""", unsafe_allow_html=True)

# ----------------- Conexão ao Banco -----------------
engine = create_engine(
    DB_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30
)

# ----------------- Locale para Moeda -----------------
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except locale.Error:
    pass

# ----------------- Helpers de OAuth -----------------
def ml_callback():
    """Trata o callback OAuth—envia o code ao backend e limpa params."""
    code = st.query_params.get("code", [None])[0]
    if not code:
        st.error("⚠️ Código de autorização não encontrado.")
        return
    st.success("✅ Código recebido. Processando autenticação...")
    resp = requests.post(f"{BACKEND_URL}/auth/callback", json={"code": code})
    if resp.ok:
        st.success("✅ Conta ML autenticada com sucesso!")
        # Limpa o código da URL
        st.experimental_set_query_params()
        st.experimental_rerun()
    else:
        st.error(f"❌ Falha na autenticação: {resp.text}")

# ----------------- Persistência de Tokens -----------------
def salvar_tokens_no_banco(data: dict):
    try:
        with engine.connect() as conn:
            query = text("""
                INSERT INTO user_tokens (ml_user_id, access_token, refresh_token, expires_at)
                VALUES (:user_id, :access_token, :refresh_token, NOW() + interval '6 hours')
                ON CONFLICT (ml_user_id) DO UPDATE
                  SET access_token = EXCLUDED.access_token,
                      refresh_token = EXCLUDED.refresh_token,
                      expires_at   = NOW() + interval '6 hours';
            """")
            conn.execute(query, {
                "user_id":       data["user_id"],
                "access_token":  data["access_token"],
                "refresh_token": data["refresh_token"],
            })
    except Exception as e:
        st.error(f"❌ Erro ao salvar tokens no banco: {e}")

# ----------------- Carregamento de Vendas -----------------
@st.cache_data(ttl=300)
def carregar_vendas(conta_id: str) -> pd.DataFrame:
    sql = text("""
        SELECT date_created, item_title, status, quantity, total_amount
          FROM sales
         WHERE ml_user_id = :uid
    """")
    df = pd.read_sql(sql, engine, params={"uid": conta_id})
    df["date_created"] = pd.to_datetime(df["date_created"])
    return df

# ----------------- Componentes de Interface -----------------
def render_add_account_button():
    backend_login = f"{BACKEND_URL}/ml-login"
    st.markdown(f"""
      <a href="{backend_login}" target="_blank">
        <button style="
          background-color:#4CAF50;
          color:white;
          border:none;
          padding:10px;
          border-radius:5px;
          margin-bottom:10px;
        ">
          ➕ Adicionar Conta Mercado Livre
        </button>
      </a>
    """, unsafe_allow_html=True)

# ----------------- Sidebar de Navegação -----------------
def render_sidebar() -> str:
    st.sidebar.markdown("<div class='sidebar-title'>Navegação</div>", unsafe_allow_html=True)
    # Botões fixos em vez de dropdown
    if st.sidebar.button("Dashboard", key="btn_dashboard"):
        st.session_state["page"] = "Dashboard"
    if st.sidebar.button("Contas Cadastradas", key="btn_contas"):
        st.session_state["page"] = "Contas Cadastradas"
    if st.sidebar.button("Relatórios", key="btn_relatorios"):
        st.session_state["page"] = "Relatórios"
    if st.sidebar.button("Expedição e Logística", key="btn_expedicao"):
        st.session_state["page"] = "Expedição e Logística"
    return st.session_state["page"]

# ----------------- Telas -----------------
def mostrar_dashboard():
    st.title("📊 Dashboard de Vendas")
    conta = st.query_params.get("account", [None])[0] or st.session_state.get("conta")
    df = carregar_vendas(conta)
    if df.empty:
        st.warning("Nenhuma venda encontrada para essa conta.")
        return

    total_vendas = len(df)
    total_valor  = df["total_amount"].sum()
    total_itens  = df["quantity"].sum()
    ticket_medio = total_valor / total_vendas if total_vendas else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧾 Vendas", total_vendas)
    c2.metric("💰 Valor total", locale.currency(total_valor, grouping=True))
    c3.metric("📦 Itens vendidos", int(total_itens))
    c4.metric("🎯 Ticket médio", locale.currency(ticket_medio, grouping=True))

    vendas_por_dia = (
        df.groupby(df["date_created"].dt.date)["total_amount"]
          .sum()
          .reset_index(name="total_amount")
    )
    st.plotly_chart(
        px.line(vendas_por_dia, x="date_created", y="total_amount", title="💵 Total Vendido por Dia"),
        use_container_width=True
    )

def mostrar_contas_cadastradas():
    st.title("📑 Contas Cadastradas")
    render_add_account_button()
    df = pd.read_sql(text("SELECT ml_user_id, access_token FROM user_tokens"), engine)
    if df.empty:
        st.warning("Nenhuma conta cadastrada.")
        return

    for row in df.itertuples(index=False):
        with st.expander(f"🔗 Conta ML: {row.ml_user_id}"):
            st.write(f"**Access Token:** {row.access_token}")
            if st.button("🔄 Renovar Token", key=f"renew_{row.ml_user_id}"):
                resp = requests.post(f"{BACKEND_URL}/auth/refresh", json={"user_id": row.ml_user_id})
                if resp.ok:
                    data = resp.json()
                    salvar_tokens_no_banco(data)
                    st.success("Token atualizado com sucesso!")
                else:
                    st.error("Erro ao atualizar o token.")

def mostrar_relatorios():
    st.title("📋 Relatórios de Vendas")
    conta = st.session_state.get("conta")
    df = carregar_vendas(conta)
    if df.empty:
        st.warning("Nenhum dado para exibir.")
        return

    data_ini = st.date_input("De:",  value=df["date_created"].min())
    data_fim = st.date_input("Até:", value=df["date_created"].max())
    status  = st.multiselect("Status:", options=df["status"].unique(), default=df["status"].unique())

    df_filt = df.loc[
        (df["date_created"].dt.date >= data_ini) &
        (df["date_created"].dt.date <= data_fim) &
        (df["status"].isin(status))
    ]
    if df_filt.empty:
        st.warning("Sem registros para os filtros escolhidos.")
    else:
        st.dataframe(df_filt)

def mostrar_expedicao_logistica():
    st.title("🚚 Expedição e Logística")
    st.write("" )  # Página vazia por enquanto

# ----------------- Fluxo Principal -----------------
# 1) Callback OAuth ML?
if "code" in st.query_params:
    ml_callback()

# 2) Renderiza sidebar e pega página selecionada
pagina = render_sidebar()

# 3) Navega entre páginas
if pagina == "Dashboard":
    mostrar_dashboard()
elif pagina == "Contas Cadastradas":
    mostrar_contas_cadastradas()
elif pagina == "Relatórios":
    mostrar_relatorios()
elif pagina == "Expedição e Logística":
    mostrar_expedicao_logistica()
