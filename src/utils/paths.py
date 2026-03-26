# src/utils/paths.py
from pathlib import Path

_HOME = Path.home()


def get_projects_dir() -> Path:
    """Retourne le dossier racine des projets configuré dans settings.
    Fallback sur $HOME si non configuré ou inexistant."""
    from src.infra.settings import settings
    p = settings.projects_dir.strip()
    if p:
        resolved = Path(p).expanduser()
        if resolved.exists():
            return resolved
    return _HOME
