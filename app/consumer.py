import logging
from threading import Event

import pika
import psycopg
from pydantic import ValidationError

from app.estoque import PedidoCriado, SaldoInsuficiente, dar_baixa

logger = logging.getLogger("uvicorn.error")
EXCHANGE = "pedido.criado"
FILA = "estoque"


def consumir(database_url: str, rabbitmq_url: str, parar: Event) -> None:
    def processar(canal, entrega, propriedades, corpo):
        try:
            pedido = PedidoCriado.model_validate_json(corpo)
        except ValidationError as erro:
            logger.warning("evento inválido fila=%s erros=%s", FILA, erro.error_count())
            canal.basic_reject(delivery_tag=entrega.delivery_tag, requeue=False)
            return

        try:
            processado = dar_baixa(database_url, pedido)
        except SaldoInsuficiente as erro:
            logger.warning(
                "saldo insuficiente pedido_id=%s produto_id=%s",
                pedido.pedido_id,
                erro.produto_id,
            )
        else:
            resultado = "baixa ok" if processado else "já processado"
            logger.info("%s pedido_id=%s", resultado, pedido.pedido_id)

        canal.basic_ack(delivery_tag=entrega.delivery_tag)

    parametros = pika.URLParameters(rabbitmq_url)
    parametros.socket_timeout = 5
    parametros.stack_timeout = 10
    parametros.blocked_connection_timeout = 10

    while not parar.is_set():
        try:
            with pika.BlockingConnection(parametros) as conexao:
                canal = conexao.channel()
                canal.exchange_declare(exchange=EXCHANGE, exchange_type="fanout", durable=True)
                canal.queue_declare(queue=FILA, durable=True)
                canal.queue_bind(queue=FILA, exchange=EXCHANGE)
                canal.basic_qos(prefetch_count=1)
                canal.basic_consume(queue=FILA, on_message_callback=processar, auto_ack=False)
                logger.info("consumidor pronto fila=%s", FILA)

                while not parar.is_set():
                    conexao.process_data_events(time_limit=1)
        except (pika.exceptions.AMQPError, psycopg.Error) as erro:
            # Fechar a conexão devolve ao broker a mensagem ainda sem ack.
            logger.error("consumidor interrompido fila=%s erro=%s", FILA, type(erro).__name__)
            parar.wait(5)
