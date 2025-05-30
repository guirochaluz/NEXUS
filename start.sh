#!/bin/bash

# Inicia o FastAPI em segundo plano na porta 8501
uvicorn api:app --host 0.0.0.0 --port 8501 &

# Inicia o Streamlit como serviço principal (na porta 8000, visível)
streamlit run app.py --server.port 8000 --server.address=0.0.0.0 --server.enableXsrfProtection false
