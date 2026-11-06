CREATE TABLE IF NOT EXISTS estoque (
    produto_id BIGINT PRIMARY KEY,
    quantidade INTEGER NOT NULL CHECK (quantidade >= 0)
);

CREATE TABLE IF NOT EXISTS baixa_processada (
    pedido_id BIGINT PRIMARY KEY
);

INSERT INTO estoque (produto_id, quantidade)
VALUES (1, 50), (2, 50), (3, 50)
ON CONFLICT (produto_id) DO NOTHING;
