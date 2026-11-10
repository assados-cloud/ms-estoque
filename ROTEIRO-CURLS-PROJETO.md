# Roteiro de demonstração — Lanchonete

Este roteiro acompanha uma compra: consultar o cardápio, criar o pedido de uma cliente, conferir o registro, verificar a baixa de estoque e consultar a notificação.

Os comandos foram escritos para **PowerShell**, usando `curl.exe`. Execute os passos na ordem, na mesma sessão. O `-i` mostra o status HTTP e o corpo da resposta.

## 0. Escolher o ambiente

### Pelo Ingress do Kubernetes

O endereço abaixo já está configurado com o balanceador informado. Execute o bloco no terminal onde fará os testes:

```powershell
$base = "http://aa608d6c6ebf649b9be5d4a5fa285f17-c68a2842be9be43d.elb.us-east-1.amazonaws.com"
$cardapio = $base
$pedidos = $base
$estoque = $base
$notificacoes = $base
```

Como alternativa, na raiz deste repositório, carregue o arquivo de configuração local. O ponto seguido de espaço faz as variáveis ficarem disponíveis na sessão atual:

```powershell
. .\configurar-curls.ps1
```

Depois, siga a partir do passo 1. Se abrir outro terminal, carregue a configuração novamente. Isso configura os endereços dos cURLs; não altera recursos do cluster.

### Por portas locais

Se os serviços estiverem acessíveis nas portas dos seus respectivos arquivos Compose, use estas variáveis no lugar do bloco anterior:

```powershell
$cardapio = "http://localhost:8080"
$pedidos = "http://localhost:3000"
$estoque = "http://localhost:8000"
$notificacoes = "http://localhost:8082"
```

**Pré-requisito de integração:** Pedidos precisa acessar Cardápio, e Pedidos, Estoque e Notificações precisam usar o mesmo RabbitMQ e o mesmo vhost. Subir os três Composes isoladamente não conecta o fluxo: cada um declara seu próprio broker, e os Composes de Pedidos e Notificações também disputam a porta 15672.

Antes da demonstração, confirme que os consumidores das filas `estoque` e `notificacoes` estão prontos. Eles precisam ter declarado as filas e os vínculos ao exchange `pedido.criado` antes da publicação do pedido.

## 1. Consultar o cardápio

**O que explicar:** “Primeiro, a cliente consulta os produtos disponíveis e seus preços. Essa chamada vai para o ms-cardapio.”

```powershell
curl.exe -sS -i "$cardapio/cardapio/produtos"
```

**Esperado:** HTTP `200`, com os produtos cadastrados. Nos dados iniciais do projeto:

- Produto 1: X-Burger, R$ 25,00.
- Produto 2: Batata, R$ 12,00.
- Produto 3: Refri, R$ 7,00.

Para consultar somente o produto escolhido:

```powershell
curl.exe -sS -i "$cardapio/cardapio/produtos/1"
```

**Esperado:** HTTP `200`, com `id`, `nome` e `preco` do produto 1. Essa é a mesma rota que Pedidos consulta internamente para obter o preço.

## 2. Conferir o estoque antes da compra

**O que explicar:** “Vou anotar as quantidades antes do pedido para comparar com o saldo depois da compra.”

```powershell
curl.exe -sS -i "$estoque/estoque"
```

**Esperado:** HTTP `200`, com uma lista de `produto_id` e `quantidade`. Em uma base nova, os produtos 1, 2 e 3 começam com 50 unidades cada. Se a base já foi usada, anote os saldos atuais.

Para a compra deste roteiro, os produtos 1 e 3 precisam ter pelo menos 2 e 1 unidades, respectivamente.

## 3. Criar o pedido da cliente Ana

**O que explicar:** “A Ana vai pedir dois X-Burgers e um refrigerante. Envio os IDs e as quantidades; o serviço de Pedidos consulta o Cardápio para calcular o preço. Nome e e-mail seguem no evento para o serviço de Notificações.”

Não existe uma API de cadastro de usuários nesses quatro serviços. A cliente é informada no próprio pedido.

Primeiro, prepare o arquivo JSON. Usar um arquivo evita problemas de aspas do JSON no Windows PowerShell. Execute este bloco em uma pasta de teste; ele cria ou substitui `pedido-demo.json` nessa pasta.

```powershell
@'
{
  "cliente_nome": "Ana Silva",
  "cliente_email": "ana@example.com",
  "itens": [
    { "produto_id": 1, "quantidade": 2 },
    { "produto_id": 3, "quantidade": 1 }
  ]
}
'@ | Set-Content -Encoding ascii pedido-demo.json
```

O endereço `ana@example.com` é ilustrativo: com Mailpit, o e-mail fica capturado para demonstração. Para testar entrega real, use um endereço seu e um servidor SMTP configurado para envio.

Agora crie o pedido:

```powershell
curl.exe -sS -i -X POST "$pedidos/pedidos" -H "Content-Type: application/json" --data-binary "@pedido-demo.json"
```

**Esperado no fluxo de sucesso:** HTTP `201`, com uma resposta semelhante a esta:

```json
{
  "pedido_id": 123,
  "itens": [
    { "produto_id": 1, "nome": "X-Burger", "preco_unitario": 25, "quantidade": 2 },
    { "produto_id": 3, "nome": "Refri", "preco_unitario": 7, "quantidade": 1 }
  ],
  "total": 57,
  "status": "PUBLICADO"
}
```

O total de R$ 57,00 considera os preços iniciais. O `pedido_id` é gerado pelo banco e pode ser diferente. Guarde o ID retornado na variável abaixo, substituindo `123` pelo valor real:

```powershell
$pedidoId = 123
```

**O que aconteceu internamente:** Pedidos consultou Cardápio por HTTP, gravou o pedido no MySQL e publicou `pedido.criado` no RabbitMQ. Estoque e Notificações recebem cópias do evento em filas separadas.

`PUBLICADO` indica publicação do evento; não confirma baixa de estoque nem envio do e-mail. Cada nova execução do POST cria outro pedido e pode provocar outra baixa e outro e-mail.

## 4. Consultar o pedido criado

**O que explicar:** “Com o ID retornado, consulto o pedido salvo e confiro a cliente, os itens e o total.”

```powershell
curl.exe -sS -i "$pedidos/pedidos/$pedidoId"
```

**Esperado:** HTTP `200`, com `id`, `cliente_nome`, `cliente_email`, `total`, `status`, `criado_em` e `itens`. Na consulta, o identificador aparece como `id`; na criação, aparece como `pedido_id`.

## 5. Conferir a baixa de estoque

**O que explicar:** “A baixa acontece em segundo plano. O serviço de Estoque consome o evento e desconta os produtos; Pedidos não precisa chamar a API de Estoque.”

```powershell
curl.exe -sS -i "$estoque/estoque"
```

**Esperado após o processamento:** o produto 1 diminuiu em 2, o produto 3 diminuiu em 1 e o produto 2 manteve a quantidade.

Se o saldo inicial era 50 para todos, agora deve ser:

```json
[
  { "produto_id": 1, "quantidade": 48 },
  { "produto_id": 2, "quantidade": 50 },
  { "produto_id": 3, "quantidade": 49 }
]
```

Se ainda aparecer o saldo anterior, aguarde alguns segundos e repita **somente o GET**. No Kubernetes, confira o processamento do ID nos logs:

```powershell
kubectl -n lanchonete logs deploy/ms-estoque --tail=30
```

O log esperado é `baixa ok pedido_id=...`. Se faltar saldo em algum item, toda a baixa é desfeita; a implementação atual não cancela o pedido automaticamente.

## 6. Consultar a notificação da Ana

**O que explicar:** “O serviço de Notificações também recebe o evento do pedido, registra a notificação e tenta enviar o e-mail. Ele trabalha independentemente do Estoque.”

```powershell
curl.exe -sS -i "$notificacoes/notificacoes/$pedidoId"
```

**Esperado após o processamento:** HTTP `200`, com uma resposta neste formato:

```json
{
  "pedido_id": 123,
  "status": "ENVIADO",
  "tentativas": 1,
  "criado_em": "2026-11-10T12:00:00Z",
  "enviado_em": "2026-11-10T12:00:01Z"
}
```

O ID, as datas e o número de tentativas variam. Os status possíveis são:

- `PENDENTE`: envio aguardando processamento ou nova tentativa.
- `ENVIADO`: o servidor SMTP aceitou o e-mail; não comprova leitura ou entrega na caixa de entrada.
- `FALHOU`: as cinco tentativas de envio terminaram sem sucesso.

Um HTTP `404` logo após o POST pode significar que o evento ainda não foi persistido. Aguarde e repita o GET. Se persistir, confira os logs e a fila `notificacoes.invalidas`. Embora nome e e-mail sejam opcionais em Pedidos, ambos são exigidos pelo consumidor de Notificações.

O e-mail confirma o recebimento do pedido. Ele não depende de a baixa de estoque ter sido concluída.

## 7. Mostrar o e-mail capturado no Mailpit

**O que explicar:** “No ambiente de demonstração, o Mailpit captura os e-mails para que possamos conferir destinatário, assunto e conteúdo.”

Com o Compose de Notificações, abra `http://localhost:8025` no navegador.

Se estiver usando o ambiente Kubernetes de demonstração deste repositório, abra este port-forward em outro terminal e mantenha-o executando:

```powershell
kubectl -n lanchonete port-forward service/mailpit 8025:8025
```

Depois, abra `http://localhost:8025` e procure o destinatário `ana@example.com` e o assunto `Pedido #123 recebido`, com o ID real do pedido. Essa etapa usa a interface do Mailpit; o envio já foi disparado pelo evento, sem um POST adicional.

## 8. Listar os pedidos registrados

**O que explicar:** “Por fim, listo os pedidos para mostrar que a compra ficou registrada.”

```powershell
curl.exe -sS -i "$pedidos/pedidos"
```

**Esperado:** HTTP `200`, com os últimos 100 pedidos, do mais recente para o mais antigo. A listagem traz os dados gerais; os itens são consultados em `GET /pedidos/{id}`.

## 9. Comandos para apresentar ao professor

Execute estes comandos na raiz do repositório, com `kubectl` instalado e credenciais válidas do AWS Academy. Eles complementam os cURLs com evidências da infraestrutura e da comunicação entre serviços.

### 9.1. Confirmar o cluster e os nós

**O que explicar:** “As aplicações estão executando em um cluster Kubernetes no Amazon EKS. Os nós fornecem os recursos para os Pods.”

```powershell
# Se o kubeconfig desta máquina ainda não estiver selecionado:
$env:KUBECONFIG = Join-Path $PWD ".cache\eksctl\kubeconfig"
kubectl config current-context
kubectl get nodes -o wide
```

A atribuição de `KUBECONFIG` pressupõe que o arquivo local já exista. Se você usa outro kubeconfig válido, pule essa atribuição. Confira o contexto antes de qualquer comando que altere o cluster.

**O que mostrar:** o contexto do EKS e os nós em estado `Ready`. Os nomes e a quantidade de nós dependem do ambiente atual.

### 9.2. Mostrar os quatro serviços e suas réplicas

**O que explicar:** “Cada microsserviço tem seu próprio Deployment e pode ser executado e escalado independentemente.”

```powershell
kubectl -n lanchonete get deployments
kubectl -n lanchonete get pods -o wide
kubectl -n lanchonete get pods -l app=ms-cardapio
```

**O que mostrar:** Cardápio, Pedidos, Estoque e Notificações prontos. A configuração de demonstração prevê três réplicas de Cardápio; confira se as três estão `Ready` antes de mostrar o balanceamento.

As implementações usam Java no Cardápio, JavaScript em Pedidos, Python no Estoque e Go em Notificações. A listagem de Pods comprova a execução; mostre também o código dos repositórios para comprovar as linguagens.

### 9.3. Mostrar a entrada única pelo Ingress

**O que explicar:** “Todos os cURLs usam o mesmo endereço público. O NGINX Ingress encaminha cada caminho para o Service correspondente.”

```powershell
kubectl -n ingress-nginx get service ingress-nginx-controller
kubectl -n lanchonete get ingress
kubectl -n lanchonete describe ingress lanchonete
kubectl -n lanchonete get services
```

**O que mostrar:** o LoadBalancer do controlador NGINX e as regras `/cardapio`, `/pedidos`, `/estoque` e `/notificacoes`. Os Services fazem o encaminhamento interno até os Pods.

Se o balanceador tiver sido recriado, compare seu hostname com `$base` e atualize as variáveis do passo 0 antes de continuar.

### 9.4. Demonstrar o balanceamento entre réplicas

**O que explicar:** “Vou fazer várias requisições ao mesmo endereço. Cada resposta identifica o Pod que atendeu, mostrando a distribuição entre as réplicas.”

```powershell
1..15 | ForEach-Object { curl.exe -sS --connect-timeout 5 --max-time 10 -H "Connection: close" "$cardapio/cardapio/instance"; Write-Host "" }
```

**O que mostrar:** valores diferentes de `hostname` nas respostas e sua correspondência com os nomes dos Pods do passo 9.2. Cada execução de cURL abre uma nova conexão. Não há garantia de alternância exata nem de que uma sequência curta mostre todas as réplicas; repita se necessário. Se só aparecer uma, investigue as réplicas prontas e o encaminhamento antes de afirmar que houve balanceamento.

### 9.5. Demonstrar Service Discovery e a chamada REST interna

**O que explicar:** “Pedidos encontra Cardápio pelo nome do Service no DNS do Kubernetes. A comunicação interna não depende do endereço público do balanceador.”

```powershell
kubectl -n lanchonete exec deploy/ms-pedidos -- node -p "process.env.CARDAPIO_URL"
kubectl -n lanchonete exec deploy/ms-pedidos -- node -e "require('dns').lookup('ms-cardapio', console.log)"
kubectl -n lanchonete logs -l app=ms-pedidos --prefix=true --tail=50
```

**O que mostrar:** a URL `http://ms-cardapio:8080`, a resolução do nome para um IP interno e, após criar o pedido do passo 3, os logs `GET http://ms-cardapio:8080/cardapio/produtos/...` com nome e preço dos produtos. O campo de Pod nesses logs pode aparecer como `-`; use `/cardapio/instance` para a evidência de balanceamento.

### 9.6. Mostrar a integração assíncrona pelo RabbitMQ

**O que explicar:** “Pedidos publica uma vez no exchange fanout pedido.criado. O RabbitMQ entrega uma cópia à fila de Estoque e outra à fila de Notificações.”

```powershell
kubectl -n lanchonete exec deploy/rabbitmq -- rabbitmqctl list_exchanges name type durable
kubectl -n lanchonete exec deploy/rabbitmq -- rabbitmqctl list_bindings source_name destination_name destination_kind
kubectl -n lanchonete exec deploy/rabbitmq -- rabbitmqctl list_queues name consumers messages_ready messages_unacknowledged
kubectl -n lanchonete logs -l app=ms-estoque --prefix=true --tail=50
kubectl -n lanchonete logs -l app=ms-notificacoes --prefix=true --tail=50
```

**O que mostrar:** o exchange `pedido.criado` com tipo `fanout`, os vínculos das filas `estoque` e `notificacoes` e seus consumidores ativos. Estes comandos usam o vhost padrão `/`, adotado pela configuração de demonstração.

Após o pedido, procure `baixa ok` no Estoque e `evento persistido` / `notificação processada` em Notificações para o mesmo `pedido_id`. Zero mensagens aguardando é normal quando os consumidores já processaram os eventos; use os logs e os GETs dos passos 5 e 6 para confirmar o resultado.

### 9.7. Mostrar os bancos independentes e a persistência

**O que explicar:** “Cardápio e Pedidos usam MySQL; Estoque e Notificações usam PostgreSQL. Cada serviço tem sua própria base e armazenamento.”

```powershell
kubectl -n lanchonete get services mysql-cardapio mysql-pedidos postgres-estoque postgres-notificacoes
kubectl -n lanchonete get pvc
kubectl get pv
```

**O que mostrar:** os quatro Services de banco e os PVCs/PVs associados em estado `Bound`. Para explicar o isolamento, mostre também a configuração de conexão de cada aplicação no código/manifests, sem exibir os valores dos Secrets.

**Limite do ambiente de demonstração:** o armazenamento configurado usa volumes locais nos nós (`hostPath`). Os dados podem sobreviver à recriação dos Pods no mesmo nó, mas não à perda do nó/disco. Não apresente essa configuração como armazenamento com alta disponibilidade.

### Ordem sugerida para a apresentação

1. Mostre o cluster, os quatro serviços e o Ingress (9.1 a 9.3).
2. Demonstre o balanceamento do Cardápio (9.4).
3. Execute o fluxo de compra dos passos 1 a 8, anotando o ID real e os saldos antes e depois.
4. Relacione esse mesmo pedido aos logs da chamada REST e dos consumidores (9.5 e 9.6).
5. Mostre os bancos, os volumes e explique o limite do armazenamento (9.7).
6. Cada integrante explica seu serviço, a linguagem, o banco e sua integração.

## Resultado do teste integrado executado

Em **10/11/2026 às 03:19 UTC (00:19 de Brasília)**, o teste pelo balanceador configurado retornou:

- Cardápio: HTTP `200`, com os três produtos iniciais.
- Pedidos: HTTP `201`, pedido `1`, uma unidade do produto `1`, total de R$ 25,00 e status `PUBLICADO`. Consulta do pedido: HTTP `200`.
- Estoque: HTTP `200`, produto `1` passou de `50` para `49`; produtos `2` e `3` permaneceram com `50`.
- Notificações: HTTP `200`, pedido `1` com status `ENVIADO` e uma tentativa.

Esse registro documenta o teste realizado, não garante disponibilidade futura. O pedido de teste permaneceu salvo. Assim, na apresentação, compare sempre com o saldo imediatamente anterior à nova compra, sem assumir 50 unidades iniciais.

Os comandos Kubernetes desta seção foram conferidos com o código e os manifests locais; não foram executados como parte desse teste HTTP.

## Se a criação do pedido falhar

- HTTP `400`: confira os campos do JSON; os IDs e as quantidades precisam ser inteiros positivos.
- HTTP `422`: um produto não existe no Cardápio.
- HTTP `503` com erro de Cardápio: confira se Pedidos consegue acessar a URL interna configurada em `CARDAPIO_URL`.
- HTTP `502` com `pedido_id`: o pedido foi gravado, mas houve falha na publicação do evento. Guarde esse ID e investigue o RabbitMQ; repetir o POST cria outro pedido.
- HTTP `201` com `status: PENDENTE`: o evento foi publicado, mas falhou a atualização do status no banco de Pedidos. Os consumidores ainda podem processá-lo.

## Frase para encerrar a apresentação

“Demonstramos uma chamada síncrona de Pedidos para Cardápio e a distribuição assíncrona de um evento para Estoque e Notificações. Cada serviço mantém seus próprios dados, e os consumidores processam o pedido de forma independente.”
