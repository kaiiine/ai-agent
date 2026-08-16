"""Prompt système du specialist.

Les guides par stack vivent dans `skills/*.md` et sont chargés à la demande par
`load_skill`. Ils ont existé aussi en modules Python, recopiés à la main : les
deux versions ont divergé, et c'est la copie Python — celle que personne ne
relisait — qui servait de repli. Il n'y a plus qu'une source.
"""
from __future__ import annotations

from .base import BASE_PROMPT

__all__ = ["BASE_PROMPT"]
