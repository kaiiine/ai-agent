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
    echo ""
    prompt_key "OLLAMA_API_KEY" "Clé API Ollama Cloud" "Format : ollama_xxxx  (laisser vide si tu utilises ollama signin)"

    # Ask if the user wants to sign in via the Ollama CLI
    echo ""
    echo -e "  ${ORANGE}Veux-tu aussi te connecter via la CLI Ollama ? (ollama signin)${NC}"
    echo -e "  ${DIM}Utile si tu utilises des modèles cloud sans clé API.${NC}"
    read -rp "  $(echo -e "${ORANGE}>${NC}") [o/N] " signin_choice
    if [[ "$signin_choice" =~ ^[oOyY]$ ]]; then
        # Check ollama CLI is available
        if ! command -v ollama &>/dev/null; then
            warn "La CLI Ollama n'est pas installée."
            echo -e "  ${DIM}Installe-la avec :${NC}"
            echo -e "  ${ORANGE}  curl -fsSL https://ollama.com/install.sh | sh${NC}"
            echo ""
            read -rp "  $(echo -e "${ORANGE}>${NC}") Lancer l'installation maintenant ? [o/N] " install_choice
            if [[ "$install_choice" =~ ^[oOyY]$ ]]; then
                info "Installation de la CLI Ollama..."
                curl -fsSL https://ollama.com/install.sh | sh
                if ! command -v ollama &>/dev/null; then
                    warn "Installation échouée. Relance le setup après avoir installé Ollama manuellement."
                    return
                fi
                ok "Ollama CLI installée."
            else
                warn "Connexion ignorée. Installe Ollama puis relance le setup."
                return
            fi
        fi

        # Logout first to clean any stale session
        info "Déconnexion préalable (ollama logout)..."
        ollama logout 2>/dev/null || true

        # Sign in
        info "Connexion à Ollama (ollama signin)..."
        if ollama signin; then
            ok "Connecté à Ollama Cloud."
        else
            warn "Connexion échouée. Vérifie tes identifiants et réessaie."
        fi
    fi
}

config_gemini() {
    step "Google Gemini — Backend LLM gratuit (1M tokens de contexte)"
    echo -e "  ${DIM}Gemini 2.5 Flash est gratuit avec 15 req/min et 1 500 req/jour.${NC}"
    echo -e "  ${DIM}C'est le backend recommandé si tu veux éviter les quotas Groq/Ollama.${NC}"
    echo ""
    echo -e "  ${ORANGE}Étapes :${NC}"
    echo -e "  ${DIM}1. Aller sur https://aistudio.google.com/apikey${NC}"
    echo -e "  ${DIM}2. Cliquer sur 'Create API key'${NC}"
    echo -e "  ${DIM}3. Copier la clé générée${NC}"
    echo ""
    echo -e "  ${DIM}Modèles disponibles :${NC}"
    echo -e "  ${DIM}  gemini-2.5-flash           → recommandé (rapide, gratuit)${NC}"
    echo -e "  ${DIM}  gemini-2.5-pro             → meilleur, quota limité${NC}"
    echo -e "  ${DIM}  gemini-3.1-flash-lite-preview → économique, rapide${NC}"
    prompt_key "GEMINI_API_KEY" "Clé API Gemini" "Format : AIzaSy..."
}

config_slack() {
    step "Slack — Intégration workspace"
    echo -e "  ${DIM}Permet de lire les canaux, DMs, mentions et d'envoyer des messages.${NC}"
    echo ""
    echo -e "  ${ORANGE}Étapes :${NC}"
    echo -e "  ${DIM}1. Aller sur https://api.slack.com/apps${NC}"
    echo -e "  ${DIM}2. Créer une nouvelle app → From scratch${NC}"
    echo -e "  ${DIM}3. OAuth & Permissions → User Token Scopes, ajouter :${NC}"
    echo -e "  ${DIM}   channels:read    channels:history${NC}"
    echo -e "  ${DIM}   groups:read      groups:history${NC}"
    echo -e "  ${DIM}   im:read          im:history       im:write${NC}"
    echo -e "  ${DIM}   mpim:read        mpim:history     mpim:write${NC}"
    echo -e "  ${DIM}   users:read       search:read      chat:write${NC}"
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

config_jira() {
    step "Jira — Gestion de projet"
    echo -e "  ${DIM}Permet de lire, créer et gérer les tickets de tes projets Jira.${NC}"
    echo ""
    echo -e "  ${ORANGE}Étapes :${NC}"
    echo -e "  ${DIM}1. Aller sur https://id.atlassian.com/manage-profile/security/api-tokens${NC}"
    echo -e "  ${DIM}2. Create API token → copier la clé${NC}"
    echo -e "  ${DIM}3. Ton URL Jira = https://ton-domaine.atlassian.net${NC}"
    echo -e "  ${DIM}   (visible dans la barre d'adresse quand tu ouvres Jira)${NC}"
    prompt_key "JIRA_URL"     "URL Jira"       "Format : https://ton-domaine.atlassian.net"
    prompt_key "JIRA_EMAIL"   "Email Atlassian" "Email de ton compte Atlassian"
    prompt_key "JIRA_API_KEY" "Clé API Jira"   "Format : ATATT3x..."
}

config_quant() {
    step "API-Football — Value betting (Winamax)"
    echo -e "  ${DIM}Permet à Axon de calculer de vraies probabilités (Poisson/Elo) sur les${NC}"
    echo -e "  ${DIM}matchs et de les comparer aux cotes Winamax pour détecter un edge réel.${NC}"
    echo -e "  ${DIM}Gratuit : 100 requêtes/jour. Le tier gratuit bloque la saison en cours —${NC}"
    echo -e "  ${DIM}c'est football-data.org (ci-dessous) qui la couvre, API-Football sert de${NC}"
    echo -e "  ${DIM}source complémentaire (saisons passées, autres compétitions).${NC}"
    echo ""
    echo -e "  ${ORANGE}Étapes :${NC}"
    echo -e "  ${DIM}1. Aller sur https://www.api-football.com/${NC}"
    echo -e "  ${DIM}2. Créer un compte gratuit${NC}"
    echo -e "  ${DIM}3. Dashboard → copier ta clé API (section 'My Access')${NC}"
    echo ""
    echo -e "  ${DIM}Winamax ne demande aucune clé — les cotes sont déjà accessibles.${NC}"
    prompt_key "API_FOOTBALL_KEY" "Clé API-Football" "Format : ta clé depuis le dashboard api-football.com"
}

config_football_data() {
    step "football-data.org — Données saison en cours (value betting)"
    echo -e "  ${DIM}Complète API-Football : couvre la saison EN COURS gratuitement (Ligue 1,${NC}"
    echo -e "  ${DIM}Premier League...), là où le tier gratuit d'API-Football bloque tout.${NC}"
    echo -e "  ${DIM}Gratuit : 10 requêtes/minute, 12 compétitions majeures.${NC}"
    echo ""
    echo -e "  ${ORANGE}Étapes :${NC}"
    echo -e "  ${DIM}1. Aller sur https://www.football-data.org/client/register${NC}"
    echo -e "  ${DIM}2. Créer un compte gratuit (aucune carte bancaire demandée)${NC}"
    echo -e "  ${DIM}3. La clé API arrive par email — la copier ici${NC}"
    prompt_key "FOOTBALL_DATA_ORG_KEY" "Clé football-data.org" "Format : ta clé reçue par email"
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

config_mcp() {
    step "MCP — serveurs d'outils externes"
    echo -e "  ${DIM}Axon peut consommer des serveurs MCP tiers (Blender, filesystem, GitHub…).${NC}"
    echo -e "  ${DIM}Ajouter une capacité = une ligne de configuration, aucun code à écrire.${NC}"
    echo -e "  ${DIM}Gestion dans Axon : /mcp list · add · test · tools · refresh · restart${NC}"

    # ── 1. uv / uvx ───────────────────────────────────────────
    echo ""
    if command -v uvx &>/dev/null; then
        ok "uvx présent  ${DIM}→ $(command -v uvx)${NC}"
    else
        warn "uvx introuvable — nécessaire pour lancer les serveurs MCP distribués par uv"
        echo -e "  ${DIM}Installeur officiel (ne PAS utiliser pip install uv : la commande uvx${NC}"
        echo -e "  ${DIM}peut ne pas être créée).${NC}"
        read -rp "  $(echo -e "${ORANGE}?${NC}") Installer uv maintenant ? [O/n] " rep
        if [[ ! "$rep" =~ ^[Nn] ]]; then
            curl -LsSf https://astral.sh/uv/install.sh | sh || warn "Installation d'uv échouée"
            export PATH="$HOME/.local/bin:$PATH"
            command -v uvx &>/dev/null && ok "uvx installé → $(command -v uvx)" \
                || warn "uvx toujours introuvable — ouvre un nouveau shell puis relance"
        fi
    fi

    # ── 2. Déclaration du serveur Blender ─────────────────────
    local cfg="$HOME/.axon/mcp_servers.json"
    echo ""
    echo -e "  ${ORANGE}Serveur Blender${NC}"
    echo -e "  ${DIM}Modélisation 3D, matériaux, animation, rendu, export GLB.${NC}"
    read -rp "  $(echo -e "${ORANGE}?${NC}") Déclarer le serveur blender dans $cfg ? [O/n] " rep
    if [[ ! "$rep" =~ ^[Nn] ]]; then
        # Fusion, jamais d'écrasement : les autres serveurs déjà déclarés sont conservés.
        local result
        result=$(python3 - "$cfg" <<'PY'
import json, pathlib, sys

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
servers = data.setdefault("servers", {})

if "blender" in servers:
    print("KEPT")
else:
    servers["blender"] = {
        "transport": "stdio",
        "command": "uvx",
        "args": ["--python", "3.11", "blender-mcp"],
        "env": {
            "BLENDER_HOST": "localhost",
            "BLENDER_PORT": "9876",
            "DISABLE_TELEMETRY": "true",
            "UV_PYTHON_PREFERENCE": "only-managed",
        },
        "enabled": True,
        "timeouts": {"connect_s": 15, "list_tools_s": 15, "call_s": 90},
        "tool_timeouts": {"execute_blender_code": 180},
        "reconnect": {"max_retries": 5, "backoff_s": 2, "backoff_factor": 2},
        "health": {
            "probe_tool": "get_scene_info",
            "failure_patterns": [
                "Could not connect to Blender",
                "Make sure the Blender addon is running",
            ],
            "consecutive_failures_to_degrade": 3,
        },
        "capabilities_hint": (
            "Blender, 3D modeling, mesh manipulation, materials, geometry, animation, "
            "camera, lighting, rendering, scene editing, GLB export, Python bpy"
        ),
        "risk_overrides": {"execute_blender_code": "execute"},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("ADDED")
PY
        ) || result="FAILED"
        case "$result" in
            ADDED)  ok "blender déclaré dans $cfg" ;;
            KEPT)   ok "blender déjà déclaré — configuration existante conservée" ;;
            *)      warn "Écriture de $cfg impossible" ;;
        esac
    fi

    # ── 3. Addon côté Blender ─────────────────────────────────
    echo ""
    echo -e "  ${ORANGE}Addon Blender${NC}  ${DIM}(côté Blender, une seule fois)${NC}"
    if command -v blender &>/dev/null; then
        ok "Blender présent  ${DIM}→ $(blender --version 2>/dev/null | head -1)${NC}"
    else
        warn "Blender introuvable dans le PATH — installe-le avant d'utiliser ce serveur"
    fi
    local addon="$HOME/Téléchargements/addon.py"
    [[ -d "$HOME/Téléchargements" ]] || addon="$HOME/Downloads/addon.py"
    read -rp "  $(echo -e "${ORANGE}?${NC}") Télécharger l'addon vers $addon ? [O/n] " rep
    if [[ ! "$rep" =~ ^[Nn] ]]; then
        mkdir -p "$(dirname "$addon")"
        if curl -fsSL -o "$addon" \
            https://raw.githubusercontent.com/ahujasid/blender-mcp/main/addon.py; then
            ok "addon.py téléchargé → $addon"
        else
            warn "Téléchargement échoué — récupère addon.py sur github.com/ahujasid/blender-mcp"
        fi
    fi
    echo -e "  ${DIM}Dans Blender :${NC}"
    echo -e "  ${DIM}  1. Edit > Preferences > Add-ons > Install… > choisir addon.py${NC}"
    echo -e "  ${DIM}  2. Cocher « Interface: Blender MCP »${NC}"
    echo -e "  ${DIM}  3. Vue 3D > touche N > onglet BlenderMCP > bouton de connexion${NC}"
    echo -e "  ${DIM}  Blender doit tourner en mode GRAPHIQUE (jamais -b/--background) :${NC}"
    echo -e "  ${DIM}  l'addon exécute les commandes via la boucle principale.${NC}"

    # ── 4. Sketchfab (optionnel) ──────────────────────────────
    echo ""
    echo -e "  ${ORANGE}Sketchfab${NC}  ${DIM}(optionnel — import de modèles 3D existants)${NC}"
    echo -e "  ${DIM}La clé est lue par BLENDER, pas par Axon : elle ne va pas dans .env.${NC}"
    echo -e "  ${DIM}L'addon la cherche dans ses préférences, puis la scène, puis la variable${NC}"
    echo -e "  ${DIM}d'environnement BLENDERMCP_SKETCHFAB_API_KEY — la dernière est la plus sûre :${NC}"
    echo -e "  ${DIM}elle ne transite jamais par le contexte du modèle.${NC}"
    local rc="$HOME/.bashrc"
    [[ -n "${ZSH_VERSION:-}" || "${SHELL:-}" == *zsh ]] && rc="$HOME/.zshrc"
    if grep -q "BLENDERMCP_SKETCHFAB_API_KEY" "$rc" 2>/dev/null; then
        ok "BLENDERMCP_SKETCHFAB_API_KEY déjà exportée dans $(basename "$rc")"
    else
        read -rp "  $(echo -e "${ORANGE}?${NC}") Clé API Sketchfab (Entrée pour ignorer) : " sk_key
        if [[ -n "$sk_key" ]]; then
            printf '\n# blender-mcp — lue par Blender, pas par Axon\nexport BLENDERMCP_SKETCHFAB_API_KEY=%q\n' \
                "$sk_key" >> "$rc"
            ok "export ajouté à $rc — relance Blender depuis un nouveau shell"
        else
            info "Ignoré — l'import Sketchfab restera indisponible"
        fi
    fi
    echo -e "  ${DIM}Puis dans Blender : onglet BlenderMCP > cocher « Use Sketchfab ».${NC}"
    echo -e "  ${DIM}Sans cette case, l'addon n'enregistre pas les commandes Sketchfab et${NC}"
    echo -e "  ${DIM}répond « Unknown command type » — le serveur MCP les annonce pourtant.${NC}"

    echo ""
    info "Vérification : lance Axon puis ${ORANGE}/mcp test blender${NC}"
    echo -e "  ${DIM}Si « command resolved » est vide, le PATH d'Axon diffère de ce shell :${NC}"
    echo -e "  ${DIM}remplace \"command\": \"uvx\" par le chemin absolu dans $cfg.${NC}"
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
    env_status "GEMINI_API_KEY"  "Gemini    (LLM gratuit — recommandé)"
    env_status "OLLAMA_API_KEY"  "Ollama Cloud (optionnel)"
    env_status "SLACK_USER_TOKEN" "Slack"
    env_status "JIRA_API_KEY"    "Jira      (gestion de projet)"
    env_status "API_FOOTBALL_KEY" "API-Football (value betting Winamax)"
    env_status "FOOTBALL_DATA_ORG_KEY" "football-data.org (saison en cours)"
    if [[ -f "gcp-oauth.keys.json" ]]; then
        ok "Google    (Gmail · Calendar · Drive · Docs · Slides)"
    else
        warn "Google    ${DIM}(gcp-oauth.keys.json manquant)${NC}"
    fi
    local mcp_cfg="$HOME/.axon/mcp_servers.json"
    if [[ -f "$mcp_cfg" ]]; then
        local n
        n=$(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1])).get('servers',{})))" \
            "$mcp_cfg" 2>/dev/null || echo 0)
        if [[ "$n" -gt 0 ]]; then
            ok "MCP       ${DIM}→ ${n} serveur(s) déclaré(s) · /mcp list dans Axon${NC}"
        else
            warn "MCP       ${DIM}(aucun serveur déclaré)${NC}"
        fi
    else
        warn "MCP       ${DIM}(aucun serveur déclaré)${NC}"
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
    while true; do
        step "Configuration des intégrations"
        show_status

        echo -e "  ${WHITE}Que veux-tu configurer ?${NC}"
        echo ""
        echo -e "  ${ORANGE}1${NC}  Tavily       ${DIM}(recherche web — recommandé)${NC}"
        echo -e "  ${ORANGE}2${NC}  Gemini       ${DIM}(LLM gratuit — 1M tokens — recommandé)${NC}"
        echo -e "  ${ORANGE}3${NC}  Groq         ${DIM}(LLM cloud rapide)${NC}"
        echo -e "  ${ORANGE}4${NC}  Ollama Cloud ${DIM}(optionnel)${NC}"
        echo -e "  ${ORANGE}5${NC}  Slack${NC}"
        echo -e "  ${ORANGE}6${NC}  Google       ${DIM}(Gmail · Calendar · Drive · Docs · Slides)${NC}"
        echo -e "  ${ORANGE}7${NC}  Jira         ${DIM}(gestion de tickets et projets)${NC}"
        echo -e "  ${ORANGE}8${NC}  Dossier de projets  ${DIM}(pour que l'IA trouve tes repos plus vite)${NC}"
        echo -e "  ${ORANGE}9${NC}  API-Football ${DIM}(value betting Winamax)${NC}"
        echo -e "  ${ORANGE}10${NC} football-data.org ${DIM}(saison en cours, value betting)${NC}"
        echo -e "  ${ORANGE}11${NC} MCP          ${DIM}(serveurs d'outils externes — Blender, etc.)${NC}"
        echo -e "  ${ORANGE}a${NC}  Tout configurer"
        echo -e "  ${ORANGE}q${NC}  Quitter le menu"
        echo ""

        read -rp "  $(echo -e "${ORANGE}>${NC}") Choix : " choice

        case "$choice" in
            1) config_tavily ;;
            2) config_gemini ;;
            3) config_groq ;;
            4) config_ollama_cloud ;;
            5) config_slack ;;
            6) config_google ;;
            7) config_jira ;;
            8) config_projects_dir ;;
            9) config_quant ;;
            10) config_football_data ;;
            11) config_mcp ;;
            a|A)
                config_tavily
                config_gemini
                config_groq
                config_ollama_cloud
                config_slack
                config_google
                config_jira
                config_projects_dir
                config_quant
                config_football_data
                config_mcp
                ;;
            q|Q)
                info "Configuration terminée."
                break
                ;;
            *) warn "Choix invalide — entre un numéro, 'a' ou 'q' pour quitter." ;;
        esac
    done
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

    if command -v wl-paste &>/dev/null || command -v xclip &>/dev/null || command -v xsel &>/dev/null; then
        ok "Presse-papiers ($(command -v wl-paste &>/dev/null && echo 'wl-clipboard' || echo 'xclip/xsel'))"
    else
        warn "Presse-papiers absent — commande /paste indisponible"
        warn "  Wayland : sudo pacman -S wl-clipboard   ou   sudo apt install wl-clipboard"
        warn "  X11     : sudo pacman -S xclip           ou   sudo apt install xclip"
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

    # ── 3b. Playwright (browser headless) ────────────────────
    echo ""
    if venv/bin/python -c "from playwright.sync_api import sync_playwright; b = sync_playwright().start(); b.stop()" &>/dev/null 2>&1; then
        ok "Playwright — navigateur déjà installé"
    else
        info "Installation des binaires Playwright (Chromium, ~200 MB)..."
        venv/bin/python -m playwright install chromium --with-deps --quiet 2>/dev/null \
            || venv/bin/python -m playwright install chromium 2>/dev/null \
            || warn "Playwright install échoué — l'agent browser sera indisponible"
        ok "Playwright — Chromium prêt"
    fi

    # ── 3c. RTK (proxy CLI token-efficient) ───────────────────
    echo ""
    if command -v rtk &>/dev/null; then
        ok "rtk déjà installé ($(rtk --version 2>/dev/null || echo 'version inconnue'))"
    else
        echo -e "  ${DIM}rtk compresse les outputs shell pour économiser 60-90% de tokens LLM${NC}"
        read -rp "  $(echo -e "${ORANGE}?${NC}") Installer rtk ? [o/N] " install_rtk
        if [[ "$install_rtk" =~ ^[oOyY]$ ]]; then
            info "Installation de rtk..."
            curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
            ok "rtk installé"
        else
            info "rtk ignoré (optionnel)"
        fi
    fi

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
