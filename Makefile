.PHONY: help install install-dev install-torch clean test lint format run agent ui download-openjourney download-realistic-vision setup

# Variables
PYTHON := python3
PIP := pip
VENV := venv
CONDA_ENV := sd

# Couleurs pour les messages
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
RED := \033[0;31m
NC := \033[0m # No Color

help: ## Affiche ce message d'aide
	@echo "$(BLUE)════════════════════════════════════════════════════════════$(NC)"
	@echo "$(GREEN)  AI Agent - Commandes disponibles$(NC)"
	@echo "$(BLUE)════════════════════════════════════════════════════════════$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

setup: ## Configuration initiale du projet (conda + dépendances)
	@echo "$(BLUE)🔧 Configuration de l'environnement...$(NC)"
	@if [ ! -d "$(HOME)/.conda" ] && [ ! -d "/opt/miniconda3" ]; then \
		echo "$(YELLOW)⚠️  Miniconda n'est pas installé. Installation...$(NC)"; \
		cd /tmp && wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh; \
		bash Miniconda3-latest-Linux-x86_64.sh -b -p $(HOME)/miniconda3; \
		$(HOME)/miniconda3/bin/conda init zsh; \
	fi
	@echo "$(GREEN)✓ Création de l'environnement conda$(NC)"
	@bash -c "source /opt/miniconda3/etc/profile.d/conda.sh && conda create -n $(CONDA_ENV) python=3.11 -y"
	@echo "$(GREEN)✓ Environnement créé avec succès!$(NC)"
	@echo "$(YELLOW)💡 Activez l'environnement avec: conda activate $(CONDA_ENV)$(NC)"

install: ## Installe les dépendances de base
	@echo "$(BLUE)📦 Installation des dépendances...$(NC)"
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "$(GREEN)✓ Dépendances installées!$(NC)"

install-torch: ## Installe PyTorch avec support CUDA
	@echo "$(BLUE)🔥 Installation de PyTorch avec CUDA...$(NC)"
	$(PIP) install torch torchvision --index-url https://download.pytorch.org/whl/cu121
	@echo "$(GREEN)✓ PyTorch installé avec support CUDA!$(NC)"

install-dev: install ## Installe les dépendances de développement
	@echo "$(BLUE)🛠️  Installation des outils de développement...$(NC)"
	$(PIP) install pytest pytest-cov black flake8 mypy
	@echo "$(GREEN)✓ Outils de développement installés!$(NC)"

clean: ## Nettoie les fichiers temporaires et cache
	@echo "$(BLUE)🧹 Nettoyage...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)✓ Nettoyage terminé!$(NC)"

test: ## Lance les tests
	@echo "$(BLUE)🧪 Lancement des tests...$(NC)"
	$(PYTHON) -m pytest tests/ -v --cov=src --cov-report=term-missing
	@echo "$(GREEN)✓ Tests terminés!$(NC)"

lint: ## Vérifie le code avec flake8
	@echo "$(BLUE)🔍 Analyse du code...$(NC)"
	$(PYTHON) -m flake8 src/ --max-line-length=120 --extend-ignore=E203,W503
	@echo "$(GREEN)✓ Analyse terminée!$(NC)"

format: ## Formate le code avec black
	@echo "$(BLUE)✨ Formatage du code...$(NC)"
	$(PYTHON) -m black src/ configs/ downloads/ --line-length=120
	@echo "$(GREEN)✓ Code formaté!$(NC)"

run: ## Lance l'agent en mode CLI simple
	@echo "$(BLUE)🤖 Lancement de l'agent CLI...$(NC)"
	$(PYTHON) -m src.app

agent: ## Lance l'agent avec interface Rich
	@echo "$(BLUE)🎨 Lancement de l'agent avec interface Rich...$(NC)"
	$(PYTHON) -m src.ui.main

ui: agent ## Alias pour agent

download-openjourney: ## Télécharge le modèle OpenJourney v4
	@echo "$(BLUE)📥 Téléchargement de OpenJourney v4...$(NC)"
	$(PYTHON) -m configs.downloads openjourney

download-realistic-vision: ## Télécharge le modèle Realistic Vision v6
	@echo "$(BLUE)📥 Téléchargement de Realistic Vision v6...$(NC)"
	$(PYTHON) -m configs.downloads realistic-vision

download-all: download-openjourney download-realistic-vision ## Télécharge tous les modèles

generate-image: ## Teste la génération d'image avec OpenJourney
	@echo "$(BLUE)🎨 Génération d'une image de test...$(NC)"
	$(PYTHON) test_oj.py

# Raccourcis utiles
dev: install-dev format lint test ## Setup complet pour le développement

quick: clean install ## Installation rapide sans dev deps

all: setup install-torch install ## Installation complète (setup + torch + deps)

.DEFAULT_GOAL := help
