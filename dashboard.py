import io
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import text
from typing import Optional
from app.py import carregar_vendas, format_currency, engine

def mostrar_dashboard():
    st.header("📊 Dashboard de Vendas")

    # 0) Carrega dados brutos
    df_full = carregar_vendas(None)
    if df_full.empty:
        st.warning("Nenhuma venda cadastrada.")
        return

    # 1) Layout dos filtros
    col1, col2, col3 = st.columns([3, 1, 1])
    contas_df  = pd.read_sql(text("SELECT ml_user_id FROM user_tokens ORDER BY ml_user_id"), engine)
    contas_lst = contas_df["ml_user_id"].astype(str).tolist()
    escolha    = col1.selectbox("🔹 Conta", ["Todas as contas"] + contas_lst)
    conta_id   = None if escolha == "Todas as contas" else escolha

    data_min = df_full["date_created"].dt.date.min()
    data_max = df_full["date_created"].dt.date.max()
    de  = col2.date_input("🔹 De",  value=data_min, min_value=data_min, max_value=data_max)
    ate = col3.date_input("🔹 Até", value=data_max, min_value=data_min, max_value=data_max)

    busca = st.text_input("🔹 Busca livre", placeholder="Título, MLB, Order ID…")

    # 2) Aplica filtros
    df = carregar_vendas(conta_id)
    df = df[(df["date_created"].dt.date >= de) & (df["date_created"].dt.date <= ate)]
    if busca:
        df = df[df["item_title"].str.contains(busca, case=False, na=False) |
                df["order_id"].astype(str).str.contains(busca, case=False, na=False)]
    if df.empty:
        st.warning("Nenhuma venda encontrada para os filtros selecionados.")
        return

    # 3) Métricas
    total_vendas = len(df)
    total_valor  = df["total_amount"].sum()
    total_itens  = df["quantity"].sum()
    ticket_medio = total_valor / total_vendas if total_vendas else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧾 Vendas", total_vendas)
    c2.metric("💰 Receita total", format_currency(total_valor))
    c3.metric("📦 Itens vendidos", int(total_itens))
    c4.metric("🎯 Ticket médio", format_currency(ticket_medio))

    # 4) Gráfico de Linha
    vendas_por_dia = (
        df
        .groupby(df["date_created"].dt.date)["total_amount"]
        .sum()
        .reset_index(name="total_amount")
    )
    fig = px.line(vendas_por_dia, x="date_created", y="total_amount", title="💵 Total Vendido por Dia")
    st.plotly_chart(fig, use_container_width=True)

    # 5) Download do Excel Filtrado
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Vendas")
    buffer.seek(0)

    st.download_button(
        label="📥 Baixar Excel das vendas",
        data=buffer,
        file_name="vendas_filtradas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="download_excel_vendas"
    )
