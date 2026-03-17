# src/agents/image/tools.py
from __future__ import annotations
import os
from typing import List, Optional
from langchain_core.tools import tool
from configs.config import IMAGE_SETTINGS
import requests
from pathlib import Path
from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
import torch
import gc

# Cache global pour le pipeline (évite de recharger à chaque fois)
_pipeline_cache = {}

def _get_or_load_pipeline(model_type: str):
    """Charge le pipeline une seule fois et le met en cache"""
    if model_type in _pipeline_cache:
        return _pipeline_cache[model_type]
    
    MODEL_DIR = IMAGE_SETTINGS["fantasy_model_dir"] if model_type == "fantasy" else IMAGE_SETTINGS.get("realistic_model_dir")
    
    if not MODEL_DIR or not MODEL_DIR.exists():
        raise FileNotFoundError(
            f"The directory {MODEL_DIR} is not found.\n"
            "Please download the model first using the appropriate script."
        )
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    pipe = StableDiffusionPipeline.from_pretrained(
        MODEL_DIR.as_posix(),
        dtype=dtype,
        safety_checker=None,
        feature_extractor=None,
        use_safetensors=True,
        local_files_only=True,
        low_cpu_mem_usage=True,  # Optimisation mémoire
    )

    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
    pipe = pipe.to(device)
    
    # Activer l'attention optimisée si disponible
    if hasattr(pipe, 'enable_attention_slicing'):
        pipe.enable_attention_slicing()
    
    _pipeline_cache[model_type] = pipe
    return pipe

def _cleanup_memory():
    """Libère la mémoire GPU après génération"""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()

@tool("generate_realistic_image", return_direct=True)
def generate_realistic_image(prompt: str) -> str:
    """Generate a realistic image based on a text prompt using the Stable Diffusion API.
    
    Args:
        prompt: The text prompt describing the desired image.
        
    Returns:
        A URL to the generated image.
    """
    

@tool("generate_fantasy_image", return_direct=True)
def generate_fantasy_image(prompt: str, style: Optional[str] = "fantasy art") -> str:
    """Generate a fantasy-style image based on a text prompt using the Open Journey model.
    
    Args:
        prompt: The text prompt describing the desired image.
        style: The artistic style to apply (default is "fantasy art").
        
    Returns:
        Path to the generated image.
    """
    try:
        # Charger le pipeline (mis en cache)
        pipe = _get_or_load_pipeline("fantasy")
        
        # Préparer le prompt avec le style
        full_prompt = f"{prompt}, {style}" if style else prompt
        negative = "blurry, lowres, bad anatomy, text, watermark, signature, ugly, deformed"

        # Générer l'image
        image = pipe(
            full_prompt,
            negative_prompt=negative,
            guidance_scale=7.5,
            num_inference_steps=30,  # Réduit de 40 à 30 pour plus de rapidité
            width=512, 
            height=512,
        ).images[0]

        # Sauvegarder
        out_path = Path("fantasy_image_result.png").resolve()
        image.save(out_path)
        
        # Nettoyer la mémoire
        _cleanup_memory()
        
        return f"✅ Image générée et sauvegardée : {out_path}"
    
    except Exception as e:
        _cleanup_memory()
        return f"❌ Erreur lors de la génération : {str(e)}"