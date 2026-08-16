"""La relecture SÉMANTIQUE d'une spec — ce qu'aucune expression régulière ne voit.

`analyze` attrape ce qui a une forme : un gabarit oublié, un identifiant en
double, un adjectif sans chiffre. Il ne peut pas voir qu'une spec se contredit,
que « Vite (via Next) » décrit un montage qui n'existe pas, ou que le cœur du
produit est moins détaillé que sa page de contact.

Relevé sur une vraie spec, six défauts qu'aucun contrôle de forme n'atteint :

- « français + anglais » d'un côté, « Aucun i18n — texte en anglais » de l'autre ;
- une Vision qui annonce « iframe / API » et des exigences qui imposent l'iframe ;
- « Vite (via Next) » : Next n'utilise pas Vite ;
- `next build && next export` avec App Router : incompatible ;
- « LCP ≤ 1 s sur 3G » et « 10 000 requêtes simultanées » pour une page statique
  derrière un CDN — des cibles arbitraires qui ne se testent pas ;
- `script-src 'self' 'unsafe-eval'` posé comme EXIGENCE de sécurité, alors que
  c'est précisément ce qu'on cherche à éviter.

CE QUI REND CETTE PASSE UTILISABLE, C'EST QU'ELLE NE PEUT PAS INVENTER. Chaque
constat doit citer VERBATIM la ou les lignes en cause ; une citation absente du
fichier fait rejeter le constat, silencieusement. Un modèle qui hallucine un
problème produit donc zéro constat, pas un faux constat — et c'est la seule
façon de faire confiance à une relecture automatique.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .analyze import CRITIQUE, HAUTE, MOYENNE, BASSE, Constat

_SEVERITES = {CRITIQUE, HAUTE, MOYENNE, BASSE}

_SYSTEME = """\
Tu relis une spécification technique avant qu'un agent de code ne l'exécute
AVEUGLÉMENT. Tu cherches ce qui le ferait produire quelque chose de faux.

Six familles, et rien d'autre :

1. CONTRADICTION — deux passages incompatibles. Exemple réel : « français +
   anglais » quelque part, « Aucun i18n — texte en anglais » ailleurs.
2. IMPOSSIBLE — une combinaison technique qui n'existe pas ou ne fonctionne pas.
   Exemples réels : « Vite (via Next) » alors que Next n'utilise pas Vite ;
   `next export` avec App Router.
3. ARBITRAIRE — une cible chiffrée invraisemblable ou intestable en l'état.
   Exemples réels : « LCP ≤ 1 s sur 3G » pour une page avec fonts, SVG et
   parallaxe ; « 10 000 requêtes simultanées » pour une page statique sur CDN.
4. ANTIPATTERN — une pratique déconseillée posée comme EXIGENCE. Exemple réel :
   `script-src 'self' 'unsafe-eval'` présenté comme règle de sécurité.
5. SOUS-SPECIFIE — ce que la spec désigne elle-même comme sa différenciation
   reçoit MOINS de détail que le reste. Le cœur du produit doit être la partie
   la plus précise.
6. VERSION — une version figée sans justification, ou périmée pour un projet neuf.

Réponds UNIQUEMENT avec un objet JSON, sans markdown :
{"constats": [
  {"famille": "CONTRADICTION|IMPOSSIBLE|ARBITRAIRE|ANTIPATTERN|SOUS_SPECIFIE|VERSION",
   "severite": "CRITIQUE|HAUTE|MOYENNE|BASSE",
   "citation": "<ligne recopiée EXACTEMENT depuis la spec>",
   "citation_opposee": "<l'autre ligne en conflit, EXACTEMENT, ou \\"\\">",
   "probleme": "<ce qui ne va pas, une phrase>",
   "correction": "<ce qu'il faut écrire à la place, une phrase>"}
]}

MÉTHODE — parcours les six familles DANS L'ORDRE, une par une. Pour chacune,
relis la spec entière en ne cherchant que cette famille. Une relecture globale
« à la recherche de problèmes » en trouve deux ou trois et s'arrête ; six passes
ciblées en trouvent davantage, et surtout les mêmes d'une fois sur l'autre.

RÈGLES ABSOLUES :
- `citation` doit être un extrait EXACT de la spec, copié caractère pour
  caractère. Un constat dont la citation ne se retrouve pas dans le fichier est
  REJETÉ. Ne paraphrase jamais.
- Pour une CONTRADICTION, les DEUX citations sont obligatoires.
- N'invente aucun problème pour remplir la liste. Zéro constat est une réponse
  valide et fréquente.
- Ne signale pas de préférence de style. Seulement ce qui ferait produire du faux.
- Maximum 12 constats, les plus graves d'abord.\
"""


@dataclass(frozen=True)
class ConstatSemantique:
    """Un constat de relecture, avec de quoi le vérifier dans le fichier."""

    severite: str
    famille: str
    ligne: int
    citation: str
    ligne_opposee: int
    citation_opposee: str
    probleme: str
    correction: str

    def vers_constat(self) -> Constat:
        message = self.probleme
        if self.ligne_opposee:
            message += f" (en conflit avec L{self.ligne_opposee})"
        message += f" → {self.correction}"
        return Constat(self.severite, self.famille.lower().replace("_", "-"),
                       self.ligne, self.citation, message)


#: Emphase markdown, retirée avant appariement. Le modèle cite le TEXTE qu'il
#: lit — « EF-001 : Le site doit… » — là où le fichier porte « - **EF-001** : Le
#: site doit… ». Exiger les astérisques faisait rejeter des constats justes :
#: mesuré sur une vraie spec, une contradiction réelle perdue pour deux étoiles.
#:
#: La contrainte de fond est intacte : les MOTS doivent rester ceux du fichier,
#: seule la décoration est ignorée.
_DECORATION = re.compile(r"^[-\u2013\u2014\u2022]\s*|^\s*\d+\.\s*")


def _normaliser(texte: str) -> str:
    """Espaces, typographie et emphase markdown aplanis, pour retrouver une
    citation qu'un modele a recopiee sans ses asterisques."""
    t = texte.replace("\u00a0", " ").replace("\u2019", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2013", "-").replace("\u2014", "-")
    t = _DECORATION.sub("", t.strip())
    t = re.sub(r"[*_`~\u2705\u274c]", "", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def _localiser(citation: str, lignes: list[str]) -> int:
    """Le numéro de ligne d'une citation, ou 0 si elle n'est pas dans le fichier.

    C'est ce contrôle qui rend la passe sûre : une citation introuvable signifie
    que le modèle a paraphrasé ou inventé, et le constat disparaît.
    """
    cible = _normaliser(citation)
    if len(cible) < 8:
        return 0
    for i, l in enumerate(lignes, start=1):
        if cible in _normaliser(l):
            return i
    # Repli : la citation peut chevaucher deux lignes repliées par le formateur.
    joint = _normaliser(" ".join(lignes))
    if cible in joint:
        premiers = cible.split(" ")[:4]
        for i, l in enumerate(lignes, start=1):
            if all(mot in _normaliser(l) for mot in premiers):
                return i
    return 0


def _parse(texte: str) -> list[dict]:
    nettoye = re.sub(r"```(?:json)?\s*", "", texte).replace("```", "").strip()
    for tentative in (nettoye, (re.search(r"\{.*\}", nettoye, re.DOTALL) or [""])[0]):
        try:
            charge = json.loads(tentative)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(charge, dict):
            constats = charge.get("constats", [])
            return constats if isinstance(constats, list) else []
    return []


def relire(spec: str, llm) -> list[ConstatSemantique]:
    """Les défauts de sens, chacun ancré sur une ligne réelle du fichier.

    Une panne de modèle rend une liste vide : la relecture sémantique est un
    BONUS au-dessus des contrôles déterministes, jamais leur remplacement. Une
    spec ne devient pas valide parce que le réseau est tombé, elle reste jugée
    par `analyze`.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    lignes = spec.splitlines()
    try:
        reponse = llm.invoke([SystemMessage(content=_SYSTEME),
                              HumanMessage(content=spec[:24000])])
        bruts = _parse(getattr(reponse, "content", str(reponse)))
    except Exception:                                            # noqa: BLE001
        return []

    retenus: list[ConstatSemantique] = []
    for brut in bruts[:12]:
        if not isinstance(brut, dict):
            continue
        citation = str(brut.get("citation", ""))
        ligne = _localiser(citation, lignes)
        if not ligne:
            continue                    # citation introuvable → constat rejeté

        opposee = str(brut.get("citation_opposee", "") or "")
        ligne_opposee = _localiser(opposee, lignes) if opposee else 0
        famille = str(brut.get("famille", "")).upper()
        if famille == "CONTRADICTION" and not ligne_opposee:
            continue                    # une contradiction sans les deux bords
                                        # n'est qu'une opinion

        severite = str(brut.get("severite", "")).upper()
        if severite not in _SEVERITES:
            severite = MOYENNE
        probleme = str(brut.get("probleme", "")).strip()
        if not probleme:
            continue
        retenus.append(ConstatSemantique(
            severite=severite, famille=famille or "SEMANTIQUE", ligne=ligne,
            citation=citation.strip()[:70], ligne_opposee=ligne_opposee,
            citation_opposee=opposee.strip()[:70], probleme=probleme,
            correction=str(brut.get("correction", "")).strip() or "à trancher"))
    return retenus


def fusionner(constats_formels: list[Constat],
              constats_semantiques: list[ConstatSemantique]) -> list[Constat]:
    """Les deux passes en une seule liste, triée par gravité puis par ligne."""
    from .analyze import _ORDRE

    tous = list(constats_formels) + [c.vers_constat() for c in constats_semantiques]
    tous.sort(key=lambda c: (_ORDRE.get(c.severite, 9), c.ligne, c.categorie))
    return tous
