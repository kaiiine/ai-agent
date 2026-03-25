#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  Axon — Script de déploiement
#  Usage : bash setup.sh
# ──────────────────────────────────────────────────────────────
set -euo pipefail

ORANGE='\033[38;5;214m'
ORANGE_DIM='\033[38;5;172m'
WHITE='\033[0;97m'
GREEN='\033[38;5;78m'
RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓  ${NC}$*"; }
info() { echo -e "${ORANGE}  →  ${NC}$*"; }
warn() { echo -e "${ORANGE_DIM}  ⚠  ${NC}$*"; }
fail() { echo -e "${RED}  ✗  ${NC}$*"; exit 1; }
step() { echo -e "\n${ORANGE}━━  ${WHITE}$*${NC}"; }

# ── Bannière ──────────────────────────────────────────────────
echo ""
echo -e "${ORANGE}  ██████╗ ██╗  ██╗ ██████╗ ███╗  ██╗${NC}"
echo -e "${ORANGE} ██╔══██╗╚██╗██╔╝██╔═══██╗████╗ ██║${NC}"
echo -e "${ORANGE} ███████║ ╚███╔╝ ██║   ██║██╔██╗██║${NC}"
echo -e "${ORANGE} ██╔══██║ ██╔██╗ ██║   ██║██║╚████║${NC}"
echo -e "${ORANGE} ██║  ██║██╔╝ ██╗╚██████╔╝██║ ╚███║${NC}"
echo -e "${ORANGE} ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚══╝${NC}"
echo ""
echo -e "${DIM}  Agent IA personnel — Script de déploiement${NC}"
echo -e "${ORANGE_DIM}  ─────────────────────────────────────${NC}"
echo ""

# ── 1. Prérequis système ──────────────────────────────────────
step "Prérequis système"

# Python 3.11+
if ! command -v python3 &>/dev/null; then
    fail "Python 3 introuvable. Installe Python 3.11+ puis relance."
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11 ) ]]; then
    fail "Python 3.11+ requis (version actuelle : $PY_VERSION)"
fi
ok "Python $PY_VERSION"

# Ollama
if ! command -v ollama &>/dev/null; then
    warn "Ollama non installé. Installation..."
    curl -fsSL https://ollama.com/install.sh | sh
    ok "Ollama installé"
else
    ok "Ollama $(ollama --version 2>/dev/null | head -1)"
fi

# LibreOffice (export PDF des lettres de motivation)
if command -v libreoffice &>/dev/null; then
    ok "LibreOffice (export PDF)"
else
    warn "LibreOffice absent — export PDF des lettres indisponible"
    warn "  sudo pacman -S libreoffice-still   ou   sudo apt install libreoffice"
fi

# xclip/xsel (presse-papiers → /paste)
if command -v xclip &>/dev/null || command -v xsel &>/dev/null; then
    ok "Presse-papiers (xclip/xsel)"
else
    warn "xclip/xsel absent — commande /paste indisponible"
    warn "  sudo pacman -S xclip   ou   sudo apt install xclip"
fi

# ── 2. Environnement virtuel ──────────────────────────────────
step "Environnement virtuel Python"

if [[ ! -d "venv" ]]; then
    info "Création du venv..."
    python3 -m venv venv
    ok "venv créé"
else
    ok "venv déjà présent"
fi

source venv/bin/activate
ok "venv activé"

# ── 3. Dépendances Python ─────────────────────────────────────
step "Dépendances Python"

pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
ok "requirements.txt installé"

# ── 4. Configuration (.env) ───────────────────────────────────
step "Configuration"

if [[ ! -f ".env" ]]; then
    cp .env.sample .env
    ok ".env créé depuis .env.sample"
    warn "Ouvre .env et remplis les clés API avant de lancer"
else
    ok ".env déjà présent"
fi

# ── 5. Modèles Ollama ─────────────────────────────────────────
step "Modèles Ollama"

# Démarrer Ollama si pas en cours
if ! ollama list &>/dev/null 2>&1; then
    info "Démarrage d'Ollama en arrière-plan..."
    ollama serve &>/dev/null &
    sleep 3
fi

# nomic-embed-text — OBLIGATOIRE (ToolRetriever)
if ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
    ok "nomic-embed-text (embedding) déjà présent"
else
    info "Téléchargement de nomic-embed-text (~274 MB, requis)..."
    ollama pull nomic-embed-text
    ok "nomic-embed-text prêt"
fi

# LLM local — optionnel
echo ""
echo -e "  ${DIM}Backend local (ollama) — optionnel si tu utilises groq ou ollama_cloud${NC}"
read -rp "$(echo -e "  ${ORANGE}?${NC}  Télécharger qwen2.5:7b pour le backend local ? [o/N] ")" pull_local
if [[ "$pull_local" =~ ^[oOyY]$ ]]; then
    info "Téléchargement de qwen2.5:7b (~4.4 GB)..."
    ollama pull qwen2.5:7b
    ok "qwen2.5:7b prêt"
fi

# ── 6. Google OAuth ───────────────────────────────────────────
step "Google Services (optionnel)"

if [[ -f "gcp-oauth.keys.json" ]]; then
    ok "gcp-oauth.keys.json trouvé — OAuth configuré"
else
    warn "gcp-oauth.keys.json absent"
    echo -e "  ${DIM}Gmail · Calendar · Drive · Docs · Slides ne seront pas disponibles${NC}"
    echo -e "  ${DIM}Pour activer : télécharge le fichier OAuth2 depuis Google Cloud Console${NC}"
    echo -e "  ${DIM}APIs & Services → Credentials → OAuth 2.0 → Download JSON${NC}"
    echo -e "  ${DIM}Renomme-le gcp-oauth.keys.json et place-le à la racine du projet${NC}"
fi

# ── Récapitulatif ─────────────────────────────────────────────
echo ""
echo -e "${ORANGE}  ─────────────────────────────────────${NC}"
echo -e "${ORANGE}  Prêt.${NC}"
echo ""
echo -e "  ${WHITE}Lancer Axon :${NC}"
echo -e "    ${ORANGE}source venv/bin/activate${NC}"
echo -e "    ${ORANGE}python -m src.ui.main${NC}"
echo ""
echo -e "  ${DIM}ou${NC}  ${ORANGE}make agent${NC}  ${DIM}(si venv déjà activé)${NC}"
echo ""
