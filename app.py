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
    page_title="Sistema de Gestão - Grupo Nexus",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------- Autenticação -----------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# lê query params
params = st.query_params

# login automático via ?nexus_auth=success
if params.get("nexus_auth", [None])[0] == "success":
    st.session_state["authenticated"] = True
    st.experimental_set_query_params()  # limpa nexus_auth

# callback OAuth Mercado Livre
def ml_callback():
    code = st.query_params.get("code", [None])[0]
    if not code:
        st.error("⚠️ Código de autorização não encontrado.")
        return
    st.success("✅ Código recebido. Processando autenticação...")
    resp = requests.post(f"{BACKEND_URL}/auth/callback", json={"code": code})
    if resp.ok:
        st.success("✅ Conta ML autenticada com sucesso!")
        st.experimental_set_query_params()  # limpa code
        st.experimental_rerun()
    else:
        st.error(f"❌ Falha na autenticação: {resp.text}")

if "code" in st.query_params:
    # BACKEND_URL precisa estar definido antes de chamar ml_callback()
    load_dotenv()
    BACKEND_URL = os.getenv("BACKEND_URL")
    ml_callback()

if not st.session_state["authenticated"]:
    st.title("🔐 Sistema de Gestão - Grupo Nexus", anchor=None)
    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if username == "GRUPONEXUS" and password == "NEXU$2025":
            st.session_state["authenticated"] = True
            st.experimental_rerun()
        else:
            st.error("Credenciais inválidas")
    st.stop()

# ----------------- Carregamento de variáveis -----------------
load_dotenv()
BACKEND_URL   = os.getenv("BACKEND_URL")
FRONTEND_URL  = os.getenv("FRONTEND_URL")
DB_URL        = os.getenv("DB_URL")
ML_CLIENT_ID  = os.getenv("ML_CLIENT_ID")

if not all([BACKEND_URL, FRONTEND_URL, DB_URL, ML_CLIENT_ID]):
    st.error("❌ Defina BACKEND_URL, FRONTEND_URL, DB_URL e ML_CLIENT_ID em seu .env")
    st.stop()

# ----------------- CSS Customizado -----------------
st.markdown("""
<style>
  /* Sidebar */
  [data-testid="stSidebar"] {
    background-color: #111b21;
    padding: 1rem;
  }
  [data-testid="stSidebar"] .menu-item {
    display: block;
    padding: 12px 16px;
    margin: 4px 0;
    color: #c8c8c8;
    text-decoration: none;
    border-left: 4px solid transparent;
    border-radius: 0 4px 4px 0;
    font-weight: 500;
  }
  [data-testid="stSidebar"] .menu-item:hover {
    background-color: #1f2a33;
    color: #ffffff;
  }
  [data-testid="stSidebar"] .menu-item.active {
    background-color: #16212b;
    color: #1abc9c;
    border-left-color: #1abc9c;
  }

  /* Main area */
  [data-testid="stAppViewContainer"] {
    background-color: #0e1117;
    color: #fff;
    padding: 1.5rem;
  }
  /* Headings */
  h1, h2, h3, h4, h5, h6 {
    color: #ffffff;
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
def render_add_account_button():
    backend_login = f"{BACKEND_URL}/ml-login"
    st.markdown(f"""
      <a href="{backend_login}" target="_blank">
        <button style="
          background-color:#1abc9c;
          color:white;
          border:none;
          padding:8px 16px;
          border-radius:4px;
          margin-bottom:10px;
          font-weight:500;
        ">
          ➕ Adicionar Conta Mercado Livre
        </button>
      </a>
    """, unsafe_allow_html=True)

@st.cache_data(ttl=300)
def carregar_vendas(conta_id: str) -> pd.DataFrame:
    sql = text("""
        SELECT date_created, item_title, status, quantity, total_amount
          FROM sales
         WHERE ml_user_id = :uid
    """)
    df = pd.read_sql(sql, engine, params={"uid": conta_id})
    df["date_created"] = pd.to_datetime(df["date_created"])
    return df

# ----------------- Telas -----------------
def mostrar_dashboard():
    st.header("📊 Dashboard de Vendas")
    conta = st.query_params.get("page_account", [None])[0] or st.session_state.get("conta")
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
    st.header("📑 Contas Cadastradas")
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
                    with engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE user_tokens
                               SET access_token = :access_token,
                                   refresh_token = :refresh_token,
                                   expires_at   = NOW() + interval '6 hours'
                             WHERE ml_user_id = :user_id
                        """), {
                            "user_id":       data["user_id"],
                            "access_token":  data["access_token"],
                            "refresh_token": data["refresh_token"],
                        })
                    st.success("Token atualizado com sucesso!")
                else:
                    st.error("Erro ao atualizar o token.")

def mostrar_relatorios():
    st.header("📋 Relatórios de Vendas")
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
        st.dataframe(df_filt, use_container_width=True)

def mostrar_expedicao_logistica():
    st.header("🚚 Expedição e Logística")
    st.info("Em breve...")

# ----------------- Navegação via Sidebar HTML -----------------
pages = ["Dashboard", "Contas Cadastradas", "Relatórios", "Expedição e Logística"]
current = st.query_params.get("page", [pages[0]])[0]
if current not in pages:
    current = pages[0]

for pg in pages:
    if pg == current:
        st.sidebar.markdown(f'<div class="menu-item active">{pg}</div>', unsafe_allow_html=True)
    else:
        st.sidebar.markdown(f'<a href="?page={pg}" class="menu-item">{pg}</a>', unsafe_allow_html=True)

# ----------------- Renderiza a página selecionada -----------------
if current == "Dashboard":
    mostrar_dashboard()
elif current == "Contas Cadastradas":
    mostrar_contas_cadastradas()
elif current == "Relatórios":
    mostrar_relatorios()
elif current == "Expedição e Logística":
    mostrar_expedicao_logistica()
