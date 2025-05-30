#!/bin/bash

# Inicia FastAPI na porta 8501 (em segundo plano)
uvicorn api:app --host 0.0.0.0 --port 8501 &

# Inicia Streamlit na porta 8000 (será a pública)
streamlit run app.py --server.port 8000 --server.address=0.0.0.0 --server.enableXsrfProtection false
