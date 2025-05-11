import os
import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import locale
from datetime import datetime

from oauth import get_auth_url

# ----------------- Carregamento de variáveis -----------------
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL")
DB_URL = os.getenv("DB_URL")

if not BACKEND_URL or not FRONTEND_URL or not DB_URL:
    st.error("❌ Configure BACKEND_URL, FRONTEND_URL e DB_URL no seu .env")
    st.stop()

# ----------------- Configuração da Página -----------------
st.set_page_config(
    page_title="Dashboard de Vendas - NEXUS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ----------------- Estilo Customizado -----------------
st.markdown("""
<style>
  html, body, [data-testid=\"stAppViewContainer\"] {
    overflow: hidden !important;
    height: 100vh !important;
  }
  ::-webkit-scrollbar { display: none; }
  [data-testid=\"stSidebar\"] {
    background-color: #161b22;
    overflow: hidden !important;
    height: 100vh !important;
  }
  [data-testid=\"stAppViewContainer\"] {
    background-color: #0e1117;
    color: #fff;
  }
  .sidebar-title {
    font-size: 18px;
    font-weight: bold;
    color: #ffffff;
    margin-bottom: 10px;
  }
  .menu-item {
    padding: 10px;
    color: #ffffff;
    border-radius: 5px;
    margin-bottom: 5px;
    cursor: pointer;
  }
  .menu-item:hover {
    background-color: #1d2b36;
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

# ----------------- Funções Auxiliares -----------------
def ml_callback():
    params = st.query_params
    code = params.get('code', [None])[0]
    if not code:
        st.error("⚠️ Código de autorização não encontrado.")
        return

    st.success("✅ Código recebido. Processando autenticação...")
    resp = requests.post(f"{BACKEND_URL}/auth/callback", json={"code": code})
    if resp.status_code == 200:
        st.success("✅ Autenticação realizada com sucesso!")
        st.set_query_params()
        st.experimental_rerun()
    else:
        st.error(f"❌ Erro na autenticação: {resp.text}")

@st.cache_data(ttl=300)
def carregar_vendas(conta_id: str) -> pd.DataFrame:
    sql_query = text("""
        SELECT date_created, item_title, status, quantity, total_amount
          FROM sales
         WHERE ml_user_id = :uid
    """)
    df = pd.read_sql(sql_query, engine, params={"uid": conta_id})
    df["date_created"] = pd.to_datetime(df["date_created"])
    return df


def render_add_account_button():
    auth_url = get_auth_url()
    st.markdown(f"""
        <a href=\"{auth_url}\" target=\"_blank\">
          <button style=\"background-color:#4CAF50;color:white;border:none;padding:10px;border-radius:5px;margin-bottom:10px;\">➕ Adicionar Nova Conta Mercado Livre</button>
        </a>
    """, unsafe_allow_html=True)


def login():
    st.markdown("<h2 style='text-align: center;'>🔐 Login - NEXUS</h2>", unsafe_allow_html=True)
    conta = st.text_input("ID da Conta", "")
    senha = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if not conta or not senha:
            st.error("Por favor, preencha todos os campos.")
        elif conta != "GRUPONEXUS" or senha != "NEXU$2025":
            st.error("Usuário ou senha incorretos.")
        else:
            st.session_state["logado"] = True
            st.session_state["conta"] = conta
            st.experimental_rerun()


def renovar_access_token(ml_user_id: str) -> bool:
    resp = requests.post(f"{BACKEND_URL}/auth/refresh", json={"user_id": ml_user_id})
    if resp.ok:
        return True
    return False


def mostrar_dashboard():
    st.title("📊 Dashboard de Vendas")
    conta = st.session_state.get("conta")
    if not conta:
        st.warning("Nenhuma conta selecionada.")
        return
    try:
        df = carregar_vendas(conta)
    except Exception as e:
        st.error(f"Erro ao conectar ao banco: {e}")
        return
    if df.empty:
        st.warning("Nenhuma venda encontrada para essa conta.")
        return

    total_vendas = len(df)
    total_valor = df["total_amount"].sum()
    total_itens = df["quantity"].sum()
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
    try:
        df_contas = pd.read_sql(text("SELECT ml_user_id, access_token FROM user_tokens"), engine)
    except Exception as e:
        st.error(f"Erro ao carregar contas: {e}")
        return
    if df_contas.empty:
        st.warning("Nenhuma conta cadastrada.")
        return
    for row in df_contas.itertuples(index=False):
        with st.expander(f"🔗 Conta ML: {row.ml_user_id}"):
            st.write(f"**Access Token:** {row.access_token}")
            if st.button("🔄 Renovar Token", key=f"renew_{row.ml_user_id}"):
                if renovar_access_token(row.ml_user_id):
                    st.success("Token atualizado com sucesso!")
                else:
                    st.error("Erro ao atualizar o token.")
    render_add_account_button()


def mostrar_relatorios():
    st.title("📋 Relatórios de Vendas")
    conta = st.session_state.get("conta")
    if not conta:
        st.warning("Nenhuma conta selecionada.")
        return
    try:
        df = carregar_vendas(conta)
    except Exception as e:
        st.error(f"Erro ao conectar ao banco: {e}")
        return
    if df.empty:
        st.warning("Nenhuma venda encontrada para essa conta.")
        return

    data_ini = st.date_input("De:", value=df["date_created"].min())
    data_fim = st.date_input("Até:", value=df["date_created"].max())
    status = st.multiselect("Status:", options=df["status"].unique(), default=df["status"].unique())

    filt = (
        (df["date_created"] >= pd.to_datetime(data_ini)) &
        (df["date_created"] <= pd.to_datetime(data_fim)) &
        (df["status"].isin(status))
    )
    df_filtrado = df.loc[filt]

    if df_filtrado.empty:
        st.warning("Nenhum dado encontrado para os filtros aplicados.")
    else:
        st.dataframe(df_filtrado)


def render_sidebar():
    st.sidebar.markdown("<div class='sidebar-title'>Navega
