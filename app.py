import os
import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import locale
from typing import Optional

# Tenta configurar locale pt_BR; guarda se deu certo
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
    LOCALE_OK = True
except locale.Error:
    LOCALE_OK = False

def format_currency(valor: float) -> str:
    """
    Formata um float como BRL:
    - Usa locale se LOCALE_OK for True;
    - Senão, faz um fallback manual 'R$ 1.234,56'.
    """
    if LOCALE_OK:
        try:
            return locale.currency(valor, grouping=True)
        except Exception:
            pass
    # Fallback manual:
    inteiro, frac = f"{valor:,.2f}".split('.')
    inteiro = inteiro.replace(',', '.')
    return f"R$ {inteiro},{frac}"

# ----------------- Configuração da Página -----------------
st.set_page_config(
    page_title="Dashboard de Vendas - NEXUS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ----------------- Autenticação -----------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

params = st.query_params
# login automático via ?nexus_auth=success
if params.get("nexus_auth", [None])[0] == "success":
    st.session_state["authenticated"] = True
    st.experimental_set_query_params()

if not st.session_state["authenticated"]:
    st.title("Sistema de Gestão - Grupo Nexus")
    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if username == "GRUPONEXUS" and password == "NEXU$2025":
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Credenciais inválidas")
    st.stop()

# ----------------- Título -----------------
st.title("Nexus Dashboard")

# ----------------- Variáveis de Ambiente -----------------
load_dotenv()
BACKEND_URL  = os.getenv("BACKEND_URL")
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
        carregar_vendas.clear()             # limpa cache para puxar vendas novas
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
            SELECT date_created, item_title, status, quantity, total_amount
              FROM sales
             WHERE ml_user_id = :uid
        """)
        df = pd.read_sql(sql, engine, params={"uid": conta_id})
    else:
        sql = text("""
            SELECT date_created, item_title, status, quantity, total_amount
              FROM sales
        """)
        df = pd.read_sql(sql, engine)
    df["date_created"] = pd.to_datetime(df["date_created"])
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

def render_sidebar():
    pages = ["Dashboard", "Contas Cadastradas", "Relatórios", "Expedição e Logística"]
    if "page" not in st.session_state:
        st.session_state["page"] = pages[0]
    st.sidebar.markdown("<div class='sidebar-title'>Navegação</div>", unsafe_allow_html=True)
    for pg in pages:
        if st.sidebar.button(pg, key=pg):
            st.session_state["page"] = pg
    return st.session_state["page"]

# ----------------- Telas -----------------
def mostrar_dashboard():
    st.header("📊 Dashboard de Vendas")

    # 0) Carrega dados brutos (todas as contas) para popular filtros
    df_full = carregar_vendas(None)
    if df_full.empty:
        st.warning("Nenhuma venda cadastrada.")
        return

    # ——————————————————————————————————————————
    # 1) Layout dos filtros em linha
    # ——————————————————————————————————————————
    # Colunas: [Conta (maior), De, Até, Status (maior)]
    col1, col2, col3, col4 = st.columns([2, 1, 1, 2])

    # 1.1) Filtro de Conta
    contas_df   = pd.read_sql(text("SELECT ml_user_id FROM user_tokens ORDER BY ml_user_id"), engine)
    contas_lst  = contas_df["ml_user_id"].astype(str).tolist()
    escolha     = col1.selectbox("🔹 Conta", ["Todas as contas"] + contas_lst)
    conta_id    = None if escolha == "Todas as contas" else escolha

    # 1.2) Filtro de Data De / Até
    data_min = df_full["date_created"].dt.date.min()
    data_max = df_full["date_created"].dt.date.max()
    de  = col2.date_input("🔹 De",  value=data_min, min_value=data_min, max_value=data_max)
    ate = col3.date_input("🔹 Até", value=data_max, min_value=data_min, max_value=data_max)

    # 1.3) Filtro de Status
    status_opts = df_full["status"].unique().tolist()
    status_sel  = col4.multiselect("🔹 Status", options=status_opts, default=status_opts)

    # 1.4) Busca Livre (fora das colunas, ocupa a largura total)
    busca = st.text_input("🔹 Busca livre", placeholder="Título do anúncio, MLB, etc…")

    # ——————————————————————————————————————————
    # 2) Aplica filtros ao DataFrame carregado por conta
    # ——————————————————————————————————————————
    df = carregar_vendas(conta_id)
    # período
    df = df.loc[
        (df["date_created"].dt.date >= de) &
        (df["date_created"].dt.date <= ate)
    ]
    # status
    df = df[df["status"].isin(status_sel)]
    # busca livre
    if busca:
        df = df[df["item_title"].str.contains(busca, case=False, na=False)]

    if df.empty:
        st.warning("Nenhuma venda encontrada para os filtros selecionados.")
        return

    # ——————————————————————————————————————————
    # 3) Cálculo de Métricas
    # ——————————————————————————————————————————
    total_vendas = len(df)
    total_valor  = df["total_amount"].sum()
    total_itens  = df["quantity"].sum()
    ticket_medio = total_valor / total_vendas if total_vendas else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧾 Vendas", total_vendas)
    c2.metric("💰 Receita total", format_currency(total_valor))
    c3.metric("📦 Itens vendidos", int(total_itens))
    c4.metric("🎯 Ticket médio", format_currency(ticket_medio))

    # ——————————————————————————————————————————
    # 4) Gráfico de Linha: Total Vendido por Dia
    # ——————————————————————————————————————————
    vendas_por_dia = (
        df
        .groupby(df["date_created"].dt.date)["total_amount"]
        .sum()
        .reset_index(name="total_amount")
    )
    fig = px.line(
        vendas_por_dia,
        x="date_created",
        y="total_amount",
        title="💵 Total Vendido por Dia"
    )
    st.plotly_chart(fig, use_container_width=True)

    # ——————————————————————————————————————————
    # 5) Download do CSV Filtrado
    # ——————————————————————————————————————————
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Baixar CSV das vendas",
        data=csv_bytes,
        file_name="vendas_filtradas.csv",
        mime="text/csv"
    )

    # ——————————————————————————————————————————
    # 8) Botão de Download do CSV Filtrado
    # ——————————————————————————————————————————
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Baixar CSV das vendas",
        data=csv_bytes,
        file_name="vendas_filtradas.csv",
        mime="text/csv"
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
                    salvar_tokens_no_banco(data)
                    st.success("Token atualizado com sucesso!")
                else:
                    st.error("Erro ao atualizar o token.")

def mostrar_relatorios():
    st.header("📋 Relatórios de Vendas")
    df = carregar_vendas()
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
    st.header("🚚 Expedição e Logística")
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
