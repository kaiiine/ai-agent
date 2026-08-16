"""Ce qui manque à une spec pour être exécutable — vérifié, pas estimé.

Une spec produite par un modèle a l'air finie : sections remplies, ton assuré,
longueur rassurante. Les défauts qui coûtent cher ne se voient pas à la lecture —
un « rapide » jamais chiffré, une histoire sans critère d'acceptation, un
`[à définir]` oublié au milieu d'un paragraphe convaincant. On ne les découvre
qu'en build, quand l'agent doit décider à la place de l'utilisateur.

Ces contrôles sont DÉTERMINISTES. Aucun appel de modèle : on ne demande pas à un
LLM si le texte qu'il vient d'écrire est bon. Chaque constat pointe une ligne, se
reproduit à l'identique, et peut être contredit en regardant le fichier.

Quatre sévérités, et elles ne sont pas décoratives :

  CRITIQUE  la spec n'est pas exécutable en l'état — l'agent devra inventer
  HAUTE     une décision manque ; le build produira quelque chose d'arbitraire
  MOYENNE   imprécision qui coûtera une itération
  BASSE     confort de lecture
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CRITIQUE, HAUTE, MOYENNE, BASSE = "CRITIQUE", "HAUTE", "MOYENNE", "BASSE"
_ORDRE = {CRITIQUE: 0, HAUTE: 1, MOYENNE: 2, BASSE: 3}


@dataclass(frozen=True)
class Constat:
    """Un défaut, sa ligne, et ce qu'il faut faire."""

    severite: str
    categorie: str
    ligne: int
    extrait: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severite}] L{self.ligne} · {self.categorie} — {self.message}"


#: Formulations qui ANNONCENT une décision sans la prendre. Ce sont les plus
#: coûteuses : elles occupent la place de la décision, donc personne ne remarque
#: qu'elle manque.
_NON_TRANCHE = re.compile(
    r"(?i)(\bà\s+définir\b|\bTBD\b|\bTODO\b|\bFIXME\b"
    r"|\bselon\s+les\s+besoins\b|\bau\s+choix\b|\bsi\s+nécessaire\b"
    r"|\bà\s+préciser\b|\bà\s+voir\b|\bpar\s+exemple\s+X\b"
    r"|\bou\s+bien\b|\bvoire\b)")

#: Un gabarit laissé en place. `[titre court]` est un oubli de rédaction ;
#: `[Sport]` dans une phrase est probablement du contenu. On exige donc une
#: minuscule initiale ou un mot de gabarit connu.
_GABARIT = re.compile(
    r"\[(?:titre court|même structure|liste explicite|"
    r"[a-zà-ÿ][^\]]{0,60})\]")

#: Une ligne qui n'est QUE du crochet est un gabarit, quelle que soit sa casse :
#: `[Le parcours en langage courant]` seul sur sa ligne n'est pas du contenu.
_LIGNE_GABARIT = re.compile(r"^\s*\[[^\]]{3,80}\]\s*$")

#: Adjectifs qui ne se testent pas. Un développeur ne peut pas savoir s'il les a
#: satisfaits ; un agent le décidera donc tout seul.
#: L'ACCORD compte : « une interface intuitive » échappait à un motif écrit au
#: masculin singulier, et c'est la forme la plus fréquente dans une spec
#: française. Les terminaisons couvrent féminin et pluriel.
_ADJECTIFS_FLOUS = re.compile(
    r"(?i)\b("
    r"rapides?|robustes?|fluides?|modernes?|simples?|scalables?|efficaces?"
    r"|performantes?|performants?"
    r"|intuitifs?|intuitives?"
    r"|élégantes?|élégants?"
    r"|évolutifs?|évolutives?"
    r"|sécurisées?|sécurisés?"
    r"|optimisées?|optimisés?"
    r"|légères?|légers?|léger"
    r"|réactifs?|réactives?"
    r"|ergonomiques?|conviviales?|conviviaux|convivial"
    r")\b")

#: Un chiffre suffisamment proche rend l'adjectif vérifiable.
_CHIFFRE = re.compile(r"\d")

#: L'identifiant d'exigence — ce qui rend une exigence citable dans une phase.
_EXIGENCE = re.compile(r"\*\*(EF-\d{3})\*\*")

#: Un critère d'acceptation réellement formé.
#:
#: `DOTALL` est indispensable : un critère un peu long est replié sur deux ou
#: trois lignes par n'importe quel formateur markdown, et sans lui la spec la
#: mieux écrite se voyait reprocher un critère absent.
_CRITERE = re.compile(
    r"(?i)\*\*étant\s+donné\*\*.*?\*\*quand\*\*.*?\*\*alors\*\*", re.DOTALL)

#: L'identifiant d'exigence, retiré avant de chercher un chiffre : « EF-002 »
#: en contient trois, et les compter comme une quantification faisait passer
#: « le système doit être performant » pour une exigence mesurable.
_PREFIXE_IDENTIFIANT = re.compile(r"\*\*EF-\d{3}\*\*\s*:?")

_TITRE_HISTOIRE = re.compile(r"^###\s+(P\d)\s*[—-]\s*(.+)$")
_SECTION = re.compile(r"^##\s+(.+?)\s*$")

#: Une valeur posée sous réserve. Le gabarit l'encourage — mieux vaut une valeur
#: marquée « à confirmer » qu'un blanc — mais elle DOIT alors se retrouver dans
#: les questions ouvertes, sinon la réserve se perd et le chiffre devient loi.
_A_CONFIRMER = re.compile(
    r"(?i)\((?:valeur\s+propos[ée]e?|à\s+confirmer|proposé|hypothèse)[^)]*\)")

#: Un mot ENTRE GUILLEMETS est cité, pas employé. « aucune règle "TODO" dans le
#: code » est un critère de fini parfaitement valide ; le signaler comme un TODO
#: oublié est un contresens. Mesuré sur une vraie spec : c'était le seul constat
#: HAUTE du fichier, et il était faux.
_CITATION = re.compile(r"[«\"'`“”]([^«»\"'`“”]{1,60})[»\"'`“”]")

#: Sections où une phrase ENGAGE. Ailleurs — récit d'une histoire, justification
#: d'un choix de stack, alternative rejetée — le texte EXPLIQUE, et « rapide »
#: y est une tournure de langue, pas une exigence non chiffrée.
#:
#: Le contrôle des adjectifs flous ne s'applique donc qu'ici. Sans cette
#: restriction, une spec correcte remontait six constats dont aucun ne portait
#: sur une promesse : « HMR rapide en dev » dans la colonne « pourquoi ce
#: choix » d'un tableau de stack, ou « trop lourd pour un simple site » dans les
#: alternatives rejetées.
_SECTIONS_ENGAGEANTES = (
    "exigences", "definition of done", "critères", "criteres",
    "non fonctionnel", "qualité", "qualite", "performance",
)

#: Une ligne qui EXPLIQUE au lieu de promettre, même dans une section engageante.
_LIGNE_EXPLICATIVE = re.compile(
    r"(?i)^\s*(?:>"                       # citation markdown
    r"|[-*]\s*\*?[A-Za-zÀ-ÿ ]+\*?\s*[–—-]\s"   # « - *Gatsby* – trop lourd… »
    r"|\|.*\|.*\|)")                      # ligne de tableau (colonne rationale)

#: Sections dont l'absence rend la spec inexécutable, quel que soit le profil.
_SECTIONS_REQUISES = (
    ("Périmètre", CRITIQUE, "sans périmètre, rien ne borne la v1"),
    ("Histoires utilisateur", CRITIQUE, "sans tranches, le build n'a pas d'ordre"),
    ("Exigences fonctionnelles", HAUTE, "rien à citer depuis une phase de build"),
    ("Contraintes techniques", CRITIQUE, "l'agent choisira la stack à ta place"),
    ("Definition of Done", HAUTE, "« fini » restera une opinion"),
)


def _sections(lignes: list[str]) -> dict[str, int]:
    trouvees = {}
    for i, l in enumerate(lignes, start=1):
        m = _SECTION.match(l)
        if m:
            trouvees[m.group(1).strip()] = i
    return trouvees


def _normaliser(texte: str) -> str:
    """Une exigence réduite à ses mots significatifs, pour repérer les doublons."""
    mots = re.findall(r"[a-zà-ÿ]{4,}", texte.lower())
    vides = {"doit", "peut", "avec", "pour", "dans", "être", "cette", "leur",
             "sont", "plus", "tout", "toute", "chaque", "selon"}
    return " ".join(sorted(set(mots) - vides))


#: Un terme TECHNIQUE nommé par l'utilisateur : « Three.js », « WebGL »,
#: « Tailwind », « PostgreSQL ». Repéré par sa forme — une majuscule interne ou
#: un point — ce qui évite de traiter n'importe quel mot comme une exigence.
_TERME_TECHNIQUE = re.compile(r"\b([A-Za-zÀ-ÿ]+(?:\.[a-z]{2,3}|[A-Z][\w.]*))\b")

#: Fonctionnalités nommées en toutes lettres, sans forme distinctive. La liste
#: est courte et volontairement conservatrice : mieux vaut rater une demande que
#: signaler un mot ordinaire comme une exigence perdue.
_DEMANDES_NOMMEES = (
    "3d", "webgl", "three", "parallaxe", "dark mode", "mode sombre", "i18n",
    "multilingue", "pwa", "hors-ligne", "offline", "seo", "rgpd", "a11y",
    "accessibilité", "animation", "vidéo", "webgpu", "canvas", "shader",
)

#: Mots à forme technique mais sans valeur d'exigence.
_IGNORES_TECHNIQUES = {"axon", "je", "tu", "il", "la", "le", "les", "des", "une",
                       "un", "et", "ou", "pour", "dans", "avec", "sur", "que"}


def demandes_explicites(demande: str) -> list[str]:
    """Ce que l'utilisateur a NOMMÉMENT réclamé.

    Sert à vérifier qu'une demande explicite survit jusqu'à la spec. « Inclus de
    la 3D » suivi d'une spec sans une seule mention de 3D est un défaut qu'aucun
    contrôle de cohérence interne ne peut voir : le document est parfaitement
    cohérent, il répond simplement à une autre question que celle posée.
    """
    if not demande:
        return []
    bas = demande.lower()
    trouves: list[str] = []
    for mot in _DEMANDES_NOMMEES:
        if mot in bas and mot not in trouves:
            trouves.append(mot)
    for terme in _TERME_TECHNIQUE.findall(demande):
        cle = terme.lower()
        if len(terme) >= 3 and cle not in _IGNORES_TECHNIQUES and cle not in trouves:
            trouves.append(cle)

    # « three » et « three.js » désignent la même demande : n'en garder que la
    # forme la plus complète évite de signaler deux fois le même manque.
    retenus = [t for t in trouves
               if not any(t != autre and t in autre for autre in trouves)]
    return retenus[:20]


def analyser(spec: str, demande: str = "") -> list[Constat]:
    """Tous les constats, du plus grave au moins grave.

    `demande` est le descriptif initial et les réponses du wizard. Le fournir
    ajoute une vérification que la spec seule ne permet pas : une demande
    explicite qui n'a pas survécu jusqu'au document.

    L'ordre est TOTAL et stable : deux analyses du même texte rendent la même
    liste, ce qui permet de comparer une spec avant et après correction.
    """
    lignes = spec.splitlines()
    constats: list[Constat] = []
    sections = _sections(lignes)

    def ajouter(sev, cat, n, extrait, message):
        constats.append(Constat(sev, cat, n, extrait.strip()[:70], message))

    # ── Sections manquantes ─────────────────────────────────────────────────
    for nom, severite, pourquoi in _SECTIONS_REQUISES:
        if not any(nom.lower() in s.lower() for s in sections):
            ajouter(severite, "section-absente", 0, nom,
                    f"section « {nom} » absente — {pourquoi}")

    # ── Décisions annoncées mais non prises ─────────────────────────────────
    for i, l in enumerate(lignes, start=1):
        # Ce qui est cité est mentionné, pas laissé en suspens.
        hors_citation = _CITATION.sub(" ", l)
        for m in _NON_TRANCHE.finditer(hors_citation):
            ajouter(HAUTE, "non-tranché", i, l,
                    f"« {m.group(1)} » — la décision est annoncée, pas prise")
        if _LIGNE_GABARIT.match(l):
            ajouter(CRITIQUE, "gabarit", i, l,
                    f"ligne entièrement laissée en gabarit : {l.strip()[:40]}")
            continue
        for m in _GABARIT.finditer(l):
            ajouter(CRITIQUE, "gabarit", i, l,
                    f"gabarit non remplacé : {m.group(0)}")

    # ── Adjectifs non vérifiables, LÀ OÙ LA SPEC S'ENGAGE ───────────────────
    #
    # Un adjectif flou n'est un défaut que dans une phrase qui PROMET. Dans un
    # récit d'histoire utilisateur, une justification de choix technique ou une
    # alternative rejetée, le texte explique — et « rapide » y est une tournure
    # de langue. Contrôler partout produisait six constats sur une spec correcte,
    # dont aucun ne portait sur une promesse.
    section_courante = ""
    for i, l in enumerate(lignes, start=1):
        titre = _SECTION.match(l)
        if titre:
            section_courante = titre.group(1).lower()
            continue
        if l.lstrip().startswith("#") or not l.strip():
            continue
        if not any(mot in section_courante for mot in _SECTIONS_ENGAGEANTES):
            continue
        if _LIGNE_EXPLICATIVE.match(l):
            continue
        sans_identifiant = _PREFIXE_IDENTIFIANT.sub("", l)
        for m in _ADJECTIFS_FLOUS.finditer(sans_identifiant):
            if not _CHIFFRE.search(sans_identifiant):
                ajouter(MOYENNE, "non-mesurable", i, l,
                        f"« {m.group(1)} » sans chiffre — intestable")

    # ── Histoires : priorisées, indépendantes, vérifiables ──────────────────
    histoires = [(i, m.group(1), m.group(2))
                 for i, l in enumerate(lignes, start=1)
                 if (m := _TITRE_HISTOIRE.match(l))]
    if not histoires:
        ajouter(CRITIQUE, "histoires", sections.get("Histoires utilisateur", 0), "",
                "aucune histoire P1/P2/P3 — le build n'a pas d'ordre de construction")
    else:
        priorites = [p for _, p, _ in histoires]
        if "P1" not in priorites:
            ajouter(CRITIQUE, "histoires", histoires[0][0], "",
                    "aucune histoire P1 — rien n'identifie le minimum livrable")
        bornes = [i for i, _, _ in histoires] + [len(lignes) + 1]
        for (debut, priorite, titre), fin in zip(histoires, bornes[1:]):
            corps = "\n".join(lignes[debut:fin - 1])
            if not _CRITERE.search(corps):
                ajouter(CRITIQUE, "critères", debut, titre,
                        f"{priorite} sans critère « Étant donné / Quand / Alors » — "
                        "aucune définition de fini opposable")
            if "livrable seul" not in corps.lower():
                ajouter(HAUTE, "indépendance", debut, titre,
                        f"{priorite} ne dit pas ce qu'elle livre SEULE — "
                        "la tranche n'est peut-être pas indépendante")

    # ── Exigences : citables et non redondantes ─────────────────────────────
    exigences = [(i, l) for i, l in enumerate(lignes, start=1) if _EXIGENCE.search(l)]
    if not exigences and "Exigences fonctionnelles" in sections:
        ajouter(HAUTE, "exigences", sections["Exigences fonctionnelles"], "",
                "aucune exigence numérotée EF-xxx — rien n'est citable")

    identifiants = [_EXIGENCE.search(l).group(1) for _, l in exigences]
    for ident in sorted({i for i in identifiants if identifiants.count(i) > 1}):
        n = next(i for i, l in exigences if ident in l)
        ajouter(HAUTE, "doublon", n, ident,
                f"identifiant {ident} utilisé plusieurs fois")

    vus: dict[str, int] = {}
    for n, l in exigences:
        cle = _normaliser(l)
        if len(cle.split()) < 3:
            continue
        if cle in vus:
            ajouter(MOYENNE, "doublon", n, l,
                    f"exigence quasi identique à celle de la ligne {vus[cle]}")
        else:
            vus[cle] = n

    # ── « Questions ouvertes : aucune » démenti par le corps du texte ───────
    #
    # Relevé sur une vraie spec : la section affirmait « Aucune » alors que deux
    # valeurs plus haut portaient « (valeur proposée, à confirmer) ». C'est la
    # contradiction la moins visible et la plus coûteuse — elle fait croire que
    # tout est tranché, donc personne ne rouvre le sujet.
    en_attente = [(i, l) for i, l in enumerate(lignes, start=1)
                  if _A_CONFIRMER.search(l)]
    ligne_ouvertes = next(
        (i for i, l in enumerate(lignes, start=1)
         if re.search(r"(?i)^##+\s+(?:questions?\s+ouvertes?|décisions?\s+à\s+valider)", l)),
        None)
    if ligne_ouvertes is not None and en_attente:
        suite = " ".join(lignes[ligne_ouvertes:ligne_ouvertes + 6]).lower()
        if re.search(r"\b(aucune?|néant|rien|n/a)\b", suite):
            ajouter(HAUTE, "contradiction", ligne_ouvertes, "Questions ouvertes",
                    f"déclarées « aucune » alors que {len(en_attente)} valeur(s) "
                    f"restent à confirmer (L{', L'.join(str(i) for i, _ in en_attente[:4])})")

    # NOTE — la détection de CONTRADICTION SÉMANTIQUE n'est pas ici, et c'est
    # délibéré. Une première version cherchait les négations (« Aucun i18n »)
    # démenties ailleurs dans le fichier : sur une vraie spec elle a produit six
    # constats, tous faux — « Sans une » contre « une », « Aucun motif » contre
    # « motif ». Une contradiction porte sur le SENS, pas sur la répétition d'un
    # mot, et aucune expression régulière ne franchit cet écart.
    #
    # Ce travail vit dans `review.py`, où un modèle le fait sous une contrainte
    # qui le rend vérifiable : citer les DEUX lignes en conflit, verbatim, sous
    # peine de voir le constat rejeté.

    # ── Hors-scope : présent ET non vide ────────────────────────────────────
    hors = next((i for i, l in enumerate(lignes, start=1)
                 if re.search(r"(?i)^###?\s+HORS\s+périmètre", l)), None)
    if hors is None:
        ajouter(HAUTE, "périmètre", sections.get("Périmètre", 0), "",
                "aucun hors-périmètre explicite — tout ajout paraîtra légitime")
    else:
        suite = [l for l in lignes[hors:hors + 8] if l.strip().startswith("-")]
        if not suite:
            ajouter(HAUTE, "périmètre", hors, "",
                    "hors-périmètre déclaré mais vide")

    # ── Une demande explicite a-t-elle survécu jusqu'à la spec ? ────────────
    #
    # « Inclus de la 3D » suivi d'une spec sans une seule mention de 3D est un
    # défaut invisible à tout contrôle interne : le document est cohérent, il
    # répond simplement à une autre question. Seule la confrontation avec la
    # demande le révèle.
    if demande:
        bas = spec.lower()
        for terme in demandes_explicites(demande):
            if terme not in bas:
                ajouter(HAUTE, "demande-perdue", 0, terme,
                        f"« {terme} » a été demandé explicitement et n'apparaît "
                        "nulle part dans la spec")

    constats.sort(key=lambda c: (_ORDRE[c.severite], c.ligne, c.categorie))
    return constats


def resume(constats: list[Constat]) -> str:
    """Le décompte par sévérité, en une ligne."""
    if not constats:
        return "aucun constat — la spec est exécutable en l'état"
    par_severite: dict[str, int] = {}
    for c in constats:
        par_severite[c.severite] = par_severite.get(c.severite, 0) + 1
    return " · ".join(f"{n} {s.lower()}" for s, n in
                      sorted(par_severite.items(), key=lambda kv: _ORDRE[kv[0]]))


def bloquant(constats: list[Constat]) -> bool:
    """Y a-t-il de quoi refuser de lancer un build ?

    Seul CRITIQUE bloque. Une spec avec des imprécisions moyennes produit un
    build imparfait ; une spec sans critère d'acceptation produit un build dont
    personne ne peut dire s'il est juste.
    """
    return any(c.severite == CRITIQUE for c in constats)
