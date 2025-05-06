from database.models import Base
from database.db import engine

# Apaga a tabela existente (cuidado: isso remove os dados!)
Base.metadata.drop_all(bind=engine)

# Cria as tabelas novamente com todos os campos atualizados
Base.metadata.create_all(bind=engine)
