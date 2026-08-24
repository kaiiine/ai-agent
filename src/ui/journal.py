"""Le journal d'actions : dire ce qu'on fait, pendant qu'on le fait.

L'affichage conversationnel n'annonçait qu'un `thinking` générique, réaffiché en
boucle. On ne savait ni ce qu'Axon faisait, ni si ça avançait, ni pourquoi ça
avait échoué — et quand plusieurs afficheurs se disputaient le curseur, le mot
s'empilait.

Le modèle retenu tient en une phrase : **une action, une ligne**.

    ⠋  reading     src/app/page.tsx
    ✓  reading     src/app/page.tsx                                 1.4s
    ✗  searching   « axon browser » — délai dépassé

L'action EN COURS vit dans la zone `Live` et se redessine sur place — elle ne
laisse donc aucune trace en défilant. Une action TERMINÉE est imprimée au-dessus
et reste dans l'historique du terminal. C'est cette séparation qui supprime la
répétition, et elle n'est possible que depuis qu'une seule zone existe.

Deux choix contre le bruit :

  · la durée ne s'affiche qu'au-delà d'un seuil. Écrire « 0.0s » sur chaque
    lecture de fichier remplit la colonne sans rien apprendre ;
  · le nom montré est un VERBE, pas un identifiant d'outil. « reading » se
    comprend sans savoir qu'il existe un `local_read_file`, et c'est
    l'utilisateur qu'on informe, pas le développeur.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum

from rich.console import Group, RenderableType
from rich.text import Text

#: La DA vient de `panels`, qui la définit déjà pour tout l'affichage. La
#: recopier ici en ferait une quatrième définition de l'orange — il y en avait
#: déjà trois dans le projet, et c'est précisément ce qu'on cherche à réduire.
from .panels import ACCENT

SOURD = "dim"

#: Le tourniquet braille — la même famille de glyphes que l'axolotl du bandeau.
_ROTATION = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧")

#: En dessous, la durée est du bruit : presque toutes les actions locales sont
#: instantanées et afficher « 0.0s » sur chacune remplirait la colonne pour rien.
_SEUIL_DUREE_S = 0.8

#: Au-delà, la cible est coupée. Un chemin de 200 caractères casse l'alignement
#: et n'apprend rien de plus que sa fin.
_LARGEUR_CIBLE = 58


class Etat(Enum):
    EN_COURS = "en_cours"
    REUSSI = "reussi"
    ECHOUE = "echoue"
    IGNORE = "ignore"


#: Marqueur et style par état. Rassemblés pour qu'ajouter un état soit une ligne,
#: et pour qu'aucun appelant n'écrive un glyphe en dur.
_MARQUEURS: dict[Etat, tuple[str, str]] = {
    Etat.EN_COURS: ("", f"bold {ACCENT}"),      # remplacé par le tourniquet
    Etat.REUSSI:   ("✓", "bold green"),
    Etat.ECHOUE:   ("✗", "bold red"),
    Etat.IGNORE:   ("·", SOURD),
}

#: Le rail vertical qui relie les actions d'un même tour. Il donne au journal une
#: colonne, donc une lecture : on voit d'un coup d'œil où commence et finit ce
#: qu'Axon a fait, au lieu d'une suite de lignes flottantes.
#:
#: Un seul glyphe pour toutes les lignes terminées, parce qu'elles s'impriment au
#: fil de l'eau : on ne sait jamais laquelle sera la dernière, donc aucune ne peut
#: porter un coin fermant sans risquer de mentir.
_RAIL = "│"
_RAIL_VIVANT = "╿"

#: Nom d'outil → ce qu'il est en train de faire. Ce que l'utilisateur veut
#: savoir, c'est ce qui se passe, pas quelle fonction Python tourne.
#:
#: En anglais et au participe présent, pour deux raisons. L'attente générique
#: s'appelle déjà `thinking` : mélanger « cherche sur le web » et « thinking »
#: dans la même colonne donnait deux langues sur deux lignes voisines. Et le
#: participe présent dit l'action EN COURS, ce qui est exactement l'état que la
#: ligne vivante décrit — « searching » se lit pendant, « cherche » se lit
#: comme un constat.
#:
#: Un outil absent d'ici garde son nom : mieux vaut un nom technique qu'une
#: traduction inventée.
VERBES: dict[str, str] = {
    "local_read_file": "reading",
    "local_find_file": "finding",
    "local_list_directory": "listing",
    "local_grep": "grepping",
    "local_glob": "globbing",
    "find_git_repos": "locating",
    "shell_run": "running",
    "propose_file_change": "writing",
    "edit_file": "editing",
    "web_research_report": "searching",
    "web_search_news": "searching",
    "url_fetch": "fetching",
    "run_coding_agent": "delegating",
    "load_skill": "loading",
    "axon_note": "noting",
    "gmail_search": "searching mail",
    "gmail_send_email": "drafting mail",
    "gmail_reply": "replying",
    "google_docs_create": "creating doc",
    # `google_docs_write` sur la branche où le markdown est traduit en style,
    # `google_docs_update` ici où il part encore en texte brut. Les deux noms
    # cohabitent le temps de la fusion : un verbe manquant s'affiche en brut,
    # ce qui est précisément ce qu'on cherche à éviter.
    "google_docs_write": "writing doc",
    "google_docs_update": "writing doc",
    "google_docs_read": "reading doc",
    "slides_create": "creating slides",
    "slides_add_slide": "adding a slide",
    "sheets_create": "creating sheet",
    "sheets_read": "reading sheet",
    "slack_read_channel": "reading slack",
    "slack_find_user": "finding on slack",
    "drive_list_files": "listing drive",
    "drive_get_file_metadata": "checking drive",
    "drive_read_file": "reading drive",
    "drive_find_file_id": "finding on drive",
    "sheets_append_rows": "filling sheet",
    "slides_from_markdown": "building slides",
    "slack_send_message": "posting to slack",
    "calendar_list_events": "checking calendar",
    "mermaid_diagram": "diagramming",
    "download_asset": "downloading",
    "get_weather_by_city": "checking weather",
    "get_current_time": "checking time",
}


def verbe(nom_outil: str) -> str:
    """Le verbe d'un outil, ou son nom si on ne le connaît pas."""
    return VERBES.get(nom_outil, nom_outil)


@dataclass
class Action:
    """Une chose qu'Axon fait, et ce qu'elle est devenue."""
    nom: str
    cible: str = ""
    etat: Etat = Etat.EN_COURS
    detail: str = ""
    debut: float = field(default_factory=time.monotonic)
    fin: float | None = None

    @property
    def duree(self) -> float:
        return (self.fin if self.fin is not None else time.monotonic()) - self.debut

    def rendu(self, image: str = "") -> Text:
        """Une ligne. `image` est le glyphe du tourniquet pour l'action en cours."""
        marqueur, style = _MARQUEURS[self.etat]
        vivante = self.etat is Etat.EN_COURS
        ligne = Text(no_wrap=True)
        ligne.append(f"  {_RAIL_VIVANT if vivante else _RAIL} ", style=f"dim {ACCENT}")
        ligne.append(f" {image or marqueur}  ", style=style)
        ligne.append(self.nom, style="white" if vivante else SOURD)

        if (cible := self.cible.strip()):
            if len(cible) > _LARGEUR_CIBLE:
                # On coupe par le DÉBUT : la fin d'un chemin ou d'une requête est
                # ce qui l'identifie, le préfixe est souvent commun à tout.
                cible = "…" + cible[-(_LARGEUR_CIBLE - 1):]
            ligne.append("  ")
            ligne.append(cible, style=SOURD)

        if self.etat is Etat.ECHOUE and self.detail:
            ligne.append("  ")
            ligne.append(self.detail[:80], style="red")

        if self.etat is not Etat.EN_COURS and self.duree >= _SEUIL_DUREE_S:
            ligne.append(f"  {self.duree:.1f}s", style=SOURD)
        return ligne


class Journal:
    """Tient le fil des actions et le donne à voir.

    Il ne possède pas la zone d'affichage : il la reçoit. C'est ce qui lui permet
    de servir aussi bien la conversation qu'un build, sans savoir lequel des deux
    l'utilise.
    """

    def __init__(self, zone=None, *, attente: str = "thinking"):
        self._zone = zone
        self._attente = attente
        self._courante: Action | None = None
        self._terminees: list[Action] = []
        self._tour = 0

    # ── Écriture ──────────────────────────────────────────────────────────────

    def commencer(self, nom: str, cible: str = "") -> Action:
        """Ouvre une action. Si une autre était en cours, elle est close d'abord.

        Deux actions simultanées ne s'affichent pas : on n'a qu'une ligne vivante.
        Fermer l'ancienne évite qu'elle reste éternellement « en cours » — un état
        faux qui survivrait à l'écran.
        """
        if self._courante is not None:
            self.terminer(reussi=True)
        self._courante = Action(nom=verbe(nom), cible=cible)
        self._rafraichir()
        return self._courante

    def terminer(self, reussi: bool = True, detail: str = "") -> Action | None:
        """Clôt l'action en cours et l'inscrit définitivement au-dessus."""
        action = self._courante
        if action is None:
            return None
        action.etat = Etat.REUSSI if reussi else Etat.ECHOUE
        action.detail = detail
        action.fin = time.monotonic()
        self._courante = None
        self._terminees.append(action)
        if self._zone is not None:
            self._zone.imprimer(action.rendu())
        self._rafraichir()
        return action

    def ligne(self, renderable) -> None:
        """Écrit une ligne déjà composée — les sous-lignes d'une recherche, par
        exemple. Elle reste à l'écran, comme une action terminée."""
        if self._zone is not None:
            self._zone.imprimer(renderable)

    def note(self, texte: str, style: str = SOURD) -> None:
        """Une ligne d'information qui n'est pas une action — reste à l'écran."""
        ligne = Text(no_wrap=True)
        ligne.append(f"  {_RAIL}  ", style=f"dim {ACCENT}")
        ligne.append(texte, style=style)
        if self._zone is not None:
            self._zone.imprimer(ligne)

    def attendre(self, label: str = "") -> None:
        """Rien à annoncer de précis : on montre qu'on travaille, sans mentir."""
        if label:
            self._attente = label
        self._courante = None
        self._rafraichir()

    # ── Lecture ───────────────────────────────────────────────────────────────

    @property
    def actions(self) -> tuple[Action, ...]:
        return tuple(self._terminees)

    @property
    def en_cours(self) -> Action | None:
        return self._courante

    def resume(self) -> str:
        """Une ligne de bilan : combien d'actions, combien d'échecs."""
        total = len(self._terminees)
        echecs = sum(1 for a in self._terminees if a.etat is Etat.ECHOUE)
        if not total:
            return ""
        if echecs:
            return f"{total} action(s) · {echecs} échec(s)"
        return f"{total} action(s)"

    # ── Rendu de la zone vivante ──────────────────────────────────────────────

    def image(self) -> str:
        """Le glyphe courant du tourniquet. Avancé à chaque rafraîchissement."""
        return _ROTATION[self._tour % len(_ROTATION)]

    def __rich__(self) -> RenderableType:
        """UNE seule ligne vivante : l'action en cours, ou l'attente.

        Rien de ce qui est déjà terminé n'est redessiné ici — ces lignes ont été
        imprimées une fois pour toutes. C'est ce qui empêche le journal de
        repeindre son historique à chaque image, et donc de le graver en double
        si la zone se ferme.
        """
        if self._courante is not None:
            return self._courante.rendu(self.image())
        ligne = Text(no_wrap=True)
        ligne.append(f"  {_RAIL_VIVANT} ", style=f"dim {ACCENT}")
        ligne.append(f" {self.image()}  ", style=f"bold {ACCENT}")
        ligne.append(self._attente, style=SOURD)
        return ligne

    def avancer(self) -> None:
        """Fait tourner l'animation d'un cran et redessine."""
        self._tour += 1
        self._rafraichir()

    def _rafraichir(self) -> None:
        if self._zone is not None:
            self._zone.poser(self)


def inscrire_resultat(journal: "Journal | None", nom_outil: str, message,
                      cible_connue: str = "") -> None:
    """Inscrit un appel d'outil DÉJÀ exécuté, avec son issue.

    Le flux de LangGraph ne livre pas « l'outil démarre » : quand un `ToolMessage`
    arrive, l'appel est terminé. On ouvre donc l'action et on la clôt dans le même
    geste — ce qui donne bien une ligne définitive par outil, ce qu'on veut voir.

    L'issue se lit dans le contenu. Un outil d'Axon signale son échec par
    `"status": "error"`, et `resilience` enveloppe les exceptions en
    `"TOOL_ERROR"` : deux formes, une seule règle — un échec se dit, il ne se
    déduit pas d'un contenu vide.
    """
    if journal is None:
        return
    try:
        contenu = getattr(message, "content", "") or ""
        texte = contenu if isinstance(contenu, str) else str(contenu)
        echoue = ('"status": "error"' in texte
                  or '"status":"error"' in texte
                  or "TOOL_ERROR" in texte)
        # La cible lue dans l'appel prime sur celle devinée dans le résultat :
        # elle est exacte, l'autre est une heuristique de repli.
        cible = cible_connue or _cible_lisible(texte)
        # Si une action du MÊME outil est déjà ouverte, on la clôt au lieu d'en
        # ouvrir une seconde. Sans ça, un appelant qui annonce le départ puis le
        # résultat produit DEUX lignes — vu à l'écran avant d'être corrigé : la
        # première close en « réussi » par `commencer`, la seconde par le
        # résultat réel. Une action, une ligne, quel que soit l'appelant.
        courante = journal.en_cours
        if courante is None or courante.nom != verbe(nom_outil):
            journal.commencer(nom_outil, cible)
        elif cible:
            courante.cible = cible
        journal.terminer(reussi=not echoue,
                         detail=_raison(texte) if echoue else "")
        if not echoue and nom_outil in ("web_research_report", "web_search_news"):
            sources = sources_de(texte)
            total = compter_sources(texte)
            for ligne in lignes_sources(sources, total):
                journal.ligne(ligne)
    except Exception:                                            # noqa: BLE001
        # Un journal qui casse le tour qu'il raconte serait pire que pas de
        # journal — même règle que pour la zone d'affichage.
        pass


#: Combien de sources on montre sous une recherche. Au-delà, la liste chasse la
#: réponse hors de l'écran — et les premières sont les mieux classées.
_SOURCES_MONTREES = 4

#: Les deux outils de recherche ne rendent PAS le même format, et l'oublier
#: coûtait toutes les sources des recherches d'actualité — vu à l'écran : quatre
#: lignes « fetching » sans la moindre indication d'où elles venaient.
#:
#: `web_research_report` met tout sur une ligne :
#:     1. **Titre de la page** — _lemonde.fr · 2026-08-17_
#:
#: `web_search_news` l'étale sur deux :
#:     ### 1. Titre de la page
#:     _lemonde.fr · 2026-08-17_
#:
#: On ne garde que le domaine et le titre : c'est ce qui dit « où il est allé ».
_SOURCE = re.compile(r"^\s*\d+\.\s+\*\*(.+?)\*\*\s+—\s+_([^_·]+)")
_SOURCE_TITRE = re.compile(r"^\s*#{2,4}\s*\d+\.\s+(.+?)\s*$")
_SOURCE_DOMAINE = re.compile(r"^\s*_([^_·]+)")


def sources_de(texte: str, limite: int = _SOURCES_MONTREES) -> list[tuple[str, str]]:
    """Les sources d'un rapport de recherche : (domaine, titre)."""
    trouvees: list[tuple[str, str]] = []
    lignes = texte.splitlines()
    attendu = ""                       # titre vu, dont on attend le domaine
    for ligne in lignes:
        if (m := _SOURCE.match(ligne)):
            trouvees.append((m.group(2).strip(), m.group(1).strip()))
            attendu = ""
        elif (m := _SOURCE_TITRE.match(ligne)):
            attendu = m.group(1).strip()
        elif attendu and (m := _SOURCE_DOMAINE.match(ligne)):
            trouvees.append((m.group(1).strip(), attendu))
            attendu = ""
        if len(trouvees) >= limite:
            break
    return trouvees


def compter_sources(texte: str) -> int:
    """Combien de sources le rapport contient en tout — pour dire « et N autres »
    sans les lister."""
    return len(sources_de(texte, limite=10_000))


def lignes_sources(sources: list[tuple[str, str]], total: int = 0) -> list[Text]:
    """Les sous-lignes d'une recherche, rattachées au rail par un embranchement.

    Elles répondent à « où est-il allé chercher ça ? », qui est la question qu'on
    se pose devant une recherche web — et à laquelle un simple « ✓ cherche » ne
    répond pas.
    """
    lignes: list[Text] = []
    for i, (domaine, titre) in enumerate(sources):
        dernier = i == len(sources) - 1 and total <= len(sources)
        t = Text(no_wrap=True)
        t.append(f"  {_RAIL}   ", style=f"dim {ACCENT}")
        t.append("╰─ " if dernier else "├─ ", style=f"dim {ACCENT}")
        t.append(domaine, style=ACCENT)
        if titre:
            t.append("  ")
            # Coupé par la FIN, contrairement à la cible d'une action : un titre
            # se lit de gauche à droite et son début l'identifie. Les points de
            # suspension disent que la coupe est voulue — sans eux on lit
            # « watso » et on croit à un défaut d'affichage.
            t.append(titre if len(titre) <= 52 else titre[:51] + "…", style=SOURD)
        lignes.append(t)
    if total > len(sources):
        t = Text(no_wrap=True)
        t.append(f"  {_RAIL}   ", style=f"dim {ACCENT}")
        t.append("╰─ ", style=f"dim {ACCENT}")
        t.append(f"et {total - len(sources)} autre(s) source(s)", style=SOURD)
        lignes.append(t)
    return lignes


class SortieDirecte:
    """Une sortie qui n'écrit QUE des lignes définitives, jamais la ligne vivante.

    `streaming.py` possède déjà une région `Live` et un fil d'animation qui la
    repeint. Y faire écrire le journal AUSSI, c'était mettre deux peintres sur la
    même toile — le défaut qui a produit `thinking.` / `thinking..` empilés, et
    que j'ai reproduit une fois de plus en tentant de le corriger par une façade.

    D'où le partage strict des rôles : l'animation garde la ligne vivante, le
    journal n'écrit que ce qui doit rester. `poser()` ne fait donc rien, et ce
    n'est pas un manque : c'est la garantie qu'il n'y a qu'un seul peintre.

    Rich prend en charge `console.print` pendant qu'un `Live` tourne — il remonte
    sa région et pousse la ligne dans l'historique. C'est ce qui rend ces lignes
    défilables comme un vrai chat, au lieu d'être écrasées par l'image suivante.
    """

    def __init__(self, console):
        self.console = console

    def imprimer(self, renderable) -> None:
        try:
            self.console.print(renderable)
        except Exception:                                        # noqa: BLE001
            pass

    def poser(self, renderable) -> None:
        """Sans effet — la ligne vivante appartient à l'animation en place."""


#: Les noms d'argument qui portent « sur quoi » l'outil agit, par ordre de
#: préférence. Pris dans l'APPEL et non dans le résultat : deux recherches
#: successives produisent deux lignes « cherche l'actualité » indiscernables si
#: on attend que le résultat veuille bien nommer sa requête — vu à l'écran.
_ARGS_CIBLE = ("query", "q", "question", "path", "file_path", "chemin",
               "url", "command", "cmd", "pattern", "name", "titre", "title")


def cible_de_l_appel(arguments) -> str:
    """Ce sur quoi porte un appel d'outil, lu dans ses arguments.

    C'est la source la plus fiable : elle est connue AVANT l'exécution, elle ne
    dépend pas du format du résultat, et elle distingue deux appels du même
    outil — ce que le seul verbe ne fait pas.
    """
    if not isinstance(arguments, dict):
        return ""
    for cle in _ARGS_CIBLE:
        valeur = arguments.get(cle)
        if isinstance(valeur, str) and valeur.strip():
            return valeur.strip()
    return ""


def _cible_lisible(texte: str) -> str:
    """Ce sur quoi l'outil a agi, s'il le dit clairement.

    On ne fouille pas : un chemin ou une URL en tête de résultat est utile, le
    reste ne l'est pas et prendrait la place de l'action elle-même.
    """
    for ligne in texte.splitlines()[:3]:
        nu = ligne.strip().strip("\"'`,{}")
        if nu.startswith(("/", "http://", "https://", "~/")) and len(nu) < 200:
            return nu
        # Un rapport de recherche s'ouvre sur sa requête. C'est la meilleure
        # cible possible pour la ligne : « cherche sur le web » sans dire QUOI
        # ne vaut guère mieux que « thinking ».
        if nu.startswith(("# Recherche :", "# Actualités :")):
            return nu.split(":", 1)[1].strip()
    return ""


def _raison(texte: str) -> str:
    """La raison d'un échec, en une ligne — jamais la trace entière."""
    import json as _json

    try:
        charge = _json.loads(texte)
        if isinstance(charge, dict):
            for cle in ("message", "error"):
                if (v := charge.get(cle)):
                    return str(v).splitlines()[0][:80]
    except Exception:                                            # noqa: BLE001
        pass
    return texte.strip().splitlines()[0][:80] if texte.strip() else ""


def bilan(journal: Journal) -> RenderableType:
    """Le récapitulatif de fin de tour, s'il y a quelque chose à dire.

    Affiché seulement quand il apprend quelque chose : une seule action réussie
    n'a pas besoin d'être résumée, elle est déjà à l'écran juste au-dessus.
    """
    if len(journal.actions) < 2:
        return Text("")
    lignes = [Text("")]
    t = Text(no_wrap=True)
    t.append("  ╰─ ", style=f"dim {ACCENT}")
    t.append(journal.resume(), style=SOURD)
    lignes.append(t)
    return Group(*lignes)


def compte_rendu_de_secours(journal: "Journal | None") -> str:
    """Ce qui a été fait, quand le modèle n'a rien rédigé.

    Un tour peut s'achever sans texte : le modèle rend une réponse vide, ou le
    backend tombe entre deux appels. L'utilisateur voyait alors « le modèle n'a
    rien rédigé » après dix commandes — dont quatre en échec — sans savoir si
    VirtualBox avait été supprimé ni quelles images Android étaient parties.

    Le journal, lui, sait exactement ce qui s'est passé. Le rendre est un
    constat, pas une interprétation : on n'écrit que ce que les outils ont
    répondu, et on dit explicitement que le modèle n'a pas conclu — pour que
    « rien n'a échoué » ne se lise pas comme « tout est terminé ».
    """
    if journal is None or not journal.actions:
        return ""
    faites = [a for a in journal.actions if a.etat is Etat.REUSSI]
    ratees = [a for a in journal.actions if a.etat is Etat.ECHOUE]

    lignes = ["_Le modèle n'a pas conclu ce tour._ Voici ce que les outils ont "
              "réellement fait — la tâche n'est peut-être pas terminée."]
    if faites:
        lignes.append("\n**Fait**")
        lignes += [f"- {a.nom} · {a.cible}" if a.cible else f"- {a.nom}" for a in faites]
    if ratees:
        lignes.append("\n**Échoué**")
        lignes += [f"- {a.nom} · {a.cible} — {a.detail}" if a.detail
                   else f"- {a.nom} · {a.cible}" for a in ratees]
    lignes.append(f"\n_{journal.resume()}. Relance ta demande pour la suite — rien "
                  "n'a été perdu de la conversation._")
    return "\n".join(lignes)
