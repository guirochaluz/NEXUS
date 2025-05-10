# api.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def home():
    return {"message": "Nexus API rodando perfeitamente!"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
