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
    page_title="NEXUS Group",
    page_icon="favicon.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# 3) Depois de set_page_config, importe tudo o mais que precisar
from sales import sync_all_accounts, get_full_sales, revisar_banco_de_dados, get_incremental_sales, traduzir_status
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
from datetime import datetime, timedelta
from utils import engine, DATA_INICIO, buscar_ml_fee
import time
from reconcile import reconciliar_vendas
from dateutil.relativedelta import relativedelta






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
                   s.seller_sku,
                   s.custo_unitario,
                   s.quantity_sku,
                   s.ml_fee,
                   s.level1,
                   s.level2,
                   s.ads,
                   s.payment_id,
                   s.shipment_status,
                   s.shipment_substatus,
                   s.shipment_last_updated,
                   s.shipment_mode,
                   s.shipment_logistic_type,
                   s.shipment_list_cost,
                   s.shipment_delivery_type,
                   s.shipment_receiver_name,
                   s.shipment_delivery_sla,
                   s.order_cost,
                   s.base_cost,
                   s.shipment_cost,
                   s.frete_adjust,
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
                   s.seller_sku,
                   s.custo_unitario,
                   s.quantity_sku,
                   s.ml_fee,
                   s.level1,
                   s.level2,
                   s.ads,
                   s.payment_id,
                   s.shipment_status,
                   s.shipment_substatus,
                   s.shipment_last_updated,
                   s.shipment_mode,
                   s.shipment_logistic_type,
                   s.shipment_list_cost,
                   s.shipment_delivery_type,
                   s.shipment_receiver_name,
                   s.shipment_delivery_sla,
                   s.order_cost,
                   s.base_cost,
                   s.shipment_cost,
                   s.frete_adjust,
                   u.nickname
              FROM sales s
              LEFT JOIN user_tokens u ON s.ml_user_id = u.ml_user_id
        """)
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
    # --- Injetar CSS para impedir wrap nos itens do menu ---
    st.sidebar.markdown(
        """
        <style>
          /* Aplica apenas aos links do option_menu dentro da sidebar */
          [data-testid="stSidebar"] .nav-link {
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        selected = option_menu(
            menu_title=None,
            options=[
                "Dashboard",              # Visão geral
                "Contas Cadastradas",     # Contas conectadas
                "Relatórios",             # Relatórios
                "Expedição",              # Expedição
                "Gestão de SKU",          # Produtos/SKUs
                "Painel de Metas",        # Produção
                "Supply Chain",           # Compras
                "Gestão de Anúncios",     # Marketplace
                "Gerenciar Cadastros",    # Cadastros
                "Calculadora de Custos"   # ✅ Nova página
            ],
            icons=[
                "speedometer", "people", "bar-chart", "truck", "box", "bullseye",
                "link-45deg", "megaphone", "journal-plus", "calculator"
            ],
            menu_icon="list",
            default_index=[
                "Dashboard",
                "Contas Cadastradas",
                "Relatórios",
                "Expedição",
                "Gestão de SKU",
                "Painel de Metas",
                "Supply Chain",
                "Gestão de Anúncios",
                "Gerenciar Cadastros",
                "Calculadora de Custos"
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
                    "background-color": "transparent",
                    "white-space": "nowrap"  # impede quebra
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
        
    # ✅ TRADUZ STATUS AQUI
    from sales import traduzir_status
    df_full["status"] = df_full["status"].map(traduzir_status)

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

    # --- Filtro de contas fixo com checkboxes lado a lado + botão selecionar todos ---
    contas_df = pd.read_sql(text("SELECT nickname FROM user_tokens ORDER BY nickname"), engine)
    contas_lst = contas_df["nickname"].astype(str).tolist()
    
    st.markdown("**🧾 Contas Mercado Livre:**")


    # Estado para controlar se todas estão selecionadas
    if "todas_contas_marcadas" not in st.session_state:
        st.session_state["todas_contas_marcadas"] = True
    
    
    # Renderiza os checkboxes em colunas
    colunas_contas = st.columns(8)
    selecionadas = []
    
    for i, conta in enumerate(contas_lst):
        key = f"conta_{conta}"
        if key not in st.session_state:
            st.session_state[key] = st.session_state["todas_contas_marcadas"]
        if colunas_contas[i % 8].checkbox(conta, key=key):
            selecionadas.append(conta)
    
    # Aplica filtro
    if selecionadas:
        df_full = df_full[df_full["nickname"].isin(selecionadas)]


    # --- Linha única de filtros: Rápido | De | Até | Status ---
    col1, col2, col3, col4 = st.columns([1.5, 1.2, 1.2, 1.5])

    with col1:
        filtro_rapido = st.selectbox(
            "Filtrar Período",
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
    import pytz
    hoje = pd.Timestamp.now(tz="America/Sao_Paulo").date()
    data_min = df_full["date_adjusted"].dt.date.min()
    data_max = df_full["date_adjusted"].dt.date.max()
    
    if filtro_rapido == "Hoje":
        de = ate = min(hoje, data_max)
    elif filtro_rapido == "Ontem":
        de = ate = hoje - pd.Timedelta(days=1)
    elif filtro_rapido == "Últimos 7 Dias":
        de, ate = hoje - pd.Timedelta(days=6), hoje
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
        de = st.date_input("De", value=de, min_value=data_min, max_value=data_max, disabled=not custom, key="de_q")
    
    with col3:
        ate = st.date_input("Até", value=ate, min_value=data_min, max_value=data_max, disabled=not custom, key="ate_q")
    
    with col4:
        status_options = df_full["status"].dropna().unique().tolist()
        status_opcoes = ["Todos"] + status_options
        index_padrao = status_opcoes.index("Pago") if "Pago" in status_opcoes else 0
        status_selecionado = st.selectbox("Status", status_opcoes, index=index_padrao)
    
    # Aplica filtros finais
    df = df_full[
        (df_full["date_adjusted"].dt.date >= de) &
        (df_full["date_adjusted"].dt.date <= ate)
    ]
    if status_selecionado != "Todos":
        df = df[df["status"] == status_selecionado]

    
    # --- Filtros Avançados com checkbox dentro de Expander ---
    with st.expander("🔍 Filtros Avançados", expanded=False):
        # Atualiza as opções com base nos dados filtrados até aqui
        level1_opcoes = sorted(df["level1"].dropna().unique().tolist())
        st.markdown("**📂 Hierarquia 1**")
        col_l1 = st.columns(4)
        level1_selecionados = []
        for i, op in enumerate(level1_opcoes):
            if col_l1[i % 4].checkbox(op, key=f"level1_{op}"):
                level1_selecionados.append(op)
        if level1_selecionados:
            df = df[df["level1"].isin(level1_selecionados)]
    
        # Atualiza Level2 após Level1 aplicado
        level2_opcoes = sorted(df["level2"].dropna().unique().tolist())
        st.markdown("**📁 Hierarquia 2**")
        col_l2 = st.columns(4)
        level2_selecionados = []
        for i, op in enumerate(level2_opcoes):
            if col_l2[i % 4].checkbox(op, key=f"level2_{op}"):
                level2_selecionados.append(op)
        if level2_selecionados:
            df = df[df["level2"].isin(level2_selecionados)]
    
    # Verifica se há dados após os filtros
    if df.empty:
        st.warning("Nenhuma venda encontrada para os filtros selecionados.")
        st.stop()

    
    # Estilo customizado (CSS)
    st.markdown("""
        <style>
            .kpi-title {
                font-size: 15px;
                font-weight: 600;
                color: #000000;
                margin-bottom: 4px;
            }
            .kpi-value {
                font-size: 22px;
                font-weight: bold;
                color: #000000;
                line-height: 1.2;
                word-break: break-word;
            }
            .kpi-card {
                background-color: #ffffff;
                border-radius: 12px;
                padding: 16px 20px;
                margin: 5px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);
                border-left: 5px solid #27ae60;
            }
        </style>
    """, unsafe_allow_html=True)
    
    # Função para renderizar KPI card em coluna
    def kpi_card(col, title, value):
        col.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-title">{title}</div>
                <div class="kpi-value">{value}</div>
            </div>
        """, unsafe_allow_html=True)
    
    # Cálculos (ajustado)
    total_vendas        = len(df)
    total_valor         = df["total_amount"].sum()
    total_itens         = (df["quantity_sku"] * df["quantity"]).sum()
    ticket_venda        = total_valor / total_vendas if total_vendas else 0
    ticket_unidade      = total_valor / total_itens if total_itens else 0
    frete               = df["frete_adjust"].fillna(0).sum()
    taxa_mktplace       = -df["ml_fee"].fillna(0).sum()
    cmv                 = -((df["quantity_sku"] * df["quantity"]) * df["custo_unitario"].fillna(0)).sum()
    margem_operacional  = total_valor + frete + taxa_mktplace + cmv
    colunas_chk = ["level1", "level2", "custo_unitario", "quantity_sku"]
    
    # Filtra linhas onde seller_sku NÃO é nulo e pelo menos uma coluna está nula
    df_faltantes = df_full[
        df_full["seller_sku"].notnull() & df_full[colunas_chk].isnull().any(axis=1)
    ]
    sku_incompleto = df_faltantes["seller_sku"].nunique()

    pct = lambda val: f"<span style='font-size: 70%; color: #666; display: inline-block; margin-left: 6px;'>({val / total_valor * 100:.1f}%)</span>" if total_valor else "<span style='font-size: 70%'>(0%)</span>"

    # Bloco 1: Indicadores Financeiros
    st.markdown("### 💼 Indicadores Financeiros")
    row1 = st.columns(5)
    kpi_card(row1[0], "💰 Faturamento", format_currency(total_valor))
    kpi_card(row1[1], "🚚 Frete Total", f"{format_currency(frete)} {pct(frete)}")
    kpi_card(row1[2], "📉 Taxa Marketplace", f"{format_currency(taxa_mktplace)} {pct(taxa_mktplace)}")
    kpi_card(row1[3], "📦 CMV", f"{format_currency(cmv)} {pct(cmv)}")
    kpi_card(row1[4], "💵 Margem Operacional", f"{format_currency(margem_operacional)} {pct(margem_operacional)}")
    
    # Bloco 2: Indicadores de Vendas
    st.markdown("### 📊 Indicadores de Vendas")
    row2 = st.columns(5)
    kpi_card(row2[0], "🧾 Vendas Realizadas", str(total_vendas))
    kpi_card(row2[1], "📦 Unidades Vendidas", str(int(total_itens)))
    kpi_card(row2[2], "🎯 Tkt Médio p/ Venda", format_currency(ticket_venda))
    kpi_card(row2[3], "🎯 Tkt Médio p/ Unid.", format_currency(ticket_unidade))
    kpi_card(row2[4], "❌ SKU Incompleto", str(sku_incompleto))

    
    import plotly.express as px

    # =================== Gráfico de Linha + Barra de Proporção ===================
    st.markdown("### 💵 Total Vendido por Período")
    
    # 🔘 Seletor de período + agrupamento + métrica lado a lado
    colsel1, colsel2, colsel3 = st.columns([1.2, 1.2, 1.6])

    
    with colsel1:
        st.markdown("**📆 Período**")
        tipo_visualizacao = st.radio(
            label="",
            options=["Diário", "Semanal", "Quinzenal", "Mensal"],
            horizontal=True,
            key="periodo"
        )
    
    with colsel2:
        st.markdown("**👥 Agrupamento**")
        modo_agregacao = st.radio(
            label="",
            options=["Por Conta", "Total Geral"],
            horizontal=True,
            key="modo_agregacao"
        )

    with colsel3:
        st.markdown("**📏 Métrica da Barra**")
        metrica_barra = st.radio(
            "Métrica",
            ["Faturamento", "Qtd. Vendas", "Qtd. Unidades"],
            horizontal=True,
            key="metrica_barra"
        )


    
    df_plot = df.copy()
    
    # Define bucket de datas
    if de == ate:
        df_plot["date_bucket"] = df_plot["date_adjusted"].dt.floor("h")
        periodo_label = "Hora"
    else:
        if tipo_visualizacao == "Diário":
            df_plot["date_bucket"] = df_plot["date_adjusted"].dt.date
            periodo_label = "Dia"
        elif tipo_visualizacao == "Semanal":
            df_plot["date_bucket"] = df_plot["date_adjusted"].dt.to_period("W").apply(lambda p: p.start_time.date())
            periodo_label = "Semana"
        elif tipo_visualizacao == "Quinzenal":
            df_plot["quinzena"] = df_plot["date_adjusted"].apply(
                lambda d: f"{d.year}-Q{(d.month-1)*2//30 + 1}-{1 if d.day <= 15 else 2}"
            )
            df_plot["date_bucket"] = df_plot["quinzena"]
            periodo_label = "Quinzena"
        else:
            df_plot["date_bucket"] = df_plot["date_adjusted"].dt.to_period("M").astype(str)
            periodo_label = "Mês"
    
    # Agrupamento e definição de cores
    if modo_agregacao == "Por Conta":
        vendas_por_data = (
            df_plot.groupby(["date_bucket", "nickname"])["total_amount"]
            .sum()
            .reset_index(name="Valor Total")
        )
        color_dim = "nickname"
    
        total_por_conta = (
            df_plot.groupby("nickname")["total_amount"]
            .sum()
            .reset_index(name="total")
            .sort_values("total", ascending=False)
        )
    
        color_palette = px.colors.sequential.Agsunset
        nicknames = total_por_conta["nickname"].tolist()
        color_map = {nick: color_palette[i % len(color_palette)] for i, nick in enumerate(nicknames)}
    
    else:
        vendas_por_data = (
            df_plot.groupby("date_bucket")["total_amount"]
            .sum()
            .reset_index(name="Valor Total")
        )
        color_dim = None
        color_map = None  # Não será usado
        total_por_conta = None
    
    # 🔢 Gráfico(s)
    if modo_agregacao == "Por Conta":
        col1, col2 = st.columns([4, 1])
    else:
        col1 = st.container()
        col2 = None
    
    # 📈 Gráfico de Linha
    with col1:
        fig = px.line(
            vendas_por_data,
            x="date_bucket",
            y="Valor Total",
            color=color_dim,
            labels={"date_bucket": periodo_label, "Valor Total": "Valor Total", "nickname": "Conta"},
            color_discrete_map=color_map,
        )
        fig.update_traces(mode="lines+markers", marker=dict(size=5))
        fig.update_layout(
            margin=dict(t=20, b=20, l=40, r=10),
            showlegend=True
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # 📊 Gráfico de barra proporcional (somente se Por Conta)
    if modo_agregacao == "Por Conta" and not total_por_conta.empty:

    
        if metrica_barra == "Faturamento":
            base = (
                df_plot.groupby("nickname")["total_amount"]
                .sum()
                .reset_index(name="valor")
            )
        elif metrica_barra == "Qtd. Vendas":
            base = (
                df_plot.groupby("nickname")
                .size()
                .reset_index(name="valor")
            )
        else:  # Qtd. Unidades
            base = (
                df_plot.groupby("nickname")
                .apply(lambda x: (x["quantity_sku"] * x["quantity"]).sum())
                .reset_index(name="valor")
            )
    
        base = base.sort_values("valor", ascending=False)
        base["percentual"] = base["valor"] / base["valor"].sum()
    
        # 🏷️ Texto das barras
        def formatar_valor(v):
            if metrica_barra == "Faturamento":
                return f"R$ {v:,.0f}".replace(",", "v").replace(".", ",").replace("v", ".")
            elif metrica_barra == "Qtd. Vendas":
                return f"{int(v)} vendas"
            else:
                return f"{int(v)} unid."
    
        base["texto"] = base.apply(
            lambda row: f"{row['percentual']:.0%} ({formatar_valor(row['valor'])})", axis=1
        )
        base["grupo"] = "Contas"
    
        fig_bar = px.bar(
            base,
            x="grupo",
            y="percentual",
            color="nickname",
            text="texto",
            color_discrete_map=color_map,
        )
    
        fig_bar.update_layout(
            yaxis=dict(title=None, tickformat=".0%", range=[0, 1]),
            xaxis=dict(title=None),
            showlegend=False,
            margin=dict(t=20, b=20, l=10, r=10),
            height=400
        )
    
        fig_bar.update_traces(
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(color="white", size=12)
        )
    
        with col2:
            st.plotly_chart(fig_bar, use_container_width=True)




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

import time
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
from sqlalchemy import text

from db import engine
from reconcile import reconciliar_vendas

def mostrar_contas_cadastradas():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 0rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.header("🏷️ Contas Cadastradas")
    render_add_account_button()

    df = pd.read_sql(text("SELECT ml_user_id, nickname, access_token, refresh_token FROM user_tokens ORDER BY nickname"), engine)

    if df.empty:
        st.warning("Nenhuma conta cadastrada.")
        return

    st.markdown("### 🔧 Reconciliação de Vendas")

    # — 1) Modo de reconciliação —
    modo = st.radio(
        "🔄 Modo de reconciliação",
        ("Período", "Dia único"),
        index=0,
        key="modo_reconciliacao"
    )

    # — 2) Inputs de data conforme o modo —
    if modo == "Período":
        col1, col2 = st.columns(2)
        with col1:
            data_inicio = st.date_input(
                "📅 Data inicial",
                value=datetime.today() - timedelta(days=180),
                key="dt_inicio"
            )
        with col2:
            data_fim = st.date_input(
                "📅 Data final",
                value=datetime.today(),
                key="dt_fim"
            )
    else:
        data_unica = st.date_input(
            "📅 Escolha o dia",
            value=datetime.today(),
            key="dt_unico"
        )

    # — 3) Multiselect único de contas —
    contas_dict = (
        df[["nickname", "ml_user_id"]]
        .drop_duplicates()
        .set_index("nickname")["ml_user_id"]
        .astype(str)
        .to_dict()
    )
    contas_selecionadas = st.multiselect(
        "🏢 Escolha as contas para reconciliar",
        options=list(contas_dict.keys()),
        default=list(contas_dict.keys()),
        key="contas"
    )

    # — 4) Botão único para executar —
    if st.button("🧹 Reconciliar", use_container_width=True):
        if not contas_selecionadas:
            st.warning("⚠️ Nenhuma conta selecionada.")
            return

        # Define intervalo de datas
        if modo == "Período":
            desde = datetime.combine(data_inicio, datetime.min.time())
            ate   = datetime.combine(data_fim,   datetime.max.time())
        else:
            desde = datetime.combine(data_unica, datetime.min.time())
            ate   = datetime.combine(data_unica, datetime.max.time())

        # Loop de reconciliação
        contas_df = df[df["nickname"].isin(contas_selecionadas)]
        total = len(contas_df)
        progresso = st.progress(0, text="🔁 Iniciando...")
        atualizadas = erros = 0

        for i, row in enumerate(contas_df.itertuples(index=False), start=1):
            st.write(f"🔍 Conta **{row.nickname}**")
            res = reconciliar_vendas(
                ml_user_id=str(row.ml_user_id),
                desde=desde,
                ate=ate
            )
            atualizadas += res["atualizadas"]
            erros       += res["erros"]
            progresso.progress(i/total, text=f"⏳ {i}/{total}")
            time.sleep(0.05)

        progresso.empty()
        st.success(f"✅ Concluído: {atualizadas} atualizações, {erros} erros.")

    # --- Seção por conta individual ---
    for row in df.itertuples(index=False):
        with st.expander(f"🔗 Conta ML: {row.nickname}"):
            ml_user_id = str(row.ml_user_id)
            access_token = row.access_token
            refresh_token = row.refresh_token
    
            st.write(f"**User ID:** `{ml_user_id}`")
            st.write(f"**Access Token:** `{access_token}`")
            st.write(f"**Refresh Token:** `{refresh_token}`")



def mostrar_anuncios():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 0rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

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

    # 📌 ordena da venda mais nova para a mais antiga
    df_filt = df_filt.sort_values("date_adjusted", ascending=False)

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
    import time
    import pytz
    from sales import traduzir_status

    # --- CSS de espaçamento ---
    st.markdown("""
        <style>
        .block-container { padding-top: 0rem; }
        .stSelectbox > div, .stDateInput > div { padding-top: 0; padding-bottom: 0; }
        .stMultiSelect { max-height: 40px; overflow-y: auto; }
        </style>
    """, unsafe_allow_html=True)

    st.header("📋 Relatórios de Vendas")

    # --- carga e tradução de status ---
    df_full = carregar_vendas(None)
    if df_full.empty:
        st.warning("Nenhum dado encontrado.")
        return
    df_full["status"] = df_full["status"].map(traduzir_status)
    df_full["date_adjusted"] = pd.to_datetime(df_full["date_adjusted"])

    # --- Filtro de Contas Lado a Lado ---
    contas_df   = pd.read_sql(text("SELECT nickname FROM user_tokens ORDER BY nickname"), engine)
    contas_lst  = contas_df["nickname"].tolist()
    st.markdown("**🧾 Contas Mercado Livre:**")
    if "todas_contas_marcadas" not in st.session_state:
        st.session_state["todas_contas_marcadas"] = True
    cols = st.columns(8)
    selecionadas = []
    for i, conta in enumerate(contas_lst):
        key = f"rel_conta_{conta}"
        if key not in st.session_state:
            st.session_state[key] = st.session_state["todas_contas_marcadas"]
        if cols[i % 8].checkbox(conta, key=key):
            selecionadas.append(conta)
    if selecionadas:
        df_full = df_full[df_full["nickname"].isin(selecionadas)]

    # --- Filtro Rápido | De | Até | Status | Tipo de Envio ---
    col1, col2, col3, col4, col5 = st.columns([1.5, 1.2, 1.2, 1.5, 1.5])
    hoje      = pd.Timestamp.now(tz="America/Sao_Paulo").date()
    data_min  = df_full["date_adjusted"].dt.date.min()
    data_max  = df_full["date_adjusted"].dt.date.max()
    
    # === Mapeamentos e cálculos iniciais ===
    def mapear_tipo(valor):
        match valor:
            case 'fulfillment': return 'FULL'
            case 'self_service': return 'FLEX'
            case 'drop_off': return 'Correios'
            case 'xd_drop_off': return 'Agência'
            case 'cross_docking': return 'Coleta'
            case 'me2': return 'Envio Padrão'
            case _: return 'outros'
    
    df_full["Tipo de Envio"] = df_full["shipment_logistic_type"].apply(mapear_tipo)
    
    # --- Filtros ---
    with col1:
        filtro = st.selectbox(
            "📅 Período",
            ["Personalizado", "Hoje", "Ontem", "Últimos 7 Dias", "Este Mês", "Últimos 30 Dias", "Este Ano"],
            index=1, key="rel_filtro_quick"
        )
    
    if filtro == "Hoje":
        de = ate = min(hoje, data_max)
    elif filtro == "Ontem":
        de = ate = hoje - pd.Timedelta(days=1)
    elif filtro == "Últimos 7 Dias":
        de, ate = hoje - pd.Timedelta(days=6), hoje
    elif filtro == "Últimos 30 Dias":
        de, ate = hoje - pd.Timedelta(days=30), hoje
    elif filtro == "Este Mês":
        de, ate = hoje.replace(day=1), hoje
    elif filtro == "Este Ano":
        de, ate = hoje.replace(month=1, day=1), hoje
    else:
        de, ate = data_min, data_max
    
    custom = (filtro == "Personalizado")
    with col2:
        de = st.date_input("De", value=de, min_value=data_min, max_value=data_max, disabled=not custom, key="rel_de")
    with col3:
        ate = st.date_input("Até", value=ate, min_value=data_min, max_value=data_max, disabled=not custom, key="rel_ate")
    with col4:
        opts = ["Todos"] + df_full["status"].dropna().unique().tolist()
        idx = opts.index("Pago") if "Pago" in opts else 0
        status_sel = st.selectbox("Status", opts, index=idx, key="rel_status")
    with col5:
        envio_opts = ["Todos"] + sorted(df_full["Tipo de Envio"].dropna().unique())
        tipo_envio_sel = st.selectbox("Tipo de Envio", envio_opts, index=0, key="rel_tipo_envio")
    
    # --- Aplicação dos filtros ---
    df = df_full[
        (df_full["date_adjusted"].dt.date >= de) &
        (df_full["date_adjusted"].dt.date <= ate)
    ]
    if status_sel != "Todos":
        df = df[df["status"] == status_sel]
    if tipo_envio_sel != "Todos":
        df = df[df["Tipo de Envio"] == tipo_envio_sel]


    # --- Filtros Avançados: Hierarquia 1 e 2 ---
    with st.expander("🔍 Filtros Avançados", expanded=False):
        # Hierarquia 1
        l1_opts = sorted(df["level1"].dropna().unique())
        st.markdown("**📂 Hierarquia 1**")
        cols1 = st.columns(4)
        sel1 = [op for i,op in enumerate(l1_opts) if cols1[i%4].checkbox(op, key=f"rel_l1_{op}")]
        if sel1:
            df = df[df["level1"].isin(sel1)]
        # Hierarquia 2
        l2_opts = sorted(df["level2"].dropna().unique())
        st.markdown("**📁 Hierarquia 2**")
        cols2 = st.columns(4)
        sel2 = [op for i,op in enumerate(l2_opts) if cols2[i%4].checkbox(op, key=f"rel_l2_{op}")]
        if sel2:
            df = df[df["level2"].isin(sel2)]

    if df.empty:
        st.warning("Nenhuma venda após filtros.")
        return

    # --- Ordena por timestamp completo ---
    df = df.sort_values("date_adjusted", ascending=False).copy()

    # --- Monta colunas finais ---
    df["Data"]                   = df["date_adjusted"].dt.strftime("%d/%m/%Y %H:%M:%S")
    df["ID DA VENDA"]            = df["order_id"]
    df["CONTA"]                  = df["nickname"]
    df["TÍTULO DO ANÚNCIO"]      = df["item_title"]
    df["SKU DO PRODUTO"]         = df["seller_sku"]
    df["HIERARQUIA 1"]           = df["level1"]
    df["HIERARQUIA 2"]           = df["level2"]
    df["QUANTIDADE"]             = df["quantity_sku"] * df["quantity"]
    df["VALOR DA VENDA"]         = df["total_amount"]
    df["TAXA DA PLATAFORMA"] = df["ml_fee"].fillna(0) * -1
    df["CUSTO DE FRETE"]     = df["frete_adjust"].fillna(0) 
    df["CMV"]                = (
        df["quantity_sku"].fillna(0)
        * df["quantity"].fillna(0)
        * df["custo_unitario"].fillna(0)
    ) * -1
    df["MARGEM DE CONTRIBUIÇÃO"] = (
        df["VALOR DA VENDA"]
        + df["TAXA DA PLATAFORMA"]
        + df["CUSTO DE FRETE"]
        + df["CMV"]
    )

    cols_final = [
        "ID DA VENDA","CONTA","Data","TÍTULO DO ANÚNCIO","SKU DO PRODUTO",
        "HIERARQUIA 1","HIERARQUIA 2","QUANTIDADE","VALOR DA VENDA",
        "TAXA DA PLATAFORMA","CUSTO DE FRETE","CMV","MARGEM DE CONTRIBUIÇÃO"
    ]
    st.dataframe(df[cols_final], use_container_width=True)



def mostrar_gestao_sku():
    st.markdown("""
        <style>
        .block-container {
            padding-top: 0rem;
        }
        </style>
    """, unsafe_allow_html=True)

    st.header("📦 Gestão de SKU")

    if st.button("🔄 Recarregar Dados"):
        st.session_state["atualizar_gestao_sku"] = True

    # === Consulta de combinações únicas ===
    if st.session_state.get("atualizar_gestao_sku", False) or "df_gestao_sku" not in st.session_state:
        df = pd.read_sql(text("""
            SELECT
                seller_sku,
                level1,
                level2,
                custo_unitario,
                quantity_sku,
                COUNT(DISTINCT item_id) AS qtde_vendas
            FROM sales
            WHERE seller_sku IS NOT NULL
            GROUP BY
                seller_sku,
                level1,
                level2,
                custo_unitario,
                quantity_sku
            ORDER BY seller_sku
        """), engine)
        st.session_state["df_gestao_sku"] = df
        st.session_state["atualizar_gestao_sku"] = False
    else:
        df = st.session_state["df_gestao_sku"]

    # === Métricas ===
    with engine.begin() as conn:
        vendas_sem_sku = conn.execute(text("SELECT COUNT(*) FROM sales WHERE seller_sku IS NULL")).scalar()
        mlbs_sem_sku = conn.execute(text("SELECT COUNT(DISTINCT item_id) FROM sales WHERE seller_sku IS NULL")).scalar()
        sku_incompleto = conn.execute(text("""
            SELECT COUNT(DISTINCT seller_sku)
            FROM sales
            WHERE seller_sku IS NOT NULL AND (
                level1 IS NULL OR level2 IS NULL OR custo_unitario IS NULL OR quantity_sku IS NULL
            )
        """)).scalar()

    col1, col2, col3 = st.columns(3)
    col1.metric("🚫 Vendas sem SKU", vendas_sem_sku)
    col2.metric("📦 MLBs sem SKU", mlbs_sem_sku)
    col3.metric("⚠️ SKUs com Cadastro Incompleto", sku_incompleto)

    st.markdown("---")
    st.markdown("### 🔍 Filtros de Diagnóstico")

    # === Filtros ===
    colf1, colf2, colf3, colf4, colf5 = st.columns([1.2, 1.2, 1.2, 1.2, 2])
    op_sku     = colf1.selectbox("Seller SKU", ["Todos", "Nulo", "Não Nulo"])
    op_level1  = colf2.selectbox("Hierarquia 1", ["Todos", "Nulo", "Não Nulo"])
    op_level2  = colf3.selectbox("Hierarquia ", ["Todos", "Nulo", "Não Nulo"])
    op_preco   = colf4.selectbox("Preço Unitário", ["Todos", "Nulo", "Não Nulo"])
    filtro_txt = colf5.text_input("🔎 Pesquisa (SKU, Hierarquias)")

    # === Aplicar filtros ===
    if op_sku == "Nulo":
        df = df[df["seller_sku"].isna()]
    elif op_sku == "Não Nulo":
        df = df[df["seller_sku"].notna()]
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
        df = df[df.apply(lambda row: filtro_txt in str(row["seller_sku"]).lower()
                         or filtro_txt in str(row["level1"]).lower()
                         or filtro_txt in str(row["level2"]).lower(), axis=1)]

    # === Tabela editável ===
    st.markdown("### 📝 Editar Cadastro de SKUs")

    colunas_editaveis = ["level1", "level2", "custo_unitario", "quantity_sku"]

    df_editado = st.data_editor(
        df,
        use_container_width=True,
        disabled=[col for col in df.columns if col not in colunas_editaveis],
        num_rows="dynamic",
        key="editor_sku"
    )

    # === Salvar alterações ===
    if st.button("💾 Salvar Alterações"):
        try:
            with engine.begin() as conn:
                for _, row in df_editado.iterrows():
                    conn.execute(text("""
                        INSERT INTO sku (sku, level1, level2, custo_unitario, quantity, date_created)
                        VALUES (:sku, :level1, :level2, :custo, :quantidade, NOW())
                        ON CONFLICT (sku) DO UPDATE
                        SET
                            level1 = EXCLUDED.level1,
                            level2 = EXCLUDED.level2,
                            custo_unitario = EXCLUDED.custo_unitario,
                            quantity = EXCLUDED.quantity
                    """), {
                        "sku": row["seller_sku"],
                        "level1": row["level1"],
                        "level2": row["level2"],
                        "custo": row["custo_unitario"],
                        "quantidade": row["quantity_sku"]
                    })

                conn.execute(text("""
                    UPDATE sales s
                    SET
                        level1 = sku.level1,
                        level2 = sku.level2,
                        custo_unitario = sku.custo_unitario,
                        quantity_sku = sku.quantity
                    FROM (
                        SELECT DISTINCT ON (sku) * FROM sku
                        ORDER BY sku, date_created DESC
                    ) sku
                    WHERE s.seller_sku = sku.sku
                """))

            st.success("✅ Alterações salvas com sucesso!")
            st.session_state["atualizar_gestao_sku"] = True
            st.rerun()

        except Exception as e:
            st.error(f"❌ Erro ao salvar alterações: {e}")

    # === Mostrar MLBs sem SKU com edição ===
    st.markdown("---")
    st.markdown("### 📋 MLBs sem SKU (Editar e Salvar)")
    
    # Carrega os MLBs sem SKU e traz título do anúncio e a conta (nickname)
    df_sem_sku = pd.read_sql(text("""
        SELECT 
            s.item_id AS "ID do Anúncio",
            s.item_title AS "Título do Anúncio",
            ut.nickname AS "Conta",
            s.quantity_sku AS "Quantidade",
            s.date_adjusted AS "Data do Pedido",
            s.seller_sku AS "SKU (Preencher)"
        FROM sales s
        LEFT JOIN user_tokens ut ON s.ml_user_id = ut.ml_user_id
        WHERE s.seller_sku IS NULL
        ORDER BY s.date_adjusted DESC
    """), engine)
    
    # Define colunas editáveis (somente SKU pode ser editado)
    colunas_editaveis_sem_sku = ["SKU (Preencher)"]
    
    # Tabela editável
    df_sem_sku_editado = st.data_editor(
        df_sem_sku,
        use_container_width=True,
        disabled=[col for col in df_sem_sku.columns if col not in colunas_editaveis_sem_sku],
        num_rows="dynamic",
        key="editor_sem_sku"
    )
    
    # Botão para salvar alterações
    if st.button("💾 Salvar Alterações nos MLBs sem SKU"):
        try:
            with engine.begin() as conn:
                for _, row in df_sem_sku_editado.iterrows():
                    if row["SKU (Preencher)"]:  # Apenas atualiza se o SKU foi preenchido
                        # Valida se o SKU existe na tabela sku
                        sku_info = conn.execute(text("""
                            SELECT level1, level2, custo_unitario, quantity
                            FROM sku
                            WHERE sku = :seller_sku
                            LIMIT 1
                        """), {"seller_sku": row["SKU (Preencher)"].strip()}).fetchone()
    
                        if sku_info:
                            # Atualiza sales com o SKU e dados relacionados
                            conn.execute(text("""
                                UPDATE sales
                                SET
                                    seller_sku = :seller_sku,
                                    level1 = :level1,
                                    level2 = :level2,
                                    custo_unitario = :custo_unitario,
                                    quantity_sku = :quantity
                                WHERE item_id = :item_id
                            """), {
                                "seller_sku": row["SKU (Preencher)"].strip(),
                                "level1": sku_info.level1,
                                "level2": sku_info.level2,
                                "custo_unitario": sku_info.custo_unitario,
                                "quantity": sku_info.quantity,
                                "item_id": row["ID do Anúncio"]
                            })
                        else:
                            st.warning(f"⚠️ SKU '{row['SKU (Preencher)']}' não encontrado na base de SKUs. Corrija antes de salvar.")
    
            st.success("✅ Alterações salvas com sucesso!")
            st.session_state["atualizar_gestao_sku"] = True
            st.rerun()
        except Exception as e:
            st.error(f"❌ Erro ao salvar alterações: {e}")


    # 5️⃣ Atualização da base SKU via planilha
    st.markdown("---")
    st.markdown("### 📥 Atualizar Base de SKUs via Planilha")

    modelo = pd.DataFrame(columns=["seller_sku", "level1", "level2", "custo_unitario", "quantity"])
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
        colunas_esperadas = {"seller_sku", "level1", "level2", "custo_unitario", "quantity"}
        if not colunas_esperadas.issubset(df_novo.columns):
            st.error("❌ A planilha deve conter: seller_sku, level1, level2, custo_unitario, quantity.")
        else:
            if st.button("✅ Processar Planilha e Atualizar"):
                try:
                    df_novo["quantity"] = df_novo["quantity"].fillna(0).astype(int)
                    df_novo["custo_unitario"] = df_novo["custo_unitario"].fillna(0).astype(float)
                    df_novo["seller_sku"] = df_novo["seller_sku"].astype(str).strip()
                    df_novo["level1"] = df_novo["level1"].astype(str).strip()
                    df_novo["level2"] = df_novo["level2"].astype(str).strip()

                    with engine.begin() as conn:
                        for _, row in df_novo.iterrows():
                            row_dict = row.to_dict()
                            result = conn.execute(text("""
                                SELECT 1 FROM sku
                                WHERE sku = :seller_sku
                                  AND TRIM(level1) = :level1
                                  AND TRIM(level2) = :level2
                                  AND ROUND(CAST(custo_unitario AS numeric), 2) = ROUND(CAST(:custo_unitario AS numeric), 2)
                                  AND quantity = :quantity
                                LIMIT 1
                            """), row_dict).fetchone()

                            if result is None:
                                conn.execute(text("""
                                    INSERT INTO sku (sku, level1, level2, custo_unitario, quantity, date_created)
                                    VALUES (:seller_sku, :level1, :level2, :custo_unitario, :quantity, NOW())
                                """), row_dict)

                        # Atualizar tabela de vendas
                        conn.execute(text("""
                            UPDATE sales s
                            SET
                                level1 = sku.level1,
                                level2 = sku.level2,
                                custo_unitario = sku.custo_unitario,
                                quantity_sku = sku.quantity
                            FROM (
                                SELECT DISTINCT ON (sku) *
                                FROM sku
                                ORDER BY sku, date_created DESC
                            ) sku
                            WHERE s.seller_sku = sku.sku
                        """))

                    # Recarregar métricas e dados
                    st.session_state["atualizar_gestao_sku"] = True
                    st.success("✅ Planilha importada, vendas atualizadas, métricas e tabela recarregadas!")
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Erro ao processar: {e}")

    # 6️⃣ Adição manual de SKU dentro de um expander
    st.markdown("---")
    with st.expander("➕ Adicionar SKU Manualmente"):
        st.markdown("Preencha os campos abaixo para cadastrar um novo SKU diretamente na base:")

        with st.form("adicionar_sku_form"):
            seller_sku_manual = st.text_input("🔑 Seller SKU *", "")
            level1_manual = st.text_input("📂 Level 1", "")
            level2_manual = st.text_input("📂 Level 2", "")
            custo_manual = st.number_input("💲 Custo Unitário", min_value=0.0, step=0.01, format="%.2f")
            quantity_manual = st.number_input("📦 Quantidade", min_value=0, step=1)
            submitted = st.form_submit_button("✅ Cadastrar SKU")

            if submitted:
                if not seller_sku_manual.strip():
                    st.error("❌ O campo 'Seller SKU' é obrigatório.")
                else:
                    try:
                        with engine.begin() as conn:
                            conn.execute(text("""
                                INSERT INTO sku (sku, level1, level2, custo_unitario, quantity, date_created)
                                VALUES (:sku, :level1, :level2, :custo, :quantidade, NOW())
                                ON CONFLICT (sku) DO UPDATE
                                SET
                                    level1 = EXCLUDED.level1,
                                    level2 = EXCLUDED.level2,
                                    custo_unitario = EXCLUDED.custo_unitario,
                                    quantity = EXCLUDED.quantity
                            """), {
                                "sku": seller_sku_manual.strip(),
                                "level1": level1_manual.strip() or None,
                                "level2": level2_manual.strip() or None,
                                "custo": custo_manual,
                                "quantidade": quantity_manual
                            })

                            # Atualizar tabela de vendas
                            conn.execute(text("""
                                UPDATE sales s
                                SET
                                    level1 = sku.level1,
                                    level2 = sku.level2,
                                    custo_unitario = sku.custo_unitario,
                                    quantity_sku = sku.quantity
                                FROM (
                                    SELECT DISTINCT ON (sku) * FROM sku
                                    ORDER BY sku, date_created DESC
                                ) sku
                                WHERE s.seller_sku = sku.sku
                            """))

                        st.success("✅ SKU adicionado com sucesso!")
                        st.session_state["atualizar_gestao_sku"] = True
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ Erro ao adicionar SKU: {e}")


def mostrar_expedicao_logistica(df: pd.DataFrame):
    import streamlit as st
    import plotly.express as px
    import pandas as pd
    from io import BytesIO
    import base64
    from datetime import datetime
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
    )
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib import colors
    import pytz
    from sales import traduzir_status

    # Estilo
    st.markdown(  
        """
        <style>
        .block-container { padding-top: 0rem; }
        </style>
        """, unsafe_allow_html=True
    )
    st.header("🚚 Expedição e Logística")

    if df.empty:
        st.warning("Nenhum dado encontrado.")
        return

    # === Mapeamentos e cálculos iniciais ===
    def mapear_tipo(valor):
        match valor:
            case 'fulfillment': return 'FULL'
            case 'self_service': return 'FLEX'
            case 'drop_off': return 'Correios'
            case 'xd_drop_off': return 'Agência'
            case 'cross_docking': return 'Coleta'
            case 'me2': return 'Envio Padrão'
            case _: return 'outros'

    df["Tipo de Envio"] = df["shipment_logistic_type"].apply(mapear_tipo)

    # Garantir que 'shipment_delivery_sla' esteja em datetime
    if "shipment_delivery_sla" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["shipment_delivery_sla"]):
        df["shipment_delivery_sla"] = pd.to_datetime(df["shipment_delivery_sla"], errors="coerce")

    # Cálculo de quantidade
    if "quantity" in df.columns and "quantity_sku" in df.columns:
        df["quantidade"] = df["quantity"] * df["quantity_sku"]
    else:
        st.error("Colunas 'quantity' e/ou 'quantity_sku' não encontradas.")
        st.stop()

    # Data da venda
    if "date_adjusted" not in df.columns:
        st.error("Coluna 'date_adjusted' não encontrada.")
        st.stop()
    df["data_venda"] = pd.to_datetime(df["date_adjusted"]).dt.date

    # Conversão para fuso de SP
    def _to_sp_date(x):
        if pd.isna(x):
            return pd.NaT
        ts = pd.to_datetime(x, utc=True)
        return ts.tz_convert("America/Sao_Paulo").date()

    if "shipment_delivery_sla" in df.columns:
        df["shipment_delivery_sla"] = pd.to_datetime(df["shipment_delivery_sla"], utc=True, errors="coerce")
        df["data_limite"] = df["shipment_delivery_sla"].apply(
            lambda x: x.tz_convert("America/Sao_Paulo").date() if pd.notnull(x) else pd.NaT
        )
    else:
        df["data_limite"] = pd.NaT
    
    import pytz
    hoje = pd.Timestamp.now(tz="America/Sao_Paulo").date()

    data_min_venda = df["data_venda"].dropna().min()
    data_max_venda = df["data_venda"].dropna().max()

    data_min_limite = df["data_limite"].dropna().min()
    data_max_limite = df["data_limite"].dropna().max()
    if pd.isna(data_min_limite):
        data_min_limite = hoje
    if pd.isna(data_max_limite) or data_max_limite < data_min_limite:
        data_max_limite = data_min_limite + pd.Timedelta(days=7)

    # === UNIFICADO 1: Datas (Venda + Expedição) + Filtro de Período (só Expedição) ===
    
    # --- Linha 1: Período + Despacho Limite ---
    col1, col2, col3 = st.columns([1.5, 1.2, 1.2])
    
    with col1:
        periodo = st.selectbox(
            "Filtrar Período de Expedição",
            [
                "Período Personalizado",
                "Ontem",
                "Hoje",
                "Amanhã",
                "Depois de Amanhã",
                "Próximos 7 Dias",
                "Este Mês",
                "Próximos 30 Dias",
                "Este Ano"
            ],
            index=2,
            key="filtro_expedicao_periodo"
        )
    
        # Define intervalo padrão com base no filtro
    import pytz
    from pandas.tseries.offsets import MonthEnd, YearEnd
    
    # Data atual no fuso de SP
    hoje = pd.Timestamp.now(tz="America/Sao_Paulo").date()
    
    if periodo == "Hoje":
        de_limite_default = ate_limite_default = min(hoje, data_max_limite)
    
    elif periodo == "Amanhã":
        de_limite_default = ate_limite_default = hoje + pd.Timedelta(days=1)

    elif periodo == "Depois de Amanhã":
        de_limite_default = ate_limite_default = hoje + pd.Timedelta(days=2)
    
    elif periodo == "Ontem":
        de_limite_default = ate_limite_default = hoje - pd.Timedelta(days=1)
    
    elif periodo == "Próximos 7 Dias":
        de_limite_default = hoje + pd.Timedelta(days=1)
        ate_limite_default = de_limite_default + pd.Timedelta(days=6)
    
    elif periodo == "Próximos 30 Dias":
        de_limite_default = hoje + pd.Timedelta(days=1)
        ate_limite_default = de_limite_default + pd.Timedelta(days=29)
    
    elif periodo == "Este Mês":
        de_limite_default = hoje.replace(day=1)
        ate_limite_default = (hoje + MonthEnd(0)).date()
    
    elif periodo == "Este Ano":
        de_limite_default = hoje.replace(month=1, day=1)
        ate_limite_default = (hoje + YearEnd(0)).date()
    
    else:  # Período Personalizado
        de_limite_default, ate_limite_default = data_min_limite, data_max_limite



    # Ajuste para não extrapolar as datas mínimas/máximas disponíveis
    de_limite_default = max(de_limite_default, data_min_limite)
    de_limite_default = min(de_limite_default, data_max_limite)
    ate_limite_default = max(ate_limite_default, data_min_limite)
    ate_limite_default = min(ate_limite_default, data_max_limite)
    
    modo_personalizado = (periodo == "Período Personalizado")
    
    with col2:
        de_limite = st.date_input(
            "Despacho Limite de:",
            value=de_limite_default,
            min_value=data_min_limite,
            max_value=data_max_limite,
            disabled=not modo_personalizado
        )
    with col3:
        ate_limite = st.date_input(
            "Despacho Limite até:",
            value=ate_limite_default,
            min_value=data_min_limite,
            max_value=data_max_limite,
            disabled=not modo_personalizado
        )
    
    if not modo_personalizado:
        de_limite = de_limite_default
        ate_limite = ate_limite_default
    
    # --- Linha 2: Venda de / até ---
    col_v1, col_v2 = st.columns(2)
    
    with col_v1:
        de_venda = st.date_input(
            "Venda de:",
            value=data_min_venda,
            min_value=data_min_venda,
            max_value=data_max_venda,
            key="data_venda_de"
        )
    with col_v2:
        ate_venda = st.date_input(
            "Venda até:",
            value=data_max_venda,
            min_value=data_min_venda,
            max_value=data_max_venda,
            key="data_venda_ate"
        )

    # --- Aplicar filtro por data de venda e expedição no DataFrame base ---
    df = df[
        (df["data_venda"] >= de_venda) & (df["data_venda"] <= ate_venda) &
        (df["data_limite"].isna() |
         ((df["data_limite"] >= de_limite) & (df["data_limite"] <= ate_limite)))
    ]

    df_filtrado = df.copy()
    
    # --- Linha 3: Conta, Status, Status Envio, Tipo de Envio ---
    col6, col7, col8 = st.columns(3)
    
    with col6:
        contas = df["nickname"].dropna().unique().tolist()
        conta = st.selectbox("Conta", ["Todos"] + sorted(contas))
    
    with col7:
        status_traduzido = sorted(df["status"].dropna().unique().tolist())
        status_ops = ["Todos"] + status_traduzido
        index_padrao = status_ops.index("Pago") if "Pago" in status_ops else 0
        status = st.selectbox("Status", status_ops, index=index_padrao)
    
    with col8:
        status_data_envio = st.selectbox(
            "Status Envio",
            ["Todos", "Com Data de Envio", "Sem Data de Envio"],
            index=1
        )
    

    # --- Aplicar filtros restantes ---

    if conta != "Todos":
        df_filtrado = df_filtrado[df_filtrado["nickname"] == conta]
    if status != "Todos":
        df_filtrado = df_filtrado[df_filtrado["status"] == status]
    if status_data_envio == "Com Data de Envio":
        df_filtrado = df_filtrado[df_filtrado["data_limite"].notna()]
    elif status_data_envio == "Sem Data de Envio":
        df_filtrado = df_filtrado[df_filtrado["data_limite"].isna()]
    
    
    # Aqui entra o bloco com os filtros de hierarquia
    with st.expander("🔍 Filtros Avançados", expanded=False):

        # Tipo de Envio (Checkboxes)
        tipo_envio_opcoes = sorted(df_filtrado["Tipo de Envio"].dropna().unique().tolist())
        st.markdown("**🚚 Tipo de Envio**")
        col_envio = st.columns(4)
        tipo_envio_selecionados = []
        for i, op in enumerate(tipo_envio_opcoes):
            if col_envio[i % 4].checkbox(op, key=f"tipo_envio_{op}"):
                tipo_envio_selecionados.append(op)
        if tipo_envio_selecionados:
            df_filtrado = df_filtrado[df_filtrado["Tipo de Envio"].isin(tipo_envio_selecionados)]
    
        # Hierarquia 1
        level1_opcoes = sorted(df_filtrado["level1"].dropna().unique().tolist())
        st.markdown("**📂 Hierarquia 1**")
        col_l1 = st.columns(4)
        level1_selecionados = []
        for i, op in enumerate(level1_opcoes):
            if col_l1[i % 4].checkbox(op, key=f"filtros_level1_{op}"):
                level1_selecionados.append(op)
        if level1_selecionados:
            df_filtrado = df_filtrado[df_filtrado["level1"].isin(level1_selecionados)]
    
        # Hierarquia 2
        level2_opcoes = sorted(df_filtrado["level2"].dropna().unique().tolist())
        st.markdown("**📁 Hierarquia 2**")
        col_l2 = st.columns(4)
        level2_selecionados = []
        for i, op in enumerate(level2_opcoes):
            if col_l2[i % 4].checkbox(op, key=f"filtros_level2_{op}"):
                level2_selecionados.append(op)
        if level2_selecionados:
            df_filtrado = df_filtrado[df_filtrado["level2"].isin(level2_selecionados)]


    # Verificação final
    if df_filtrado.empty:
        st.warning("Nenhum dado encontrado com os filtros aplicados.")
        return


    df_filtrado = df_filtrado.copy()
    df_filtrado["Canal de Venda"] = "MERCADO LIVRE"
    
    df_filtrado["Data Limite do Envio"] = df_filtrado["data_limite"].apply(
        lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "—"
    )


    tabela = df_filtrado[[
        "order_id",                  
        "shipment_receiver_name",    
        "nickname",                  
        "Tipo de Envio",            
        "quantidade",              
        "level1",                    
        "Data Limite do Envio"     
    ]].rename(columns={
        "order_id": "ID VENDA",
        "shipment_receiver_name": "NOME CLIENTE",
        "nickname": "CONTA",
        "Tipo de Envio": "TIPO DE ENVIO",
        "quantidade": "QUANTIDADE",
        "level1": "PRODUTO [HIERARQUIA 1]",
        "Data Limite do Envio": "DATA DE ENVIO"
    })

    
    # Ordenar pela quantidade em ordem decrescente
    tabela = tabela.sort_values(by="QUANTIDADE", ascending=False)
    
    # === KPIs ===
    total_vendas = len(df_filtrado)
    total_quantidade = int(df_filtrado["quantidade"].sum())
    
    k1, k2 = st.columns(2)
    with k1:
        st.metric(label="Total de Vendas Filtradas", value=f"{total_vendas:,}")
    with k2:
        st.metric(label="Quantidade Total", value=f"{total_quantidade:,}")
    
    # em seguida exibe a tabela
    st.markdown("### 📋 Tabela de Expedição por Venda")
    st.dataframe(tabela, use_container_width=True, height=500)

    df_grouped = df_filtrado.groupby("level1", as_index=False).agg({"quantidade": "sum"})
    df_grouped = df_grouped.rename(columns={"level1": "Hierarquia 1", "quantidade": "Quantidade"})
    
    # Ordenar do maior para o menor
    df_grouped = df_grouped.sort_values(by="Quantidade", ascending=False)
    
    fig_bar = px.bar(
        df_grouped,
        x="Hierarquia 1",
        y="Quantidade",
        text="Quantidade",  # Adiciona o rótulo
        barmode="group",
        height=400,
        color_discrete_sequence=["#2ECC71"]
    )
    
    # Ajustar posição dos rótulos (em cima)
    fig_bar.update_traces(textposition="outside")
    
    # Ajustar layout para não cortar os rótulos
    fig_bar.update_layout(uniformtext_minsize=8, uniformtext_mode='hide', margin=dict(t=40, b=40))
    
    st.plotly_chart(fig_bar, use_container_width=True)


    # === TABELAS LADO A LADO COM UNIDADES E VENDAS ===
    st.markdown("### 📊 Resumo por Agrupamento")
    col_r1, col_r2, col_r3 = st.columns(3)
    
    # ===== Tabela 1: Hierarquia 1 =====
    df_h1 = (
        df_filtrado
        .groupby("level1", as_index=False)
        .agg(
            Unidade=("quantidade", "sum"),
            Vendas=("order_id", "nunique")
        )
        .rename(columns={"level1": "Hierarquia 1"})
    )
    tot_q1 = df_h1["Unidade"].sum()
    tot_v1 = df_h1["Vendas"].sum()
    df_h1 = pd.concat([
        df_h1,
        pd.DataFrame({
            "Hierarquia 1": ["Total"],
            "Unidade": [tot_q1],
            "Vendas": [tot_v1]
        })
    ], ignore_index=True)
    with col_r1:
        st.dataframe(df_h1, use_container_width=True, hide_index=True)
    
    # ===== Tabela 2: Hierarquia 2 =====
    df_h2 = (
        df_filtrado
        .groupby("level2", as_index=False)
        .agg(
            Unidade=("quantidade", "sum"),
            Vendas=("order_id", "nunique")
        )
        .rename(columns={"level2": "Hierarquia 2"})
    )
    tot_q2 = df_h2["Unidade"].sum()
    tot_v2 = df_h2["Vendas"].sum()
    df_h2 = pd.concat([
        df_h2,
        pd.DataFrame({
            "Hierarquia 2": ["Total"],
            "Unidade": [tot_q2],
            "Vendas": [tot_v2]
        })
    ], ignore_index=True)
    with col_r2:
        st.dataframe(df_h2, use_container_width=True, hide_index=True)
    
    # ===== Tabela 3: Tipo de Envio =====
    df_tipo = (
        df_filtrado
        .groupby("Tipo de Envio", as_index=False)
        .agg(
            Unidade=("quantidade", "sum"),
            Vendas=("order_id", "nunique")
        )
    )
    tot_qt = df_tipo["Unidade"].sum()
    tot_vt = df_tipo["Vendas"].sum()
    df_tipo = pd.concat([
        df_tipo,
        pd.DataFrame({
            "Tipo de Envio": ["Total"],
            "Unidade": [tot_qt],
            "Vendas": [tot_vt]
        })
    ], ignore_index=True)
    with col_r3:
        st.dataframe(df_tipo, use_container_width=True, hide_index=True)



    def gerar_relatorio_pdf(
        tabela_df, df_h1, df_h2, df_tipo,
        periodo_venda, periodo_expedicao
    ):
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                leftMargin=20, rightMargin=20,
                                topMargin=20, bottomMargin=20)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            name="CenteredTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            fontSize=16
        )
        normal = styles["Normal"]
        elems = []
    
        # --- Cabeçalho ---
        try:
            logo = Image("favicon.png", width=50, height=50)
        except:
            logo = Paragraph("", normal)
        titulo = Paragraph("Relatório de Expedição e Logística", title_style)
        header = Table([[logo, titulo]], colWidths=[60, 460])
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN",  (1, 0), (1, 0), "CENTER"),
            ("LEFTPADDING",  (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ]))
        elems.append(header)
        elems.append(Spacer(1, 8))
    
        # --- Períodos ---
        txt = (
            f"<b>Venda:</b> {periodo_venda[0].strftime('%d/%m/%Y')} ↔ {periodo_venda[1].strftime('%d/%m/%Y')}<br/>"
            f"<b>Expedição:</b> {periodo_expedicao[0].strftime('%d/%m/%Y')} ↔ {periodo_expedicao[1].strftime('%d/%m/%Y')}"
        )
        elems.append(Paragraph(txt, normal))
        elems.append(Spacer(1, 12))
    
        # --- KPIs em mini-tabela ---
        total_vendas     = len(tabela_df)
        total_quantidade = int(tabela_df["QUANTIDADE"].fillna(0).sum())
        page_w, _ = A4
        usable_w = page_w - doc.leftMargin - doc.rightMargin
        kpi_data = [
            ["Total de Vendas Filtradas", f"{total_vendas:,}"],
            ["Quantidade Total",          f"{total_quantidade:,}"]
        ]
        kpi_table = Table(kpi_data, colWidths=[usable_w*0.5, usable_w*0.5])
        kpi_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.whitesmoke),
            ("BACKGROUND",   (0, 1), (-1, 1), colors.lightgrey),
            ("TEXTCOLOR",    (0, 0), (-1, -1), colors.black),
            ("ALIGN",        (0, 0), (-1, -1), "LEFT"),
            ("FONTSIZE",     (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("GRID",         (0, 0), (-1, -1), 0.25, colors.grey),
        ]))
        elems.append(kpi_table)
        elems.append(Spacer(1, 12))
    
        # --- Tabela principal ---
        main = tabela_df.copy()
        main["QUANTIDADE"] = main["QUANTIDADE"].fillna(0).astype(int)
        data = [main.columns.tolist()] + main.values.tolist()
        tab = Table(data, repeatRows=1, splitByRow=1)
        tab.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), colors.lightgrey),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.black),
            ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
            ("FONTSIZE",     (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, 0), 6),
            ("GRID",         (0, 0), (-1, -1), 0.25, colors.grey),
        ]))
        elems.append(tab)
        elems.append(PageBreak())
    
        # --- Preparar resumos para o PDF ---
        def _prep_summary(df, label):
            df = df.copy()
            cols = df.columns.tolist()
            return df.rename(columns={
                cols[0]: label,
                "Quantidade_Unidades": "Quantidade",
                "Quantidade_de_Vendas": "Quantidade de Vendas"
            })
    
        df_h1_pdf   = _prep_summary(df_h1,   "Hierarquia 1")
        df_h2_pdf   = _prep_summary(df_h2,   "Hierarquia 2")
        df_tipo_pdf = _prep_summary(df_tipo, "Tipo de Envio")
    
        def resume(df, title):
            d = df.copy()
            for col in d.columns[1:]:
                d[col] = d[col].fillna(0).astype(int)
            data = [d.columns.tolist()] + d.values.tolist()
            t = Table(data, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
                ("ALIGN",      (0,0), (-1,-1), "CENTER"),
                ("FONTSIZE",   (0,0), (-1,-1), 6),
                ("GRID",       (0,0), (-1,-1), 0.25, colors.grey),
            ]))
            return [Paragraph(title, styles["Heading3"]), Spacer(1,4), t]
    
        # --- Página de resumo: Hierarquia 1 ---
        elems.extend(resume(df_h1_pdf, "Hierarquia 1"))
        elems.append(PageBreak())
    
        # --- Página de resumo: Hierarquia 2 ---
        elems.extend(resume(df_h2_pdf, "Hierarquia 2"))
        elems.append(PageBreak())
    
        # --- Página de resumo: Tipo de Envio ---
        elems.extend(resume(df_tipo_pdf, "Tipo de Envio"))
        # (não precisa de PageBreak() final se for a última página)
    
        # --- Build e links ---
        doc.build(elems)
    
        pdf_b64 = base64.b64encode(buffer.getvalue()).decode()
        href_pdf = (
            f'<a style="margin-right:20px;" '
            f'href="data:application/pdf;base64,{pdf_b64}" '
            f'download="relatorio_expedicao.pdf">📄 Baixar PDF</a>'
        )
    
        xlsx_buf = BytesIO()
        with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as w:
            main.to_excel(w, index=False, sheet_name="Dados")
            df_h1.to_excel(w, index=False, sheet_name="Hierarquia_1")
            df_h2.to_excel(w, index=False, sheet_name="Hierarquia_2")
            df_tipo.to_excel(w, index=False, sheet_name="Tipo_Envio")
        xlsx_b64 = base64.b64encode(xlsx_buf.getvalue()).decode()
        href_xlsx = (
            f'<a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{xlsx_b64}" '
            f'download="relatorio_expedicao.xlsx">⬇️ Baixar Excel</a>'
        )
    
        return href_pdf + href_xlsx

    # -- logo após os blocos de st.dataframe das 3 tabelas de resumo --
    periodo_venda     = (de_venda, ate_venda)
    periodo_expedicao = (de_limite, ate_limite)
    botoes = gerar_relatorio_pdf(
        tabela, df_h1, df_h2, df_tipo,
        periodo_venda, periodo_expedicao
    )
    st.markdown(botoes, unsafe_allow_html=True)

from sqlalchemy import text
import streamlit as st
import pandas as pd
from datetime import datetime
from utils import engine  # 🔥 usa seu engine já configurado

def mostrar_painel_metas():
    from datetime import datetime
    import pandas as pd
    import streamlit as st
    from sqlalchemy import text
    import plotly.graph_objects as go

    # ======== Data atual ========
    hoje = datetime.now()
    ano_mes_atual = hoje.strftime("%Y-%m")

    if st.button("⚙️ Configurações", key="config_btn"):
        st.session_state.show_config = True
        st.rerun()

    # ======== Carregar Meta Mensal ========
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT meta_unidades FROM meta_mensal WHERE ano_mes = :ano_mes"),
            {"ano_mes": ano_mes_atual}
        ).fetchone()
        meta_mensal = result[0] if result else 0

    # ======== Carregar Produção do Mês ========
    with engine.connect() as conn:
        df_producao = pd.read_sql(
            text("""
                SELECT data, quantidade
                FROM producao_diaria
                WHERE TO_CHAR(data, 'YYYY-MM') = :ano_mes
                ORDER BY data
            """),
            conn,
            params={"ano_mes": ano_mes_atual}
        )
    producao_mes = df_producao["quantidade"].sum()
    percentual_atingido = (producao_mes / meta_mensal) * 100 if meta_mensal else 0

    # ======== Definir cores dinâmicas ========
    cor_percentual = (
        "#2ecc71" if percentual_atingido >= 80 else
        "#f1c40f" if percentual_atingido >= 50 else
        "#e74c3c"
    )

    # ======== Estilo customizado ========
    st.markdown(f"""
        <style>
            body {{
                background-color: #0e1117;
                color: #fff;
            }}
            .container {{
                display: flex;
                justify-content: space-evenly;
                align-items: flex-start;
                margin-top: -30px;  /* 🔥 cards bem no topo */
                margin-bottom: 50px;  /* espaço abaixo dos cards */
            }}
            .title {{
                font-size: 1.6rem;
                text-align: center;
                margin-bottom: 6px;
                color: #d1d1d1;
            }}
            .card {{
                background-color: #1f2630;
                border-radius: 16px;
                padding: 16px;
                text-align: center;
                width: 25%;
                box-shadow: 0 0 12px rgba(0,0,0,0.3);
            }}
            .card-number {{
                font-size: 2.8rem;
                font-weight: bold;
                color: #ffffff;
                white-space: nowrap;
            }}
        </style>
    """, unsafe_allow_html=True)

    # ======== Blocos principais ========
    st.markdown(f"""
        <div class="container">
            <div class="card">
                <div class="title">🎯 Meta do Mês</div>
                <div class="card-number">{meta_mensal:,}</div>
            </div>
            <div class="card">
                <div class="title">🏭 Produção Atual</div>
                <div class="card-number">{producao_mes:,}</div>
            </div>
            <div class="card">
                <div class="title">📊 % Atingido</div>
                <div class="card-number" style="color:{cor_percentual};">{percentual_atingido:.1f}%</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # ======== Velocímetro (Gauge) ========
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=percentual_atingido,
        number={'suffix': "%", 'font': {'size': 40}},
        title={'text': "Progresso Mensal (%)", 'font': {'size': 22}},
        gauge={
            'axis': {'range': [0, 100]},
            'bar': {'color': cor_percentual, 'thickness': 0.3},
            'steps': [
                {'range': [0, 50], 'color': "#e74c3c"},
                {'range': [50, 80], 'color': "#f1c40f"},
                {'range': [80, 100], 'color': "#2ecc71"}
            ],
            'threshold': {
                'line': {'color': "white", 'width': 4},
                'thickness': 0.75,
                'value': 100
            }
        }
    ))
    fig_gauge.update_layout(margin=dict(t=40, b=40, l=30, r=30))  # 🔥 mais espaço acima/abaixo
    st.plotly_chart(fig_gauge, use_container_width=True)

    # ======== Barra de Progresso ========
    st.markdown(f"""
        <div style="width: 85%; height: 25px; background-color: #333; border-radius: 12px; margin: 50px auto 30px auto;">
            <div style="
                width: {min(percentual_atingido, 100)}%;
                height: 100%;
                background-color: {cor_percentual};
                border-radius: 12px;
                transition: width 0.5s ease-in-out;">
            </div>
        </div>
    """, unsafe_allow_html=True)

    # ======== Botão de Configuração ========
    if "show_config" not in st.session_state:
        st.session_state.show_config = False


    if st.session_state.show_config:
        st.markdown("---")
        st.subheader("⚙️ Configurações")

        # ======= Seleção de Mês/Ano para Meta =======
        st.markdown("#### 📆 Definir Meta Mensal")
        col1, col2 = st.columns(2)
        with col1:
            mes_meta = st.selectbox(
                "Mês",
                options=list(range(1, 13)),
                format_func=lambda x: datetime(1900, x, 1).strftime("%B").capitalize(),
                index=hoje.month - 1
            )
        with col2:
            ano_meta = st.selectbox(
                "Ano",
                options=list(range(hoje.year - 5, hoje.year + 6)),
                index=5
            )
        ano_mes_meta = f"{ano_meta}-{mes_meta:02d}"

        nova_meta = st.number_input(
            f"Definir Meta para {ano_mes_meta} (unidades)",
            min_value=0,
            value=meta_mensal if ano_mes_meta == ano_mes_atual else 0,
            step=100
        )
        if st.button("💾 Salvar Meta"):
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO meta_mensal (ano_mes, meta_unidades)
                        VALUES (:ano_mes, :meta)
                        ON CONFLICT (ano_mes) DO UPDATE
                        SET meta_unidades = EXCLUDED.meta_unidades
                    """),
                    {"ano_mes": ano_mes_meta, "meta": nova_meta}
                )
            st.success(f"✅ Meta atualizada para {ano_mes_meta} com sucesso!")
            st.rerun()

        # ======= Seleção de Dia para Produção =======
        st.markdown("#### 🏭 Registrar Produção Diária")
        data_producao = st.date_input("📅 Data da Produção", hoje)
        producao_hoje = st.number_input(
            f"Produção em {data_producao.strftime('%d/%m/%Y')} (unidades)",
            min_value=0,
            step=10
        )
        if st.button("➕ Registrar Produção"):
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO producao_diaria (data, quantidade)
                        VALUES (:data, :qtd)
                        ON CONFLICT (data) DO UPDATE
                        SET quantidade = EXCLUDED.quantidade
                    """),
                    {"data": data_producao.strftime("%Y-%m-%d"), "qtd": producao_hoje}
                )
            st.success(f"✅ Produção registrada para {data_producao.strftime('%d/%m/%Y')}!")
            st.rerun()

        # ======= Histórico Produção =======
        st.markdown("### 📊 Histórico de Produção")
        st.dataframe(df_producao.rename(
            columns={"data": "Data", "quantidade": "Unidades"}
        ), use_container_width=True)

        if st.button("🔙 Voltar ao Painel"):
            st.session_state.show_config = False
            st.rerun()


import streamlit as st
from sqlalchemy import text
import pandas as pd
from datetime import datetime

def mostrar_supply_chain():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 0rem;
        }
        .stTextInput, .stSelectbox, .stDateInput {
            width: 100%;
        }
        .stForm {
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    
    st.header("🚚 Supply Chain - Compra de Insumos")
    st.info("Aqui você pode registrar e analisar as compras de insumos.")

    # === Formulário de Compra de Insumo (dentro de expander) ===
    with st.expander("➕ Registrar Nova Compra", expanded=False):
        with st.form("form_compra_insumo", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                fornecedor = st.selectbox("Fornecedor *", ["Selecione um Fornecedor"] + get_fornecedores())
            
            with col2:
                insumos_df = get_insumos_df()
                insumo_options = [
                    f"{row['descricao']} | {row['categoria']} | {row['classificacao']} | {row['cores']} | {row['medida']}{row['unidade_medida']}"
                    for _, row in insumos_df.iterrows()
                ]
                insumo = st.selectbox("Insumo *", ["Selecione um Insumo"] + insumo_options)
            
            with col3:
                quantidade = st.number_input("Quantidade *", min_value=1, step=1)
            
            col1, col2 = st.columns(2)
            with col1:
                preco_unitario = st.number_input("Preço Unitário *", format="%.2f", min_value=0.0)
            
            with col2:
                data_compra = st.date_input("Data da Compra *", value=datetime.today())
            
            col1, col2 = st.columns(2)
            with col1:
                data_entrega = st.date_input("Data de Entrega Esperada", value=datetime.today())
            
            observacoes = st.text_area("Observações")
            
            submitted = st.form_submit_button("💾 Salvar Compra")
            
            if submitted:
                try:
                    with engine.begin() as conn:
                        conn.execute(text("""
                            INSERT INTO compras_insumos (
                                fornecedor_id, insumo_id, quantidade, preco_unitario,
                                total_compra, data_compra, data_entrega_esperada, observacoes
                            ) VALUES (
                                (SELECT id FROM fornecedores WHERE empresa_nome = :fornecedor),
                                (SELECT id FROM insumos WHERE descricao = :insumo),
                                :quantidade, :preco_unitario,
                                :total_compra, :data_compra, :data_entrega, :observacoes
                            )
                        """), {
                            "fornecedor": fornecedor,
                            "insumo": insumo.split(" | ")[0],  # pega só a descrição
                            "quantidade": quantidade,
                            "preco_unitario": preco_unitario,
                            "total_compra": quantidade * preco_unitario,
                            "data_compra": data_compra,
                            "data_entrega": data_entrega,
                            "observacoes": observacoes
                        })
                    st.success("✅ Compra registrada com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao registrar compra: {e}")

    # === Filtros ===
    st.markdown("### 🔍 Filtros de Pesquisa")
    col1, col2, col3 = st.columns(3)
    with col1:
        filtro_fornecedor = st.selectbox("Fornecedor", ["Todos"] + get_fornecedores())
    with col2:
        insumos_df = get_insumos_df()
        insumo_options = [
            f"{row['descricao']} | {row['categoria']} | {row['classificacao']} | {row['cores']} | {row['medida']}{row['unidade_medida']}"
            for _, row in insumos_df.iterrows()
        ]
        filtro_insumo = st.selectbox("Insumo", ["Todos"] + insumo_options)
    with col3:
        filtro_data_inicio = st.date_input("Data Início", value=datetime.today())
    
    # Data fim em linha abaixo
    filtro_data_fim = st.date_input("Data Fim", value=datetime.today())

    # === Consultar e Exibir Compras ===
    try:
        compras = get_compras(filtro_fornecedor, filtro_insumo, filtro_data_inicio, filtro_data_fim)
        if compras.empty:
            st.info("📭 Nenhuma compra encontrada com os filtros aplicados.")
        else:
            st.dataframe(compras, use_container_width=True)
    except Exception as e:
        st.error(f"❌ Erro ao carregar compras: {e}")

# === Funções auxiliares ===
def get_fornecedores():
    query = "SELECT empresa_nome FROM fornecedores ORDER BY empresa_nome"
    df = pd.read_sql(query, engine)
    return df["empresa_nome"].tolist()

def get_insumos_df():
    query = """
        SELECT descricao, categoria, classificacao, cores, medida, unidade_medida
        FROM insumos
        ORDER BY descricao
    """
    return pd.read_sql(query, engine)

def get_compras(fornecedor, insumo, data_inicio, data_fim):
    query = """
        SELECT ci.id, f.empresa_nome AS fornecedor, i.descricao AS insumo,
               ci.quantidade, ci.preco_unitario, ci.total_compra,
               ci.data_compra, ci.data_entrega_esperada, ci.observacoes
        FROM compras_insumos ci
        JOIN fornecedores f ON ci.fornecedor_id = f.id
        JOIN insumos i ON ci.insumo_id = i.id
        WHERE ci.data_compra BETWEEN :data_inicio AND :data_fim
    """
    params = {"data_inicio": data_inicio, "data_fim": data_fim}

    if fornecedor != "Todos":
        query += " AND f.empresa_nome = :fornecedor"
        params["fornecedor"] = fornecedor
    
    if insumo != "Todos":
        insumo_descricao = insumo.split(" | ")[0]  # pega só a descrição
        query += " AND i.descricao = :insumo"
        params["insumo"] = insumo_descricao

    return pd.read_sql(text(query), engine, params=params)

def mostrar_gerenciar_cadastros():
    import streamlit as st
    from sqlalchemy import text
    import pandas as pd
    from io import BytesIO

    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 0rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.header("📝 Gerenciar Cadastros")
    st.info("Aqui você pode criar, editar e gerenciar seus cadastros.")

    # === Abas para cada tipo de cadastro ===
    aba = st.radio(
        "Escolha o tipo de cadastro:",
        ["🏢 Fornecedores", "👥 Stakeholders", "🧱 Insumos"],
        horizontal=True
    )

    def gerar_excel_modelo(df_modelo, nome_arquivo):
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_modelo.to_excel(writer, index=False, sheet_name="Modelo")
        output.seek(0)
        st.download_button(
            label=f"⬇️ Baixar modelo {nome_arquivo}",
            data=output,
            file_name=f"{nome_arquivo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def importar_excel(table_name, df_upload):
        try:
            df_upload.to_sql(table_name, con=engine, if_exists="append", index=False)
            st.success("✅ Dados importados com sucesso!")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Erro ao importar dados: {e}")

    # ==============================
    # FORNECEDORES
    # ==============================
    if aba == "🏢 Fornecedores":
        st.subheader("🏢 Cadastro de Fornecedores")

        # 🔽 Modelo para download
        df_modelo = pd.DataFrame({
            "empresa_nome": [""],
            "cnpj": [""],
            "referencia_nome": [""],
            "whatsapp": [""],
            "endereco_completo": [""],
            "tipo_insumo": [""]
        })
        gerar_excel_modelo(df_modelo, "fornecedores_modelo")

        # 📤 Upload do arquivo Excel
        file = st.file_uploader("📤 Importar Fornecedores (Excel)", type=["xlsx"])
        if file:
            try:
                df_upload = pd.read_excel(file)
                if set(df_modelo.columns).issubset(df_upload.columns):
                    st.dataframe(df_upload, use_container_width=True)
                    if st.button("📥 Importar Fornecedores para o Banco"):
                        importar_excel("fornecedores", df_upload)
                else:
                    st.error("❌ O arquivo não possui todas as colunas necessárias.")
            except Exception as e:
                st.error(f"❌ Erro ao ler o arquivo: {e}")

        # === Formulário manual
        with st.form("form_fornecedor", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                empresa_nome = st.text_input("Nome da Empresa *")
                cnpj = st.text_input("CNPJ")
                referencia_nome = st.text_input("Nome de Referência")
            with col2:
                whatsapp = st.text_input("WhatsApp")
                endereco_completo = st.text_area("Endereço Completo")
                tipo_insumo = st.text_input("Tipo de Insumo")

            submitted = st.form_submit_button("➕ Adicionar Fornecedor")
            if submitted:
                if empresa_nome.strip() == "":
                    st.warning("⚠️ Nome da Empresa é obrigatório.")
                else:
                    try:
                        with engine.begin() as conn:
                            conn.execute(text("""
                                INSERT INTO fornecedores (
                                    empresa_nome, cnpj, referencia_nome,
                                    whatsapp, endereco_completo, tipo_insumo
                                ) VALUES (
                                    :empresa_nome, :cnpj, :referencia_nome,
                                    :whatsapp, :endereco_completo, :tipo_insumo
                                )
                            """), {
                                "empresa_nome": empresa_nome,
                                "cnpj": cnpj,
                                "referencia_nome": referencia_nome,
                                "whatsapp": whatsapp,
                                "endereco_completo": endereco_completo,
                                "tipo_insumo": tipo_insumo
                            })
                        st.success("✅ Fornecedor adicionado com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao adicionar fornecedor: {e}")

        # === Lista de fornecedores cadastrados ===
        try:
            df = pd.read_sql("SELECT * FROM fornecedores ORDER BY id DESC", engine)
            if df.empty:
                st.info("📭 Nenhum fornecedor cadastrado ainda.")
            else:
                st.dataframe(df, use_container_width=True)
        except Exception as e:
            st.error(f"❌ Erro ao carregar fornecedores: {e}")

    # ==============================
    # STAKEHOLDERS
    # ==============================
    elif aba == "👥 Stakeholders":
        st.subheader("👥 Cadastro de Stakeholders")

        # 🔽 Modelo para download
        df_modelo = pd.DataFrame({
            "relacao": [""],
            "nome": [""],
            "whatsapp": [""],
            "observacao": [""]
        })
        gerar_excel_modelo(df_modelo, "stakeholders_modelo")

        # 📤 Upload do arquivo Excel
        file = st.file_uploader("📤 Importar Stakeholders (Excel)", type=["xlsx"])
        if file:
            try:
                df_upload = pd.read_excel(file)
                if set(df_modelo.columns).issubset(df_upload.columns):
                    st.dataframe(df_upload, use_container_width=True)
                    if st.button("📥 Importar Stakeholders para o Banco"):
                        importar_excel("stakeholders", df_upload)
                else:
                    st.error("❌ O arquivo não possui todas as colunas necessárias.")
            except Exception as e:
                st.error(f"❌ Erro ao ler o arquivo: {e}")

        # === Formulário manual
        with st.form("form_stakeholder", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                relacao = st.selectbox("Relação *", ["Colaborador", "Sócio", "Outro"])
                nome = st.text_input("Nome *")
            with col2:
                whatsapp = st.text_input("WhatsApp")
                observacao = st.text_area("Observações")

            submitted = st.form_submit_button("➕ Adicionar Stakeholder")
            if submitted:
                if nome.strip() == "":
                    st.warning("⚠️ Nome é obrigatório.")
                else:
                    try:
                        with engine.begin() as conn:
                            conn.execute(text("""
                                INSERT INTO stakeholders (
                                    relacao, nome, whatsapp, observacao
                                ) VALUES (
                                    :relacao, :nome, :whatsapp, :observacao
                                )
                            """), {
                                "relacao": relacao,
                                "nome": nome,
                                "whatsapp": whatsapp,
                                "observacao": observacao
                            })
                        st.success("✅ Stakeholder adicionado com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao adicionar stakeholder: {e}")

        # === Lista de stakeholders cadastrados ===
        try:
            df = pd.read_sql("SELECT * FROM stakeholders ORDER BY id DESC", engine)
            if df.empty:
                st.info("📭 Nenhum stakeholder cadastrado ainda.")
            else:
                st.dataframe(df, use_container_width=True)
        except Exception as e:
            st.error(f"❌ Erro ao carregar stakeholders: {e}")

    # ==============================
    # INSUMOS
    # ==============================
    elif aba == "🧱 Insumos":
        st.subheader("🧱 Cadastro de Insumos")

        # 🔽 Modelo para download
        df_modelo = pd.DataFrame({
            "descricao": [""],
            "categoria": [""],
            "classificacao": [""],
            "unidade_medida": [""],
            "medida": [""],
            "cores": [""],
            "observacao": [""]
        })
        gerar_excel_modelo(df_modelo, "insumos_modelo")

        # 📤 Upload do arquivo Excel
        file = st.file_uploader("📤 Importar Insumos (Excel)", type=["xlsx"])
        if file:
            try:
                df_upload = pd.read_excel(file)
                if set(df_modelo.columns).issubset(df_upload.columns):
                    st.dataframe(df_upload, use_container_width=True)
                    if st.button("📥 Importar Insumos para o Banco"):
                        importar_excel("insumos", df_upload)
                else:
                    st.error("❌ O arquivo não possui todas as colunas necessárias.")
            except Exception as e:
                st.error(f"❌ Erro ao ler o arquivo: {e}")

        # === Formulário manual
        with st.form("form_insumo", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                descricao = st.text_input("Descrição do Insumo *")
                categoria = st.text_input("Categoria do Insumo")
                classificacao = st.selectbox("Classificação", ["Bruto", "Acabado"])
            with col2:
                unidade_medida = st.selectbox("Unidade de Medida *", ["mm", "cm", "m", "und", "L", "Kg"])
                medida = st.text_input("Medida")
                cores = st.text_input("Cor(es) (separadas por vírgula)")
            observacao = st.text_area("Observações")

            submitted = st.form_submit_button("➕ Adicionar Insumo")
            if submitted:
                if descricao.strip() == "":
                    st.warning("⚠️ Descrição do Insumo é obrigatória.")
                else:
                    try:
                        with engine.begin() as conn:
                            conn.execute(text("""
                                INSERT INTO insumos (
                                    descricao, categoria, classificacao,
                                    unidade_medida, medida, cores, observacao
                                ) VALUES (
                                    :descricao, :categoria, :classificacao,
                                    :unidade_medida, :medida, :cores, :observacao
                                )
                            """), {
                                "descricao": descricao,
                                "categoria": categoria,
                                "classificacao": classificacao,
                                "unidade_medida": unidade_medida,
                                "medida": medida,
                                "cores": cores,
                                "observacao": observacao
                            })
                        st.success("✅ Insumo adicionado com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao adicionar insumo: {e}")

        # === Lista de insumos cadastrados ===
        try:
            df = pd.read_sql("SELECT * FROM insumos ORDER BY id DESC", engine)
            if df.empty:
                st.info("📭 Nenhum insumo cadastrado ainda.")
            else:
                st.dataframe(df, use_container_width=True)
        except Exception as e:
            st.error(f"❌ Erro ao carregar insumos: {e}")


# ----------------- Adicionar página Calculadora -----------------
def mostrar_calculadora_custos():
    import streamlit as st
    import pandas as pd
    from sqlalchemy import text
    from datetime import datetime
    from utils import engine
    from io import BytesIO

    st.markdown("""
        <style>
        .block-container { padding-top: 0rem; }
        .input-container {
            background-color: #1f2630;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            margin-bottom: 20px;
        }
        .remove-button {
            background-color: #ff4b4b;
            color: white;
            border: none;
            border-radius: 5px;
            padding: 5px 10px;
            cursor: pointer;
            margin-top: -10px;
        }
        </style>
    """, unsafe_allow_html=True)

    st.header("🧮 Calculadora de Custo Unitário")
    st.info("Simule o custo unitário do produto informando os insumos e seus detalhes.")

    # 🔄 Carregar opções do banco de dados
    with engine.connect() as conn:
        insumos_df = pd.read_sql(
            text("SELECT descricao, categoria, classificacao, medida, unidade_medida FROM insumos ORDER BY descricao"),
            conn
        )

    # 🏷️ Nome do produto simulado
    produto_simulado = st.text_input("📦 Nome do Produto Simulado")

    # Inicializar sessão
    if "insumos_config" not in st.session_state:
        st.session_state.insumos_config = []

    # ➕ Adicionar novo insumo
    if st.button("➕ Adicionar Insumo"):
        st.session_state.insumos_config.append({
            "insumo": None,
            "quantidade": 0.0,
            "rendimento": 1.0,
            "preco": 0.0
        })

    # Renderizar insumos configurados
    for idx, config in enumerate(st.session_state.insumos_config):
        with st.container():
            # Cabeçalho com botão remover
            col_header1, col_header2 = st.columns([8, 1])
            with col_header1:
                st.markdown(f"### 🔧 Configuração do Insumo #{idx + 1}")
            with col_header2:
                if st.button("❌", key=f"remove_{idx}"):
                    st.session_state.insumos_config.pop(idx)
                    st.rerun()

            # Dropdown concatenado com as colunas relevantes
            insumo_options = [
                f"{row.descricao} | {row.categoria} | {row.classificacao} | {row.cores} | {row.medida}{row.unidade_medida}"
                for _, row in insumos_df.iterrows()
            ]
            selected_insumo = st.selectbox(
                "Selecione o Insumo",
                options=insumo_options,
                index=insumo_options.index(config["insumo"]) if config["insumo"] in insumo_options else 0,
                key=f"insumo_{idx}"
            )
            st.session_state.insumos_config[idx]["insumo"] = selected_insumo

            # Inputs
            col1, col2, col3 = st.columns(3)
            with col1:
                quantidade = st.number_input(
                    "Quantidade usada (unidade)",
                    min_value=0.0, step=0.01,
                    key=f"qtd_{idx}"
                )
                st.session_state.insumos_config[idx]["quantidade"] = quantidade

            with col2:
                rendimento = st.number_input(
                    "Rendimento (quantidade produzida)",
                    min_value=0.01, step=0.01,
                    key=f"rend_{idx}"
                )
                st.session_state.insumos_config[idx]["rendimento"] = rendimento

            with col3:
                preco = st.number_input(
                    "Preço do insumo (R$/unidade)",
                    min_value=0.0, step=0.01,
                    key=f"preco_{idx}"
                )
                st.session_state.insumos_config[idx]["preco"] = preco

    # 📊 Calcular custo unitário
    if st.button("📊 Calcular Custo Unitário"):
        total_custo = 0
        detalhes = []

        for item in st.session_state.insumos_config:
            if item["insumo"] is None:
                continue
            custo_total_insumo = (item["quantidade"] / item["rendimento"]) * item["preco"]
            total_custo += custo_total_insumo
            detalhes.append({
                "Insumo": item["insumo"],
                "Quantidade Usada": item["quantidade"],
                "Rendimento": item["rendimento"],
                "Preço (R$)": item["preco"],
                "Custo Total (R$)": custo_total_insumo
            })

        # Mostrar resultados
        st.markdown("## 📈 **Resultado Final**")
        st.metric("💵 Custo Unitário Total", f"R$ {total_custo:,.2f}")

        df_detalhes = pd.DataFrame(detalhes)
        st.markdown("### 📋 Detalhamento dos Insumos")
        st.dataframe(df_detalhes, use_container_width=True)

        # Exportação para Excel
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_detalhes.to_excel(writer, index=False, sheet_name="Custo_Unitario")
            summary_df = pd.DataFrame({"Produto": [produto_simulado], "Custo Total": [total_custo]})
            summary_df.to_excel(writer, index=False, sheet_name="Resumo")
        output.seek(0)
        st.download_button(
            label="⬇️ Exportar Detalhamento (Excel)",
            data=output,
            file_name="detalhamento_custo_unitario.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        # ✅ Salvar no banco
        if st.button("💾 Salvar Simulação no Banco"):
            try:
                with engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO cotacoes (data_simulacao, produto, custo_unitario)
                        VALUES (:data_simulacao, :produto, :custo_unitario)
                    """), {
                        "data_simulacao": datetime.now(),
                        "produto": produto_simulado,
                        "custo_unitario": total_custo
                    })
                st.success("✅ Simulação salva no banco com sucesso!")
            except Exception as e:
                st.error(f"❌ Erro ao salvar no banco: {e}")



# ----------------- Fluxo Principal -----------------
if "code" in st.query_params:
    ml_callback()

df_vendas = carregar_vendas()

pagina = render_sidebar()
if pagina == "Dashboard":
    mostrar_dashboard()
elif pagina == "Contas Cadastradas":
    mostrar_contas_cadastradas()
elif pagina == "Relatórios":
    mostrar_relatorios()
elif pagina == "Expedição":
    mostrar_expedicao_logistica(df_vendas)
elif pagina == "Gestão de SKU":
    mostrar_gestao_sku()
elif pagina == "Painel de Metas":
    mostrar_painel_metas()
elif pagina == "Supply Chain":
    mostrar_supply_chain()
elif pagina == "Gestão de Anúncios":
    mostrar_anuncios()
elif pagina == "Gerenciar Cadastros":
    mostrar_gerenciar_cadastros()
elif pagina == "Calculadora de Custos":
    mostrar_calculadora_custos()
