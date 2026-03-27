.PHONY: help install install-dev install-torch clean test lint format run agent setup

PYTHON := python3
PIP    := pip
VENV   := venv

ORANGE     := \033[38;5;214m
ORANGE_DIM := \033[38;5;172m
GREEN      := \033[38;5;78m
WHITE      := \033[0;97m
DIM        := \033[2m
RED        := \033[0;31m
NC         := \033[0m

help: ## Affiche cette aide
	@echo ""
	@echo -e "$(ORANGE)  ██████╗ ██╗  ██╗ ██████╗ ███╗  ██╗$(NC)"
	@echo -e "$(ORANGE) ██╔══██╗╚██╗██╔╝██╔═══██╗████╗ ██║$(NC)"
	@echo -e "$(ORANGE) ███████║ ╚███╔╝ ██║   ██║██╔██╗██║$(NC)"
	@echo -e "$(ORANGE) ██╔══██║ ██╔██╗ ██║   ██║██║╚████║$(NC)"
	@echo -e "$(ORANGE) ██║  ██║██╔╝ ██╗╚██████╔╝██║ ╚███║$(NC)"
	@echo -e "$(ORANGE) ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚══╝$(NC)"
	@echo ""
	@echo -e "$(DIM)  Agent IA personnel$(NC)"
	@echo -e "$(ORANGE_DIM)  ─────────────────────────────────────$(NC)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  $(ORANGE)%-18s$(NC) $(DIM)%s$(NC)\n", $$1, $$2}'
	@echo ""

setup: ## Premier déploiement (venv + deps + modèles Ollama + config services)
	@bash setup.sh

config: ## Reconfigurer les intégrations (Slack, Google, Groq, Tavily...)
	@bash setup.sh --config-only

install: ## Installe les dépendances Python
	@echo -e "$(ORANGE)  →  $(NC)Installation des dépendances..."
	@$(PIP) install --upgrade pip --quiet
	@$(PIP) install -r requirements.txt --quiet
	@echo -e "$(GREEN)  ✓  $(NC)Dépendances installées"

install-dev: install ## Installe les outils de développement
	@echo -e "$(ORANGE)  →  $(NC)Outils de développement..."
	@$(PIP) install pytest pytest-cov black flake8 mypy --quiet
	@echo -e "$(GREEN)  ✓  $(NC)pytest · black · flake8 · mypy installés"

install-torch: ## Installe PyTorch avec support CUDA
	@echo -e "$(ORANGE)  →  $(NC)PyTorch CUDA..."
	@$(PIP) install torch torchvision --index-url https://download.pytorch.org/whl/cu121 --quiet
	@echo -e "$(GREEN)  ✓  $(NC)PyTorch installé"

agent: ## Lance Axon (interface Rich)
	@PYTHONIOENCODING=utf-8 LANG=fr_FR.UTF-8 $(PYTHON) -m src.ui.main

ui: agent ## Alias pour agent

run: ## Lance Axon en mode CLI simple
	@$(PYTHON) -m src.app

test: ## Lance les tests
	@echo -e "$(ORANGE)  →  $(NC)Tests..."
	@$(PYTHON) -m pytest tests/ -v --cov=src --cov-report=term-missing

lint: ## Vérifie le code (flake8)
	@echo -e "$(ORANGE)  →  $(NC)Lint..."
	@$(PYTHON) -m flake8 src/ --max-line-length=120 --extend-ignore=E203,W503

format: ## Formate le code (black)
	@echo -e "$(ORANGE)  →  $(NC)Formatage..."
	@$(PYTHON) -m black src/ configs/ --line-length=120
	@echo -e "$(GREEN)  ✓  $(NC)Code formaté"

clean: ## Supprime les fichiers temporaires et cache
	@echo -e "$(ORANGE)  →  $(NC)Nettoyage..."
	@find . -type d -name "__pycache__" -not -path "./venv/*" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -not -path "./venv/*" -delete 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache"   -exec rm -rf {} + 2>/dev/null || true
	@echo -e "$(GREEN)  ✓  $(NC)Nettoyage terminé"

.DEFAULT_GOAL := help
