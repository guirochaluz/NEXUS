import streamlit as st
from sqlalchemy import text
from datetime import datetime
from utils import engine  # usa sua conexão

st.title("📦 Registro de Estoque")

# 🔄 Buscar produtos (hierarquia level1)
with engine.connect() as conn:
    produtos = conn.execute(text("""
        SELECT DISTINCT level1 
        FROM sales 
        WHERE level1 IS NOT NULL
        ORDER BY level1
    """)).fetchall()

# Criar botões para cada produto
for produto in produtos:
    produto_nome = produto[0]
    if st.button(f"📦 {produto_nome}"):
        st.session_state["produto_selecionado"] = produto_nome

# Formulário aparece só depois de clicar no botão
if "produto_selecionado" in st.session_state:
    st.subheader(f"Registrar estoque para: {st.session_state['produto_selecionado']}")
    quantidade = st.number_input("Quantidade", min_value=0.0, step=1.0)
    observacao = st.text_area("Observação (opcional)")

    if st.button("💾 Salvar"):
        try:
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO estoque_registros (produto, quantidade, observacao, data_registro)
                    VALUES (:produto, :quantidade, :observacao, :data_registro)
                """), {
                    "produto": st.session_state["produto_selecionado"],
                    "quantidade": quantidade,
                    "observacao": observacao,
                    "data_registro": datetime.now()
                })
            st.success("✅ Estoque registrado com sucesso!")
            del st.session_state["produto_selecionado"]  # limpa
        except Exception as e:
            st.error(f"❌ Erro ao salvar: {e}")
