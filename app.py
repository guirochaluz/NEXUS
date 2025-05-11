import streamlit as st
import pandas as pd
import plotly.express as px
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import locale
from datetime import datetime

# ----------------- Carregamento de variáveis -----------------
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL", "https://nexus-backend.onrender.com")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://nexus-frontend.com")
DB_URL = os.getenv("DB_URL", "")

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

# ----------------- Sidebar Retrátil -----------------
def render_sidebar():
    st.sidebar.markdown("<div class='sidebar-title'>Navegação</div>", unsafe_allow_html=True)
    pages = {
        'Dashboard': '📊 Dashboard',
        'Contas Cadastradas': '📑 Contas Cadastradas',
        'Relatórios': '📋 Relatórios'
    }
    selected = st.sidebar.selectbox("Menu", options=list(pages.keys()), format_func=lambda x: pages[x])

    return selected

# ----------------- Autenticação / Login -----------------
def login():
    st.markdown("<h2 style='text-align: center;'>🔐 Login - NEXUS</h2>", unsafe_allow_html=True)
    
    conta = st.text_input("ID da Conta", "")
    senha = st.text_input("Senha", type="password")

    if st.button("Entrar"):
        if not conta or not senha:
            st.error("Por favor, preencha todos os campos.")
        elif senha != "NEXU$2025" or conta != "GRUPONEXUS":
            st.error("Usuário ou senha incorretos.")
        else:
            st.session_state["logado"] = True
            st.session_state["conta"] = conta
            st.experimental_rerun()

# ----------------- Dashboard -----------------
def mostrar_dashboard():
    st.title("📊 Dashboard de Vendas")
    conta = st.session_state.get("conta")

    try:
        df = carregar_vendas(conta)
    except Exception as e:
        st.error(f"Erro ao conectar ao banco: {e}")
        return

    if df.empty:
        st.warning("Nenhuma venda encontrada para essa conta.")
        return

    # KPIs
    total_vendas = len(df)
    total_valor = df["total_amount"].sum()
    total_itens = df["quantity"].sum()
    ticket_medio = total_valor / total_vendas if total_vendas else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧾 Vendas", total_vendas)
    c2.metric("💰 Valor total", locale.currency(total_valor, grouping=True))
    c3.metric("📦 Itens vendidos", int(total_itens))
    c4.metric("🎯 Ticket médio", locale.currency(ticket_medio, grouping=True))

    # Gráficos
    vendas_por_dia = (
        df.groupby(df["date_created"].dt.date)["total_amount"]
        .sum()
        .reset_index()
    )
    st.plotly_chart(
        px.line(vendas_por_dia, x="date_created", y="total_amount", title="💵 Total Vendido por Dia"),
        use_container_width=True
    )

# ----------------- Contas Cadastradas -----------------
def mostrar_contas_cadastradas():
    st.title("📑 Contas Cadastradas")

    # Botão para autenticação no Mercado Livre
    ml_auth_url = f"{BACKEND_URL}/ml-login"
    st.markdown(
        f"""
        <a href='{ml_auth_url}' target='_blank'>
        <button style='background-color:#4CAF50; color:white; border:none; padding:10px; border-radius:5px;'>
        ➕ Adicionar Nova Conta Mercado Livre
        </button></a>
        """,
        unsafe_allow_html=True
    )

    # Carregar contas do banco
    query = text("SELECT ml_user_id, access_token FROM user_tokens")
    try:
        df_contas = pd.read_sql(query, engine)
    except Exception as e:
        st.error(f"Erro ao carregar contas: {e}")
        return

    if df_contas.empty:
        st.warning("Nenhuma conta cadastrada.")
        return

    for index, row in df_contas.iterrows():
        with st.expander(f"🔗 Conta ML: {row['ml_user_id']}"):
            st.write(f"**Access Token:** {row['access_token']}")
            if st.button(f"🔄 Renovar Token - {row['ml_user_id']}"):
                novo_token = renovar_access_token(row['ml_user_id'])
                if novo_token:
                    st.success("Token atualizado com sucesso!")
                else:
                    st.error("Erro ao atualizar o token.")

# ----------------- Carregar Dados com SQL Parametrizado -----------------
@st.cache_data(ttl=300)
def carregar_vendas(conta_id: str) -> pd.DataFrame:
    sql = text("""
        SELECT date_created, item_title, status, quantity, total_amount
          FROM sales
         WHERE ml_user_id = :uid
    """)
    return pd.read_sql(sql, engine, params={"uid": conta_id})

# ----------------- Inicialização -----------------
if "logado" not in st.session_state:
    st.session_state["logado"] = False

if not st.session_state["logado"]:
    login()
else:
    page = render_sidebar()
    if page == "Dashboard":
        mostrar_dashboard()
    elif page == "Contas Cadastradas":
        mostrar_contas_cadastradas()
