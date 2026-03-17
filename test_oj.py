from pathlib import Path
from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
import torch

# --- Chemin du modèle téléchargé ---
MODEL_DIR = Path("models/openjourney").resolve()

if not MODEL_DIR.exists():
    raise FileNotFoundError(
        f"❌ Le dossier {MODEL_DIR} est introuvable.\n"
        "Télécharge d'abord le modèle avec download_openjourney.py."
    )

# --- Matos ---
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32
print(f"💻 Utilisation de : {device} ({dtype})")

# --- Chargement du pipeline ---
print("🔧 Chargement du modèle OpenJourney...")

# CORRECTION: Utiliser dtype au lieu de torch_dtype et ajouter use_safetensors
pipe = StableDiffusionPipeline.from_pretrained(
    MODEL_DIR.as_posix(),
    dtype=dtype,  # Changé de torch_dtype à dtype
    safety_checker=None,
    feature_extractor=None,
    use_safetensors=True,  # Ajouté
    local_files_only=True,  # Ajouté pour éviter de télécharger
)

pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
pipe = pipe.to(device)

# --- Prompt ---
prompt = (
    "Autoportrait d'un français du 18ème siècle, style peinture à l'huile, "
)
negative = "blurry, lowres, bad anatomy, text, watermark, signature"

# --- Génération ---
print("🎨 Génération en cours...")
image = pipe(
    prompt,
    negative_prompt=negative,
    guidance_scale=7.5,
    num_inference_steps=40,
    width=512, 
    height=512,
).images[0]

# --- Sauvegarde ---
out_path = Path("openjourney_result.png").resolve()
image.save(out_path)
print(f"✅ Image générée : {out_path}")