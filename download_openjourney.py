# download_openjourney.py
from huggingface_hub import snapshot_download
from pathlib import Path

# Dossier où tu veux stocker le modèle
TARGET_DIR = Path("models/openjourney").resolve()

print(f"📦 Téléchargement d'OpenJourney dans : {TARGET_DIR}")

# Essaie la version v4, puis fallback sur v1 si indisponible
try:
    snapshot_download(
        repo_id="prompthero/openjourney-v4",
        local_dir=TARGET_DIR.as_posix(),
        local_dir_use_symlinks=False,
    )
    print("✅ Téléchargement réussi : openjourney-v4")
except Exception as e:
    print(f"⚠️ openjourney-v4 non trouvé ({e}), tentative avec openjourney...")
    snapshot_download(
        repo_id="prompthero/openjourney",
        local_dir=TARGET_DIR.as_posix(),
        local_dir_use_symlinks=False,
    )
    print("✅ Téléchargement réussi : openjourney")

print("\n🎉 Modèle OpenJourney prêt à l'emploi (offline) !")
print(f"➡️  Fichiers dans : {TARGET_DIR}")
