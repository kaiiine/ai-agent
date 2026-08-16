"""Le VERDICT d'une capacité — distinct de l'état de sa collecte.

`ClvReadiness.status` répond à « peut-on mesurer ? » : MEASURABLE dès qu'une
paire décision/clôture existe. C'est une lecture de collecte, et elle ne dit
rien du résultat. Un rapport qui s'arrête là écrit « il manque 24 rencontres »
sous une capacité dont l'échantillon est atteint depuis longtemps et dont le
signe est franchement négatif — ce qui inverse la lecture : le lecteur attend
des données là où il faut lire un résultat.

Ces quatre verdicts séparent les deux questions :

  DATA_ACCUMULATION            l'échantillon requis n'est pas atteint. Attendre
                               a un sens ; le signe observé ne conclut rien.
  MEASURED_NEGATIVE            l'échantillon EST atteint et la borne haute reste
                               sous zéro. Ce n'est pas un manque de données,
                               c'est un résultat : le modèle ne bat pas la
                               clôture. Attendre ne le retournera pas.
  MEASURED_POSITIVE_NOT_MATURE échantillon atteint, CLV moyenne positive, mais
                               la borne BASSE ne l'est pas encore. Le signe est
                               encourageant et non démontré.
  MATURE                       échantillon atteint ET borne basse strictement
                               positive. Le seul verdict qui autorise la mise.

Aucun seuil n'est défini ici : ils viennent tous de la politique de maturité
versionnée. Ce module LIT, il ne décide pas — et surtout il n'optimise rien
pour retourner un signe.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

DATA_ACCUMULATION = "DATA_ACCUMULATION"
MEASURED_NEGATIVE = "MEASURED_NEGATIVE"
MEASURED_POSITIVE_NOT_MATURE = "MEASURED_POSITIVE_NOT_MATURE"
MATURE = "MATURE"
NOT_MEASURABLE = "NOT_MEASURABLE"

#: Ordre de gravité, du plus bloquant au plus permissif. Sert à trier un rapport,
#: jamais à comparer deux capacités sur le fond.
ORDRE = (NOT_MEASURABLE, DATA_ACCUMULATION, MEASURED_NEGATIVE,
         MEASURED_POSITIVE_NOT_MATURE, MATURE)


@dataclass(frozen=True)
class VerdictClv:
    """Le verdict d'une capacité, avec de quoi le contredire."""

    verdict: str
    n_independants: int
    requis: int
    mean_clv: Decimal | None
    borne_basse: float | None
    explication: str

    @property
    def echantillon_atteint(self) -> bool:
        return self.n_independants >= self.requis

    @property
    def attendre_peut_aider(self) -> bool:
        """Attendre n'a de sens QUE tant que l'échantillon manque.

        Un MEASURED_NEGATIVE dont l'échantillon est atteint ne se répare pas par
        la patience : c'est le modèle qu'il faudrait changer, et le dire
        autrement enverrait attendre indéfiniment.
        """
        return self.verdict in (DATA_ACCUMULATION, NOT_MEASURABLE)


def verdict_de_capacite(ligne: Any, *, requis: int,
                        borne_haute: float | None = None) -> VerdictClv:
    """Le verdict d'une ligne de `collect_par_capacite`.

    `borne_haute` est optionnelle : quand elle est connue et négative, le signe
    est tranché sans ambiguïté. À défaut on lit la moyenne, qui suffit à
    distinguer « négatif » de « positif non démontré ».
    """
    lire = (lambda cle: ligne.get(cle) if isinstance(ligne, dict)
            else getattr(ligne, cle, None))
    n = int(lire("independants") or 0)
    moyenne = lire("mean_clv")
    basse = lire("borne_basse")

    if not n or moyenne is None:
        return VerdictClv(
            NOT_MEASURABLE, n, requis, None, basse,
            "aucune paire décision/clôture admissible — rien n'est mesuré")

    if n < requis:
        return VerdictClv(
            DATA_ACCUMULATION, n, requis, moyenne, basse,
            f"{n}/{requis} rencontres indépendantes — le signe observé "
            "({moyenne}) ne conclut rien à cette taille".replace(
                "{moyenne}", f"{float(moyenne) * 100:+.2f} %"))

    if basse is not None and basse > 0:
        return VerdictClv(
            MATURE, n, requis, moyenne, basse,
            f"borne basse {basse * 100:+.2f} % strictement positive sur "
            f"{n} rencontres indépendantes")

    negatif = (borne_haute is not None and borne_haute < 0) or float(moyenne) < 0
    if negatif:
        return VerdictClv(
            MEASURED_NEGATIVE, n, requis, moyenne, basse,
            f"échantillon atteint ({n}/{requis}) et CLV moyenne "
            f"{float(moyenne) * 100:+.2f} % — le modèle ne bat pas la clôture. "
            "Ce n'est pas un manque de données")

    return VerdictClv(
        MEASURED_POSITIVE_NOT_MATURE, n, requis, moyenne, basse,
        f"CLV moyenne {float(moyenne) * 100:+.2f} % mais borne basse "
        f"{'non calculée' if basse is None else f'{basse * 100:+.2f} %'} — "
        "encourageant, pas démontré")


def verdicts(lignes, *, requis: int) -> list[tuple[str, VerdictClv]]:
    """Les verdicts de toutes les capacités, triés du plus bloquant au moins."""
    sortie = []
    for ligne in lignes:
        nom = (ligne.get("capacite") if isinstance(ligne, dict)
               else getattr(ligne, "capacite", "?"))
        sortie.append((nom, verdict_de_capacite(ligne, requis=requis)))
    return sorted(sortie, key=lambda kv: (ORDRE.index(kv[1].verdict), kv[0]))
