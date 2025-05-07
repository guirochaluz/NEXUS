import streamlit as st
import pandas as pd
import plotly.express as px
import os
from sqlalchemy import create_engine
from dotenv import load_dotenv
import locale

# ----------------- Configuração da Página -----------------
st.set_page_config(
    page_title="Dashboard de Vendas - ContaZoom",
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
  [data-testid="stSidebar"] { background-color: #161b22; overflow: hidden !important; height: 100vh !important; }
  [data-testid="stAppViewContainer"] { background-color: #0e1117; color: #fff; }
  #MainMenu, footer { visibility: hidden; }
  .stTabs [role="tablist"] button[role="tab"] { color: #0e76a8 !important; }
  .stButton>button { border-radius: 8px !important; background-color: #0e76a8 !important; color: #fff !important; }
  .stDownloadButton>button { border-radius: 8px !important; background-color: #28a745 !important; color: #fff !important; }
  .stTextInput>div>input { max-width: 300px !important; }
</style>
""", unsafe_allow_html=True)

# ----------------- Carregamento de Variáveis -----------------
load_dotenv()
DB_URL = os.getenv("DB_URL")
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

# ----------------- Autenticação & Marketing -----------------
def login():
    # Exibe arte de marketing
    art_path = os.path.join(os.path.dirname(__file__), "Captura de tela 2025-05-06 223641.png")
    if os.path.exists(art_path):
        st.image(art_path, use_container_width=True)

    # Formulário de login
    st.sidebar.title("🔐 Login ContaZoom")
    conta = st.sidebar.text_input("ID da conta")
    senha = st.sidebar.text_input("Senha", type="password")
    if st.sidebar.button("Entrar"):
        if not conta:
            st.sidebar.warning("Preencha o ID da conta.")
        elif senha != "Giguisa*":
            st.sidebar.error("Senha incorreta.")
        else:
            st.session_state["logado"] = True
            st.session_state["conta"] = conta
            st.experimental_rerun()

    # Botão de cadastro com redirecionamento de volta
    registration_url = (
        "https://contazoom-api.onrender.com/register?"
        "redirect_url=https://contazoom.com"
    )
    st.sidebar.markdown(
        f'<a href="{registration_url}" target="_blank">'
        '<button style="width:100%; padding:8px; margin-top:10px; '
        'background-color:#ffa500; color:#fff; border:none; border-radius:5px;">'
        'Cadastrar</button></a>',
        unsafe_allow_html=True
    )

# ----------------- Logout -----------------
def logout():
    st.session_state.pop("logado", None)
    st.session_state.pop("conta", None)
    st.experimental_rerun()

# ----------------- Carregar Dados -----------------
@st.cache_data(ttl=300)
def carregar_vendas(conta_id: str) -> pd.DataFrame:
    query = f"SELECT * FROM sales WHERE ml_user_id = '{conta_id}'"
    return pd.read_sql(query, engine)

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
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")

    # Filtros no sidebar
    data_ini = st.sidebar.date_input("De", df["date_created"].min().date())
    data_fim = st.sidebar.date_input("Até", df["date_created"].max().date())
    status = st.sidebar.multiselect("Status", df["status"].unique(), df["status"].unique())
    # Slider para valor total por venda
    valor_min, valor_max = st.sidebar.slider(
        "Valor Total por Venda",
        float(df["total_amount"].min()),
        float(df["total_amount"].max()),
        (float(df["total_amount"].min()), float(df["total_amount"].max()))
    )
    # Slider para quantidade por venda
    qtd_min, qtd_max = st.sidebar.slider(
        "Quantidade por Venda",
        int(df["quantity"].min()),
        int(df["quantity"].max()),
        (int(df["quantity"].min()), int(df["quantity"].max()))
    )
    busca = st.sidebar.text_input("🔍 Buscar (produto, comprador etc)")

    # Aplicar filtros
    df_filtrado = df[
        (df["date_created"].dt.date >= data_ini) &
        (df["date_created"].dt.date <= data_fim) &
        (df["status"].isin(status)) &
        (df["total_amount"] >= valor_min) &
        (df["total_amount"] <= valor_max) &
        (df["quantity"] >= qtd_min) &
        (df["quantity"] <= qtd_max)
    ]
    if busca:
        df_filtrado = df_filtrado[df_filtrado.apply(lambda row: busca.lower() in str(row).lower(), axis=1)]

    if df_filtrado.empty:
        st.warning("Nenhum registro após aplicar filtros.")
        return

    # KPIs
    total_vendas = len(df_filtrado)
    total_valor = df_filtrado["total_amount"].sum()
    total_itens = df_filtrado["quantity"].sum()
    ticket_medio = total_valor / total_vendas if total_vendas else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧾 Vendas", total_vendas)
    c2.metric("💰 Valor total", locale.currency(total_valor, grouping=True))
    c3.metric("📦 Itens vendidos", int(total_itens))
    c4.metric("🎯 Ticket médio", locale.currency(ticket_medio, grouping=True))

    # Abas de visualização
    tabs = st.tabs(["📋 Tabela", "📈 Gráficos", "🔍 Insights", "📤 Exportar"])

    # Aba 1: Tabela filtrada
    with tabs[0]:
        st.markdown("### 📄 Detalhamento das Vendas")
        cols = ["date_created", "item_title", "status", "quantity", "total_amount"]
        df_principal = df_filtrado[cols].reset_index(drop=True)
        st.dataframe(df_principal, use_container_width=True)

    # Aba 2: Gráficos básicos
    with tabs[1]:
        vendas_por_dia = df_filtrado.groupby(df_filtrado["date_created"].dt.date)["total_amount"].sum().reset_index()
        fig1 = px.line(vendas_por_dia, x="date_created", y="total_amount", title="💵 Total Vendido por Dia", markers=True)
        st.plotly_chart(fig1, use_container_width=True)

        status_count = df_filtrado["status"].value_counts().rename_axis("status").reset_index(name="count")
        fig2 = px.pie(status_count, names="status", values="count", title="🧾 Distribuição por Status")
        st.plotly_chart(fig2, use_container_width=True)

        top_produtos = df_filtrado.groupby("item_title")["quantity"].sum().nlargest(10).reset_index()
        fig3 = px.bar(top_produtos, x="quantity", y="item_title", orientation="h", title="🏆 Top 10 Produtos")
        st.plotly_chart(fig3, use_container_width=True)

        acumulado = vendas_por_dia.copy()
        acumulado["Acumulado"] = acumulado["total_amount"].cumsum()
        fig4 = px.area(acumulado, x="date_created", y="Acumulado", title="📈 Acumulado de Vendas")
        st.plotly_chart(fig4, use_container_width=True)

    # Aba 3: Insights Avançados
    with tabs[2]:
        weekday_map = {0:'Segunda',1:'Terça',2:'Quarta',3:'Quinta',4:'Sexta',5:'Sábado',6:'Domingo'}
        df_filtrado['weekday'] = df_filtrado['date_created'].dt.weekday.map(weekday_map)
        vendas_semana = df_filtrado.groupby('weekday')['total_amount'].sum().reindex(
            ['Segunda','Terça','Quarta','Quinta','Sexta','Sábado','Domingo']
        ).reset_index()
        fig5 = px.bar(vendas_semana, x='weekday', y='total_amount', title='🗓️ Vendas por Dia da Semana')
        st.plotly_chart(fig5, use_container_width=True)

        df_filtrado['hour'] = df_filtrado['date_created'].dt.hour
        vendas_hora = df_filtrado.groupby('hour')['total_amount'].sum().reset_index()
        fig6 = px.line(vendas_hora, x='hour', y='total_amount', title='⏰ Vendas por Hora do Dia', markers=True)
        st.plotly_chart(fig6, use_container_width=True)

        rolling = vendas_por_dia.copy()
        rolling['7d_ma'] = rolling['total_amount'].rolling(window=7).mean()
        fig7 = px.line(rolling, x='date_created', y='7d_ma', title='📊 Média Móvel 7 Dias')
        st.plotly_chart(fig7, use_container_width=True)

        df_filtrado['ticket'] = df_filtrado['total_amount'] / df_filtrado['quantity']
        fig8 = px.histogram(df_filtrado, x='ticket', nbins=30, title='📈 Distribuição de Ticket Médio')
        st.plotly_chart(fig8, use_container_width=True)

    # Aba 4: Exportar
    with tabs[3]:
        st.markdown("### 📤 Exportar Vendas")
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
    st.session_state["conta"] = ""

if st.session_state["logado"]:
    mostrar_dashboard()
else:
    login()
