import os
import io
from datetime import date, timedelta
from typing import Optional

import streamlit as st
from sqlalchemy import create_engine, text
import pandas as pd
import plotly.express as px
import requests
import locale
from dotenv import load_dotenv
from streamlit_option_menu import option_menu
from streamlit_plotly_events import plotly_events

# --- Configuração da Página ---
st.set_page_config(
    page_title="Dashboard de Vendas - NEXUS",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Configuração de locale pt_BR ---
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
    LOCALE_OK = True
except locale.Error:
    LOCALE_OK = False

def format_currency(valor: float) -> str:
    if LOCALE_OK:
        try:
            return locale.currency(valor, grouping=True)
        except Exception:
            pass
    inteiro, frac = f"{valor:,.2f}".split('.')
    inteiro = inteiro.replace(',', '.')
    return f"R$ {inteiro},{frac}"

# --- Carrega variáveis de ambiente ---
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL")
FRONTEND_URL = os.getenv("FRONTEND_URL")
DB_URL = os.getenv("DB_URL")
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID")

if not all([BACKEND_URL, FRONTEND_URL, DB_URL, ML_CLIENT_ID]):
    st.error("❌ Defina BACKEND_URL, FRONTEND_URL, DB_URL e ML_CLIENT_ID em seu .env")
    st.stop()

# --- Conexão com o banco de dados ---
engine = create_engine(DB_URL, pool_size=5, max_overflow=10, pool_timeout=30)

# --- Autenticação ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

params = st.query_params
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

# --- Callback OAuth Mercado Livre ---
def ml_callback():
    code = st.query_params.get("code", [None])[0]
    if not code:
        st.error("⚠️ Código de autorização não encontrado.")
        return
    st.success("✅ Código recebido. Processando autenticação...")
    resp = requests.post(f"{BACKEND_URL}/auth/callback", json={"code": code})
    if resp.ok:
        data = resp.json()
        salvar_tokens_no_banco(data)
        try:
            carregar_vendas.clear()
        except:
            pass
        st.experimental_set_query_params()
        st.session_state["conta"] = data["user_id"]
        st.success("✅ Conta ML autenticada com sucesso!")
        st.rerun()
    else:
        st.error(f"❌ Falha na autenticação: {resp.text}")

# --- Salvar tokens no banco ---
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
                "user_id": data["user_id"],
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
            })
    except Exception as e:
        st.error(f"❌ Erro ao salvar tokens no banco: {e}")

# --- Carrega vendas (cache 5min) ---
@st.cache_data(ttl=300)
def carregar_vendas(conta_id: Optional[str] = None) -> pd.DataFrame:
    if conta_id:
        sql = text("""
            SELECT ml_user_id, order_id, date_created, item_title, status, quantity, total_amount
              FROM sales
             WHERE ml_user_id = :uid
        """)
        df = pd.read_sql(sql, engine, params={"uid": conta_id})
    else:
        sql = text("""
            SELECT ml_user_id, order_id, date_created, item_title, status, quantity, total_amount
              FROM sales
        """)
        df = pd.read_sql(sql, engine)

    df["date_created"] = (
        pd.to_datetime(df["date_created"], utc=True)
          .dt.tz_convert("America/Sao_Paulo")
          .dt.tz_localize(None)
    )
    return df

# --- Botão para adicionar conta ML ---
def render_add_account_button():
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

# --- Menu lateral ---
def render_sidebar():
    with st.sidebar:
        st.markdown("## Navegação")
        st.markdown("---")
        selected = option_menu(
            menu_title=None,
            options=["Dashboard", "Contas Cadastradas", "Relatórios", "Expedição e Logística"],
            icons=["house", "collection", "file-earmark-text", "truck"],
            default_index=0,
            orientation="vertical",
            styles={
                "container": {"padding": "0", "background-color": "#161b22"},
                "icon": {"color": "#2ecc71", "font-size": "18px"},
                "nav-link": {"font-size": "16px", "text-align": "left", "margin": "4px 0", "color": "#fff", "background-color": "transparent"},
                "nav-link:hover": {"background-color": "#27ae60"},
                "nav-link-selected": {"background-color": "#2ecc71", "color": "white"},
            },
        )
    return selected

# --- Página Dashboard ---
def mostrar_dashboard():
    st.header("📊 Dashboard de Vendas")
    df_full = carregar_vendas(None)
    if df_full.empty:
        st.warning("Nenhuma venda cadastrada.")
        return

    col1, col2, col3, col4 = st.columns([3,2,2,3])

    # Multiselect de contas
    contas_df = pd.read_sql(text("SELECT DISTINCT ml_user_id FROM user_tokens ORDER BY ml_user_id"), engine)
    contas_lst = contas_df["ml_user_id"].astype(str).tolist()
    contas_selected = col1.multiselect("🔹 Contas", options=["Todas as contas"] + contas_lst, default=["Todas as contas"])
    if "Todas as contas" in contas_selected or not contas_selected:
        df = df_full.copy()
    else:
        df = df_full[df_full["ml_user_id"].astype(str).isin(contas_selected)]

    # Dropdown de Período
    period_option = col2.selectbox("🔹 Período", ["Hoje","Últimos 7 dias","Este mês","Últimos 30 dias"])
    today = date.today()
    if period_option=="Hoje":
        de=ate=today
    elif period_option=="Últimos 7 dias":
        de=today-timedelta(days=7); ate=today
    elif period_option=="Este mês":
        de=today.replace(day=1); ate=today
    else:
        de=today-timedelta(days=30); ate=today

    # Filtro de Status
    statuses=["Todos"]+sorted(df["status"].dropna().unique().tolist())
    status_selected=col3.selectbox("🔹 Status de pagamento",statuses)
    if status_selected!="Todos":
        df=df[df["status"]==status_selected]

    # Busca avançada
    busca=col4.text_input("🔹 Busca livre (regex ou vírgulas)", placeholder="Ex: desconto|promo, Order ID…")
    if busca:
        pattern="("+"|".join([b.strip() for b in busca.split(",")])+")"
        df=df[df["item_title"].str.contains(pattern,case=False,na=False,regex=True)|df["order_id"].astype(str).str.contains(pattern,case=False,na=False,regex=True)]

    # Filtro por data
    df=df[(df["date_created"].dt.date>=de)&(df["date_created"].dt.date<=ate)]
    if df.empty:
        st.warning("Nenhuma venda encontrada para os filtros selecionados.")
        return

    # Métricas
    total_vendas=len(df); total_valor=df["total_amount"].sum(); total_itens=df["quantity"].sum()
    ticket_medio=total_valor/total_vendas if total_vendas else 0
    m1,m2,m3,m4=st.columns(4)
    m1.metric("🧾 Vendas",total_vendas)
    m2.metric("💰 Receita total",format_currency(total_valor))
    m3.metric("📦 Itens vendidos",int(total_itens))
    m4.metric("🎯 Ticket médio",format_currency(ticket_medio))

    # Top 10 Itens Vendidos
    top_items=df.groupby("item_title")["quantity"].sum().sort_values(ascending=False).head(10).reset_index()
    fig_top=px.bar(top_items,x="item_title",y="quantity",title="🔝 Top 10 Itens Vendidos",color_discrete_sequence=["green"])
    clicked=plotly_events(fig_top)
    st.plotly_chart(fig_top,use_container_width=True)
    if clicked:
        item=clicked[0]["x"]
        st.write(f"➔ Detalhes para: **{item}**")
        st.dataframe(df[df["item_title"]==item])

    # Heatmap Dia x Hora
    df["hour"]=df["date_created"].dt.hour
    df["weekday"]=df["date_created"].dt.day_name()
    heatmap_data=df.groupby(["weekday","hour"]).size().reset_index(name="count")
    fig_heat=px.density_heatmap(heatmap_data,x="weekday",y="hour",z="count",title="🗓️ Heatmap Vendas por Dia x Hora",color_continuous_scale="Greens")
    st.plotly_chart(fig_heat,use_container_width=True)

    # Gráfico de Linha Vendas por Dia
    vendas_por_dia=df.groupby(df["date_created"].dt.date)["total_amount"].sum().reset_index(name="total_amount")
    fig_line=px.line(vendas_por_dia,x="date_created",y="total_amount",title="💵 Total Vendido por Dia",color_discrete_sequence=["green"])
    st.plotly_chart(fig_line,use_container_width=True)

    # Download Excel
    buffer=io.BytesIO()
    with pd.ExcelWriter(buffer,engine="openpyxl") as writer:
        df.to_excel(writer,index=False,sheet_name="Vendas")
    buffer.seek(0)
    st.download_button("📥 Baixar Excel das vendas",data=buffer,file_name="vendas_filtradas.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# --- Página Contas Cadastradas ---
def mostrar_contas_cadastradas():
    st.header("📑 Contas Cadastradas")
    render_add_account_button()
    df=pd.read_sql(text("SELECT ml_user_id, access_token FROM user_tokens"),engine)
    if df.empty:
        st.warning("Nenhuma conta cadastrada.")
        return
    for row in df.itertuples(index=False):
        with st.expander(f"🔗 Conta ML: {row.ml_user_id}"):
            st.write(f"**Access Token:** {row.access_token}")
            if st.button("🔄 Renovar Token",key=f"renew_{row.ml_user_id}"):
                resp=requests.post(f"{BACKEND_URL}/auth/refresh",json={"user_id":row.ml_user_id})
                if resp.ok:
                    salvar_tokens_no_banco(resp.json()); st.success("Token atualizado com sucesso!")
                else:
                    st.error("Erro ao atualizar o token.")

# --- Página Relatórios ---
def mostrar_relatorios():
    st.header("📋 Relatórios de Vendas")
    df=carregar_vendas()
    if df.empty:
        st.warning("Nenhum dado para exibir.")
        return
    data_ini=st.date_input("De:",value=df["date_created"].min())
    data_fim=st.date_input("Até:",value=df["date_created"].max())
    status_sel=st.multiselect("Status:",options=df["status"].unique(),default=df["status"].unique())
    df_filt=df[(df["date_created"].dt.date>=data_ini)&(df["date_created"].dt.date<=data_fim)&(df["status"].isin(status_sel))]
    if df_filt.empty:
        st.warning("Sem registros para os filtros escolhidos.")
    else:
        st.dataframe(df_filt)

# --- Página Expedição e Logística ---
def mostrar_expedicao_logistica():
    st.header("🚚 Expedição e Logística")
    st.info("Em breve...")

# --- Fluxo Principal ---
if "code" in st.query_params: ml_callback()
pagina=render_sidebar()
if pagina=="Dashboard": mostrar_dashboard()
elif pagina=="Contas Cadastradas": mostrar_contas_cadastradas()
elif pagina=="Relatórios": mostrar_relatorios()
elif pagina=="Expedição e Logística": mostrar_expedicao_logistica()

