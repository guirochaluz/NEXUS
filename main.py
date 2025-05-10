import os
import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import locale

# ----------------- Carrega variáveis de ambiente -----------------
load_dotenv()
BACKEND_URL  = os.getenv("BACKEND_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL")
DB_URL       = os.getenv("DB_URL")

if not BACKEND_URL or not DB_URL:
    st.error("❌ Configure BACKEND_URL e DB_URL no seu .env")
    st.stop()

# ----------------- Configuração da Página -----------------
st.set_page_config(
    page_title=f"Dashboard de Vendas - NEXUS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- Carrega CSS externo -----------------
st.markdown('<link rel="stylesheet" href="styles.css">', unsafe_allow_html=True)

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

# ----------------- Função para carregar vendas -----------------
@st.cache_data(ttl=300)
def carregar_vendas(conta_id: str) -> pd.DataFrame:
    sql = text("""
        SELECT date_created, item_title, status, quantity, total_amount
          FROM sales
         WHERE ml_user_id = :uid
    """)
    return pd.read_sql(sql, engine, params={"uid": conta_id})

# ----------------- Estado Inicial -----------------
if "logado" not in st.session_state:
    st.session_state["logado"] = False
    st.session_state["conta"]  = ""

# ----------------- Login -----------------
def login():
    params     = st.experimental_get_query_params()
    registered = params.get("registered", [""])[0]
    if registered:
        st.sidebar.success(f"✅ Cadastro concluído! Use o ID **{registered}**")
    st.sidebar.title("🔐 Login NEXUS")
    conta = st.sidebar.text_input("ID da conta", value=registered)
    senha = st.sidebar.text_input("Senha", type="password")
    if st.sidebar.button("Entrar"):
        if not conta:
            st.sidebar.warning("Preencha o ID.")
        elif senha != "Giguisa*":
            st.sidebar.error("Senha incorreta.")
        else:
            st.session_state["logado"] = True
            st.session_state["conta"]  = conta
            st.experimental_rerun()
    st.sidebar.markdown(
        f'<a href="{BACKEND_URL}/ml-login"><button>Cadastrar com Mercado Livre</button></a>',
        unsafe_allow_html=True
    )
    st.stop()

# ----------------- Logout -----------------
def logout():
    st.session_state.clear()
    st.experimental_rerun()

# ----------------- Dashboard -----------------
def mostrar_dashboard():
    st.sidebar.title("📅 Filtros")
    if st.sidebar.button("🔓 Logout"):
        logout()

    conta = st.session_state["conta"]
    try:
        df = carregar_vendas(conta)
    except Exception as e:
        st.error(f"Erro ao conectar ao banco: {e}")
        return

    if df.empty:
        st.warning("Nenhuma venda encontrada.")
        return

    # ---------- Pré-processamento e Filtros (igual ao app.py) ----------
    df["date_created"] = pd.to_datetime(df["date_created"])
    df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["quantity"]     = pd.to_numeric(df["quantity"], errors="coerce")

    data_ini, data_fim = (
        st.sidebar.date_input("De", df["date_created"].min().date()),
        st.sidebar.date_input("Até", df["date_created"].max().date())
    )
    status = st.sidebar.multiselect("Status", df["status"].unique(), df["status"].unique())
    vmin, vmax = st.sidebar.slider(
        "Valor Total",
        float(df["total_amount"].min()),
        float(df["total_amount"].max()),
        (float(df["total_amount"].min()), float(df["total_amount"].max()))
    )
    qmin, qmax = st.sidebar.slider(
        "Quantidade",
        int(df["quantity"].min()),
        int(df["quantity"].max()),
        (int(df["quantity"].min()), int(df["quantity"].max()))
    )
    busca = st.sidebar.text_input("🔍 Buscar")

    mask = (
        (df["date_created"].dt.date >= data_ini) &
        (df["date_created"].dt.date <= data_fim) &
        (df["status"].isin(status)) &
        (df["total_amount"].between(vmin, vmax)) &
        (df["quantity"].between(qmin, qmax))
    )
    df_filtrado = df[mask]
    if busca:
        df_filtrado = df_filtrado[df_filtrado.apply(lambda r: busca.lower() in str(r).lower(), axis=1)]

    if df_filtrado.empty:
        st.warning("Nenhum resultado após filtros.")
        return

    # ---------- Exibição de KPIs e abas ----------
    total_vendas = len(df_filtrado)
    total_valor  = df_filtrado["total_amount"].sum()
    total_itens  = df_filtrado["quantity"].sum()
    ticket_medio = total_valor / total_vendas if total_vendas else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧾 Vendas", total_vendas)
    c2.metric("💰 Valor total", locale.currency(total_valor, grouping=True))
    c3.metric("📦 Itens vendidos", int(total_itens))
    c4.metric("🎯 Ticket médio", locale.currency(ticket_medio, grouping=True))

    tabs = st.tabs(["📋 Tabela", "📈 Gráficos", "🔍 Insights", "📤 Exportar"])
    # … copie as abas do app.py conforme necessário …

# ----------------- Inicialização -----------------
if not st.session_state["logado"]:
    login()
else:
    mostrar_dashboard()
