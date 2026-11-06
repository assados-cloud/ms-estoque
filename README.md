# Estoque da Lanchonete

Microsserviço da Equipe 15 para consultar saldo e dar baixa nos produtos após a criação de um pedido. Usa FastAPI, PostgreSQL e RabbitMQ.

## Executar localmente

```bash
docker compose up --build -d
docker compose logs -f ms-estoque
```

Aguarde o log `consumidor pronto fila=estoque` antes de publicar. Em outro terminal, consulte o saldo inicial.

```bash
curl -fsS http://localhost:8000/estoque
```

Na primeira execução, os produtos 1, 2 e 3 começam com 50 unidades cada. A API retorna uma lista de objetos com `produto_id` e `quantidade`, ordenada por ID.

## Exercitar o consumidor

O serviço Pedidos publica no exchange durável `pedido.criado` do tipo fanout. Para testar o Estoque sozinho, publique uma mensagem no RabbitMQ do Compose.

```bash
docker compose exec -T ms-estoque python - <<'PY'
import json
import os

import pika

evento = {
    "pedido_id": 1,
    "itens": [
        {"produto_id": 1, "quantidade": 2},
        {"produto_id": 3, "quantidade": 1},
    ],
    "total": 57.00,
    "criado_em": "2026-11-10T20:30:00-03:00",
}

with pika.BlockingConnection(pika.URLParameters(os.environ["RABBITMQ_URL"])) as conexao:
    canal = conexao.channel()
    canal.confirm_delivery()
    canal.basic_publish(
        exchange="pedido.criado",
        routing_key="",
        body=json.dumps(evento),
        properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
        mandatory=True,
    )
PY
```

Após o log `baixa ok pedido_id=1`, consulte `GET /estoque` novamente. Em uma base nova, os saldos esperados são 48, 50 e 49. Republicar o mesmo evento registra `já processado` e mantém esses valores.

A baixa e o registro de `pedido_id` são gravados na mesma transação. Se qualquer item estiver sem saldo, a transação inteira é desfeita. A confirmação ao RabbitMQ ocorre depois do commit ou após identificar um caso que encerra o processamento, como duplicidade ou saldo insuficiente. A API de Pedidos pode responder antes da baixa.

Para integrar ao ambiente da equipe, configure `DATABASE_URL` e `RABBITMQ_URL` com os endereços e credenciais dos Services. Os valores no Compose são exclusivos do ambiente local.

## Integrar ao EKS da equipe

Use o mesmo namespace dos serviços da equipe. O PostgreSQL precisa de uma StorageClass padrão capaz de provisionar o PVC. Confira o contexto e o storage antes de aplicar os manifests.

```bash
kubectl config current-context
kubectl get storageclass
```

Publique a imagem com uma tag fixa no registry escolhido pela equipe. Use a arquitetura dos nós do cluster. O exemplo assume nós AMD64.

```bash
IMAGE='REGISTRY/ms-estoque:TAG'
docker buildx build --platform linux/amd64 --tag "$IMAGE" --push .
```

Crie um arquivo local `.env.eks` com estas três chaves. Substitua os valores de exemplo pelas credenciais do ambiente. Use a mesma senha em `POSTGRES_PASSWORD` e em `DATABASE_URL`, com percent-encoding na URL se houver caracteres reservados. A URL do RabbitMQ deve apontar para o Service e o vhost usados por Pedidos. O exemplo usa o vhost padrão `/`, codificado como `%2F`.

```dotenv
POSTGRES_PASSWORD=SENHA_DO_POSTGRES
DATABASE_URL=postgresql://estoque:SENHA_DO_POSTGRES@postgres-estoque:5432/estoquedb
RABBITMQ_URL=amqp://USUARIO:SENHA_DO_RABBITMQ@rabbitmq:5672/%2F
```

```bash
NS='NAMESPACE_DA_EQUIPE'
kubectl -n "$NS" create secret generic ms-estoque --from-env-file=.env.eks
kubectl -n "$NS" apply -f k8s/postgres-estoque.yaml
kubectl -n "$NS" rollout status deploy/postgres-estoque --timeout=180s

kubectl -n "$NS" apply -f k8s/ms-estoque-service.yaml
kubectl set image --local -f k8s/ms-estoque.yaml ms-estoque="$IMAGE" -o yaml |
  kubectl -n "$NS" apply -f -
kubectl -n "$NS" rollout status deploy/ms-estoque --timeout=180s
```

Inclua este item na lista `spec.rules[].http.paths` do Ingress compartilhado, preservando o path `/estoque` até o FastAPI.

```yaml
- path: /estoque
  pathType: Exact
  backend:
    service:
      name: ms-estoque
      port:
        number: 8000
```

### Testar antes da apresentação

1. Confirme no log do deployment a mensagem `consumidor pronto fila=estoque` antes de criar o primeiro pedido.
2. Com o hostname público do Ingress em `BASE_URL` (por exemplo, `http://HOSTNAME_DO_INGRESS`), rode `curl -fsS "$BASE_URL/estoque"` e anote os saldos.
3. Dispare o `POST /pedidos` da equipe com 2 unidades do produto 1 e 1 do produto 3. Anote o `pedido_id` retornado.
4. Rode `kubectl -n "$NS" logs deploy/ms-estoque --tail=20`. Após aparecer `baixa ok` para aquele `pedido_id`, consulte `/estoque` de novo. O produto 1 deve cair em 2, o produto 3 em 1 e o produto 2 deve manter o saldo.
