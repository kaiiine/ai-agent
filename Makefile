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

setup: 
	@bash setup.sh

config: 
	@bash setup.sh --config-only

install: 
	@echo -e "$(ORANGE)  →  $(NC)Installation des dépendances..."
	@$(PIP) install --upgrade pip --quiet
	@$(PIP) install -r requirements.txt --quiet
	@echo -e "$(GREEN)  ✓  $(NC)Dépendances installées"

install-dev: install 
	@echo -e "$(ORANGE)  →  $(NC)Outils de développement..."
	@$(PIP) install pytest pytest-cov black flake8 mypy --quiet
	@echo -e "$(GREEN)  ✓  $(NC)pytest · black · flake8 · mypy installés"

install-torch:
	@echo -e "$(ORANGE)  →  $(NC)PyTorch CUDA..."
	@$(PIP) install torch torchvision --index-url https://download.pytorch.org/whl/cu121 --quiet
	@echo -e "$(GREEN)  ✓  $(NC)PyTorch installé"

agent:
	@PYTHONIOENCODING=utf-8 LANG=fr_FR.UTF-8 $(PYTHON) -m src.ui.main

ui: agent 

run:
	@$(PYTHON) -m src.app

test: 
	@echo -e "$(ORANGE)  →  $(NC)Tests..."
	@$(PYTHON) -m pytest tests/ -v --cov=src --cov-report=term-missing

lint:
	@echo -e "$(ORANGE)  →  $(NC)Lint..."
	@$(PYTHON) -m flake8 src/ --max-line-length=120 --extend-ignore=E203,W503

format: 
	@echo -e "$(ORANGE)  →  $(NC)Formatage..."
	@$(PYTHON) -m black src/ configs/ --line-length=120
	@echo -e "$(GREEN)  ✓  $(NC)Code formaté"

clean:
	@echo -e "$(ORANGE)  →  $(NC)Nettoyage..."
	@find . -type d -name "__pycache__" -not -path "./venv/*" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -not -path "./venv/*" -delete 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache"   -exec rm -rf {} + 2>/dev/null || true
	@echo -e "$(GREEN)  ✓  $(NC)Nettoyage terminé"

.DEFAULT_GOAL := help
