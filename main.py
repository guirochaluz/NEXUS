import os
import streamlit as st
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL")
DB_URL = os.getenv("DB_URL")

# Configuração da página
st.set_page_config(
    page_title="NEXUS - Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Verificação de variáveis de ambiente
if not BACKEND_URL or not DB_URL:
    st.error("❌ Configure BACKEND_URL e DB_URL no seu .env")
    st.stop()

# Inicia a interface principal
st.write("🎉 Sistema NEXUS iniciado com sucesso. Acesse o app.py para usar a interface.")
