#!/bin/bash
# Clique duplo: atualiza os dados a partir do Drive e abre o BI no navegador.
cd "$(dirname "$0")"

# Se um BI antigo ainda estiver aberto na porta 8020, encerra antes (senão o navegador mostraria a versão velha).
ANTIGO=$(lsof -t -iTCP:8020 -sTCP:LISTEN 2>/dev/null)
if [ -n "$ANTIGO" ]; then
  echo "Encerrando BI que já estava aberto..."
  kill $ANTIGO 2>/dev/null
  sleep 1
fi

python3 build_data.py || { echo "Falha ao ler as planilhas do Drive."; read -p "Enter para fechar"; exit 1; }
(sleep 2; open "http://localhost:8020") &
python3 server.py
