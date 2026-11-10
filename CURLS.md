# cURLs de teste — API de Estoque

Os comandos abaixo correspondem às rotas de `app/main.py`. A única rota de negócio é `GET /estoque`; ela não exige autenticação, parâmetros ou corpo.

## Preparação

Na raiz do projeto, inicie o ambiente local:

```sh
docker compose up --build -d
docker compose logs -f ms-estoque
```

Aguarde a aplicação iniciar e o log `consumidor pronto fila=estoque`. Use outro terminal para os testes.

Os exemplos usam `http://localhost:8000`. Para outro ambiente, substitua essa base pela URL da API. No Windows PowerShell, use `curl.exe` no lugar de `curl` para evitar o alias de `Invoke-WebRequest`. Os comandos estão em uma linha para facilitar a execução em ambos os shells.

O `-i` mostra o status HTTP, os cabeçalhos e o corpo. O `-sS` oculta o progresso e mantém as mensagens de erro.

## 1. Consultar todo o estoque

```sh
curl -sS -i -H "Accept: application/json" "http://localhost:8000/estoque"
```

Esperado: **200 OK**, com uma lista ordenada por `produto_id`.

Em uma base recém-criada:

```json
[
  { "produto_id": 1, "quantidade": 50 },
  { "produto_id": 2, "quantidade": 50 },
  { "produto_id": 3, "quantidade": 50 }
]
```

Os saldos podem ser diferentes se pedidos já tiverem sido processados. Reiniciar os containers não restaura as quantidades: o PostgreSQL usa um volume persistente e a inicialização preserva os registros existentes.

Para uma checagem que retorne código de saída diferente de zero em erros HTTP:

```sh
curl -fsS "http://localhost:8000/estoque"
```

## 2. Conferir o contrato OpenAPI

```sh
curl -sS -i "http://localhost:8000/openapi.json"
```

Esperado: **200 OK**, com o contrato JSON, incluindo `GET /estoque` e o modelo `SaldoProduto` (`produto_id` e `quantidade`, ambos inteiros).

## 3. Conferir as páginas de documentação

Swagger UI:

```sh
curl -sS -i "http://localhost:8000/docs"
```

ReDoc:

```sh
curl -sS -i "http://localhost:8000/redoc"
```

Esperado: **200 OK**, com HTML. Para usar a interface interativa, abra a mesma URL no navegador.

Essas rotas são fornecidas pelo FastAPI. No EKS, um Ingress configurado somente para o caminho exato `/estoque` não as expõe; teste-as pelo acesso direto ao serviço ou por port-forward.

## 4. Testar a barra final

Sem seguir o redirecionamento:

```sh
curl -sS -i "http://localhost:8000/estoque/"
```

Esperado no acesso direto à aplicação: **307 Temporary Redirect**, com `Location` apontando para `/estoque`.

Seguindo o redirecionamento:

```sh
curl -sS -i -L "http://localhost:8000/estoque/"
```

Esperado: redirecionamento seguido de **200 OK** com o estoque. Um Ingress com caminho exato `/estoque` pode rejeitar `/estoque/` antes de a requisição chegar à aplicação.

## 5. Rejeitar métodos não implementados

Execute cada comando separadamente:

```sh
curl -sS -i -X POST "http://localhost:8000/estoque"
curl -sS -i -X PUT "http://localhost:8000/estoque"
curl -sS -i -X PATCH "http://localhost:8000/estoque"
curl -sS -i -X DELETE "http://localhost:8000/estoque"
curl -sS -i -X OPTIONS "http://localhost:8000/estoque"
```

Esperado para todos no acesso direto à aplicação: **405 Method Not Allowed**.

```json
{ "detail": "Method Not Allowed" }
```

Teste de HEAD (mostra apenas os cabeçalhos):

```sh
curl -sS -I "http://localhost:8000/estoque"
```

Esperado: **405 Method Not Allowed**. A aplicação declara apenas GET para esse caminho.

## 6. Consultar rotas inexistentes

Raiz:

```sh
curl -sS -i "http://localhost:8000/"
```

Consulta individual por produto:

```sh
curl -sS -i "http://localhost:8000/estoque/1"
```

Health check dedicado:

```sh
curl -sS -i "http://localhost:8000/health"
```

Esperado para todos no acesso direto à aplicação: **404 Not Found**.

```json
{ "detail": "Not Found" }
```

Essas rotas não estão implementadas. A consulta de estoque é feita exclusivamente pela listagem completa.

## 7. Banco indisponível

Este cenário exige que a aplicação já esteja iniciada e perca o acesso ao PostgreSQL. Para reproduzir no ambiente local de teste, pare somente o banco:

```sh
docker compose stop postgres-estoque
```

Em seguida:

```sh
curl -sS -i --max-time 15 "http://localhost:8000/estoque"
```

Esperado: **503 Service Unavailable**.

```json
{ "detail": "Banco de estoque indisponível" }
```

Restaure o banco e repita a consulta após ele ficar disponível:

```sh
docker compose start postgres-estoque
curl -sS -i "http://localhost:8000/estoque"
```

Esperado após a recuperação: **200 OK**. Se o banco estiver indisponível durante a inicialização da aplicação, ela pode não iniciar; nesse caso, o cURL terá erro de conexão em vez de resposta HTTP 503.

## 8. Conferir o saldo após um pedido

Antes de publicar o evento:

```sh
curl -sS -i "http://localhost:8000/estoque"
```

Publique um evento `pedido.criado` conforme o exemplo da seção [Exercitar o consumidor](README.md#exercitar-o-consumidor). Aguarde o log `baixa ok` para o `pedido_id` usado e consulte novamente:

```sh
curl -sS -i "http://localhost:8000/estoque"
```

Com o evento do README (2 unidades do produto 1 e 1 do produto 3), em uma base nova, o resultado esperado é:

```json
[
  { "produto_id": 1, "quantidade": 48 },
  { "produto_id": 2, "quantidade": 50 },
  { "produto_id": 3, "quantidade": 49 }
]
```

Republicar o mesmo `pedido_id` deve manter os saldos. Um pedido novo com quantidade insuficiente deve manter todos os saldos anteriores, pois a transação inteira é desfeita.

A publicação é feita via AMQP. O Compose atual não expõe uma API HTTP de gerenciamento do RabbitMQ, portanto não há um cURL de publicação disponível nessa configuração. O serviço também não implementa `POST /pedidos` nem uma rota HTTP de baixa de estoque.

## Acesso ao serviço no Kubernetes

Para executar os mesmos testes diretamente no serviço, abra um port-forward em outro terminal, substituindo `NAMESPACE_DA_EQUIPE`:

```sh
kubectl -n NAMESPACE_DA_EQUIPE port-forward service/ms-estoque 8000:8000
```

Mantenha esse comando em execução e use os cURLs com `http://localhost:8000`. A porta local 8000 deve estar livre.

Pelo Ingress, substitua o hostname abaixo pelo endereço do ambiente:

```sh
curl -sS -i "http://HOSTNAME_DO_INGRESS/estoque"
```

Os testes de rotas, métodos e redirecionamentos pelo Ingress podem ter respostas próprias do proxy. Use o acesso direto para verificar o comportamento da aplicação descrito neste documento.
