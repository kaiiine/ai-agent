# src/infra/erreurs.py
"""Compter les signaux d'erreur que la trace écrit déjà. Rien de plus.

Deux signaux sont inscrits dans `decisions.jsonl` depuis la branche
`feat/monitoring`, et personne ne les avait encore lus comme des erreurs :

    genre = rattrapage        le routeur n'a pas lié l'outil que le modèle a
                              dû réclamer au catalogue
    confirmation = REFUS      l'utilisateur a vu l'action proposée et a dit non

Ils ont ceci de rare qu'ils ne demandent AUCUN jugement de modèle : le premier
est une auto-déclaration du système, le second une décision explicite de
l'utilisateur. Distinguer « correction » et « nouvelle requête » en conversation
libre est un problème ouvert ; ces deux-là sont déjà tranchés à l'écriture.

CE MODULE COMPTE, IL NE CONCLUT PAS. Un rattrapage atteste que la sélection n'a
pas proposé l'outil réclamé — pas que l'outil réclamé était le bon. Le modèle
peut s'être trompé de nom. Compter reste juste ; durcir une porte sur ce compte
sans relire un échantillon apprendrait l'erreur du modèle à la porte. La
relecture appartient à la consolidation, pas ici.

Lecteur pur : il ne touche jamais `decisions.jsonl`, ne tourne jamais pendant un
tour, et n'a donc aucun moyen de coûter quoi que ce soit au chemin critique.
C'est la condition qui a fait choisir un fichier plutôt qu'un compteur en
mémoire — ce qui est cher finit désactivé.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.infra import trace

#: `hitl.REFUS`, recopié plutôt qu'importé : `src.infra` ne dépend pas de
#: `src.orchestrator`, et un lecteur de journal n'a aucune raison de charger le
#: graphe pour lire un fichier.
_REFUS = "refus"

#: Au-delà, on n'accumule plus d'exemples. Trois suffisent à reconnaître le
#: motif ; les garder tous ferait d'un compteur un second journal.
_EXEMPLES = 3


@dataclass
class Compte:
    """Un signal, regroupé par ce qui le rend comparable d'une fois sur l'autre.

    `quoi` est court et stable — un nom d'outil, un chemin — parce que ce qui se
    compte doit se grouper. La requête entière, elle, ne se groupe pas : deux
    formulations de la même erreur donneraient deux lignes et le total se
    perdrait. Elle est gardée à côté, en exemples.
    """
    quoi: str
    projet: str
    motif: str = ""
    n: int = 0
    dernier: str = ""
    exemples: list[str] = field(default_factory=list)

    def _ajouter(self, ligne: dict, exemple: str) -> None:
        self.n += 1
        at = str(ligne.get("at") or "")
        if at > self.dernier:
            self.dernier = at
        exemple = (exemple or "").strip()
        if exemple and len(self.exemples) < _EXEMPLES and exemple not in self.exemples:
            self.exemples.append(exemple)


def _grouper(paires: list[tuple[tuple[str, str, str], dict, str]]) -> list[Compte]:
    """Regroupe, puis trie par fréquence décroissante.

    Le tri est par compte d'abord : ce qui revient est ce qui mérite une règle,
    et une liste triée par date noierait le récurrent dans le récent.
    """
    comptes: dict[tuple[str, str, str], Compte] = {}
    for cle, ligne, exemple in paires:
        compte = comptes.get(cle)
        if compte is None:
            compte = comptes[cle] = Compte(quoi=cle[0], projet=cle[1], motif=cle[2])
        compte._ajouter(ligne, exemple)
    return sorted(comptes.values(), key=lambda c: (-c.n, c.quoi))


def rattrapages(lignes: list[dict]) -> list[Compte]:
    """Les outils que la sélection n'a pas liés, par outil et par projet.

    Séparés par projet volontairement : le catalogue d'outils d'un dépôt n'est
    pas celui d'un autre, et fondre les deux produirait un compte qui ne
    correspond à aucune sélection réelle.
    """
    return _grouper([
        ((str(l.get("outil") or "?"), str(l.get("projet") or trace.HORS_REPO), ""),
         l, str(l.get("intent") or ""))
        for l in lignes if l.get("genre") == trace.RATTRAPAGE
    ])


def refus(lignes: list[dict]) -> list[Compte]:
    """Ce que l'utilisateur a arrêté à la demande, par cible.

    Le motif (`refuser` / `preciser`) est dans la clé et non à côté : « refusé
    net » et « refusé avec une consigne » sont deux erreurs différentes. La
    seconde porte la correction, la première ne dit que le rejet — les compter
    ensemble effacerait exactement la distinction qui sert.
    """
    return _grouper([
        ((str(l.get("cible") or "?"), str(l.get("projet") or trace.HORS_REPO),
          str(l.get("erreur") or "refuser")),
         l, str((l.get("extra") or {}).get("precision") or ""))
        for l in lignes
        if l.get("confirmation") == _REFUS and l.get("resultat") == trace.BLOQUE
    ])


def couverture(lignes: list[dict]) -> dict:
    """Combien de tours ont été observés, et combien portent un signal.

    Sans ce dénominateur, « trois rattrapages » ne veut rien dire : sur trois
    tours c'est un routeur cassé, sur trois cents c'est du bruit. C'est la seule
    mise en rapport qu'on se permette — un ratio affiché serait la métrique que
    le PRD écarte, à ce volume-là.
    """
    runs = {str(l.get("run_id") or "") for l in lignes if l.get("run_id")}
    avec: set[str] = set()
    for ligne in lignes:
        touche = (ligne.get("genre") == trace.RATTRAPAGE
                  or (ligne.get("confirmation") == _REFUS
                      and ligne.get("resultat") == trace.BLOQUE))
        if touche and ligne.get("run_id"):
            avec.add(str(ligne["run_id"]))
    return {"runs": len(runs), "avec_signal": len(avec),
            "projets": sorted({str(l.get("projet") or trace.HORS_REPO)
                               for l in lignes})}
