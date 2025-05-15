import os
import io
from datetime import date, timedelta
from typing import Optional

import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import locale
from streamlit_option_menu import option_menu

# --- Page Config & Locale ---
st.set_page_config(
    page_title="Dashboard de Vendas - NEXUS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
    LOCALE_OK = True
except locale.Error:
    LOCALE_OK = False

def format_currency(val: float) -> str:
    if LOCALE_OK:
        try:
            return locale.currency(val, grouping=True)
        except:
            pass
    i, f = f"{val:,.2f}".split('.')
    return f"R$ {i.replace(',', '.')},{f}"

# --- Env & DB ---
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL")
DB_URL = os.getenv("DB_URL")
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID")
if not all([BACKEND_URL, FRONTEND_URL, DB_URL, ML_CLIENT_ID]):
    st.error("❌ Defina variáveis de ambiente no .env")
    st.stop()
engine = create_engine(DB_URL, pool_size=5, max_overflow=10)

# --- Auth State ---
if "auth" not in st.session_state:
    st.session_state["auth"] = False
if not st.session_state["auth"]:
    st.sidebar.title("Login")
    user = st.sidebar.text_input("Usuário")
    pwd = st.sidebar.text_input("Senha", type="password")
    if st.sidebar.button("Entrar"):
        if user == "GRUPONEXUS" and pwd == "NEXU$2025":
            st.session_state["auth"] = True
            st.experimental_rerun()
        else:
            st.sidebar.error("Credenciais inválidas")
    st.stop()

# --- OAuth Callback ---
def ml_callback():
    params = st.experimental_get_query_params()
    code = params.get("code", [None])[0]
    if code:
        resp = requests.post(f"{BACKEND_URL}/auth/callback", json={"code": code})
        if resp.ok:
            data = resp.json()
            save_tokens(data)
            try:
                carregar_vendas.clear()
            except:
                pass
            st.experimental_rerun()
        else:
            st.error(f"Autenticação falhou: {resp.text}")

# --- Token Storage ---
def save_tokens(d: dict):
    query = text("""
        INSERT INTO user_tokens (ml_user_id, access_token, refresh_token, expires_at)
        VALUES (:u,:a,:r,NOW()+interval '6 hours')
        ON CONFLICT (ml_user_id) DO UPDATE SET
          access_token=EXCLUDED.access_token,
          refresh_token=EXCLUDED.refresh_token,
          expires_at=NOW()+interval '6 hours';
    """)
    with engine.begin() as conn:
        conn.execute(query, {"u": d["user_id"], "a": d["access_token"], "r": d["refresh_token"]})

# --- Load Sales with Cache ---
@st.cache_data(ttl=300)
def carregar_vendas(conta: Optional[str] = None) -> pd.DataFrame:
    sql = "SELECT ml_user_id, order_id, date_created, item_title, status, quantity, total_amount FROM sales"
    params = {}
    if conta:
        sql += " WHERE ml_user_id = :u"
        params = {"u": conta}
    df = pd.read_sql(text(sql), engine, params=params)
    df["date_created"] = (
        pd.to_datetime(df["date_created"], utc=True)
          .dt.tz_convert("America/Sao_Paulo")
          .dt.tz_localize(None)
    )
    return df

# --- Sidebar Menu ---
def sidebar_menu() -> str:
    with st.sidebar:
        st.title("Nexus")
        return option_menu(
            None,
            ["Dashboard", "Contas", "Relatórios", "Logística"],
            icons=["house", "link", "file-text", "truck"],
            default_index=0,
            styles={"nav-link-selected": {"background-color": "#2ecc71"}}
        )

# --- Dashboard Screen ---
def dash():
    st.header("📊 Dashboard de Vendas")
    df = carregar_vendas()
    if df.empty:
        st.warning("Nenhuma venda registrada.")
        return

    # Filtros
    c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
    # Contas
    contas = ["Todas"] + df["ml_user_id"].astype(str).unique().tolist()
    sel_contas = c1.multiselect("Contas", contas, default=["Todas"])
    if "Todas" not in sel_contas:
        df = df[df["ml_user_id"].astype(str).isin(sel_contas)]
    # Período
    opts = {"Hoje": (date.today(), date.today()),
            "Últimos 7 dias": (date.today() - timedelta(days=7), date.today()),
            "Este mês": (date.today().replace(day=1), date.today()),
            "Últimos 30 dias": (date.today() - timedelta(days=30), date.today())}
    escolha = c2.selectbox("Período", list(opts.keys()))
    d0, d1 = opts[escolha]
    df = df[(df["date_created"].dt.date >= d0) & (df["date_created"].dt.date <= d1)]
    # Status
    stats = ["Todos"] + df["status"].dropna().unique().tolist()
    st_sel = c3.selectbox("Status", stats)
    if st_sel != "Todos":
        df = df[df["status"] == st_sel]
    # Busca
    query = c4.text_input("Busca (regex ou vírgulas)")
    if query:
        pattern = "(" + "|".join([p.strip() for p in query.split(",")]) + ")"
        df = df[df["item_title"].str.contains(pattern, case=False, na=False, regex=True) |
                df["order_id"].astype(str).str.contains(pattern, case=False, na=False, regex=True)]

    if df.empty:
        st.warning("Nenhum registro para filtros aplicados.")
        return

    # Métricas
    total = len(df)
    receita = df["total_amount"].sum()
    itens = int(df["quantity"].sum())
    ticket = receita / total if total else 0
    cols = st.columns(4)
    cols[0].metric("Vendas", total)
    cols[1].metric("Receita", format_currency(receita))
    cols[2].metric("Itens", itens)
    cols[3].metric("Ticket Médio", format_currency(ticket))

    # Top 10 Itens
    top = df.groupby("item_title")["quantity"].sum().nlargest(10).reset_index()
    fig1 = px.bar(top, x="item_title", y="quantity", color_discrete_sequence=["green"],
                  title="Top 10 Itens Vendidos")
    st.plotly_chart(fig1, use_container_width=True)
    sel_item = st.selectbox("Detalhar item", options=top["item_title"].tolist())
    st.dataframe(df[df["item_title"] == sel_item])

    # Heatmap Dia x Hora
    df['hour'] = df['date_created'].dt.hour
    df['weekday'] = df['date_created'].dt.day_name()
    hm = df.groupby(['weekday', 'hour']).size().reset_index(name='count')
    fig2 = px.density_heatmap(hm, x='weekday', y='hour', z='count',
                              color_continuous_scale='Greens', title="Heatmap Dia x Hora")
    st.plotly_chart(fig2, use_container_width=True)

    # Linha Vendas por Dia
    byday = df.groupby(df['date_created'].dt.date)['total_amount'].sum().reset_index()
    fig3 = px.line(byday, x='date_created', y='total_amount',
                   color_discrete_sequence=['green'], title="Vendas por Dia")
    st.plotly_chart(fig3, use_container_width=True)

    # Download Excel
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Vendas')
    buf.seek(0)
    st.download_button("Baixar Excel", data=buf, file_name="vendas.xlsx")

# --- Contas Screen ---
def contas_screen():
    st.header("Contas Cadastradas")
    login_url = f"{BACKEND_URL}/ml-login?client_id={ML_CLIENT_ID}&redirect_uri={FRONTEND_URL}?nexus_auth=success"
    st.markdown(f"[+ Adicionar Conta ML]({login_url})")
    df = pd.read_sql(text("SELECT ml_user_id, access_token FROM user_tokens"), engine)
    st.dataframe(df)

# --- Relatórios Screen ---
def relatorios_screen():
    st.header("Relatórios")
    df = carregar_vendas()
    st.dataframe(df)

# --- Logística Screen ---
def logistica_screen():
    st.header("Expedição & Logística")
    st.info("Em breve...")

# --- App Flow ---
ml_callback()
page = sidebar_menu()
if page == "Dashboard":
    dash()
elif page == "Contas":
    contas_screen()
elif page == "Relatórios":
    relatorios_screen()
else:
    logistica_screen()
