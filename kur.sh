#!/bin/bash
# OXO Studio - kurulum
# Apple Silicon (M1/M2/M3/M4) Mac icin. Tek sefer calistirilir.
set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE"

echo "=== [1/5] Gereksinim kontrolu ==="
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg bulunamadi. Kurmak icin: brew install ffmpeg"; exit 1
fi

PY=""
for c in python3.12 python3.11 python3.10 /opt/homebrew/bin/python3.11; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10-3.12 bulunamadi. Kurmak icin: brew install python@3.11"; exit 1
fi
echo "Python: $PY ($($PY --version 2>&1))"

echo "=== [2/5] ACE-Step kaynak kodu ==="
if [ -d acestep/.git ]; then
  echo "zaten var, atlaniyor"
else
  git clone --depth 1 https://github.com/ace-step/ACE-Step.git acestep
fi

echo "=== [3/5] Sanal ortam ==="
[ -d venv ] || "$PY" -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip --no-cache-dir -q

echo "=== [4/5] PyTorch (Apple Silicon / MPS) ==="
pip install --no-cache-dir -q torch torchaudio torchvision

echo "=== [5/5] Cikarim bagimliliklari ==="
# Egitim paketleri (datasets, pytorch_lightning, tensorboard, matplotlib,
# gradio) cikarim icin gereksiz; ~1 GB disk tasarrufu saglar.
pip install --no-cache-dir -q \
  "diffusers>=0.33.0" "transformers==4.50.0" huggingface_hub \
  loguru tqdm click soundfile "librosa==0.11.0" numpy \
  "py3langid==0.3.0" "pypinyin==0.53.0" "hangul-romanize==0.1.0" \
  "num2words==0.5.14" "spacy==3.8.4" "accelerate==1.6.0" \
  fastapi uvicorn
pip install --no-cache-dir -q --no-deps -e "$BASE/acestep"

echo
echo "================================================"
echo "  Kurulum tamam."
echo "  Baslatmak icin: \"OXO Studio.command\" dosyasina cift tikla"
echo "  veya: ./venv/bin/python arayuz/sunucu.py"
echo "================================================"
du -sh venv
