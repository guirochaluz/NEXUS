import os
import warnings

# 1) Suprime todos os DeprecationWarning do Python
os.environ["PYTHONWARNINGS"] = "ignore::DeprecationWarning"
warnings.filterwarnings("ignore", category=DeprecationWarning)

# 2) (Opcional) Suprime warnings internos do Streamlit
import logging
logging.getLogger("streamlit").setLevel(logging.ERROR)


from dotenv import load_dotenv
import locale

# 1) Carrega .env antes de tudo
load_dotenv()
COOKIE_SECRET = os.getenv("COOKIE_SECRET")
BACKEND_URL    = os.getenv("BACKEND_URL")
FRONTEND_URL   = os.getenv("FRONTEND_URL")
DB_URL         = os.getenv("DB_URL")
ML_CLIENT_ID   = os.getenv("ML_CLIENT_ID")

# 2) Agora sim importe o Streamlit e configure a página _antes_ de qualquer outra chamada st.*
import streamlit as st
st.set_page_config(
    page_title="Sistema de Gestão - NEXUS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 3) Depois de set_page_config, importe tudo o mais que precisar
from streamlit_cookies_manager import EncryptedCookieManager
import pandas as pd
import plotly.express as px
import requests
from sqlalchemy import create_engine, text
from streamlit_option_menu import option_menu
from typing import Optional
from sales import sync_all_accounts
import matplotlib.pyplot as plt
from wordcloud import WordCloud
import altair as alt
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from textblob import TextBlob


# 4) Configuração de locale
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
    LOCALE_OK = True
except locale.Error:
    LOCALE_OK = False

def format_currency(valor: float) -> str:
    # ...
    ...

# 5) Validações iniciais de ambiente
if not COOKIE_SECRET:
    st.error("⚠️ Defina COOKIE_SECRET no seu .env")
    st.stop()

if not all([BACKEND_URL, FRONTEND_URL, DB_URL, ML_CLIENT_ID]):
    st.error("❌ Defina BACKEND_URL, FRONTEND_URL, DB_URL e ML_CLIENT_ID em seu .env")
    st.stop()

# 6) Gerenciador de cookies e autenticação
cookies = EncryptedCookieManager(prefix="nexus/", password=COOKIE_SECRET)
if not cookies.ready():
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if cookies.get("access_token"):
    st.session_state["authenticated"] = True
    st.session_state["access_token"] = cookies["access_token"]

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
    padding: 8px;
    margin-bottom: 5px;
    background-color: #1d2b36;
    color: #fff;
    border: none;
    border-radius: 5px;
    text-align: left;
    cursor: pointer;
  }
  .menu-button:hover {
    background-color: #263445;
  }
</style>
""", unsafe_allow_html=True)

# ----------------- Banco de Dados -----------------
engine = create_engine(
    DB_URL,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30
)

# ----------------- OAuth Callback -----------------
def ml_callback():
    """Trata o callback OAuth — envia o code ao backend, salva tokens e redireciona."""
    code = st.query_params.get("code", [None])[0]
    if not code:
        st.error("⚠️ Código de autorização não encontrado.")
        return
    st.success("✅ Código recebido. Processando autenticação...")
    resp = requests.post(f"{BACKEND_URL}/auth/callback", json={"code": code})
    if resp.ok:
        data = resp.json()                   # {"user_id": "...", ...}
        salvar_tokens_no_banco(data)
        st.cache_data.clear()             # limpa cache para puxar vendas novas
        st.experimental_set_query_params(account=data["user_id"])
        st.session_state["conta"] = data["user_id"]
        st.success("✅ Conta ML autenticada com sucesso!")
        st.rerun()
    else:
        st.error(f"❌ Falha na autenticação: {resp.text}")

# ----------------- Salvando Tokens -----------------
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
            """)
            conn.execute(query, {
                "user_id":       data["user_id"],
                "access_token":  data["access_token"],
                "refresh_token": data["refresh_token"],
            })
    except Exception as e:
        st.error(f"❌ Erro ao salvar tokens no banco: {e}")

# ----------------- Carregamento de Vendas -----------------
@st.cache_data(ttl=300)
def carregar_vendas(conta_id: Optional[str] = None) -> pd.DataFrame:
    if conta_id:
        # Verifica se é um nickname e faz a conversão
        ml_user_id = pd.read_sql(text("SELECT ml_user_id FROM user_tokens WHERE nickname = :nickname"), 
                                 engine, params={"nickname": conta_id})

        if ml_user_id.empty:
            st.error(f"Nickname '{conta_id}' não encontrado no banco de dados.")
            return pd.DataFrame()

        # Converte para tipo nativo Python (int)
        ml_user_id = int(ml_user_id.iloc[0]["ml_user_id"])

        sql = text("""
            SELECT s.order_id,
                   s.date_created,
                   s.item_title,
                   s.status,
                   s.quantity,
                   s.total_amount,
                   u.nickname
              FROM sales s
              LEFT JOIN user_tokens u ON s.ml_user_id = u.ml_user_id
             WHERE s.ml_user_id = :uid
        """)
        df = pd.read_sql(sql, engine, params={"uid": ml_user_id})
    else:
        sql = text("""
            SELECT s.order_id,
                   s.date_created,
                   s.item_title,
                   s.status,
                   s.quantity,
                   s.total_amount,
                   u.nickname
              FROM sales s
              LEFT JOIN user_tokens u ON s.ml_user_id = u.ml_user_id
        """)
        df = pd.read_sql(sql, engine)

    # converte de UTC para Horário de Brasília e descarta info de tz
    df["date_created"] = (
        pd.to_datetime(df["date_created"], utc=True)
          .dt.tz_convert("America/Sao_Paulo")
          .dt.tz_localize(None)
    )
    return df

# ----------------- Componentes de Interface -----------------
def render_add_account_button():
    # agora com ML_CLIENT_ID e redirect_uri completos
    login_url = (
      f"{BACKEND_URL}/ml-login"
      f"?client_id={ML_CLIENT_ID}"
      f"&redirect_uri={FRONTEND_URL}/?nexus_auth=success"
    )
    st.markdown(f"""
      <a href="{login_url}" target="_blank">
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

from streamlit_option_menu import option_menu

def render_sidebar():
    with st.sidebar:
        # Menu de navegação sem título
        selected = option_menu(
            menu_title=None,
            options=[
                "Dashboard",
                "Contas Cadastradas",
                "Relatórios",
                "Expedição e Logística",
                "Gestão de SKU",
                "Gestão de Despesas",
                "Painel de Metas",
                "Gestão de Anúncios"
            ],
            icons=[
                "house",
                "collection",
                "file-earmark-text",
                "truck",
                "box-seam",
                "currency-dollar",
                "bar-chart-line",
                "bullseye"
            ],
            menu_icon="list",
            default_index=[
                "Dashboard",
                "Contas Cadastradas",
                "Relatórios",
                "Expedição e Logística",
                "Gestão de SKU",
                "Gestão de Despesas",
                "Painel de Metas",
                "Gestão de Anúncios"
            ].index(st.session_state.get("page", "Dashboard")),
            orientation="vertical",
            styles={
                "container": {
                    "padding": "0",
                    "background-color": "#161b22"
                },
                "icon": {
                    "color": "#2ecc71",      # ícones em verde
                    "font-size": "18px"
                },
                "nav-link": {
                    "font-size": "16px",
                    "text-align": "left",
                    "margin": "4px 0",
                    "color": "#fff",          # texto branco
                    "background-color": "transparent"
                },
                "nav-link:hover": {
                    "background-color": "#27ae60"  # hover verde escuro
                },
                "nav-link-selected": {
                    "background-color": "#2ecc71", # seleção em verde claro
                    "color": "white"
                },
            },
        )

    st.session_state["page"] = selected
    return selected
# ----------------- Telas -----------------
import io  # no topo do seu script

def format_currency(value):
    """Formata valores para o padrão brasileiro."""
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def mostrar_dashboard():

    # --- botão de sincronização ---
    if st.button("🔄 Sincronizar Vendas"):
        count = sync_all_accounts()
        st.cache_data.clear()
        st.success(f"{count} vendas novas sincronizadas com sucesso!")
        st.rerun()

    # --- carrega todos os dados ---
    df_full = carregar_vendas(None)
    if df_full.empty:
        st.warning("Nenhuma venda cadastrada.")
        return

    # --- filtro discreto de Contas no topo ---
    contas_df  = pd.read_sql(text("SELECT nickname FROM user_tokens ORDER BY nickname"), engine)
    contas_lst = contas_df["nickname"].astype(str).tolist()
    selecionadas = st.multiselect(
        "🔹 Contas (opcional)",
        options=contas_lst,
        default=contas_lst,
        key="contas_ms",
        help="Filtre por uma ou mais contas; deixe todas selecionadas para não filtrar."
    )
    # aplica filtro de contas
    if selecionadas:
        df_full = df_full[df_full["nickname"].isin(selecionadas)]

    # --- linha única de filtros: Quick-Filter | De | Até ---
    col1, col2, col3 = st.columns([2, 1.5, 1.5])

        # 1) Filtro Rápido (incluindo “Ontem”)
    filtro_rapido = col1.selectbox(
        "🔹 Filtro Rápido",
        [
            "Período Personalizado",
            "Hoje",
            "Ontem",
            "Últimos 7 Dias",
            "Este Mês",
            "Últimos 30 Dias"
        ], index = 1,
        key="filtro_quick"
    )
    
    # 2) Determina intervalos de data (com “Ontem”)
    data_min = df_full["date_created"].dt.date.min()
    data_max = df_full["date_created"].dt.date.max()
    hoje     = pd.Timestamp.now().date()
    
    if filtro_rapido == "Hoje":
        de = ate = min(hoje, data_max)
    
    elif filtro_rapido == "Ontem":
        ontem = hoje - pd.Timedelta(days=1)
        de, ate = ontem, ontem
    
    elif filtro_rapido == "Últimos 7 Dias":
        de, ate = hoje - pd.Timedelta(days=7), hoje
    
    elif filtro_rapido == "Este Mês":
        de, ate = hoje.replace(day=1), hoje
    
    elif filtro_rapido == "Últimos 30 Dias":
        de, ate = hoje - pd.Timedelta(days=30), hoje
    
    else:  # Período Personalizado
        de, ate = data_min, data_max

    # 3) Date inputs (sempre visíveis, mas desabilitados se não for personalizado)
    custom = (filtro_rapido == "Período Personalizado")
    de = col2.date_input(
        "🔹 De",
        value=de,
        min_value=data_min,
        max_value=data_max,
        disabled=not custom,
        key="de_q"
    )
    ate = col3.date_input(
        "🔹 Até",
        value=ate,
        min_value=data_min,
        max_value=data_max,
        disabled=not custom,
        key="ate_q"
    )

    # --- aplica filtro de datas ---
    df = df_full[
        (df_full["date_created"].dt.date >= de) &
        (df_full["date_created"].dt.date <= ate)
    ]

    if df.empty:
        st.warning("Nenhuma venda encontrada para os filtros selecionados.")
        return


    # =================== Ajuste de Timezone ===================
    # Primeiro, define o timezone como UTC para os timestamps "naive"
    df["date_created"] = df["date_created"].dt.tz_localize("UTC")

    # Converte para o fuso horário de São Paulo
    df["date_created"] = df["date_created"].dt.tz_convert("America/Sao_Paulo")

    
    # 4) Métricas
    total_vendas = len(df)
    total_valor  = df["total_amount"].sum()
    total_itens  = df["quantity"].sum()
    ticket_medio = total_valor / total_vendas if total_vendas else 0

    # Exibição das métricas
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧾 Vendas Realizadas", total_vendas)
    c2.metric("💰 Receita Total", format_currency(total_valor))
    c3.metric("📦 Itens Vendidos", int(total_itens))
    c4.metric("🎯 Ticket Médio", format_currency(ticket_medio))
    
    import plotly.express as px

    # =================== Gráfico de Linha - Total Vendido ===================
    col_title, col_visao, col_periodo = st.columns([8, 1, 1])
    title_placeholder = col_title.empty()
    
    modo_agregacao = col_visao.radio(
        "Agrupamento",
        ["Por Conta", "Total Geral"],
        horizontal=True,
        key="modo_agregacao"
    )
    
    tipo_visualizacao = col_periodo.radio(
        "Período",
        ["Diário", "Mensal"],
        horizontal=True,
        key="periodo"
    )
    
    # 2) Prepara e agrega os dados
    df_plot = df.copy()
    
    # Ajuste de fuso para São Paulo
    df_plot["date_created"] = df_plot["date_created"].dt.tz_convert('America/Sao_Paulo')
    
    # agrupa por hora sempre que o período for um único dia
    if de == ate:
        df_plot["date_hour"] = df_plot["date_created"].dt.floor("H")
        eixo_x = "date_hour"
        periodo_label = "Hora"
    else:
        # mais de um dia: usa o seletor Diário/Mensal
        if tipo_visualizacao == "Diário":
            df_plot["date_created"] = df_plot["date_created"].dt.date
            eixo_x = "date_created"
            periodo_label = "Dia"
        else:
            df_plot["date_created"] = df_plot["date_created"].dt.to_period("M").astype(str)
            eixo_x = "date_created"
            periodo_label = "Mês"
    
    # aplica agregação comum
    if modo_agregacao == "Por Conta":
        vendas_por_data = (
            df_plot
            .groupby([eixo_x, "nickname"])["total_amount"]
            .sum()
            .reset_index(name="Valor Total")
        )
        color_dim = "nickname"
        color_seq = px.colors.sequential.Agsunset
    else:
        vendas_por_data = (
            df_plot
            .groupby(eixo_x)["total_amount"]
            .sum()
            .reset_index(name="Valor Total")
        )
        color_dim = None
        color_seq = ["#27ae60"]
    
    titulo = f"💵 Total Vendido por {periodo_label} " + (
        "(Linha por Conta)" if modo_agregacao=="Por Conta" else "(Soma Total)"
    )
    
    # 3) Atualiza o título
    title_placeholder.markdown(f"### {titulo}")
    
    # 4) Desenha o gráfico
    fig = px.line(
        vendas_por_data,
        x=eixo_x,
        y="Valor Total",
        color=color_dim,
        labels={eixo_x: "Data", "Valor Total": "Valor Total", "nickname": "Conta"},
        color_discrete_sequence=color_seq,
    )
    fig.update_traces(
        mode="lines+markers",
        marker=dict(size=5),
        texttemplate="%{y:,.2f}",
        textposition="top center"
    )
    fig.update_layout(margin=dict(t=30, b=20, l=40, r=10))
    
    st.plotly_chart(fig, use_container_width=True)

    # === Gráfico de barras: Média por dia da semana ===
    st.markdown('<div class="section-title">📅 Vendas por Dia da Semana</div>', unsafe_allow_html=True)
    dias = ["Segunda","Terça","Quarta","Quinta","Sexta","Sábado","Domingo"]
    df["dia"] = df["date_created"].dt.day_name().map({
        "Monday":"Segunda","Tuesday":"Terça","Wednesday":"Quarta",
        "Thursday":"Quinta","Friday":"Sexta","Saturday":"Sábado","Sunday":"Domingo"
    })
    gb = df.groupby(["dia", df["date_created"].dt.date])["total_amount"].sum().reset_index()
    ab = gb.groupby("dia")["total_amount"].mean().reindex(dias).reset_index()
    fig_bar = px.bar(
        ab, x="dia", y="total_amount", text_auto=".2s",
        labels={"dia":"Dia","total_amount":"Média"},
        color_discrete_sequence=["#27ae60"]
    )
    st.plotly_chart(fig_bar, use_container_width=True, theme="streamlit")


    # =================== Gráfico de Linha - Faturamento Acumulado por Hora ===================
    st.markdown("### ⏰ Faturamento Acumulado por Hora do Dia (Média)")
    
    # Extrai hora e calcula média acumulada
    df["hora"] = df["date_created"].dt.hour
    faturamento_por_hora = (
        df.groupby("hora")["total_amount"]
          .mean()
          .cumsum()
          .reset_index(name="Valor Médio Acumulado")
    )
    
    # Plota
    fig_hora = px.line(
        faturamento_por_hora,
        x="hora",
        y="Valor Médio Acumulado",
        title="⏰ Média de Faturamento Acumulado por Hora",
        labels={
            "hora": "Hora do Dia",
            "Valor Médio Acumulado": "Valor Médio Acumulado"
        },
        color_discrete_sequence=["#27ae60"],
        markers=True
    )
    st.plotly_chart(fig_hora, use_container_width=True)


def mostrar_contas_cadastradas():
    st.header("🏷️ Contas Cadastradas")
    
    # Botão para Adicionar Nova Conta
    render_add_account_button()

    # Carregar as contas cadastradas
    df = pd.read_sql(text("SELECT ml_user_id, nickname, access_token, refresh_token FROM user_tokens ORDER BY nickname"), engine)
    
    if df.empty:
        st.warning("Nenhuma conta cadastrada.")
        return

    # Loop para criar expansores para cada conta
    for row in df.itertuples(index=False):
        with st.expander(f"🔗 Conta ML: {row.nickname}"):
            st.write(f"**User ID:** {row.ml_user_id}")
            st.write(f"**Access Token:** `{row.access_token}`")
            st.write(f"**Refresh Token:** `{row.refresh_token}`")
            
            # Botão para renovar o token
            if st.button("🔄 Renovar Token", key=f"renew_{row.ml_user_id}"):
                try:
                    resp = requests.post(f"{BACKEND_URL}/auth/refresh", json={"user_id": row.ml_user_id})
                    if resp.ok:
                        data = resp.json()
                        salvar_tokens_no_banco(data)
                        st.success("✅ Token atualizado com sucesso!")
                    else:
                        st.error(f"❌ Erro ao atualizar o token: {resp.text}")
                except Exception as e:
                    st.error(f"❌ Erro ao conectar com o servidor: {e}")

def mostrar_anuncios():
    st.header("🎯 Análise de Anúncios")
    df = carregar_vendas() 

    if df.empty:
        st.warning("Nenhum dado para exibir.")
        return

    # — garanta que date_created seja datetime —
    df['date_created'] = pd.to_datetime(df['date_created'])

    # — filtros de período —
    data_ini = st.date_input("De:",  value=df['date_created'].min().date())
    data_fim = st.date_input("Até:", value=df['date_created'].max().date())

    # — filtro multiselect para MLB (item_id) —
    mlb_opts = df['item_id'].unique()
    mlb_sel = st.multiselect("MLB (item_id):", options=mlb_opts, default=mlb_opts)

    # — aplica filtros —
    df_filt = df.loc[
        (df['date_created'].dt.date >= data_ini) &
        (df['date_created'].dt.date <= data_fim) &
        (df['item_id'].isin(mlb_sel))
    ]

    if df_filt.empty:
        st.warning("Sem registros para os filtros escolhidos.")
        return

    title_col = 'item_title'
    faturamento_col = 'total_amount'

    # 1️⃣ WordCloud dos títulos
    st.subheader("🔍 Nuvem de Palavras dos Títulos")
    text = " ".join(df_filt[title_col])
    wc = WordCloud(width=800, height=400, background_color="white").generate(text)
    st.image(wc.to_array(), use_column_width=True)

    # 2️⃣ Top 10 títulos por faturamento
    st.subheader("🌟 Top 10 Títulos por Faturamento")
    top10 = (
        df_filt
        .groupby(title_col)[faturamento_col]
        .sum()
        .sort_values(ascending=False)
        .head(10)
    )
    st.bar_chart(top10)

    # 3️⃣ Correlação comprimento do título × faturamento
    st.subheader("🔗 Comprimento do Título vs. Faturamento")
    df_filt['title_len'] = df_filt[title_col].str.split().apply(len)
    corr_df = (
        df_filt
        .groupby(title_col)
        .agg(title_len=('title_len','mean'), total_amount=(faturamento_col,'sum'))
        .reset_index()
    )
    chart = alt.Chart(corr_df).mark_circle(size=60).encode(
        x='title_len',
        y='total_amount',
        tooltip=['item_title','total_amount']
    ).properties(width=700, height=400)
    st.altair_chart(chart, use_container_width=True)

    # 4️⃣ Cluster de anúncios por palavras-chave
    st.subheader("🔎 Faturamento Médio por Cluster de Títulos")
    vec = TfidfVectorizer(max_features=300)
    X = vec.fit_transform(df_filt[title_col])
    kmeans = KMeans(n_clusters=4, random_state=0).fit(X)
    df_filt['cluster'] = kmeans.labels_
    perf_cluster = df_filt.groupby('cluster')[faturamento_col].mean()
    st.bar_chart(perf_cluster)

    # 5️⃣ Análise de sentimento dos títulos
    st.subheader("😊 Sentimento dos Títulos vs. Faturamento")
    df_filt['sentiment'] = df_filt[title_col].apply(lambda t: TextBlob(t).sentiment.polarity)
    df_filt['sent_cat'] = pd.cut(
        df_filt['sentiment'],
        bins=[-1, -0.05, 0.05, 1],
        labels=['Negativo','Neutro','Positivo']
    )
    perf_sent = df_filt.groupby('sent_cat')[faturamento_col].sum()
    st.bar_chart(perf_sent)

    # 📊 Tabela de faturamento por MLB (item_id)
    st.subheader("📊 Faturamento por MLB (item_id)")
    df_mlb = (
        df_filt
        .groupby('item_id')[faturamento_col]
        .sum()
        .reset_index()
        .sort_values(by=faturamento_col, ascending=False)
    )
    st.dataframe(df_mlb)

    # ⬇️ Exportar CSV
    csv = df_mlb.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="⬇️ Exportar CSV",
        data=csv,
        file_name="anuncios_faturamento_item_id.csv",
        mime="text/csv"
    )

    
# Funções para cada página
def mostrar_expedicao_logistica():
    st.header("🚚 Expedição e Logística")
    st.info("Em breve...")


def mostrar_gestao_sku():
    st.header("📦 Gestão de SKU")
    st.info("Em breve...")

def mostrar_gestao_despesas():
    st.header("💰 Gestão de Despesas")
    st.info("Em breve...")

def mostrar_painel_metas():
    st.header("🎯 Painel de Metas")
    st.info("Em breve...")
    

# ----------------- Fluxo Principal -----------------
if "code" in st.query_params:
    ml_callback()

pagina = render_sidebar()
if pagina == "Dashboard":
    mostrar_dashboard()
elif pagina == "Contas Cadastradas":
    mostrar_contas_cadastradas()
elif pagina == "Relatórios":
    mostrar_relatorios()
elif pagina == "Expedição e Logística":
    mostrar_expedicao_logistica()
elif pagina == "Gestão de SKU":
    mostrar_gestao_sku()
elif pagina == "Gestão de Despesas":
    mostrar_gestao_despesas()
elif pagina == "Painel de Metas":
    mostrar_painel_metas()
elif pagina == "Gestão de Anúncios":
    mostrar_anuncios()
