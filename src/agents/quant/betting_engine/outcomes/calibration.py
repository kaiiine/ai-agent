"""Justesse RÉELLE du modèle, mesurée sur les issues observées.

Jusqu'ici la seule mesure venait d'un walk-forward historique sur un CSV figé :
elle dit comment le modèle se serait comporté sur le passé, jamais comment il se
comporte. Ce module lit les prédictions réglées et rend Brier, ECE et un profil
de calibration par tranche de probabilité.

Aucune valeur fabriquée : sans prédiction réglée, tout vaut None — jamais 0, qui
serait un score parfait.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .record import PredictionRecord

#: En deçà, un Brier n'est que du bruit. Seuil d'AFFICHAGE, jamais un gate.
N_MIN_LISIBLE = 30


@dataclass(frozen=True)
class Tranche:
    borne_basse: Decimal
    borne_haute: Decimal
    n: int
    probabilite_moyenne: Decimal    # ce que le modèle annonçait
    frequence_observee: Decimal     # ce qui est réellement arrivé

    @property
    def ecart(self) -> Decimal:
        """> 0 : le modèle promet plus qu'il ne réalise (surconfiance)."""
        return self.probabilite_moyenne - self.frequence_observee


@dataclass(frozen=True)
class CalibrationReelle:
    n_reglees: int
    n_annulees: int
    brier: Decimal | None
    ece: Decimal | None
    taux_reussite: Decimal | None       # fréquence brute de sélections sorties
    probabilite_moyenne: Decimal | None
    tranches: tuple[Tranche, ...]
    model_version: str | None

    @property
    def lisible(self) -> bool:
        """Assez d'observations pour que les chiffres veuillent dire quelque chose."""
        return self.n_reglees >= N_MIN_LISIBLE

    @property
    def biais(self) -> Decimal | None:
        """> 0 : le modèle est globalement SURCONFIANT sur ses sélections."""
        if self.probabilite_moyenne is None or self.taux_reussite is None:
            return None
        return self.probabilite_moyenne - self.taux_reussite


def _moyenne(valeurs: list[Decimal]) -> Decimal:
    return sum(valeurs, Decimal("0")) / Decimal(len(valeurs))


def calibration_reelle(records, *, n_tranches: int = 5,
                       model_version: str | None = None) -> CalibrationReelle:
    """Brier / ECE / profil par tranche sur les prédictions réellement réglées.

    Les sélections ANNULÉES (walkover, forfait) sont comptées à part : elles n'ont
    pas d'issue, et les traiter comme des pertes fabriquerait de la surconfiance.
    """
    tous = [r for r in records
            if model_version is None or r.model_version == model_version]
    annulees = sum(1 for r in tous if r.est_reglee and not r.compte_pour_la_calibration)
    utiles = [r for r in tous if r.compte_pour_la_calibration]

    if not utiles:
        return CalibrationReelle(0, annulees, None, None, None, None, (), model_version)

    paires = [(r.fair_probability, r.realise) for r in utiles]
    brier = _moyenne([(p - y) ** 2 for p, y in paires])
    proba_moyenne = _moyenne([p for p, _ in paires])
    taux = _moyenne([y for _, y in paires])

    tranches: list[Tranche] = []
    ecart_total = Decimal("0")
    for i in range(n_tranches):
        basse = Decimal(i) / n_tranches
        haute = Decimal(i + 1) / n_tranches
        dedans = [(p, y) for p, y in paires
                  if basse <= p < haute or (i == n_tranches - 1 and p == haute)]
        if not dedans:
            continue
        p_moy = _moyenne([p for p, _ in dedans])
        f_obs = _moyenne([y for _, y in dedans])
        tranches.append(Tranche(basse, haute, len(dedans), p_moy, f_obs))
        ecart_total += (Decimal(len(dedans)) / len(paires)) * abs(p_moy - f_obs)

    return CalibrationReelle(
        n_reglees=len(utiles), n_annulees=annulees,
        brier=brier, ece=ecart_total, taux_reussite=taux,
        probabilite_moyenne=proba_moyenne, tranches=tuple(tranches),
        model_version=model_version)


def rendre_texte(c: CalibrationReelle) -> list[str]:
    """Rendu lisible — dit toujours si l'échantillon permet de conclure."""
    if c.n_reglees == 0:
        return ["Aucune prédiction réglée : la justesse en production n'est pas "
                "encore mesurable." + (f" ({c.n_annulees} annulée(s))" if c.n_annulees else "")]

    def pct(v: Decimal | None) -> str:
        return "n/d" if v is None else f"{v * 100:.2f} %"

    lignes = [
        f"Prédictions réglées : {c.n_reglees}"
        + (f" (+ {c.n_annulees} annulée(s), hors calcul)" if c.n_annulees else ""),
        f"Brier : {c.brier:.4f}   ECE : {c.ece:.4f}",
        f"Annoncé en moyenne : {pct(c.probabilite_moyenne)}   "
        f"Réellement sorti : {pct(c.taux_reussite)}   "
        f"Biais : {pct(c.biais)}"
        + ("  (surconfiance)" if c.biais and c.biais > 0 else
           "  (sous-confiance)" if c.biais and c.biais < 0 else ""),
    ]
    if not c.lisible:
        lignes.append(f"⚠ {c.n_reglees} observation(s) : sous {N_MIN_LISIBLE}, ces "
                      "chiffres sont du bruit. Aucune conclusion à en tirer.")
    if c.tranches:
        lignes.append("")
        lignes.append("  tranche      n   annoncé   observé    écart")
        for t in c.tranches:
            lignes.append(
                f"  {t.borne_basse:.1f}-{t.borne_haute:.1f}  {t.n:5d}   "
                f"{t.probabilite_moyenne * 100:6.2f} %  {t.frequence_observee * 100:6.2f} %  "
                f"{t.ecart * 100:+6.2f} pts")
    return lignes
