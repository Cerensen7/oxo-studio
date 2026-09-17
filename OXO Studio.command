#!/bin/bash
# OXO Studio - cift tiklayarak baslat
cd "$(dirname "$0")"

PORT=7878

# Ayni port zaten calisiyorsa yeni sunucu acma, sadece tarayiciyi ac
if lsof -ti tcp:$PORT >/dev/null 2>&1; then
  echo "OXO Studio zaten calisiyor, tarayici aciliyor..."
  open "http://127.0.0.1:$PORT"
  sleep 1
  exit 0
fi

echo "======================================"
echo "  OXO Studio baslatiliyor..."
echo "  Bu pencereyi KAPATMA - sunucu burada calisiyor."
echo "  Kapatmak icin: Ctrl+C"
echo "======================================"
echo

# Sunucu hazir olunca tarayiciyi ac
( for i in $(seq 1 60); do
    if curl -s -o /dev/null "http://127.0.0.1:$PORT/"; then
      open "http://127.0.0.1:$PORT"; break
    fi
    sleep 0.5
  done ) &

exec ./venv/bin/python arayuz/sunucu.py
