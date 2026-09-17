#!/usr/bin/env python
"""
OXO Studio - ACE-Step icin yerel web arayuzu.
Tarayicidan tek tek parca uretir, dinler, siler ve uzun mix cikarir.
"""
import os

# pipeline importundan ONCE: MPS'te fp32'ye dusmeyi engeller (16 GB RAM icin sart)
os.environ.setdefault("ACE_PIPELINE_DTYPE", "float16")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# xet arka ucu dosyayi ancak indirme bitince yazar; panelin ilerleme
# cubugu klasor boyutundan okudugu icin %0'da takili kalirdi.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import json
import random
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent.parent
ARAYUZ = BASE / "arayuz"
MODEL_DIR = BASE / "model"
PARCA_DIR = BASE / "output" / "parcalar"
MIX_DIR = BASE / "output"
KAYIT = BASE / "output" / "uretim_kaydi.json"

PARCA_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

MODEL_BOYUT_GB = 8.28  # indirme ilerlemesini yuzdeye cevirmek icin

TEMEL_PROMPT = (
    "lo-fi hip hop, chillhop, instrumental, no vocals, "
    "warm vinyl crackle, soft dusty drums, mellow sub bass, "
    "cozy, calm, relaxing, analog tape warmth, low pass filtered"
)

STILLER = [
    {"ad": "Jazzy Rhodes", "tag": "jazzy rhodes electric piano, laid back swing, 72 bpm"},
    {"ad": "Naylon Gitar", "tag": "soft nylon string guitar, gentle brushes, 68 bpm"},
    {"ad": "Rüyalı Piyano", "tag": "dreamy felt piano, sparse chords, 65 bpm"},
    {"ad": "Sordinli Trompet", "tag": "muted trumpet, late night jazz club, 70 bpm"},
    {"ad": "Analog Pad", "tag": "warm analog synth pad, slow bloom, 66 bpm"},
    {"ad": "Vibrafon / Yağmur", "tag": "vibraphone melody, rainy window mood, 69 bpm"},
    {"ad": "Boom Bap", "tag": "dusty sampled piano loop, boom bap drums, 74 bpm"},
    {"ad": "Flüt / Sonbahar", "tag": "soft flute, autumn afternoon, 71 bpm"},
    {"ad": "Reverb Gitar", "tag": "mellow electric guitar, reverb tails, 67 bpm"},
    {"ad": "Kahve Dükkânı", "tag": "lofi wurlitzer, coffee shop ambience, 73 bpm"},
    {"ad": "Arp / Süzülen", "tag": "gentle harp arpeggio, floating, 64 bpm"},
    {"ad": "Saksofon / Gece", "tag": "smooth saxophone, midnight city, 70 bpm"},
    {"ad": "Müzik Kutusu", "tag": "toy piano, nostalgic music box, 66 bpm"},
    {"ad": "Kontrbas", "tag": "warm upright bass walking, jazzy drums, 75 bpm"},
    {"ad": "Ambient / Vurgusuz", "tag": "ambient pad with tape hiss, almost beatless, 62 bpm"},
]

app = FastAPI(title="OXO Studio")

# ---------------------------------------------------------------- durum

DURUM = {
    "asama": "bos",          # bos | model_indiriliyor | model_yukleniyor | uretiliyor | mix
    "mesaj": "Hazır",
    "adim": 0,
    "toplam_adim": 0,
    "baslangic": None,
    "son_hata": None,
    "son_dosya": None,
    "model_yuklu": False,
}
KILIT = threading.Lock()
IPTAL = threading.Event()
PIPE = None


def _durum(**kw):
    DURUM.update(kw)


def mesgul() -> bool:
    return DURUM["asama"] != "bos"


# ---------------------------------------------------------------- yardimcilar

def sure_al(yol: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(yol)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def kayitlari_oku() -> dict:
    if not KAYIT.exists():
        return {}
    try:
        veri = json.loads(KAYIT.read_text())
        return {k["dosya"]: k for k in veri}
    except Exception:
        return {}


def kayit_ekle(kayit: dict):
    veri = []
    if KAYIT.exists():
        try:
            veri = json.loads(KAYIT.read_text())
        except Exception:
            veri = []
    veri = [k for k in veri if k.get("dosya") != kayit["dosya"]]
    veri.append(kayit)
    KAYIT.write_text(json.dumps(veri, ensure_ascii=False, indent=2))


def parcalari_listele() -> list:
    kayitlar = kayitlari_oku()
    out = []
    for p in sorted(PARCA_DIR.glob("*.wav")):
        k = kayitlar.get(p.name, {})
        out.append({
            "dosya": p.name,
            "sure": round(sure_al(p), 1),
            "boyut_mb": round(p.stat().st_size / 1e6, 1),
            "tarih": time.strftime("%d.%m %H:%M", time.localtime(p.stat().st_mtime)),
            "stil": k.get("stil", "-"),
            "seed": k.get("seed"),
            "prompt": k.get("prompt", ""),
        })
    return out


def klasor_boyut_gb(yol: Path) -> float:
    # HF cache'i blobs/ altindaki gercek dosyalari snapshots/ altinda symlink
    # olarak gosterir; symlink'leri atlamazsak boyut iki kat cikar.
    t = 0
    for f in yol.rglob("*"):
        if f.is_file() and not f.is_symlink():
            try:
                t += f.stat().st_size
            except OSError:
                pass
    return t / 1e9


def sonraki_numara() -> int:
    en = 0
    for p in PARCA_DIR.glob("lofi_*.wav"):
        m = re.match(r"lofi_(\d+)", p.stem)
        if m:
            en = max(en, int(m.group(1)))
    return en + 1


# ---------------------------------------------------------------- model

def _tqdm_yamasi():
    """pipeline_ace_step icindeki tqdm'i sararak gercek difuzyon adimlarini
    panele yansitir ve iptal bayragini kontrol eder."""
    import acestep.pipeline_ace_step as pl

    orijinal = pl.tqdm

    def sarmalayici(iterable=None, total=None, **kw):
        n = total
        if n is None:
            try:
                n = len(iterable)
            except TypeError:
                n = 0
        # kisa donguler (ornegin decode) ilerleme cubugunu bozmasin
        izle = n and n > 5
        if izle:
            _durum(adim=0, toplam_adim=n)
        for i, oge in enumerate(orijinal(iterable, total=total, **kw)):
            if IPTAL.is_set():
                raise RuntimeError("Üretim kullanıcı tarafından iptal edildi")
            if izle:
                _durum(adim=i + 1)
            yield oge

    pl.tqdm = sarmalayici


def model_yukle():
    global PIPE
    if PIPE is not None:
        return PIPE

    var_olan = klasor_boyut_gb(MODEL_DIR)
    if var_olan < MODEL_BOYUT_GB * 0.95:
        _durum(asama="model_indiriliyor",
               mesaj="Model ağırlıkları indiriliyor (~8.3 GB, tek seferlik)")
        dur = threading.Event()

        def izle():
            while not dur.is_set():
                gb = klasor_boyut_gb(MODEL_DIR)
                _durum(adim=int(gb * 100), toplam_adim=int(MODEL_BOYUT_GB * 100),
                       mesaj=f"Model indiriliyor: {gb:.2f} / {MODEL_BOYUT_GB} GB")
                time.sleep(2)

        t = threading.Thread(target=izle, daemon=True)
        t.start()
    else:
        dur = None

    try:
        _tqdm_yamasi()
        from acestep.pipeline_ace_step import ACEStepPipeline
        PIPE = ACEStepPipeline(
            checkpoint_dir=str(MODEL_DIR),
            dtype="float16",
            torch_compile=False,
            cpu_offload=False,
            overlapped_decode=False,
        )
        _durum(asama="model_yukleniyor", mesaj="Model belleğe yükleniyor",
               adim=0, toplam_adim=0)
        PIPE.load_checkpoint(str(MODEL_DIR))
        DURUM["model_yuklu"] = True
    finally:
        if dur:
            dur.set()
    return PIPE


def model_bosalt():
    global PIPE
    PIPE = None
    DURUM["model_yuklu"] = False
    try:
        import gc, torch
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


# ---------------------------------------------------------------- uretim

class UretIstek(BaseModel):
    stil: int = 0
    ek_prompt: str = ""
    sure: float = 240.0
    adim: int = 60
    seed: int | None = None


def uretim_isi(istek: UretIstek):
    try:
        IPTAL.clear()
        pipe = model_yukle()

        stil = STILLER[istek.stil % len(STILLER)]
        parcalar = [TEMEL_PROMPT, stil["tag"]]
        if istek.ek_prompt.strip():
            parcalar.append(istek.ek_prompt.strip())
        prompt = ", ".join(parcalar)

        seed = istek.seed if istek.seed else random.randint(1, 2**31 - 1)
        idx = sonraki_numara()
        hedef = PARCA_DIR / f"lofi_{idx:03d}.wav"

        _durum(asama="uretiliyor", baslangic=time.time(), son_hata=None,
               mesaj=f"{hedef.name} üretiliyor — {stil['ad']}",
               adim=0, toplam_adim=istek.adim)

        pipe(
            format="wav",
            audio_duration=istek.sure,
            prompt=prompt,
            lyrics="[instrumental]",
            infer_step=istek.adim,
            guidance_scale=15.0,
            scheduler_type="euler",
            cfg_type="apg",
            omega_scale=10.0,
            manual_seeds=[seed],
            guidance_interval=0.5,
            guidance_interval_decay=0.0,
            min_guidance_scale=3.0,
            use_erg_tag=True,
            use_erg_lyric=False,
            use_erg_diffusion=True,
            save_path=str(hedef),
            batch_size=1,
        )

        gecen = time.time() - DURUM["baslangic"]
        kayit_ekle({
            "dosya": hedef.name, "prompt": prompt, "stil": stil["ad"],
            "seed": seed, "sure_sn": istek.sure, "adim": istek.adim,
            "uretim_sn": round(gecen, 1),
        })
        _durum(asama="bos", mesaj=f"{hedef.name} hazır ({gecen/60:.1f} dk)",
               son_dosya=hedef.name, adim=0, toplam_adim=0)

    except Exception as e:
        _durum(asama="bos", son_hata=str(e), mesaj=f"Hata: {e}",
               adim=0, toplam_adim=0)


# ---------------------------------------------------------------- mix

class MixIstek(BaseModel):
    saat: float = 3.0
    xfade: float = 6.0
    lufs: float = -16.0
    bitrate: str = "256k"


def mix_isi(istek: MixIstek):
    try:
        _durum(asama="mix", baslangic=time.time(), son_hata=None,
               mesaj="Mix hazırlanıyor", adim=0, toplam_adim=0)
        cikti = MIX_DIR / f"lofi_mix_{istek.saat:g}saat.mp3"
        komut = [
            str(BASE / "venv" / "bin" / "python"), str(BASE / "birlestir.py"),
            "--saat", str(istek.saat), "--xfade", str(istek.xfade),
            "--lufs", str(istek.lufs), "--bitrate", istek.bitrate,
            "--cikti", cikti.name,
        ]
        r = subprocess.run(komut, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip()[-400:])
        gecen = time.time() - DURUM["baslangic"]
        _durum(asama="bos", mesaj=f"Mix hazır: {cikti.name} ({gecen/60:.1f} dk)")
    except Exception as e:
        _durum(asama="bos", son_hata=str(e), mesaj=f"Mix hatası: {e}")


# ---------------------------------------------------------------- API

@app.get("/api/durum")
def api_durum():
    parcalar = parcalari_listele()
    toplam_sure = sum(p["sure"] for p in parcalar)
    gecen = time.time() - DURUM["baslangic"] if DURUM["baslangic"] and mesgul() else 0
    kalan = None
    if mesgul() and DURUM["adim"] > 0 and DURUM["toplam_adim"] > 0:
        birim = gecen / DURUM["adim"]
        kalan = birim * (DURUM["toplam_adim"] - DURUM["adim"])

    mixler = []
    for m in sorted(MIX_DIR.glob("*.mp3")):
        mixler.append({
            "dosya": m.name,
            "boyut_mb": round(m.stat().st_size / 1e6, 1),
            "sure": round(sure_al(m), 1),
            "tarih": time.strftime("%d.%m %H:%M", time.localtime(m.stat().st_mtime)),
        })

    try:
        kullanim = shutil.disk_usage(str(BASE))
        bos_gb = round(kullanim.free / 1e9, 1)
    except Exception:
        bos_gb = None

    return {
        "asama": DURUM["asama"],
        "mesaj": DURUM["mesaj"],
        "adim": DURUM["adim"],
        "toplam_adim": DURUM["toplam_adim"],
        "gecen": round(gecen, 1),
        "kalan": round(kalan, 1) if kalan else None,
        "son_hata": DURUM["son_hata"],
        "son_dosya": DURUM["son_dosya"],
        "model_yuklu": DURUM["model_yuklu"],
        "model_gb": round(klasor_boyut_gb(MODEL_DIR), 2),
        "model_hedef_gb": MODEL_BOYUT_GB,
        "bos_disk_gb": bos_gb,
        "parcalar": parcalar,
        "mixler": mixler,
        "istatistik": {
            "adet": len(parcalar),
            "toplam_dakika": round(toplam_sure / 60, 1),
            "toplam_mb": round(sum(p["boyut_mb"] for p in parcalar), 1),
        },
        "stiller": [s["ad"] for s in STILLER],
    }


@app.post("/api/uret")
def api_uret(istek: UretIstek):
    with KILIT:
        if mesgul():
            raise HTTPException(409, "Şu an başka bir iş çalışıyor")
        threading.Thread(target=uretim_isi, args=(istek,), daemon=True).start()
    return {"tamam": True}


@app.post("/api/iptal")
def api_iptal():
    if not mesgul():
        raise HTTPException(400, "Çalışan iş yok")
    IPTAL.set()
    _durum(mesaj="İptal ediliyor, mevcut adım bitince duracak")
    return {"tamam": True}


@app.post("/api/mix")
def api_mix(istek: MixIstek):
    with KILIT:
        if mesgul():
            raise HTTPException(409, "Şu an başka bir iş çalışıyor")
        if not list(PARCA_DIR.glob("*.wav")):
            raise HTTPException(400, "Önce parça üretmelisin")
        threading.Thread(target=mix_isi, args=(istek,), daemon=True).start()
    return {"tamam": True}


@app.post("/api/model-bosalt")
def api_model_bosalt():
    if mesgul():
        raise HTTPException(409, "Çalışan iş varken model boşaltılamaz")
    model_bosalt()
    _durum(mesaj="Model bellekten boşaltıldı")
    return {"tamam": True}


def _guvenli_parca(ad: str) -> Path:
    yol = (PARCA_DIR / ad).resolve()
    if yol.parent != PARCA_DIR.resolve() or not yol.exists():
        raise HTTPException(404, "Parça bulunamadı")
    return yol


@app.delete("/api/parca/{ad}")
def api_parca_sil(ad: str):
    yol = _guvenli_parca(ad)
    yol.unlink()
    return {"tamam": True}


@app.get("/ses/{ad}")
def api_ses(ad: str):
    yol = (PARCA_DIR / ad).resolve()
    if not yol.exists() or yol.parent != PARCA_DIR.resolve():
        yol = (MIX_DIR / ad).resolve()
        if not yol.exists() or yol.parent != MIX_DIR.resolve():
            raise HTTPException(404, "Dosya yok")
    return FileResponse(str(yol))


@app.get("/indir/{ad}")
def api_indir(ad: str):
    return api_ses(ad)


@app.get("/api/klasor-ac")
def api_klasor_ac():
    subprocess.run(["open", str(MIX_DIR)])
    return {"tamam": True}


@app.get("/")
def anasayfa():
    return FileResponse(str(ARAYUZ / "index.html"))


app.mount("/statik", StaticFiles(directory=str(ARAYUZ / "statik")), name="statik")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=7878, log_level="warning")
