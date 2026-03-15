#!/usr/bin/env bash
# Garantir que o DISPLAY está configurado
export DISPLAY="${DISPLAY:-:0}"

# Adicionar pyenv ao PATH
export PATH="/home/python/pyenv/bin:$PATH"
export PYTHONPATH="/home/python/pyenv/bin"

# Mudar para o diretório do projeto
cd /home/jamaj/src/python/pyTweeter || exit 1

# Executar o aplicativo com o python do pyenv
exec /home/python/pyenv/bin/python3 /home/jamaj/src/python/pyTweeter/wxAsyncNewsReaderv6.py

