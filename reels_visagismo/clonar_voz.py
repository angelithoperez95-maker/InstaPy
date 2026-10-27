#!/usr/bin/env python3
"""Genera la locución de cada escena con la voz clonada del barbero.

1. Texto -> voz base en español (Piper / VITS, vía sherpa-onnx).
2. Voz base -> tu voz con kNN-VC (WavLM + HiFi-GAN), usando como referencia un audio tuyo.

Uso:
    python3 clonar_voz.py --ref mi_audio.mp3 --models DIR_MODELOS [--solo 1 3]

DIR_MODELOS tiene que tener:
    vits-piper-es_MX-ald-medium/   (github.com/k2-fsa/sherpa-onnx/releases, tag tts-models)
    knn-vc/                        (clon de github.com/bshall/knn-vc)
    prematch_g_02500000.pt, WavLM-Large.pt  (releases v0.1 de bshall/knn-vc)
Salida: voz/<video>/esc<N>.wav a 16 kHz.
"""
import argparse
import os
import shutil
import subprocess
import sys

import numpy as np
import soundfile as sf

from locucion import LOCUCION

HERE = os.path.dirname(os.path.abspath(__file__))


def load_vc(models):
    import torch
    ckpt = os.path.join(torch.hub.get_dir(), "checkpoints")
    os.makedirs(ckpt, exist_ok=True)
    for f in ("prematch_g_02500000.pt", "WavLM-Large.pt"):
        if not os.path.exists(os.path.join(ckpt, f)):
            os.symlink(os.path.join(models, f), os.path.join(ckpt, f))
    sys.path.insert(0, os.path.join(models, "knn-vc"))
    from hubconf import knn_vc
    return knn_vc(pretrained=True, prematched=True, device="cpu")


def load_tts(models, voice="vits-piper-es_MX-ald-medium"):
    import sherpa_onnx
    d = os.path.join(models, voice)
    onnx = [f for f in os.listdir(d) if f.endswith(".onnx")][0]
    cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=os.path.join(d, onnx), tokens=os.path.join(d, "tokens.txt"),
                                                   data_dir=os.path.join(d, "espeak-ng-data")),
        num_threads=4))
    return sherpa_onnx.OfflineTts(cfg)


def to16k(src, dst, extra=()):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, *extra, "-ac", "1", "-ar", "16000", dst], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="audio con tu voz (idealmente 1+ min, sin música)")
    ap.add_argument("--ref-hasta", type=float, default=0, help="usar solo los primeros N segundos de la referencia")
    ap.add_argument("--models", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "voz"))
    ap.add_argument("--speed", type=float, default=1.08)
    ap.add_argument("--topk", type=int, default=4)
    ap.add_argument("--solo", type=int, nargs="*")
    a = ap.parse_args()

    import torch
    tmp = os.path.join(a.out, "_tmp")
    os.makedirs(tmp, exist_ok=True)
    ref = os.path.join(tmp, "ref16k.wav")
    to16k(a.ref, ref, ["-t", str(a.ref_hasta)] if a.ref_hasta else [])

    vc = load_vc(a.models)
    tts = load_tts(a.models)
    wav, _ = sf.read(ref, dtype="float32")
    step = 10 * 16000  # en tramos de 10 s para no saturar memoria
    chunks = [torch.from_numpy(wav[i:i + step])[None] for i in range(0, len(wav), step) if len(wav[i:i + step]) > 16000]
    matching = vc.get_matching_set(chunks)

    for i, (slug, lines) in enumerate(LOCUCION.items(), 1):
        if a.solo and i not in a.solo:
            continue
        od = os.path.join(a.out, slug)
        os.makedirs(od, exist_ok=True)
        for j, text in enumerate(lines, 1):
            audio = tts.generate(text, sid=0, speed=a.speed)
            raw = os.path.join(tmp, "tts.wav")
            sf.write(raw, np.array(audio.samples, dtype=np.float32), audio.sample_rate)
            src = os.path.join(tmp, "tts16k.wav")
            to16k(raw, src)
            q = vc.get_features(torch.from_numpy(sf.read(src, dtype="float32")[0])[None])
            out = vc.match(q, matching, topk=a.topk).cpu().numpy()
            dst = os.path.join(od, f"esc{j}.wav")
            sf.write(os.path.join(tmp, "vc.wav"), out, 16000)
            # recortar silencios de punta y normalizar volumen
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.join(tmp, "vc.wav"), "-af",
                            "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                            "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                            "highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "16000", dst], check=True)
            print(f"{slug} esc{j}: {sf.info(dst).duration:.1f}s")
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
