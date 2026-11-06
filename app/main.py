import os
from contextlib import asynccontextmanager
from threading import Event, Thread

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.consumer import consumir
from app.estoque import consultar_saldo, inicializar_banco


class SaldoProduto(BaseModel):
    produto_id: int
    quantidade: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.environ["DATABASE_URL"]
    rabbitmq_url = os.environ["RABBITMQ_URL"]
    await run_in_threadpool(inicializar_banco, database_url)
    app.state.database_url = database_url

    parar = Event()
    consumidor = Thread(target=consumir, args=(database_url, rabbitmq_url, parar), daemon=True)
    consumidor.start()
    try:
        yield
    finally:
        parar.set()
        await run_in_threadpool(consumidor.join, 12)


app = FastAPI(title="Estoque da Lanchonete", lifespan=lifespan)


@app.get("/estoque", response_model=list[SaldoProduto])
def obter_estoque():
    try:
        return consultar_saldo(app.state.database_url)
    except psycopg.OperationalError:
        raise HTTPException(status_code=503, detail="Banco de estoque indisponível") from None
