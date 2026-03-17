# improve_sd_quality.py
from pathlib import Path
from PIL import Image
import torch
from diffusers import (
    StableDiffusionPipeline,
    StableDiffusionImg2ImgPipeline,
    AutoencoderKL,
    DPMSolverMultistepScheduler,
)

# --------- Config minimaliste ----------
MODEL = Path("models/realistic-vision-v6/Realistic_Vision_V6.0_NV_B1.safetensors").resolve()
assert MODEL.is_file(), f"Fichier introuvable: {MODEL}"
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32
SEED = 42

prompt = (
  "Autopportait d'un jeune français en 2025, étudiant en ingénieur, style très réaliste"
)
negative = "blurry, lowres, bad anatomy, text, watermark, signature"


# --------- Chargement pipeline ----------
pipe = StableDiffusionPipeline.from_single_file(
    MODEL.as_posix(),
    torch_dtype=dtype,
    safety_checker=None,
    feature_extractor=None,
)
# Scheduler DPM++ 2M Karras = très net/stable
pipe.scheduler = DPMSolverMultistepScheduler.from_config(
    pipe.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True
)

# Ton checkpoint est NV (sans VAE) -> on met un VAE de qualité
pipe.vae = AutoencoderKL.from_pretrained(
    "./models/sd-vae-ft-ema", torch_dtype=dtype
)


# Optimisations
if device == "cuda":
    torch.backends.cuda.matmul.allow_tf32 = True
pipe.enable_attention_slicing()
pipe.enable_vae_slicing()
pipe.enable_vae_tiling()
pipe = pipe.to(device)

gen = torch.Generator(device=device).manual_seed(SEED)

# --------- PASS 1 : génération propre à 512px ----------
base = pipe(
    prompt,
    negative_prompt=negative,
    num_inference_steps=40,    # 35–50 pour du détail
    guidance_scale=6.5,        # 5.5–7.5 ; évite trop haut (sur-lissage)
    height=896, width=640,     # natif SD1.5 -> + propre
    guidance_rescale=0.7,      # atténue les artefacts CFG
    generator=gen,
).images[0]
base.save("out_base_512.png")

# --------- PASS 2 : HIRES-FIX (img2img) ----------
# On upscale d’abord proprement (LANCZOS), puis on “raffine” avec faible strength
target_long_side = 712  # mets 768, 1024 ou 1280 selon ta VRAM
w, h = base.size
if w >= h:
    new_w = target_long_side
    new_h = int(h * (target_long_side / w))
else:
    new_h = target_long_side
    new_w = int(w * (target_long_side / h))

up = base.resize((new_w, new_h), Image.LANCZOS)

img2img = StableDiffusionImg2ImgPipeline.from_pipe(pipe)
# strength bas (= conserve la composition, ajoute du micro-détail)
hires = img2img(
    prompt=prompt,
    negative_prompt=negative,
    image=up,
    strength=0.25,             # 0.2–0.35 ; plus haut = plus différent, plus bas = plus fidèle
    num_inference_steps=35,
    guidance_scale=6.0,
    generator=gen,
).images[0]

hires.save("out_final.png")
print("✅ Images écrites : out_base_512.png (étape 1), out_final.png (hires)")
