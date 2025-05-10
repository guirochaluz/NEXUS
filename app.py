import streamlit as st
import pandas as pd
import plotly.express as px
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import locale

# ----------------- Carregamento de variáveis -----------------
load_dotenv()
BACKEND_URL   = os.getenv("BACKEND_URL", "https://nexus-backend.onrender.com")
FRONTEND_URL  = os.getenv("FRONTEND_URL", "https://nexus-frontend.com")
DB_URL        = os.getenv("DB_URL", "")

# ----------------- Configuração da Página -----------------
st.set_page_config(
    page_title="Dashboard de Vendas - NEXUS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----------------- Estilo Customizado -----------------
st.markdown("""
<style>
  /* Bloqueia scroll e define altura fixa */
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
  #MainMenu, footer { visibility: hidden; }
  .stTabs [role="tablist"] button[role="tab"] { color: #0e76a8 !important; }
  .stButton>button { 
    border-radius: 8px !important; 
    background-color: #0e76a8 !important; 
    color: #fff !important; 
  }
  .stDownloadButton>button { 
    border-radius: 8px !important; 
    background-color: #28a745 !important; 
    color: #fff !important; 
  }
  .stTextInput>div>input { max-width: 300px !important; }
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

# ----------------- Autenticação / Login -----------------
def login():
    # Exibe arte de marketing (se existir)
    art_path = os.path.join(os.path.dirname(__file__), "Captura de tela 2025-05-06 223641.png")
    if os.path.exists(art_path):
        st.image(art_path, use_container_width=True)

    st.sidebar.title("🔐 Login NEXUS")
    conta = st.sidebar.text_input("ID da conta")
    senha = st.sidebar.text_input("Senha", type="password")

    if st.sidebar.button("Entrar"):
        if not conta:
            st.sidebar.warning("Preencha o ID da conta.")
        elif senha != "Giguisa*":  # mantendo a checagem hard-coded por ora
            st.sidebar.error("Senha incorreta.")
        else:
            st.session_state["logado"] = True
            st.session_state["conta"]  = conta
            st.experimental_rerun()

    # Botão de cadastro
    registration_url = f"{BACKEND_URL}/register?redirect_url={FRONTEND_URL}"
    st.sidebar.markdown(
        f'''
        <a href="{registration_url}" target="_blank">
          <button style="
            width:100%; padding:8px; margin-top:10px;
            background-color:#ffa500; color:#fff;
            border:none; border-radius:5px;
          ">
            Cadastrar
          </button>
        </a>''',
        unsafe_allow_html=True
    )

# ----------------- Logout -----------------
def logout():
    st.session_state.pop("logado", None)
    st.session_state.pop("conta", None)
    st.experimental_rerun()

# ----------------- Carregar Dados com SQL Parametrizado -----------------
@st.cache_data(ttl=300)
def carregar_vendas(conta_id: str) -> pd.DataFrame:
    sql = text("""
        SELECT date_created, item_title, status, quantity, total_amount
          FROM sales
         WHERE ml_user_id = :uid
    """)
    return pd.read_sql(sql, engine, params={"uid": conta_id})

# ----------------- Dashboard -----------------
def mostrar_dashboard():
    st.sidebar.title("📅 Filtros")
    st.sidebar.button("🔓 Logout", on_click=logout)
    conta = st.session_state.get("conta")

    try:
        df = carregar_vendas(conta)
    except Exception as e:
        st.error(f"Erro ao conectar ao banco: {e}")
        return

    if df.empty:
        st.warning("Nenhuma venda encontrada para essa conta.")
        return

    # Pré-processamento
    df["date_created"] = pd.to_datetime(df["date_created"])
    df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce")
    df["quantity"]     = pd.to_numeric(df["quantity"], errors="coerce")

    # Filtros
    data_ini = st.sidebar.date_input("De",   df["date_created"].min().date())
    data_fim = st.sidebar.date_input("Até",  df["date_created"].max().date())
    status   = st.sidebar.multiselect("Status", df["status"].unique(), df["status"].unique())
    valor_min, valor_max = st.sidebar.slider(
        "Valor Total por Venda",
        float(df["total_amount"].min()),
        float(df["total_amount"].max()),
        (float(df["total_amount"].min()), float(df["total_amount"].max()))
    )
    qtd_min, qtd_max = st.sidebar.slider(
        "Quantidade por Venda",
        int(df["quantity"].min()),
        int(df["quantity"].max()),
        (int(df["quantity"].min()), int(df["quantity"].max()))
    )
    busca = st.sidebar.text_input("🔍 Buscar (produto, comprador etc)")

    df_filtrado = df[
        (df["date_created"].dt.date >= data_ini) &
        (df["date_created"].dt.date <= data_fim) &
        (df["status"].isin(status)) &
        (df["total_amount"].between(valor_min, valor_max)) &
        (df["quantity"].between(qtd_min, qtd_max))
    ]
    if busca:
        df_filtrado = df_filtrado[df_filtrado.apply(lambda r: busca.lower() in str(r).lower(), axis=1)]

    if df_filtrado.empty:
        st.warning("Nenhum registro após aplicar filtros.")
        return

    # KPIs
    total_vendas = len(df_filtrado)
    total_valor  = df_filtrado["total_amount"].sum()
    total_itens  = df_filtrado["quantity"].sum()
    ticket_medio = total_valor / total_vendas if total_vendas else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧾 Vendas",          total_vendas)
    c2.metric("💰 Valor total",     locale.currency(total_valor, grouping=True))
    c3.metric("📦 Itens vendidos",   int(total_itens))
    c4.metric("🎯 Ticket médio",     locale.currency(ticket_medio, grouping=True))

    # Abas de visualização
    tabs = st.tabs(["📋 Tabela", "📈 Gráficos", "🔍 Insights", "📤 Exportar"])

    with tabs[0]:
        st.markdown("### 📄 Detalhamento das Vendas")
        st.dataframe(
            df_filtrado[["date_created","item_title","status","quantity","total_amount"]],
            use_container_width=True
        )

    with tabs[1]:
        vendas_por_dia = (
            df_filtrado
            .groupby(df_filtrado["date_created"].dt.date)["total_amount"]
            .sum()
            .reset_index()
        )
        st.plotly_chart(
            px.line(vendas_por_dia, x="date_created", y="total_amount",
                    title="💵 Total Vendido por Dia", markers=True),
            use_container_width=True
        )
        status_count = (
            df_filtrado["status"]
            .value_counts()
            .rename_axis("status")
            .reset_index(name="count")
        )
        st.plotly_chart(
            px.pie(status_count, names="status", values="count", title="🧾 Distribuição por Status"),
            use_container_width=True
        )
        # ... (outros gráficos conforme seu original) ...

    with tabs[2]:
        st.write("Insights avançados em desenvolvimento…")

    with tabs[3]:
        csv_bytes = df_filtrado.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Baixar CSV",
            data=csv_bytes,
            file_name="vendas_filtradas.csv",
            mime="text/csv"
        )

# ----------------- Inicialização -----------------
if "logado" not in st.session_state:
    st.session_state["logado"] = False
    st.session_state["conta"]  = ""

if st.session_state["logado"]:
    mostrar_dashboard()
else:
    login()
