#!/usr/bin/env python3
"""
Script de lancement pour l'interface Rich moderne de l'Agent IA
"""

import sys
import os

# Ajouter le dossier src au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.modern_rich_interface import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Interface fermée par l'utilisateur.")
    except Exception as e:
        print(f"❌ Erreur: {e}")
