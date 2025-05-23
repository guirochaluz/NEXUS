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
from sales import sync_all_accounts, get_full_sales, revisar_status_historico, atualizar_sales_com_sku, get_incremental_sales, padronizar_status_sales
from streamlit_cookies_manager import EncryptedCookieManager
import pandas as pd
import plotly.express as px
import requests
from sqlalchemy import create_engine, text
from streamlit_option_menu import option_menu
from typing import Optional
from wordcloud import WordCloud
import altair as alt
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from textblob import TextBlob
import io


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
        # … seu código de consulta por nickname …
        sql = text("""
            SELECT s.order_id,
                   s.date_adjusted,
                   s.item_id,
                   s.item_title,
                   s.status,
                   s.quantity,
                   s.unit_price,
                   s.total_amount,
                   s.ml_user_id,
                   s.buyer_nickname,
                   s.sku,
                   s.custo_unitario,
                   s.level1,
                   s.level2,
                   u.nickname
              FROM sales s
              LEFT JOIN user_tokens u ON s.ml_user_id = u.ml_user_id
             WHERE s.ml_user_id = :uid
        """)
        df = pd.read_sql(sql, engine, params={"uid": conta_id})

    else:
        sql = text("""
            SELECT s.order_id,
                   s.date_adjusted,
                   s.item_id,
                   s.item_title,
                   s.status,
                   s.quantity,
                   s.unit_price,
                   s.total_amount,
                   s.ml_user_id,
                   s.buyer_nickname,
                   s.sku,
                   s.custo_unitario,
                   s.level1,
                   s.level2,
                   u.nickname
              FROM sales s
              LEFT JOIN user_tokens u ON s.ml_user_id = u.ml_user_id
        """)
        # **ADICIONE esta linha abaixo**
        df = pd.read_sql(sql, engine)
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
                "Gestão de Anúncios",
                "Configurações"  # 🔧 Nova tela adicionada
            ],
            icons=[
                "house",
                "collection",
                "file-earmark-text",
                "truck",
                "box-seam",
                "currency-dollar",
                "bar-chart-line",
                "bullseye",
                "gear"  # ícone para Configurações
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
                "Gestão de Anúncios",
                "Configurações"
            ].index(st.session_state.get("page", "Dashboard")),
            orientation="vertical",
            styles={
                "container": {
                    "padding": "0",
                    "background-color": "#161b22"
                },
                "icon": {
                    "color": "#2ecc71",
                    "font-size": "18px"
                },
                "nav-link": {
                    "font-size": "16px",
                    "text-align": "left",
                    "margin": "4px 0",
                    "color": "#fff",
                    "background-color": "transparent"
                },
                "nav-link:hover": {
                    "background-color": "#27ae60"
                },
                "nav-link-selected": {
                    "background-color": "#2ecc71",
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
    import time

    # --- sincroniza as vendas automaticamente apenas 1x ao carregar ---
    if "vendas_sincronizadas" not in st.session_state:
        with st.spinner("🔄 Sincronizando vendas..."):
            count = sync_all_accounts()
            padronizar_status_sales(engine)  # 👈 Aqui entra a padronização após sincronizar
            st.cache_data.clear()
        placeholder = st.empty()
        with placeholder:
            st.success(f"{count} vendas novas sincronizadas com sucesso!")
            time.sleep(3)
        placeholder.empty()
        st.session_state["vendas_sincronizadas"] = True

    # --- carrega todos os dados ---
    df_full = carregar_vendas(None)
    if df_full.empty:
        st.warning("Nenhuma venda cadastrada.")
        return
    

    # --- CSS para compactar inputs e remover espaços ---
    st.markdown(
        """
        <style>
        .stSelectbox > div, .stDateInput > div {
            padding-top: 0rem;
            padding-bottom: 0rem;
        }
        .stMultiSelect {
            max-height: 40px;
            overflow-y: auto;
        }
        .block-container {
            padding-top: 0rem;
        }
        .stMarkdown h1 { display: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # --- Estilo para mostrar as contas em linha única, sem scroll vertical ---
    st.markdown("""
        <style>
        div[data-baseweb="select"] > div {
            flex-wrap: nowrap !important;
            overflow-x: auto !important;
            scrollbar-width: thin;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # --- Expander de contas (opcional) ---
    with st.expander("Contas", expanded=False):
        contas_df  = pd.read_sql(text("SELECT nickname FROM user_tokens ORDER BY nickname"), engine)
        contas_lst = contas_df["nickname"].astype(str).tolist()
        selecionadas = st.multiselect("", options=contas_lst, default=contas_lst, key="contas_ms")
        if selecionadas:
            df_full = df_full[df_full["nickname"].isin(selecionadas)]

    # --- Linha única de filtros: Rápido | De | Até | Status ---
    col1, col2, col3, col4 = st.columns([1.5, 1.2, 1.2, 1.5])

    with col1:
        filtro_rapido = st.selectbox(
            "",  # escondido
            [
                "Período Personalizado",
                "Hoje",
                "Ontem",
                "Últimos 7 Dias",
                "Este Mês",
                "Últimos 30 Dias",
                "Este Ano"
            ],
            index=1,
            key="filtro_quick"
        )

    hoje = pd.Timestamp.now().date()
    data_min = df_full["date_adjusted"].dt.date.min()
    data_max = df_full["date_adjusted"].dt.date.max()

    if filtro_rapido == "Hoje":
        de = ate = min(hoje, data_max)
    elif filtro_rapido == "Ontem":
        de = ate = hoje - pd.Timedelta(days=1)
    elif filtro_rapido == "Últimos 7 Dias":
        de, ate = hoje - pd.Timedelta(days=7), hoje
    elif filtro_rapido == "Últimos 30 Dias":
        de, ate = hoje - pd.Timedelta(days=30), hoje
    elif filtro_rapido == "Este Mês":
        de, ate = hoje.replace(day=1), hoje
    elif filtro_rapido == "Este Ano":
        de, ate = hoje.replace(month=1, day=1), hoje
    else:
        de, ate = data_min, data_max

    custom = (filtro_rapido == "Período Personalizado")

    with col2:
        de = st.date_input(
            "De", value=de,
            min_value=data_min, max_value=data_max,
            disabled=not custom,
            key="de_q"
        )

    with col3:
        ate = st.date_input(
            "Até", value=ate,
            min_value=data_min, max_value=data_max,
            disabled=not custom,
            key="ate_q"
        )

    with col4:
        status_options = df_full["status"].dropna().unique().tolist()
        status_selecionado = st.selectbox("Status", ["Todos"] + status_options, index=0)

    # --- Filtro de datas e status ---
    df = df_full[
        (df_full["date_adjusted"].dt.date >= de) &
        (df_full["date_adjusted"].dt.date <= ate)
    ]
    if status_selecionado != "Todos":
        df = df[df["status"] == status_selecionado]
    
    # --- Filtros adicionais: Level1, Level2, SKU ---
    with st.expander("🔍 Filtros Avançados", expanded=False):
        col_a1, col_a2, col_a3 = st.columns(3)
    
        op_level1 = col_a1.multiselect(
            "Level1",
            options=sorted(df_full["level1"].dropna().unique().tolist()),
            default=[],
        )
        if op_level1:
            df = df[df["level1"].isin(op_level1)]
    
        op_level2 = col_a2.multiselect(
            "Level2",
            options=sorted(df_full["level2"].dropna().unique().tolist()),
            default=[],
        )
        if op_level2:
            df = df[df["level2"].isin(op_level2)]
    
        op_sku = col_a3.multiselect(
            "SKU",
            options=sorted(df_full["sku"].dropna().unique().tolist()),
            default=[],
        )
        if op_sku:
            df = df[df["sku"].isin(op_sku)]
    
    # Verifica se há dados após os filtros
    if df.empty:
        st.warning("Nenhuma venda encontrada para os filtros selecionados.")
        return
    
    # 4️⃣ Métricas detalhadas
    
    # Métricas base
    total_vendas   = len(df)
    total_valor    = df["total_amount"].sum()
    total_itens    = df["quantity"].sum()
    ticket_venda   = total_valor / total_vendas if total_vendas else 0
    ticket_unidade = total_valor / total_itens if total_itens else 0
    
    # Custos estimados
    frete = total_valor * 0.10
    taxa_mktplace = total_valor * 0.20
    cmv = (df["quantity"] * df["custo_unitario"].fillna(0)).sum()
    margem_operacional = total_valor - frete - taxa_mktplace - cmv
    
    # Linha 1: Faturamento e custos
    st.subheader("💼 Indicadores Financeiros")
    colf1, colf2, colf3, colf4, colf5 = st.columns(5)
    colf1.metric("💰 Faturamento", format_currency(total_valor))
    colf2.metric("🚚 Frete (10%)", format_currency(frete))
    colf3.metric("📉 Taxa Marketplace (20%)", format_currency(taxa_mktplace))
    colf4.metric("📦 CMV (Custo)", format_currency(cmv))
    colf5.metric("💵 Margem Operacional", format_currency(margem_operacional))
    
    # Linha 2: Volume e tickets
    st.subheader("📊 Indicadores de Volume")
    colv1, colv2, colv3, colv4 = st.columns(4)
    colv1.metric("🧾 Vendas Realizadas", total_vendas)
    colv2.metric("📦 Unidades Vendidas", int(total_itens))
    colv3.metric("🎯 Ticket Médio por Venda", format_currency(ticket_venda))
    colv4.metric("🎯 Ticket Médio por Unidade", format_currency(ticket_unidade))
    
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
    
    # agrupa por hora sempre que o período for um único dia
    if de == ate:
        df_plot["date_hour"] = df_plot["date_adjusted"].dt.floor("H")
        eixo_x = "date_hour"
        periodo_label = "Hora"
    else:
        # mais de um dia: usa o seletor Diário/Mensal
        if tipo_visualizacao == "Diário":
            df_plot["date_adjusted"] = df_plot["date_adjusted"].dt.date
            eixo_x = "date_adjusted"
            periodo_label = "Dia"
        else:
            df_plot["date_adjusted"] = df_plot["date_adjusted"].dt.to_period("M").astype(str)
            eixo_x = "date_adjusted"
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
    
    # Nome dos dias na ordem certa
    dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    
    # Extrai dia da semana em português
    df["dia_semana"] = df["date_adjusted"].dt.day_name().map({
        "Monday": "Segunda", "Tuesday": "Terça", "Wednesday": "Quarta",
        "Thursday": "Quinta", "Friday": "Sexta", "Saturday": "Sábado", "Sunday": "Domingo"
    })
    
    # Extrai a data (sem hora)
    df["data"] = df["date_adjusted"].dt.date
    
    # Soma o total vendido por dia (independente da hora)
    total_por_data = df.groupby(["dia_semana", "data"])["total_amount"].sum().reset_index()
    
    # Agora calcula a média por dia da semana
    media_por_dia = total_por_data.groupby("dia_semana")["total_amount"].mean().reindex(dias).reset_index()
    
    # Plota o gráfico de barras
    fig_bar = px.bar(
        media_por_dia,
        x="dia_semana",
        y="total_amount",
        text_auto=".2s",
        labels={"dia_semana": "Dia da Semana", "total_amount": "Média Vendida (R$)"},
        color_discrete_sequence=["#27ae60"]
    )
    
    st.plotly_chart(fig_bar, use_container_width=True, theme="streamlit")




    # =================== Gráfico de Linha - Faturamento Acumulado por Hora ===================
    st.markdown("### ⏰ Faturamento Acumulado por Hora do Dia (Média)")
    
    # Extrai hora e data
    df["hora"] = df["date_adjusted"].dt.hour
    df["data"] = df["date_adjusted"].dt.date
    
    # Soma o total vendido por hora e por dia
    vendas_por_dia_e_hora = df.groupby(["data", "hora"])["total_amount"].sum().reset_index()
    
    # Garante que todas as horas estejam presentes para todos os dias
    todos_dias = vendas_por_dia_e_hora["data"].unique()
    todas_horas = list(range(0, 24))
    malha_completa = pd.MultiIndex.from_product([todos_dias, todas_horas], names=["data", "hora"])
    vendas_completa = vendas_por_dia_e_hora.set_index(["data", "hora"]).reindex(malha_completa, fill_value=0).reset_index()
    
    # Acumula por hora dentro de cada dia
    vendas_completa["acumulado_dia"] = vendas_completa.groupby("data")["total_amount"].cumsum()
    
    # Agora calcula a média acumulada por hora (entre os dias)
    media_acumulada_por_hora = (
        vendas_completa
        .groupby("hora")["acumulado_dia"]
        .mean()
        .reset_index(name="Valor Médio Acumulado")
    )
    
    # Verifica se é filtro de hoje
    hoje = pd.Timestamp.now(tz="America/Sao_Paulo").date()
    filtro_hoje = (de == ate) and (de == hoje)
    
    if filtro_hoje:
        hora_atual = pd.Timestamp.now(tz="America/Sao_Paulo").hour
        df_hoje = df[df["data"] == hoje]
        vendas_hoje_por_hora = (
            df_hoje.groupby("hora")["total_amount"].sum().reindex(range(24), fill_value=0)
            .cumsum()
            .reset_index(name="Valor Médio Acumulado")
            .rename(columns={"index": "hora"})
        )
        # Traz o ponto até hora atual
        ponto_extra = pd.DataFrame([{
            "hora": hora_atual,
            "Valor Médio Acumulado": vendas_hoje_por_hora.loc[hora_atual, "Valor Médio Acumulado"]
        }])
        media_acumulada_por_hora = pd.concat([media_acumulada_por_hora, ponto_extra]).groupby("hora").last().reset_index()
    
    else:
        # Para histórico, adiciona o ponto final às 23h com média total diária
        media_final = df.groupby("data")["total_amount"].sum().mean()
        ponto_final = pd.DataFrame([{
            "hora": 23,
            "Valor Médio Acumulado": media_final
        }])
        media_acumulada_por_hora = pd.concat([media_acumulada_por_hora, ponto_final]).groupby("hora").last().reset_index()
    
    # Plota o gráfico
    fig_hora = px.line(
        media_acumulada_por_hora,
        x="hora",
        y="Valor Médio Acumulado",
        title="⏰ Faturamento Acumulado por Hora (Média por Dia)",
        labels={
            "hora": "Hora do Dia",
            "Valor Médio Acumulado": "Valor Acumulado (R$)"
        },
        color_discrete_sequence=["#27ae60"],
        markers=True
    )
    fig_hora.update_layout(xaxis=dict(dtick=1))
    
    st.plotly_chart(fig_hora, use_container_width=True)




def mostrar_contas_cadastradas():
    st.header("🏷️ Contas Cadastradas")
    render_add_account_button()

    df = pd.read_sql(text("SELECT ml_user_id, nickname, access_token, refresh_token FROM user_tokens ORDER BY nickname"), engine)

    if df.empty:
        st.warning("Nenhuma conta cadastrada.")
        return

    # --- Botões globais ---
    col_a, col_b, col_c = st.columns(3)
    
    with col_a:
        if st.button("🔄 Atualizar Vendas Recentes (Todas)", use_container_width=True):
            with st.spinner("🔄 Executando atualizações incrementais..."):
                for row in df.itertuples(index=False):
                    ml_user_id = str(row.ml_user_id)
                    access_token = row.access_token
                    nickname = row.nickname

                    st.subheader(f"🔗 Conta: {nickname}")
                    novas = get_incremental_sales(ml_user_id, access_token)
                    st.success(f"✅ {novas} novas vendas ou alterações recentes importadas.")

    with col_b:
        if st.button("♻️ Processar Status (Todas)", use_container_width=True):
            with st.spinner("♻️ Atualizando status de todas as vendas..."):
                for row in df.itertuples(index=False):
                    ml_user_id = str(row.ml_user_id)
                    access_token = row.access_token
                    nickname = row.nickname

                    st.subheader(f"🔗 Conta: {nickname}")
                    atualizadas, _ = revisar_status_historico(ml_user_id, access_token, return_changes=False)
                    st.info(f"♻️ {atualizadas} vendas com status alterados.")

                # ✅ Executa padronização depois de todas as contas
                padronizar_status_sales(engine)
                st.success("✅ Todos os status foram padronizados com sucesso.")
                    
    with col_c:
        if st.button("📜 Reprocessar Histórico (Todas)", use_container_width=True):
            with st.spinner("📜 Reprocessando histórico completo..."):
                for row in df.itertuples(index=False):
                    ml_user_id = str(row.ml_user_id)
                    access_token = row.access_token
                    nickname = row.nickname

                    st.subheader(f"🔗 Conta: {nickname}")
                    novas = get_full_sales(ml_user_id, access_token)
                    st.success(f"✅ {novas} vendas históricas importadas.")

    # --- Seção por conta individual ---
    for row in df.itertuples(index=False):
        with st.expander(f"🔗 Conta ML: {row.nickname}"):
            ml_user_id = str(row.ml_user_id)
            access_token = row.access_token
            refresh_token = row.refresh_token

            st.write(f"**User ID:** `{ml_user_id}`")
            st.write(f"**Access Token:** `{access_token}`")
            st.write(f"**Refresh Token:** `{refresh_token}`")

            col1, col2, col3 = st.columns(3)

            # Renovar Token
            with col1:
                if st.button("🔄 Renovar Token", key=f"renew_{ml_user_id}"):
                    try:
                        resp = requests.post(f"{BACKEND_URL}/auth/refresh", json={"user_id": ml_user_id})
                        if resp.ok:
                            data = resp.json()
                            salvar_tokens_no_banco(data)
                            st.success("✅ Token atualizado com sucesso!")
                        else:
                            st.error(f"❌ Erro ao atualizar o token: {resp.text}")
                    except Exception as e:
                        st.error(f"❌ Erro ao conectar com o servidor: {e}")

            # Processar Status (somente da conta)
            with col2:
                if st.button("♻️ Processar Status", key=f"status_{ml_user_id}"):
                    with st.spinner("♻️ Atualizando status das vendas..."):
                        atualizadas, _ = revisar_status_historico(ml_user_id, access_token, return_changes=False)
                        st.info(f"♻️ {atualizadas} vendas com status alterados.")

            # Histórico Completo por conta
            with col3:
                if st.button("📜 Histórico Completo", key=f"historico_{ml_user_id}"):
                    progresso = st.progress(0, text="🔁 Iniciando reprocessamento...")
                    with st.spinner("📜 Importando histórico completo..."):
                        novas = get_full_sales(ml_user_id, access_token)
                        atualizadas, alteracoes = revisar_status_historico(ml_user_id, access_token, return_changes=True)
                        progresso.progress(100, text="✅ Concluído!")
                        st.success(f"✅ {novas} vendas históricas importadas.")
                        st.info(f"♻️ {atualizadas} vendas com status alterados.")
                        st.cache_data.clear()
                    progresso.empty()

                    if alteracoes:
                        df_alt = pd.DataFrame(alteracoes, columns=["order_id", "status_antigo", "status_novo"])
                        csv = df_alt.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            label="⬇️ Exportar Alterações de Status",
                            data=csv,
                            file_name=f"status_alterados_{row.nickname}.csv",
                            mime="text/csv",
                            use_container_width=True
                        )

def mostrar_anuncios():
    st.header("🎯 Análise de Anúncios")
    df = carregar_vendas()

    if df.empty:
        st.warning("Nenhum dado para exibir.")
        return

    df['date_adjusted'] = pd.to_datetime(df['date_adjusted'])

    # ========== FILTROS ==========
    data_ini = st.date_input("De:",  value=df['date_adjusted'].min().date())
    data_fim = st.date_input("Até:", value=df['date_adjusted'].max().date())

    df_filt = df.loc[
    (df['date_adjusted'].dt.date >= data_ini) &
    (df['date_adjusted'].dt.date <= data_fim)
    ]

    if df_filt.empty:
        st.warning("Sem registros para os filtros escolhidos.")
        return

    title_col = 'item_title'
    faturamento_col = 'total_amount'

    # 1️⃣ Nuvem de Palavras
    st.subheader("1️⃣ 🔍 Nuvem de Palavras dos Títulos")
    text = " ".join(df_filt[title_col])
    wc = WordCloud(width=600, height=300, background_color="white").generate(text)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.image(wc.to_array(), use_column_width=True)

    # 2️⃣ Top 10 Títulos por Faturamento
    st.subheader("2️⃣ 🌟 Top 10 Títulos por Faturamento")
    top10_df = (
        df_filt
        .groupby(title_col)[faturamento_col]
        .sum()
        .reset_index()
        .sort_values(by=faturamento_col, ascending=False)
        .head(10)
    )
    fig_top10 = px.bar(
        top10_df,
        x=title_col,
        y=faturamento_col,
        text_auto='.2s',
        labels={title_col: "Título", faturamento_col: "Faturamento (R$)"},
        color_discrete_sequence=["#1abc9c"]
    )
    st.plotly_chart(fig_top10, use_container_width=True)

    # 4️⃣ Faturamento por Palavra
    st.subheader("3️⃣ 🧠 Palavras que mais faturam nos Títulos")
    from collections import Counter
    word_faturamento = Counter()
    for _, row in df_filt.iterrows():
        palavras = str(row[title_col]).lower().split()
        for p in palavras:
            word_faturamento[p] += row[faturamento_col]

    df_words = pd.DataFrame(word_faturamento.items(), columns=['palavra', 'faturamento'])
    df_words = df_words.sort_values(by='faturamento', ascending=False).head(15)
    fig_words = px.bar(
        df_words,
        x='palavra',
        y='faturamento',
        text_auto='.2s',
        labels={'palavra': 'Palavra no Título', 'faturamento': 'Faturamento (R$)'},
        color_discrete_sequence=["#f39c12"]
    )
    st.plotly_chart(fig_words, use_container_width=True)

    # 5️⃣ Faturamento por Comprimento de Título
    st.subheader("4️⃣ 📏 Faturamento por Comprimento de Título (nº de palavras)")
    df['title_len'] = df[title_col].str.split().apply(len)
    df_len_fat = (
        df
        .groupby('title_len')[faturamento_col]
        .sum()
        .reset_index()
        .sort_values('title_len')
    )
    fig_len = px.bar(
        df_len_fat,
        x='title_len',
        y=faturamento_col,
        labels={'title_len': 'Nº de Palavras no Título', 'total_amount': 'Faturamento (R$)'},
        text_auto='.2s',
        color_discrete_sequence=["#9b59b6"]
    )
    st.plotly_chart(fig_len, use_container_width=True)

    # 6️⃣ Títulos com 0 vendas no período filtrado
    st.subheader("5️⃣ 🚨 Títulos sem Vendas no Período")
    df_sem_venda = (
        df_filt[df_filt['quantity'] == 0]
        .groupby(['item_id', 'item_title'])
        .agg(total_amount=('total_amount', 'sum'), quantidade=('quantity', 'sum'))
        .reset_index()
    )
    df_sem_venda['link'] = df_sem_venda['item_id'].apply(
        lambda x: f"https://www.mercadolivre.com.br/anuncio/{x}"
    )
    df_sem_venda['link'] = df_sem_venda['link'].apply(
        lambda url: f"[🔗 Ver Anúncio]({url})"
    )
    df_sem_venda['total_amount'] = df_sem_venda['total_amount'].apply(
        lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )
    df_sem_venda['quantidade'] = df_sem_venda['quantidade'].astype(int)
    st.dataframe(df_sem_venda, use_container_width=True)

    # 7️⃣ Faturamento por item_id com link
    st.subheader("6️⃣ 📊 Faturamento por MLB (item_id, Título e Link)")

    df_mlb = (
        df_filt
        .groupby(['item_id', 'item_title'])[faturamento_col]
        .sum()
        .reset_index()
        .sort_values(by=faturamento_col, ascending=False)
    )
    df_mlb['link'] = df_mlb['item_id'].apply(
        lambda x: f"https://www.mercadolivre.com.br/anuncio/{x}"
    )
    df_mlb_display = df_mlb.copy()
    df_mlb_display['total_amount'] = df_mlb_display['total_amount'].apply(
        lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )
    df_mlb_display['link'] = df_mlb_display['link'].apply(
        lambda url: f"[🔗 Ver Anúncio]({url})"
    )
    st.dataframe(df_mlb_display, use_container_width=True)

    # Exportação CSV (sem formatação)
    csv = df_mlb.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="⬇️ Exportar CSV",
        data=csv,
        file_name="faturamento_por_mlb.csv",
        mime="text/csv"
    )

def mostrar_relatorios():
    st.header("📋 Relatórios de Vendas")

    df = carregar_vendas()

    if df.empty:
        st.warning("Nenhum dado encontrado.")
        return

    df['date_adjusted'] = pd.to_datetime(df['date_adjusted'])

    # Filtro de período
    col1, col2 = st.columns(2)
    with col1:
        data_ini = st.date_input("De:", value=df['date_adjusted'].min().date())
    with col2:
        data_fim = st.date_input("Até:", value=df['date_adjusted'].max().date())

    df_filt = df.loc[
        (df['date_adjusted'].dt.date >= data_ini) &
        (df['date_adjusted'].dt.date <= data_fim)
    ]

    if df_filt.empty:
        st.warning("Nenhuma venda no período selecionado.")
        return

    # Adiciona coluna de link para o anúncio
    df_filt['link'] = df_filt['item_id'].apply(
        lambda x: f"[🔗 Ver Anúncio](https://www.mercadolivre.com.br/anuncio/{x})"
    )

    # Reorganiza e seleciona as colunas principais
    colunas = [
        'date_adjusted',
        'item_id',
        'item_title',
        'quantity',
        'unit_price',
        'total_amount',
        'order_id',
        'buyer_nickname',
        'ml_user_id',
        'status',
        'link'
    ]

    df_exibir = df_filt[colunas].copy()

    # Formatação visual
    df_exibir['unit_price'] = df_exibir['unit_price'].apply(
        lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )
    df_exibir['total_amount'] = df_exibir['total_amount'].apply(
        lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )

    st.dataframe(df_exibir, use_container_width=True)

    # Exportação CSV com dados crus
    csv = df_filt[colunas].to_csv(index=False).encode('utf-8')
    st.download_button(
        label="⬇️ Exportar CSV das Vendas",
        data=csv,
        file_name="relatorio_vendas.csv",
        mime="text/csv"
    )


def mostrar_gestao_sku():
    st.header("📦 Gestão de SKU")

    # 🔄 Botão de atualização total (atualiza banco + recarrega dados)
    if st.button("🔄 Atualizar Dados"):
        atualizar_sales_com_sku(engine)
        st.session_state["atualizar_gestao_sku"] = True

    # 🔁 Recarrega os dados do banco se necessário
    if st.session_state.get("atualizar_gestao_sku", False) or "df_gestao_sku" not in st.session_state:
        df = pd.read_sql(text("""
            SELECT s.item_id, s.sku, s.level1, s.level2, s.custo_unitario, s.quantity_sku
            FROM sales s
            ORDER BY s.date_closed DESC
        """), engine)
        st.session_state["df_gestao_sku"] = df
        st.session_state["atualizar_gestao_sku"] = False
    else:
        df = st.session_state["df_gestao_sku"]

    # 1️⃣ Métricas principais
    with engine.begin() as conn:
        total_com_sku = conn.execute(text("SELECT COUNT(*) FROM sales WHERE sku IS NOT NULL")).scalar()
        total_sem_sku = conn.execute(text("SELECT COUNT(*) FROM sales WHERE sku IS NULL")).scalar()
        total_sem_preco = conn.execute(text("""
            SELECT COUNT(*) FROM sales
            WHERE sku IS NOT NULL AND custo_unitario IS NULL
        """)).scalar()
        mlb_com_sku = conn.execute(text("SELECT COUNT(DISTINCT item_id) FROM sales WHERE sku IS NOT NULL")).scalar()
        mlb_sem_sku = conn.execute(text("SELECT COUNT(DISTINCT item_id) FROM sales WHERE sku IS NULL")).scalar()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("🔗 Vendas com SKU", total_com_sku)
    col2.metric("🚫 Vendas sem SKU", total_sem_sku)
    col3.metric("❌ SKUs sem Preço", total_sem_preco)
    col4.metric("📦 MLBs com SKU", mlb_com_sku)
    col5.metric("📦 MLBs sem SKU", mlb_sem_sku)

    st.markdown("---")
    st.markdown("### 🔍 Filtros de Diagnóstico")

    # 3️⃣ Filtros dinâmicos
    colf1, colf2, colf3, colf4, colf5 = st.columns([1.2, 1.2, 1.2, 1.2, 2])
    op_sku     = colf1.selectbox("SKU", ["Todos", "Nulo", "Não Nulo"])
    op_level1  = colf2.selectbox("Level1", ["Todos", "Nulo", "Não Nulo"])
    op_level2  = colf3.selectbox("Level2", ["Todos", "Nulo", "Não Nulo"])
    op_preco   = colf4.selectbox("Preço Unitário", ["Todos", "Nulo", "Não Nulo"])
    filtro_txt = colf5.text_input("🔎 Pesquisa (MLB, SKU, Level1, Level2)")

    if op_sku == "Nulo":
        df = df[df["sku"].isna()]
    elif op_sku == "Não Nulo":
        df = df[df["sku"].notna()]
    if op_level1 == "Nulo":
        df = df[df["level1"].isna()]
    elif op_level1 == "Não Nulo":
        df = df[df["level1"].notna()]
    if op_level2 == "Nulo":
        df = df[df["level2"].isna()]
    elif op_level2 == "Não Nulo":
        df = df[df["level2"].notna()]
    if op_preco == "Nulo":
        df = df[df["custo_unitario"].isna()]
    elif op_preco == "Não Nulo":
        df = df[df["custo_unitario"].notna()]
    if filtro_txt:
        filtro_txt = filtro_txt.lower()
        df = df[df.apply(lambda row: filtro_txt in str(row["item_id"]).lower()
                         or filtro_txt in str(row["sku"]).lower()
                         or filtro_txt in str(row["level1"]).lower()
                         or filtro_txt in str(row["level2"]).lower(), axis=1)]

    # 4️⃣ Tabela de visualização
    st.markdown("### 📊 Tabela de Vendas com SKUs")
    if df.empty:
        st.warning("⚠️ Nenhum dado encontrado com os filtros aplicados.")
    else:
        st.dataframe(df, use_container_width=True)

    # 5️⃣ Atualização da base SKU via planilha
    st.markdown("---")
    st.markdown("### 📥 Atualizar Base de SKUs via Planilha")
    modelo = pd.DataFrame(columns=["sku", "level1", "level2", "custo_unitario", "quantity"])
    buffer = io.BytesIO()
    modelo.to_excel(buffer, index=False, engine="openpyxl")
    st.download_button(
        label="⬇️ Baixar Modelo Excel de SKUs",
        data=buffer.getvalue(),
        file_name="modelo_sku.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    arquivo = st.file_uploader("Selecione um arquivo Excel (.xlsx)", type=["xlsx"])
    if arquivo is not None:
        df_novo = pd.read_excel(arquivo)
        colunas_esperadas = {"sku", "level1", "level2", "custo_unitario", "quantity"}
        if not colunas_esperadas.issubset(df_novo.columns):
            st.error("❌ A planilha deve conter: sku, level1, level2, custo_unitario, quantity.")
        else:
            if st.button("✅ Processar Planilha e Atualizar"):
                try:
                    df_novo["quantity"] = df_novo["quantity"].fillna(0).astype(int)
                    df_novo["custo_unitario"] = df_novo["custo_unitario"].fillna(0).astype(float)
                    df_novo["sku"] = df_novo["sku"].astype(str).str.strip()
                    df_novo["level1"] = df_novo["level1"].astype(str).str.strip()
                    df_novo["level2"] = df_novo["level2"].astype(str).str.strip()

                    with engine.begin() as conn:
                        for _, row in df_novo.iterrows():
                            row_dict = row.to_dict()
                            result = conn.execute(text("""
                                SELECT 1 FROM sku
                                WHERE sku = :sku
                                  AND TRIM(level1) = :level1
                                  AND TRIM(level2) = :level2
                                  AND ROUND(CAST(custo_unitario AS numeric), 2) = ROUND(CAST(:custo_unitario AS numeric), 2)
                                  AND quantity = :quantity
                                LIMIT 1
                            """), row_dict).fetchone()
                            if result is None:
                                conn.execute(text("""
                                    INSERT INTO sku (sku, level1, level2, custo_unitario, quantity, date_created)
                                    VALUES (:sku, :level1, :level2, :custo_unitario, :quantity, NOW())
                                """), row_dict)
                    st.success("✅ Planilha importada com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao processar: {e}")

    # 6️⃣ Relação SKU ↔ MLB
    st.markdown("---")
    st.markdown("### 🔄 Relação SKU com MLB")
    modelo_relacao = pd.DataFrame(columns=["sku", "mlb"])
    buffer_rel = io.BytesIO()
    modelo_relacao.to_excel(buffer_rel, index=False, engine="openpyxl")
    st.download_button(
        label="⬇️ Baixar Modelo Relação SKU ↔ MLB",
        data=buffer_rel.getvalue(),
        file_name="modelo_relacao_skumlb.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    arquivo_relacao = st.file_uploader("Selecione a planilha de relação (SKU + MLB)", type=["xlsx"], key="relacao_skumlb")
    if arquivo_relacao:
        df_relacao = pd.read_excel(arquivo_relacao)
        colunas_esperadas = {"sku", "mlb"}
        if not colunas_esperadas.issubset(df_relacao.columns):
            st.error("❌ A planilha precisa conter as colunas: sku e mlb.")
        else:
            if st.button("📥 Processar Planilha de SKU-MLB"):
                try:
                    with engine.begin() as conn:
                        for _, row in df_relacao.iterrows():
                            conn.execute(text("""
                                INSERT INTO skumlb (sku, mlb)
                                VALUES (:sku, :mlb)
                                ON CONFLICT (sku, mlb) DO NOTHING
                            """), row.to_dict())
                        conn.execute(text("""
                            UPDATE sales
                            SET sku = skumlb.sku
                            FROM skumlb
                            WHERE sales.item_id = skumlb.mlb
                              AND sales.sku IS NULL
                        """))
                    st.success("✅ Relações SKU-MLB importadas e conciliadas com sucesso!")
                    st.session_state["atualizar_gestao_sku"] = True
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao importar ou conciliar dados: {e}")

def mostrar_expedicao_logistica():
    st.header("🚚 Expedição e Logística")
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
elif pagina == "Configurações":
    mostrar_configuracoes()
