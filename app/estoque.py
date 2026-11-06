from pathlib import Path
from typing import Annotated

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

Identificador = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]


class ItemPedido(BaseModel):
    produto_id: Identificador
    quantidade: Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]


class PedidoCriado(BaseModel):
    pedido_id: Identificador
    itens: Annotated[list[ItemPedido], Field(min_length=1)]


class SaldoInsuficiente(Exception):
    def __init__(self, produto_id: int):
        self.produto_id = produto_id


def inicializar_banco(database_url: str) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        conn.execute(schema)


def consultar_saldo(database_url: str):
    with psycopg.connect(database_url, connect_timeout=5, row_factory=dict_row) as conn:
        return conn.execute(
            "SELECT produto_id, quantidade FROM estoque ORDER BY produto_id"
        ).fetchall()


def dar_baixa(database_url: str, pedido: PedidoCriado) -> bool:
    quantidades: dict[int, int] = {}
    for item in pedido.itens:
        quantidades[item.produto_id] = quantidades.get(item.produto_id, 0) + item.quantidade

    with psycopg.connect(database_url, connect_timeout=5) as conn:
        registrado = conn.execute(
            """
            INSERT INTO baixa_processada (pedido_id) VALUES (%s)
            ON CONFLICT (pedido_id) DO NOTHING
            """,
            (pedido.pedido_id,),
        )
        if registrado.rowcount == 0:
            return False

        # A ordem estável evita que dois pedidos bloqueiem produtos em ordem inversa.
        for produto_id, quantidade in sorted(quantidades.items()):
            atualizado = conn.execute(
                """
                UPDATE estoque SET quantidade = quantidade - %s
                WHERE produto_id = %s AND quantidade >= %s
                """,
                (quantidade, produto_id, quantidade),
            )
            if atualizado.rowcount == 0:
                raise SaldoInsuficiente(produto_id)

    return True
