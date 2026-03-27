#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  Axon — Script de déploiement
#  Usage : bash setup.sh [--config-only]
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
banner() {
    echo ""
    echo -e "${ORANGE}  ██████╗ ██╗  ██╗ ██████╗ ███╗  ██╗${NC}"
    echo -e "${ORANGE} ██╔══██╗╚██╗██╔╝██╔═══██╗████╗ ██║${NC}"
    echo -e "${ORANGE} ███████║ ╚███╔╝ ██║   ██║██╔██╗██║${NC}"
    echo -e "${ORANGE} ██╔══██║ ██╔██╗ ██║   ██║██║╚████║${NC}"
    echo -e "${ORANGE} ██║  ██║██╔╝ ██╗╚██████╔╝██║ ╚███║${NC}"
    echo -e "${ORANGE} ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚══╝${NC}"
    echo ""
}

# ── Helpers .env ──────────────────────────────────────────────

# Lit la valeur d'une clé dans .env (retourne "" si absente)
env_get() {
    local key="$1"
    grep -E "^${key}=" .env 2>/dev/null | cut -d= -f2- | tr -d '"' || echo ""
}

# Écrit ou met à jour une clé dans .env
env_set() {
    local key="$1" value="$2"
    if grep -qE "^${key}=" .env 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" .env
    else
        echo "${key}=${value}" >> .env
    fi
}

# Affiche le statut d'une clé : ✓ configurée / ⚠ manquante
env_status() {
    local key="$1" label="$2"
    local val
    val=$(env_get "$key")
    if [[ -n "$val" && "$val" != *"..."* && "$val" != "your_"* ]]; then
        ok "${label}"
    else
        warn "${label} ${DIM}(non configuré)${NC}"
    fi
}

# Demande une valeur, propose de conserver l'existante
prompt_key() {
    local key="$1" label="$2" hint="$3"
    local current
    current=$(env_get "$key")

    echo ""
    echo -e "  ${ORANGE}${label}${NC}"
    echo -e "  ${DIM}${hint}${NC}"
    if [[ -n "$current" && "$current" != *"..."* && "$current" != "your_"* ]]; then
        echo -e "  ${DIM}Valeur actuelle : ${current:0:12}…  (Entrée pour conserver)${NC}"
    fi
    read -rp "  $(echo -e "${ORANGE}>${NC}") " input
    if [[ -n "$input" ]]; then
        env_set "$key" "$input"
        ok "${key} enregistré"
    else
        [[ -n "$current" ]] && ok "${key} conservé" || warn "${key} ignoré"
    fi
}

# ──────────────────────────────────────────────────────────────
#  CONFIGURATION DES SERVICES
# ──────────────────────────────────────────────────────────────

config_tavily() {
    step "Tavily — Recherche web"
    echo -e "  ${DIM}Tavily permet la recherche web. Requis pour le tool web_research_report.${NC}"
    echo -e "  ${DIM}Créer un compte gratuit → https://app.tavily.com${NC}"
    echo -e "  ${DIM}Settings → API Keys → Copy${NC}"
    prompt_key "TAVILY_API_KEY" "Clé API Tavily" "Format : tvly-xxxxxxxxxxxxxxxxxxxx"
}

config_groq() {
    step "Groq — Backend LLM cloud rapide"
    echo -e "  ${DIM}Groq donne accès à LLaMA, Qwen, DeepSeek avec une latence très faible.${NC}"
    echo -e "  ${DIM}Créer un compte → https://console.groq.com${NC}"
    echo -e "  ${DIM}API Keys → Create API Key → Copy${NC}"
    prompt_key "GROQ_API_KEY" "Clé API Groq" "Format : gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
}

config_ollama_cloud() {
    step "Ollama Cloud — Backend cloud (optionnel)"
    echo -e "  ${DIM}Permet d'utiliser des modèles cloud via Ollama (ex: kimi-k2, qwen3-next).${NC}"
    echo -e "  ${DIM}Compte Ollama → https://ollama.com/settings/api-keys${NC}"
    echo -e "  ${DIM}Laisser vide pour utiliser ollama_cloud sans clé (connexion locale via 'ollama signin').${NC}"
    prompt_key "OLLAMA_API_KEY" "Clé API Ollama Cloud" "Format : ollama_xxxx  (optionnel)"
}

config_slack() {
    step "Slack — Intégration workspace"
    echo -e "  ${DIM}Permet de lire les canaux, DMs, mentions et d'envoyer des messages.${NC}"
    echo ""
    echo -e "  ${ORANGE}Étapes :${NC}"
    echo -e "  ${DIM}1. Aller sur https://api.slack.com/apps${NC}"
    echo -e "  ${DIM}2. Créer une nouvelle app → From scratch${NC}"
    echo -e "  ${DIM}3. OAuth & Permissions → User Token Scopes, ajouter :${NC}"
    echo -e "  ${DIM}   channels:read  channels:history  users:read  users:read.email${NC}"
    echo -e "  ${DIM}   im:read  im:history  chat:write  search:read  groups:read${NC}"
    echo -e "  ${DIM}4. Install to Workspace → Copy User OAuth Token${NC}"
    prompt_key "SLACK_USER_TOKEN" "User Token Slack" "Format : xoxp-xxxxxxxxxxxx-xxxxxxxxxxxx-xxxxxxxxxxxxxxxx"
}

config_google() {
    step "Google — Gmail · Calendar · Drive · Docs · Slides"
    echo -e "  ${DIM}Utilise OAuth2 via un fichier de credentials (pas une clé API).${NC}"
    echo -e "  ${DIM}Le token est sauvegardé automatiquement à ~/.ai-agent/google_token.pickle.${NC}"
    echo ""
    echo -e "  ${ORANGE}Étapes :${NC}"
    echo -e "  ${DIM}1. Aller sur https://console.cloud.google.com${NC}"
    echo -e "  ${DIM}2. Créer un projet (ou en sélectionner un existant)${NC}"
    echo -e "  ${DIM}3. APIs & Services → Enable APIs :${NC}"
    echo -e "  ${DIM}   Gmail API · Google Calendar API · Drive API${NC}"
    echo -e "  ${DIM}   Docs API · Slides API · Sheets API${NC}"
    echo -e "  ${DIM}4. APIs & Services → Credentials → Create Credentials${NC}"
    echo -e "  ${DIM}   → OAuth 2.0 Client ID → Desktop App${NC}"
    echo -e "  ${DIM}5. Download JSON → renommer en gcp-oauth.keys.json${NC}"
    echo -e "  ${DIM}6. Placer gcp-oauth.keys.json à la racine du projet${NC}"
    echo ""

    if [[ -f "gcp-oauth.keys.json" ]]; then
        ok "gcp-oauth.keys.json déjà présent"
        echo -e "  ${DIM}Le navigateur s'ouvrira au premier lancement pour l'autorisation OAuth.${NC}"
    else
        warn "gcp-oauth.keys.json absent"
        read -rp "  $(echo -e "${ORANGE}?${NC}") Chemin vers ton fichier OAuth2 JSON (Entrée pour ignorer) : " oauth_path
        if [[ -n "$oauth_path" && -f "$oauth_path" ]]; then
            cp "$oauth_path" gcp-oauth.keys.json
            ok "gcp-oauth.keys.json copié"
        else
            warn "Google Services non configurés — à faire manuellement"
        fi
    fi
}

config_user_name() {
    step "Ton identité"
    echo -e "  ${DIM}Ton prénom ou alias sera utilisé par Axon pour te répondre personnellement.${NC}"
    local current
    current=$(env_get "USER_NAME")
    echo ""
    if [[ -n "$current" && "$current" != "Ton Prénom Nom" ]]; then
        echo -e "  ${DIM}Valeur actuelle : ${current}  (Entrée pour conserver)${NC}"
    fi
    read -rp "  $(echo -e "${ORANGE}>  Ton prénom / alias :${NC} ")" input
    if [[ -n "$input" ]]; then
        env_set "USER_NAME" "$input"
        ok "Bonjour, ${input} !"
    else
        if [[ -n "$current" && "$current" != "Ton Prénom Nom" ]]; then
            ok "Conservé : ${current}"
        else
            warn "USER_NAME ignoré — modifiable dans .env"
        fi
    fi
}

config_projects_dir() {
    step "Dossier de projets"
    echo -e "  ${DIM}Indiquer ton dossier racine de projets permet à l'IA de trouver tes repos git plus vite.${NC}"
    echo -e "  ${DIM}Laisser vide → l'IA cherchera depuis \$HOME (fonctionne, juste plus lent).${NC}"
    echo ""

    current=$(env_get "PROJECTS_DIR")
    if [[ -n "$current" ]]; then
        echo -e "  ${DIM}Valeur actuelle : $current${NC}"
    fi

    # Essayer d'ouvrir un gestionnaire de fichiers graphique
    chosen=""
    if command -v zenity &>/dev/null && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        chosen=$(zenity --file-selection --directory \
            --title="Sélectionne ton dossier de projets" \
            --filename="${current:-$HOME/}" 2>/dev/null) || chosen=""
    elif command -v kdialog &>/dev/null && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        chosen=$(kdialog --getexistingdirectory "${current:-$HOME}" \
            --title "Sélectionne ton dossier de projets" 2>/dev/null) || chosen=""
    fi

    # Fallback texte si pas de GUI
    if [[ -z "$chosen" ]]; then
        read -rp "  $(echo -e "${ORANGE}?${NC}") Chemin vers ton dossier de projets (Entrée pour ignorer) : " chosen
    fi

    if [[ -n "$chosen" && -d "$chosen" ]]; then
        env_set "PROJECTS_DIR" "$chosen"
        ok "PROJECTS_DIR → $chosen"
    else
        env_set "PROJECTS_DIR" ""
        warn "Non configuré — l'IA cherchera depuis \$HOME"
    fi
}

# ──────────────────────────────────────────────────────────────
#  MENU DE CONFIGURATION
# ──────────────────────────────────────────────────────────────

show_status() {
    echo ""
    echo -e "  ${WHITE}Statut des intégrations :${NC}"
    echo ""
    local uname
    uname=$(env_get "USER_NAME")
    if [[ -n "$uname" && "$uname" != "Ton Prénom Nom" ]]; then
        ok "Identité  ${DIM}→ ${uname}${NC}"
    else
        warn "Identité  ${DIM}(USER_NAME non configuré)${NC}"
    fi
    env_status "TAVILY_API_KEY"  "Tavily    (recherche web)"
    env_status "GROQ_API_KEY"    "Groq      (LLM cloud)"
    env_status "OLLAMA_API_KEY"  "Ollama Cloud (optionnel)"
    env_status "SLACK_BOT_TOKEN" "Slack"
    if [[ -f "gcp-oauth.keys.json" ]]; then
        ok "Google    (Gmail · Calendar · Drive · Docs · Slides)"
    else
        warn "Google    ${DIM}(gcp-oauth.keys.json manquant)${NC}"
    fi
    local pdir
    pdir=$(env_get "PROJECTS_DIR")
    if [[ -n "$pdir" ]]; then
        ok "Projets   ${DIM}→ $pdir${NC}"
    else
        warn "Projets   ${DIM}(non configuré — recherche depuis \$HOME)${NC}"
    fi
    echo ""
}

config_menu() {
    step "Configuration des intégrations"
    show_status

    echo -e "  ${WHITE}Que veux-tu configurer ?${NC}"
    echo ""
    echo -e "  ${ORANGE}1${NC}  Tavily       ${DIM}(recherche web — recommandé)${NC}"
    echo -e "  ${ORANGE}2${NC}  Groq         ${DIM}(LLM cloud rapide)${NC}"
    echo -e "  ${ORANGE}3${NC}  Ollama Cloud ${DIM}(optionnel)${NC}"
    echo -e "  ${ORANGE}4${NC}  Slack"
    echo -e "  ${ORANGE}5${NC}  Google       ${DIM}(Gmail · Calendar · Drive · Docs · Slides)${NC}"
    echo -e "  ${ORANGE}6${NC}  Dossier de projets  ${DIM}(pour que l'IA trouve tes repos plus vite)${NC}"
    echo -e "  ${ORANGE}a${NC}  Tout configurer"
    echo -e "  ${ORANGE}q${NC}  Ignorer"
    echo ""

    read -rp "  $(echo -e "${ORANGE}>${NC}") Choix : " choice

    case "$choice" in
        1) config_tavily ;;
        2) config_groq ;;
        3) config_ollama_cloud ;;
        4) config_slack ;;
        5) config_google ;;
        6) config_projects_dir ;;
        a|A)
            config_tavily
            config_groq
            config_ollama_cloud
            config_slack
            config_google
            config_projects_dir
            ;;
        *) info "Configuration ignorée — tu pourras la faire plus tard dans .env" ;;
    esac
}

# ──────────────────────────────────────────────────────────────
#  DÉPLOIEMENT
# ──────────────────────────────────────────────────────────────

deploy() {
    # ── 1. Prérequis système ──────────────────────────────────
    step "Prérequis système"

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

    if ! command -v ollama &>/dev/null; then
        warn "Ollama non installé — installation..."
        curl -fsSL https://ollama.com/install.sh | sh
        ok "Ollama installé"
    else
        ok "Ollama $(ollama --version 2>/dev/null | head -1)"
    fi

    if command -v libreoffice &>/dev/null; then
        ok "LibreOffice (export PDF)"
    else
        warn "LibreOffice absent — export PDF des lettres indisponible"
        warn "  sudo pacman -S libreoffice-still   ou   sudo apt install libreoffice"
    fi

    if command -v xclip &>/dev/null || command -v xsel &>/dev/null; then
        ok "Presse-papiers (xclip/xsel)"
    else
        warn "xclip/xsel absent — commande /paste indisponible"
        warn "  sudo pacman -S xclip   ou   sudo apt install xclip"
    fi

    # ── 2. Environnement virtuel ──────────────────────────────
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

    # ── 3. Dépendances ────────────────────────────────────────
    step "Dépendances Python"

    pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    ok "requirements.txt installé"

    # ── 4. .env ───────────────────────────────────────────────
    step "Fichier de configuration"

    if [[ ! -f ".env" ]]; then
        cp .env.sample .env
        ok ".env créé depuis .env.sample"
    else
        ok ".env déjà présent"
    fi
    config_user_name

    # ── 5. Modèles Ollama ─────────────────────────────────────
    step "Modèles Ollama"

    if ! ollama list &>/dev/null 2>&1; then
        info "Démarrage d'Ollama en arrière-plan..."
        ollama serve &>/dev/null &
        sleep 3
    fi

    if ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
        ok "nomic-embed-text (embedding) déjà présent"
    else
        info "Téléchargement de nomic-embed-text (~274 MB, requis)..."
        ollama pull nomic-embed-text
        ok "nomic-embed-text prêt"
    fi

    echo ""
    if ollama list 2>/dev/null | grep -q "qwen2.5:7b"; then
        ok "qwen2.5:7b déjà présent"
    else
        echo -e "  ${DIM}Backend local optionnel — utile si tu n'as pas accès au cloud${NC}"
        read -rp "  $(echo -e "${ORANGE}?${NC}") Télécharger qwen2.5:7b pour le backend local ? [o/N] " pull_local
        if [[ "$pull_local" =~ ^[oOyY]$ ]]; then
            info "Téléchargement de qwen2.5:7b (~4.4 GB)..."
            ollama pull qwen2.5:7b
            ok "qwen2.5:7b prêt"
        fi
    fi

    # ── 6. Configuration des services ─────────────────────────
    config_menu
}

# ──────────────────────────────────────────────────────────────
#  ENTRÉE
# ──────────────────────────────────────────────────────────────

banner

if [[ "${1:-}" == "--config-only" ]]; then
    # Juste reconfigurer les services sans tout réinstaller
    if [[ ! -f ".env" ]]; then
        cp .env.sample .env
        ok ".env créé depuis .env.sample"
    fi
    config_user_name
    config_menu
else
    deploy
fi

# ── Récapitulatif final ───────────────────────────────────────
echo ""
show_status
echo -e "${ORANGE}  ─────────────────────────────────────${NC}"
echo -e "${ORANGE}  Prêt.${NC}"
echo ""
echo -e "  ${WHITE}Lancer Axon :${NC}"
echo -e "    ${ORANGE}source venv/bin/activate${NC}"
echo -e "    ${ORANGE}python -m src.ui.main${NC}"
echo ""
echo -e "  ${DIM}Reconfigurer les intégrations :${NC}  ${ORANGE}bash setup.sh --config-only${NC}"
echo ""
