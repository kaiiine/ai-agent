#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  Axon — Installateur one-line
#  Usage : curl -fsSL https://ton-serveur.com/install.sh | sh
# ──────────────────────────────────────────────────────────────
set -euo pipefail

ORANGE='\033[38;5;214m'
WHITE='\033[0;97m'
GREEN='\033[38;5;78m'
RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

ok()   { echo -e "${GREEN}  ✓  ${NC}$*"; }
info() { echo -e "${ORANGE}  →  ${NC}$*"; }
fail() { echo -e "${RED}  ✗  ${NC}$*" >&2; exit 1; }
step() { echo -e "\n${ORANGE}━━  ${WHITE}$*${NC}"; }

# ── À modifier selon ton hébergement ──────────────────────────
REPO_URL="https://github.com/kaiiine/ai-agent.git"
INSTALL_DIR="${AXON_INSTALL_DIR:-$HOME/.axon}"
# ──────────────────────────────────────────────────────────────

echo ""
echo -e "${ORANGE}  ██████╗ ██╗  ██╗ ██████╗ ███╗  ██╗${NC}"
echo -e "${ORANGE} ██╔══██╗╚██╗██╔╝██╔═══██╗████╗ ██║${NC}"
echo -e "${ORANGE} ███████║ ╚███╔╝ ██║   ██║██╔██╗██║${NC}"
echo -e "${ORANGE} ██╔══██║ ██╔██╗ ██║   ██║██║╚████║${NC}"
echo -e "${ORANGE} ██║  ██║██╔╝ ██╗╚██████╔╝██║ ╚███║${NC}"
echo -e "${ORANGE} ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚══╝${NC}"
echo ""

# ── Prérequis : git ───────────────────────────────────────────
step "Vérification des prérequis"

if ! command -v git &>/dev/null; then
    info "git non trouvé — installation..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y git
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm git
    elif command -v brew &>/dev/null; then
        brew install git
    else
        fail "Installe git manuellement puis relance."
    fi
fi
ok "git $(git --version | cut -d' ' -f3)"

# ── Clonage ───────────────────────────────────────────────────
step "Téléchargement d'Axon"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Mise à jour de l'installation existante..."
    git -C "$INSTALL_DIR" pull --ff-only
    ok "Mis à jour → $INSTALL_DIR"
else
    if [[ -d "$INSTALL_DIR" ]]; then
        fail "$INSTALL_DIR existe déjà mais n'est pas un repo git. Supprime-le ou définis AXON_INSTALL_DIR."
    fi
    info "Clonage dans $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    ok "Cloné → $INSTALL_DIR"
fi

# ── Lancement du setup ────────────────────────────────────────
cd "$INSTALL_DIR"
exec < /dev/tty
bash setup.sh

# ── Alias global (optionnel) ──────────────────────────────────
step "Commande globale 'axon'"

SHELL_RC=""
if [[ -f "$HOME/.zshrc" ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [[ -f "$HOME/.bashrc" ]]; then
    SHELL_RC="$HOME/.bashrc"
fi

ALIAS_LINE="alias axon='cd $INSTALL_DIR && source venv/bin/activate && PYTHONIOENCODING=utf-8 LANG=fr_FR.UTF-8 python -m src.ui.main'"

if [[ -n "$SHELL_RC" ]]; then
    if grep -q "alias axon=" "$SHELL_RC" 2>/dev/null; then
        ok "Alias 'axon' déjà présent dans $SHELL_RC"
    else
        echo "" >> "$SHELL_RC"
        echo "# Axon — assistant IA" >> "$SHELL_RC"
        echo "$ALIAS_LINE" >> "$SHELL_RC"
        ok "Alias 'axon' ajouté dans $SHELL_RC"
    fi
fi

echo ""
echo -e "${ORANGE}  ─────────────────────────────────────${NC}"
echo -e "${ORANGE}  Installation terminée.${NC}"
echo ""
echo -e "  Lance Axon avec :"
echo -e "    ${ORANGE}axon${NC}   ${DIM}(après avoir rechargé ton shell : source $SHELL_RC)${NC}"
echo ""
echo -e "  Ou directement :"
echo -e "    ${ORANGE}cd $INSTALL_DIR && source venv/bin/activate && python -m src.ui.main${NC}"
echo ""
