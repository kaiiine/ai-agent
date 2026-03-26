from huggingface_hub import snapshot_download
from pathlib import Path
from configs.config import DOWNLOAD_SETTINGS
import click

@click.group()
def downloads():
    """Download models for AI agent"""
    pass

@downloads.command("openjourney")
def openjourney_download():
    """Download OpenJourney v4 model"""
    try:
        snapshot_download(
            repo_id=DOWNLOAD_SETTINGS["openjourney_repo"],
            local_dir=DOWNLOAD_SETTINGS["openjourney_download_dir"].as_posix(),
            local_dir_use_symlinks=False
        )
        print('=== SUCCESSFUL DOWNLOAD: OPENJOURNEY-V4 ===')
    except Exception as e:
        print(f"openjourney-v4 not found ({e}), maybe try openjourney...")

@downloads.command("realistic-vision")
def realistic_vision_download():
    """Download Realistic Vision v6 model"""
    try:
        snapshot_download(
            repo_id=DOWNLOAD_SETTINGS["realistic_vision_repo"],
            local_dir=DOWNLOAD_SETTINGS["realistic_vision_download_dir"].as_posix(),
            local_dir_use_symlinks=False
        )
        print('=== SUCCESSFUL DOWNLOAD: REALISTIC-VISION-V6 ===')
    except Exception as e:
        print(f"realistic-vision-v6 not found ({e}), maybe try another model...")


if __name__ == "__main__":
    downloads()