"""Lire une source RÉFÉRENCÉE par l'utilisateur — et dire quand elle ne dit rien.

« Regarder dans le repo ai-agent, il y a toute la DA dedans. » Répondu deux fois
pendant un wizard. La spec produite a inventé une palette cyan/corail, trois
références (Vercel, Stripe, OpenAI) et une iconographie Feather — alors que
l'identité réelle du dépôt est ambre et violet sur fond GitHub sombre, et vit
dans `assets/banner.svg`.

Deux défauts distincts, et le second est le pire :

1. la résolution de référence ne lisait que `README.md`. Une charte visuelle n'y
   est presque jamais : elle est dans un SVG, une config Tailwind, un
   `globals.css`. La source pointée était donc lue, et vide de ce qu'on
   cherchait ;
2. n'ayant rien trouvé, le modèle a INVENTÉ au lieu de le dire. C'est le mode
   d'échec le plus coûteux : le résultat a l'air décidé, il est fictif, et rien
   dans la spec ne permet de s'en apercevoir.

Ce module traite le premier. Le second est traité dans le gabarit, par une règle
qui interdit de substituer une invention à une source muette.

Ce qu'il extrait est VÉRIFIABLE : des couleurs comptées dans des fichiers réels,
des polices lues dans des déclarations réelles. Aucune interprétation.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

#: Là où une identité visuelle vit réellement. Le README arrive en DERNIER :
#: c'est le fichier qu'on lisait en premier, et celui qui contient le moins de
#: décisions visuelles.
_FICHIERS_DESIGN = (
    "tailwind.config.js", "tailwind.config.ts", "theme.json", "tokens.json",
    "globals.css", "app.css", "styles.css", "index.css",
)
_DOSSIERS_ASSETS = ("assets", "public", "static", "src/styles", "src/app")

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_POLICE = re.compile(r"""font-family\s*[:=]\s*["']?([^;"'}\n]{3,80})""", re.I)
_VARIABLE_CSS = re.compile(r"(--[\w-]+)\s*:\s*([^;\n]{1,60});")

#: Gris neutres et noirs/blancs purs : présents partout, ils ne caractérisent
#: aucune identité. Les inclure noierait les vraies couleurs de marque.
_NEUTRES = {"#ffffff", "#000000", "#fafafa", "#f5f5f5", "#eeeeee", "#cccccc",
            "#999999", "#666666", "#333333", "#111111", "#f8f9fa", "#e5e7eb"}


@dataclass(frozen=True)
class Design:
    """Ce qu'une source dit RÉELLEMENT de son identité visuelle."""

    couleurs: list[tuple[str, int]] = field(default_factory=list)
    polices: list[str] = field(default_factory=list)
    variables: list[tuple[str, str]] = field(default_factory=list)
    fichiers_lus: list[str] = field(default_factory=list)

    @property
    def vide(self) -> bool:
        return not (self.couleurs or self.polices or self.variables)

    def rendu(self, source: str) -> str:
        """Le bloc injecté dans le prompt — ou l'aveu qu'il n'y a rien.

        L'AVEU EST LE POINT IMPORTANT. Sans lui, le modèle reçoit un silence et
        le comble ; avec lui, il reçoit un fait — « cette source ne porte pas de
        palette » — dont il peut rendre compte.
        """
        if self.vide:
            return (
                f"\n\n[DESIGN NON TROUVÉ dans {source}]\n"
                f"Fichiers inspectés : {', '.join(self.fichiers_lus) or 'aucun'}\n"
                "Aucune couleur de marque, police ni variable de thème n'y est "
                "déclarée. NE PAS INVENTER de palette : signale que la source "
                "référencée ne contient pas cette information, et place la "
                "question dans « Questions ouvertes ».\n[/DESIGN]"
            )
        lignes = [f"\n\n[DESIGN RÉEL extrait de {source}]"]
        if self.couleurs:
            lignes.append("Couleurs (par fréquence, les plus utilisées d'abord) :")
            lignes += [f"  {c}  ×{n}" for c, n in self.couleurs]
        if self.polices:
            lignes.append("Polices déclarées :")
            lignes += [f"  {p}" for p in self.polices]
        if self.variables:
            lignes.append("Variables de thème :")
            lignes += [f"  {k} = {v}" for k, v in self.variables]
        lignes.append(f"Fichiers : {', '.join(self.fichiers_lus)}")
        lignes.append("CES VALEURS FONT FOI. N'en invente aucune autre.")
        lignes.append("[/DESIGN]")
        return "\n".join(lignes)


#: Titres markdown — la table des matières d'une source.
_TITRE = re.compile(r"^(#{1,4})\s+(.+?)\s*#*$", re.M)

#: Budget d'injection du CORPS d'une source. L'ancien valait 6 000 caractères et
#: coupait au milieu du document : sur un README de 19 196 caractères, 69 % du
#: contenu disparaissait — dont `/build`, la mémoire de projet, les fiches, les
#: présentations, l'intégration IDE, MCP, le serveur d'API.
#:
#: Mesuré : la spec produite listait trois fonctionnalités, exactement les trois
#: qui survivaient à la coupe. Le modèle n'avait jamais vu le reste du produit.
BUDGET_CORPS = 24_000


def sommaire(texte: str) -> list[tuple[int, str]]:
    """Les titres d'un document, avec leur niveau.

    Le sommaire est INTÉGRAL même quand le corps est tronqué, et c'est le point :
    un modèle qui voit toute la liste des fonctionnalités peut en parler ; un
    modèle qui n'en voit que le premier tiers croit que le produit s'y arrête.
    """
    return [(len(d), t.strip()) for d, t in _TITRE.findall(texte)]


def resumer_source(racine: Path, budget: int = BUDGET_CORPS) -> str:
    """Le contenu d'un dépôt référencé : sommaire complet, puis corps.

    La troncature est ANNONCÉE. Couper en silence laisse croire au modèle qu'il a
    tout lu, et c'est ainsi qu'une spec décrit un produit réduit à son premier
    tiers sans que rien ne le signale.
    """
    lecture = _lire_readme(racine)
    if not lecture:
        return ""
    nom, texte = lecture

    titres = sommaire(texte)
    bloc = [f"\n\n[SOMMAIRE COMPLET de {nom}]"]
    bloc += [f"{'  ' * (n - 1)}- {t}" for n, t in titres] or ["(aucun titre)"]
    bloc.append("[/SOMMAIRE]")
    bloc.append(f"\n[CONTENU de {nom}]")
    bloc.append(texte[:budget])
    if len(texte) > budget:
        bloc.append(
            f"\n… [CORPS TRONQUÉ : {len(texte)} caractères au total, "
            f"{budget} injectés. Le SOMMAIRE ci-dessus est COMPLET — traite "
            "chaque titre listé comme une fonctionnalité réelle du produit, même "
            "si son paragraphe n'apparaît pas ici.]")
    bloc.append("[/CONTENU]")
    return "\n".join(bloc)


def _lire_readme(racine: Path) -> tuple[str, str] | None:
    for nom in ("README.md", "readme.md", "AXON.md", "README.rst"):
        p = racine / nom
        if p.is_file():
            try:
                return f"{racine.name}/{nom}", p.read_text(encoding="utf-8",
                                                           errors="replace")
            except OSError:
                continue
    return None


def _candidats(racine: Path, max_fichiers: int = 40) -> list[Path]:
    """Les fichiers susceptibles de porter une identité visuelle."""
    vus: list[Path] = []
    for nom in _FICHIERS_DESIGN:
        p = racine / nom
        if p.is_file():
            vus.append(p)
    for dossier in _DOSSIERS_ASSETS:
        d = racine / dossier
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if len(vus) >= max_fichiers:
                return vus
            if p.is_file() and p.suffix.lower() in (".svg", ".css", ".json"):
                vus.append(p)
    return vus[:max_fichiers]


def extraire_design(racine: Path) -> Design:
    """L'identité visuelle réellement déclarée dans un dépôt.

    Compte les couleurs par FRÉQUENCE : une couleur de marque revient, une
    couleur d'illustration apparaît une fois. Le classement porte donc plus
    d'information que la simple présence.
    """
    if not racine.is_dir():
        return Design()

    couleurs: Counter[str] = Counter()
    polices: list[str] = []
    variables: list[tuple[str, str]] = []
    lus: list[str] = []

    for chemin in _candidats(racine):
        try:
            contenu = chemin.read_text(encoding="utf-8", errors="replace")[:120_000]
        except OSError:
            continue
        trouve = False
        for hexa in _HEX.findall(contenu):
            bas = hexa.lower()
            if bas not in _NEUTRES:
                couleurs[bas] += 1
                trouve = True
        for police in _POLICE.findall(contenu):
            nettoye = police.strip().strip("\"'")
            if nettoye and nettoye not in polices:
                polices.append(nettoye)
                trouve = True
        for nom, valeur in _VARIABLE_CSS.findall(contenu):
            if len(variables) < 20 and ("color" in nom or "font" in nom
                                        or _HEX.search(valeur)):
                variables.append((nom, valeur.strip()))
                trouve = True
        if trouve:
            lus.append(str(chemin.relative_to(racine)))

    return Design(couleurs=couleurs.most_common(10), polices=polices[:6],
                  variables=variables, fichiers_lus=lus)
