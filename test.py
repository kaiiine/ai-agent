#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil
from pathlib import Path
from typing import List
from huggingface_hub import hf_hub_download, list_repo_files, HfApi

REPO_ID = "SG161222/Realistic_Vision_V6.0_B1_noVAE"
CANDIDATE_FILENAMES: List[str] = [
    "Realistic_Vision_V6.0_B1_noVAE.safetensors",  # le plus probable pour ce repo
    "Realistic_Vision_V6.0_B1.safetensors",
    "Realistic_Vision_V6.0_NV_B1.safetensors",
]
LOCAL_DIR = Path("./models/realistic-vision-v6")
CLEAN_BEFORE = True  # passe à False si tu veux garder l’existant

def main():
    print("🔧 Préparation...")

    if CLEAN_BEFORE and LOCAL_DIR.exists():
        print(f"🧹 Suppression de {LOCAL_DIR} ...")
        shutil.rmtree(LOCAL_DIR)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Lister les fichiers dispo sur le repo pour éviter un 404
    print(f"🔎 Listing des fichiers sur '{REPO_ID}' ...")
    try:
        files = list_repo_files(REPO_ID, repo_type="model", token=os.getenv("HF_TOKEN"))
    except Exception as e:
        print(f"❌ Impossible de lister les fichiers du repo: {e}")
        sys.exit(1)

    if not files:
        print("❌ Aucun fichier trouvé sur le repo (ou accès refusé).")
        print("   - Si privé: exporte HF_TOKEN=hf_xxx")
        sys.exit(1)

    # 2) Choisir un nom qui existe vraiment
    picked = None
    for name in CANDIDATE_FILENAMES:
        if name in files:
            picked = name
            break

    if not picked:
        # tenter une détection automatique d'un .safetensors
        safes = [f for f in files if f.lower().endswith(".safetensors")]
        if safes:
            picked = safes[0]
            print(f"ℹ️ Aucun des noms candidats trouvés, mais j’ai détecté: {picked}")
        else:
            print("❌ Aucun fichier .safetensors trouvé sur ce repo.")
            print("   Fichiers disponibles (extrait):")
            for f in files[:50]:
                print("  -", f)
            sys.exit(1)

    # 3) Télécharger
    print(f"⬇️  Téléchargement: {picked}")
    try:
        local_path = hf_hub_download(
            repo_id=REPO_ID,
            filename=picked,
            repo_type="model",
            local_dir=str(LOCAL_DIR),
            token=os.getenv("HF_TOKEN"),
            # depuis huggingface_hub>=0.26, resume est implicite.
            # utilise force_download=True si tu veux forcer un redownload.
        )
    except Exception as e:
        print("\n❌ Échec du téléchargement.")
        print(f"Raison: {e}\n")
        print("Pistes:")
        print("- 404: mauvais nom de fichier → voir listing ci-dessus.")
        print("- 403/401: repo privé → exporte HF_TOKEN=hf_xxx.")
        print("- Réseau instable → relance, la reprise est automatique.")
        sys.exit(1)

    size_mb = Path(local_path).stat().st_size / (1024 * 1024)
    print(f"\n✅ Fichier téléchargé: {local_path}")
    print(f"   Taille: {size_mb:.1f} MB")
    print(f"📂 Dossier: {LOCAL_DIR.resolve()}")

    # 4) Exemple d’usage
    print("\n💡 Exemple d’utilisation (diffusers.from_single_file):")
    print(f"""\
from diffusers import StableDiffusionPipeline
import torch
pipe = StableDiffusionPipeline.from_single_file(
    "{(LOCAL_DIR / picked).as_posix()}",
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    safety_checker=None,
    feature_extractor=None,
).to("cuda" if torch.cuda.is_available() else "cpu")
img = pipe("a realistic photo of a city street at night, ultra-detailed").images[0]
img.save("test.png")
print("Image écrite: test.png")
""")

if __name__ == "__main__":
    main()
