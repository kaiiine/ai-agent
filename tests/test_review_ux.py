"""L'UX de la revue : ce qui doit rester VISIBLE quand rien n'est misable.

Le produit répondait « aucun pari » sur un run qui avait pourtant produit plus
d'un millier de probabilités. Le défaut n'était pas dans le moteur — il calculait
juste — mais dans la marche entre ACTIONABLE et l'affichage : sans candidat
misable, la sortie se taisait, et la couche de langage comblait le vide par des
promesses que rien ne mesure.

Ces tests portent les quatre garanties de ce comportement :

1. ACTIONABLE = 0 avec des candidats en revue N'EST JAMAIS une sortie vide ;
2. une préférence de probabilité ORDONNE l'affichage, elle ne filtre pas, et ne
   se satisfait jamais de `fair_probability` à la place de `probability_low` ;
3. un candidat refusé par la politique ne devient pas un candidat de revue ;
4. un combiné dont l'indépendance n'est pas établie vaut NOT_ESTIMATED — jamais
   un produit de probabilités.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.agents.quant.betting_engine.markets.families import MarketFamily
from src.agents.quant.betting_engine.markets.review_ranking import (
    ProductStatus, ReviewCandidate,
)
from src.agents.quant.conversation.review_preference import (
    cible_depuis_texte, partitionner,
)


# ══ Fabriques ═══════════════════════════════════════════════════════════════
def _candidat(*, event="e1", selection="under", low=0.91, fair=0.93,
              vig=0.80, odds=1.11, ev=0.03, participants=("a", "b"),
              famille=MarketFamily.TOTALS, parametres=None) -> ReviewCandidate:
    return ReviewCandidate(
        source_event_id=event, sport="football", competition="c",
        family=famille, parameters=parametres or {"line": "5.5"}, context={},
        selection=selection, bookmaker_odds=odds,
        implied_probability=None if odds is None else 1 / odds,
        vig_adjusted_probability=vig, fair_probability=fair, probability_low=low,
        expected_value=ev, maturity="EXPERIMENTAL", freshness=0.98,
        # L'origine porte l'ÉVÉNEMENT, comme en production
        # (« dixon_coles:score_matrix:event:… ») : deux candidats de rencontres
        # différentes ne partagent donc pas de loi jointe par défaut.
        data_quality=1.0, probability_origin=f"modele:test:{event}",
        event_label="A – B", model_name="m", model_version="m.v0",
        event_id=event, participant_ids=participants)


class _Rang:
    """Le strict nécessaire du `RankedCandidate` pour ces tests."""

    def __init__(self, candidate, status=ProductStatus.REVIEW, ev_low=Decimal("0.01")):
        self.candidate = candidate
        self.status = status
        self.expected_value_low = ev_low
        self.global_rank = 1
        self.event_rank = 1
        self.reasons = ()


class _Revue:
    def __init__(self, rangs, tous_cotes=None):
        self._rangs = tuple(rangs)
        self._tous = tuple(tous_cotes if tous_cotes is not None else rangs)
        self.non_comparables = ()
        self.ecartes_par_politique = ()
        self.par_evenement = {}
        self.global_ranking = self._rangs
        self.comparables = self._tous

    @property
    def review(self):
        return tuple(r for r in self._rangs if r.status is ProductStatus.REVIEW)

    @property
    def review_tous_cotes(self):
        return tuple(r for r in self._tous if r.status is ProductStatus.REVIEW)

    @property
    def evenements_dont_le_meilleur_n_est_pas_le_vainqueur(self):
        return ()


# ══ 1 · La préférence se lit, et seulement quand elle est dite ══════════════
@pytest.mark.parametrize("texte, attendu", [
    ("je veux environ 90 % de chances", Decimal("0.90")),
    ("au moins 85% de probabilité", Decimal("0.85")),
    ("un truc fiable à 95 %", Decimal("0.95")),
    # Un pourcentage SANS mot de probabilité n'est pas une préférence.
    ("mise 10 % de ma bankroll", None),
    ("objectif x2", None),
    ("", None),
])
def test_la_preference_ne_se_lit_que_si_elle_parle_de_probabilite(texte, attendu):
    assert cible_depuis_texte(texte) == attendu


# ══ 2 · La préférence ORDONNE, elle ne filtre jamais ════════════════════════
def test_les_candidats_sous_le_seuil_restent_disponibles():
    """« Aucun candidat n'atteint 90 % » suivi du silence serait la même impasse
    que de ne rien montrer du tout."""
    rangs = [_Rang(_candidat(event="e1", low=0.55)),
             _Rang(_candidat(event="e2", low=0.42))]

    partition = partitionner(rangs, Decimal("0.90"))

    assert partition.au_seuil == ()
    assert len(partition.sous_seuil) == 2, "les candidats sous le seuil sont gardés"
    assert partition.total == 2


def test_le_seuil_se_compare_a_la_borne_basse_jamais_a_la_probabilite_du_modele():
    """`fair_probability` est une estimation ponctuelle. Qui demande 90 % demande
    une garantie : la substituer répondrait « oui » avec le mauvais chiffre."""
    # fair = 0.97 (au-dessus du seuil) mais borne basse = 0.71 (en dessous).
    rangs = [_Rang(_candidat(fair=0.97, low=0.71))]

    partition = partitionner(rangs, Decimal("0.90"))

    assert partition.au_seuil == (), "fair_probability ne vaut pas garantie"
    assert len(partition.sous_seuil) == 1


def test_une_borne_basse_absente_n_atteint_aucun_seuil_et_n_echoue_pas():
    """`probability_low=None` n'est ni au-dessus ni en dessous : il n'est pas
    comparable, et le compter comme un échec le ferait passer pour mesuré."""
    rangs = [_Rang(_candidat(low=None))]

    partition = partitionner(rangs, Decimal("0.90"))

    assert partition.au_seuil == ()
    assert partition.sous_seuil == ()
    assert len(partition.sans_borne_basse) == 1


def test_sans_preference_aucun_candidat_n_est_ecarte():
    rangs = [_Rang(_candidat(event=f"e{i}", low=0.1 * i)) for i in range(1, 6)]

    partition = partitionner(rangs, None)

    assert partition.cible is None
    assert len(partition.sous_seuil) == 5


def test_les_candidats_au_seuil_sont_ordonnes_par_borne_basse_decroissante():
    rangs = [_Rang(_candidat(event="e1", low=0.91)),
             _Rang(_candidat(event="e2", low=0.97)),
             _Rang(_candidat(event="e3", low=0.94))]

    partition = partitionner(rangs, Decimal("0.90"))

    assert [float(r.candidate.probability_low) for r in partition.au_seuil] == [
        0.97, 0.94, 0.91]


# ══ 3 · ACTIONABLE = 0 n'est jamais une sortie vide ═════════════════════════
class _Reponse:
    portfolios = ()


def test_actionable_zero_avec_review_affiche_des_candidats():
    """La condition de TEST FAIL énoncée par le produit : 0 misable + des
    candidats en revue, et aucun affiché."""
    from src.agents.quant.conversation.summary import render_marches_en_revue

    revue = _Revue([_Rang(_candidat(event=f"e{i}", low=0.5)) for i in range(3)])

    lignes = render_marches_en_revue(revue, cible=None)

    assert lignes, "une revue non vide doit produire un affichage"
    assert any("Sélection" in l for l in lignes)


def test_aucun_candidat_au_seuil_affiche_quand_meme_les_meilleurs_en_dessous():
    from src.agents.quant.conversation.summary import render_marches_en_revue

    revue = _Revue([_Rang(_candidat(event=f"e{i}", low=0.4)) for i in range(3)])

    texte = "\n".join(render_marches_en_revue(revue, cible=Decimal("0.90")))

    assert "Aucun candidat n'atteint 90 %" in texte
    assert "meilleurs candidats EXPERIMENTAL" in texte
    assert "Sélection" in texte, "les candidats sous le seuil sont bien affichés"


def test_les_compteurs_disent_la_meme_population_que_l_affichage():
    """Un compteur annonçant trois candidats pendant que la section n'en montre
    qu'un est exactement le défaut que ces nombres servent à rendre impossible."""
    from src.agents.quant.conversation.summary import (
        population_de_revue, render_compteurs_revue,
    )

    rangs = [_Rang(_candidat(event=f"e{i}", low=0.95)) for i in range(3)]
    revue = _Revue(rangs[:1], tous_cotes=rangs)     # le classement n'en garde qu'un

    lignes = render_compteurs_revue(_Reponse(), revue, Decimal("0.90"))
    texte = "\n".join(lignes)

    assert "ACTIONABLE: 0" in texte
    assert "REVIEW >= seuil demandé (probability_low): 3" in texte
    assert len(population_de_revue(revue, Decimal("0.90"))) == 3


def test_la_preference_voit_les_deux_cotes_d_un_marche():
    """Le classement ne garde qu'un côté par marché, celui au meilleur score —
    donc orienté espérance. Sur un « Moins de 5,5 » à 1.11, le côté conservé est
    le « Plus » à grosse cote, et le côté à 91 % disparaît."""
    from src.agents.quant.conversation.summary import population_de_revue

    cote_probable = _Rang(_candidat(selection="under", low=0.91, odds=1.11))
    cote_valeur = _Rang(_candidat(selection="over", low=0.05, odds=9.0))
    revue = _Revue([cote_valeur], tous_cotes=[cote_valeur, cote_probable])

    sans_preference = population_de_revue(revue, None)
    avec_preference = population_de_revue(revue, Decimal("0.90"))

    assert len(sans_preference) == 1, "le classement reste inchangé"
    assert len(avec_preference) == 2, "la préférence retrouve le côté probable"


# ══ 4 · Le vocabulaire de l'affichage ══════════════════════════════════════
def test_la_fiche_porte_tous_les_champs_demandes():
    from src.agents.quant.conversation.summary import _fiche_candidat

    texte = "\n".join(_fiche_candidat(_Rang(_candidat())))

    for attendu in ("Marché", "Sélection", "Cote", "fair", "probability_low",
                    "vig_adjusted", "Edge", "EV settlement-aware",
                    "Qualité des données", "Fraîcheur", "Modèle / capacité",
                    "Maturité", "Ce qui empêche ACTIONABLE"):
        assert attendu in texte, attendu


def test_une_grandeur_absente_ne_devient_jamais_un_zero():
    """`freshness=None` veut dire « non mesurée ». L'écrire `0` en ferait
    « périmé », qui est une autre réponse."""
    from src.agents.quant.conversation.observability import NON_MESURE
    from src.agents.quant.conversation.summary import _fiche_candidat

    candidat = _candidat(low=None, vig=None)
    texte = "\n".join(_fiche_candidat(_Rang(candidat)))

    assert NON_MESURE in texte
    assert "0.0 %" not in texte


def test_le_statut_experimental_est_dit_et_le_bloqueur_nomme():
    from src.agents.quant.conversation.summary import _fiche_candidat

    texte = "\n".join(_fiche_candidat(_Rang(_candidat())))

    assert "EXPERIMENTAL" in texte
    assert "aucune mise" in texte.lower()
    assert "m.v0" in texte, "le modèle bloqué est nommé"


# ══ 5 · Les combinés exploratoires ═════════════════════════════════════════
def test_deux_selections_du_meme_match_ne_sont_jamais_multipliees():
    """Structurellement dépendantes : leur produit supposerait une indépendance
    que rien n'établit."""
    from src.agents.quant.conversation.review_combos import construire

    rangs = [_Rang(_candidat(event="e1", selection="under",
                             parametres={"line": "2.5"})),
             _Rang(_candidat(event="e1", selection="home",
                             famille=MarketFamily.MATCH_WINNER, parametres={}))]

    combines = construire(rangs, n_legs=2)

    # Le groupement retient une seule sélection par événement : aucune paire
    # intra-match ne peut même être formée.
    assert combines == ()


def test_deux_matchs_partageant_une_equipe_donnent_not_estimated():
    from src.agents.quant.conversation.review_combos import NOT_ESTIMATED, construire

    rangs = [_Rang(_candidat(event="e1", participants=("psg", "lyon"))),
             _Rang(_candidat(event="e2", participants=("psg", "nice")))]

    combines = construire(rangs, n_legs=2)

    assert len(combines) == 1
    combo = combines[0]
    assert combo.probabilite_jointe is None
    assert combo.probabilite_lisible == NOT_ESTIMATED
    assert combo.ev_lisible == NOT_ESTIMATED
    assert "dépendance" in (combo.motif_non_estimee or "")


def test_la_cote_combinee_reste_calculable_meme_sans_probabilite():
    """La cote est une donnée OBSERVÉE : son produit ne dépend d'aucun modèle."""
    from src.agents.quant.conversation.review_combos import construire

    rangs = [_Rang(_candidat(event="e1", odds=2.0, participants=("psg", "lyon"))),
             _Rang(_candidat(event="e2", odds=3.0, participants=("psg", "nice")))]

    combo = construire(rangs, n_legs=2)[0]

    assert combo.cote_combinee == Decimal("6.00")
    assert combo.probabilite_jointe is None


def test_un_combine_independant_est_price_et_reste_experimental():
    from src.agents.quant.conversation.review_combos import construire

    rangs = [_Rang(_candidat(event="e1", odds=2.0, fair=0.5, low=0.45,
                             participants=("psg", "lyon"))),
             _Rang(_candidat(event="e2", odds=2.0, fair=0.5, low=0.45,
                             participants=("ajax", "psv")))]

    combo = construire(rangs, n_legs=2)[0]

    assert combo.probabilite_jointe == Decimal("0.25")
    assert combo.expected_value == Decimal("0.00")
    assert combo.statut == "EXPERIMENTAL"


def test_aucun_combine_ne_porte_de_mise():
    """Un combiné de revue n'est jamais transformé en ACTIONABLE : rien dans
    l'objet ne permet de le dimensionner."""
    from src.agents.quant.conversation.review_combos import ComboExploratoire

    champs = ComboExploratoire.__dataclass_fields__
    for interdit in ("stake", "mise", "kelly", "sizing", "net_profit"):
        assert interdit not in champs


# ══ 6 · Les promesses non fondées sont bloquées ════════════════════════════
@pytest.mark.parametrize("phrase", [
    "Les équipes de recherche mettent à jour les modèles chaque jour.",
    "Nos modèles sont mis à jour chaque jour.",
    "Limiter la fenêtre augmente la probabilité de trouver des paris validés.",
    "Réduire la fenêtre améliore vos chances de trouver des paris validés.",
])
def test_les_promesses_sur_le_produit_sont_bloquees(phrase):
    from src.agents.quant.conversation.guard import enforce

    verdict = enforce(phrase, None)

    assert verdict.blocked
    assert verdict.reason == "UNFOUNDED_PROCESS_CLAIM"
    assert "ledger CLV" in verdict.replacement


@pytest.mark.parametrize("phrase", [
    "Aucune mise validée actuellement.",
    "La maturité reste EXPERIMENTAL pour cette capacité.",
    "La fenêtre demandée contient 321 rencontres.",
])
def test_les_enonces_fondes_passent(phrase):
    from src.agents.quant.conversation.guard import enforce

    assert not enforce(phrase, None).blocked


# ══ 7 · L'objectif de cote / multiplicateur ════════════════════════════════
@pytest.mark.parametrize("texte, cible, basse, haute", [
    ("je veux faire x2", "2.00", "1.70", "2.30"),
    ("viser x3", "3.00", "2.55", "3.45"),
    ("autour de 2 de cote", "2.00", "1.70", "2.30"),
    ("entre 1.8 et 2.2", "2.00", "1.80", "2.20"),
    ("doubler 10 €", "2.00", "1.70", "2.30"),
    ("cote de 2,10", "2.10", "1.785", "2.415"),
    ("tripler ma mise", "3.00", "2.55", "3.45"),
])
def test_l_objectif_de_cote_est_extrait(texte, cible, basse, haute):
    from src.agents.quant.conversation.review_preference import objectif_de_cote

    o = objectif_de_cote(texte)

    assert o is not None
    assert o.target_odds == Decimal(cible)
    assert o.borne_basse == Decimal(basse)
    assert o.borne_haute == Decimal(haute)
    assert o.source_text == texte


@pytest.mark.parametrize("texte", [
    "10 € de bankroll",
    "mise 10 % de ma bankroll",
    "je mise 50 euros",
    "environ 90 % de chances",
    "",
])
def test_un_montant_ne_devient_jamais_un_objectif_de_cote(texte):
    """« doubler 10 € » vise x2, pas x10. Sans cette règle une bankroll de 10 €
    produisait un objectif de cote 10."""
    from src.agents.quant.conversation.review_preference import objectif_de_cote

    assert objectif_de_cote(texte) is None


def test_un_intervalle_explicite_prime_sur_la_tolerance_par_defaut():
    from src.agents.quant.conversation.review_preference import objectif_de_cote

    o = objectif_de_cote("entre 1.8 et 2.2")

    assert o.bornes_explicites
    assert (o.min_odds, o.max_odds) == (Decimal("1.8"), Decimal("2.2"))


def test_une_cote_inferieure_a_un_n_est_pas_un_objectif():
    from src.agents.quant.conversation.review_preference import objectif_de_cote

    assert objectif_de_cote("x0.5") is None


# ══ 8 · La cote ne rattrape jamais la probabilité ══════════════════════════
def test_les_trois_groupes_sont_disjoints_et_complets():
    from src.agents.quant.conversation.review_preference import (
        objectif_de_cote, partitionner_par_objectifs,
    )

    rangs = [
        _Rang(_candidat(event="a", low=0.95, odds=2.0)),    # A : les deux
        _Rang(_candidat(event="b", low=0.95, odds=1.1)),    # B : proba seule
        _Rang(_candidat(event="c", low=0.40, odds=2.0)),    # C : proche cote
        _Rang(_candidat(event="d", low=0.40, odds=9.0)),    # C : ni l'un ni l'autre
        _Rang(_candidat(event="e", low=None, odds=2.0)),    # sans borne basse
    ]

    p = partitionner_par_objectifs(rangs, Decimal("0.90"), objectif_de_cote("x2"))

    assert len(p.a_les_deux) == 1
    assert len(p.b_probabilite_seule) == 1
    assert len(p.c_sous_le_seuil) == 2
    assert len(p.sans_borne_basse) == 1
    assert p.total == 5, "aucun candidat n'est perdu"
    assert len(p.c_proches_de_la_cote) == 1


def test_un_candidat_sous_le_seuil_ne_remonte_jamais_dans_le_groupe_a():
    """« Ne cherche pas une grosse cote en abaissant silencieusement la
    probabilité » : un candidat pile sur la cible mais sous le seuil reste en C."""
    from src.agents.quant.conversation.review_preference import (
        objectif_de_cote, partitionner_par_objectifs,
    )

    rangs = [_Rang(_candidat(low=0.5, odds=2.0))]

    p = partitionner_par_objectifs(rangs, Decimal("0.90"), objectif_de_cote("x2"))

    assert p.a_les_deux == ()
    assert len(p.c_sous_le_seuil) == 1


def test_le_groupe_c_est_ordonne_par_proximite_a_la_cible():
    from src.agents.quant.conversation.review_preference import (
        objectif_de_cote, partitionner_par_objectifs,
    )

    rangs = [_Rang(_candidat(event="loin", low=0.3, odds=5.0)),
             _Rang(_candidat(event="pres", low=0.3, odds=2.05)),
             _Rang(_candidat(event="moyen", low=0.3, odds=3.0))]

    p = partitionner_par_objectifs(rangs, Decimal("0.90"), objectif_de_cote("x2"))

    assert [r.candidate.event_id for r in p.c_sous_le_seuil] == ["pres", "moyen", "loin"]


def test_l_incompatibilite_mathematique_est_dite_explicitement():
    from src.agents.quant.conversation.review_preference import objectif_de_cote
    from src.agents.quant.conversation.summary import render_marches_en_revue

    # Probabilité haute mais cote basse : les deux critères s'excluent.
    revue = _Revue([_Rang(_candidat(low=0.95, odds=1.1))])

    texte = "\n".join(render_marches_en_revue(
        revue, cible=Decimal("0.90"), objectif=objectif_de_cote("x2")))

    assert "Aucun candidat ne satisfait simultanément ces deux critères." in texte
    assert "respecte 90 %, mais cote hors objectif" in texte
    assert "proche de l'objectif de cote, mais sous 90 %" in texte


# ══ 9 · Combinés autour de la cible ════════════════════════════════════════
def test_les_combines_sont_ordonnes_par_proximite_a_la_cible():
    from src.agents.quant.conversation.review_combos import construire
    from src.agents.quant.conversation.review_preference import objectif_de_cote

    rangs = [_Rang(_candidat(event="a", odds=1.4, participants=("a1", "a2"))),
             _Rang(_candidat(event="b", odds=1.43, participants=("b1", "b2"))),
             _Rang(_candidat(event="c", odds=4.0, participants=("c1", "c2")))]

    combos = construire(rangs, top=3, objectif=objectif_de_cote("x2"))

    ecarts = [abs(c.cote_combinee - Decimal("2.0")) for c in combos]
    assert ecarts == sorted(ecarts)


def test_un_leg_sans_grandeur_mesuree_n_entre_dans_aucun_combine():
    """Les filtres de sécurité passent AVANT la recherche de proximité."""
    from src.agents.quant.conversation.review_combos import construire
    from src.agents.quant.conversation.review_preference import objectif_de_cote

    rangs = [_Rang(_candidat(event="a", odds=1.41, participants=("a1", "a2"))),
             _Rang(_candidat(event="b", odds=1.42, participants=("b1", "b2")))]
    # La qualité de `b` n'est pas mesurée : il est écarté malgré une cote idéale.
    object.__setattr__(rangs[1].candidate, "data_quality", None)

    assert construire(rangs, top=3, objectif=objectif_de_cote("x2")) == ()


def test_deux_jambes_de_meme_origine_ne_sont_jamais_multipliees():
    """Deux marchés tirés de la MÊME loi jointe sont corrélés, même si leurs
    identités diffèrent — la classification structurelle ne peut pas le voir."""
    from src.agents.quant.conversation.review_combos import (
        CORRELATED_SAME_ORIGIN, NOT_ESTIMATED, construire,
    )

    a = _candidat(event="a", participants=("a1", "a2"))
    b = _candidat(event="b", participants=("b1", "b2"))
    object.__setattr__(a, "probability_origin", "dixon_coles:matrice:X")
    object.__setattr__(b, "probability_origin", "dixon_coles:matrice:X")

    combo = construire([_Rang(a), _Rang(b)], top=1)[0]

    assert combo.dependance == CORRELATED_SAME_ORIGIN
    assert combo.probabilite_jointe is None
    assert combo.probabilite_lisible == NOT_ESTIMATED
    assert combo.ev_lisible == NOT_ESTIMATED


# ══ 10 · Jamais « sûr à 90 % » ═════════════════════════════════════════════
@pytest.mark.parametrize("phrase", [
    "Ce pari est sûr à 90 %.",
    "90 % certain de passer.",
    "Une certitude de 90 % sur ce marché.",
    "garanti à 95 %",
])
def test_une_probabilite_prudente_n_est_jamais_presentee_comme_une_certitude(phrase):
    from src.agents.quant.conversation.guard import enforce

    verdict = enforce(phrase, None)

    assert verdict.blocked
    assert verdict.reason == "MISLEADING_LANGUAGE"


@pytest.mark.parametrize("phrase", [
    "Probabilité prudente estimée à 91,00 %.",
    "La borne basse mesurée atteint 90 %.",
    "Probabilité du modèle (fair) : 93.03 %",
])
def test_le_vocabulaire_prudent_reste_autorise(phrase):
    from src.agents.quant.conversation.guard import enforce

    assert not enforce(phrase, None).blocked


def test_le_rendu_ne_promet_jamais_de_certitude():
    from src.agents.quant.conversation.guard import enforce
    from src.agents.quant.conversation.summary import _fiche_candidat

    texte = "\n".join(_fiche_candidat(_Rang(_candidat(low=0.95))))

    assert not enforce(texte, None).blocked
    assert "prudente" in texte or "basse mesurée" in texte


# ══ 11 · Le seuil ne s'invente pas, et se laisse changer ═══════════════════
#
# Trois défauts relevés sur de vrais runs, chacun ancré ici :
#   · l'utilisateur demande 80 %, le moteur continue d'annoncer 90 % ;
#   · l'utilisateur ne demande AUCUN seuil, le moteur en pose un à 90 % ;
#   · l'utilisateur veut « des paris sûrs », le moteur répond « aucun pari »
#     au lieu de classer par probabilité décroissante.
@pytest.mark.parametrize("texte, attendu", [
    ("80%", Decimal("0.80")),
    ("≥ 80 %", Decimal("0.80")),
    (">=80%", Decimal("0.80")),
    ("80", Decimal("0.80")),
    ("environ 85 %", Decimal("0.85")),
])
def test_une_reponse_qui_ne_porte_que_le_seuil_est_lue(texte, attendu):
    """Elle vient d'une question fermée : le mot « probabilité » est déjà dans
    la question. La refuser laissait le seuil PRÉCÉDENT en place."""
    assert cible_depuis_texte(texte) == attendu


@pytest.mark.parametrize("texte", [
    "pas de seuil en tant que tel, juste des paris quasi sûrs de passer",
    "aucun seuil",
    "sans seuil",
    "peu importe le seuil",
])
def test_un_refus_de_seuil_est_une_instruction_pas_un_silence(texte):
    from src.agents.quant.conversation.review_preference import SANS_SEUIL

    assert cible_depuis_texte(texte) == SANS_SEUIL


def test_un_refus_de_seuil_efface_le_seuil_precedent():
    """« Rien dit » hérite du tour précédent ; « pas de seuil » l'EFFACE. Les
    confondre laissait le moteur exiger 90 % après que l'utilisateur l'ait retiré."""
    from src.agents.quant.conversation.constraints import (
        EFFACER, UserBettingConstraints, merge_constraints,
    )

    avant = UserBettingConstraints(probability_target=Decimal("0.90"))

    rien_dit = merge_constraints(avant, probability_target=None)
    efface = merge_constraints(avant, probability_target=EFFACER)

    assert rien_dit.probability_target == Decimal("0.90"), "l'héritage est conservé"
    assert efface.probability_target is None, "le refus retire la contrainte"


def test_sans_seuil_le_produit_classe_par_probabilite_decroissante():
    """« Des paris quasi sûrs, autour de x2 » admet une réponse : les plus
    probables parmi ceux qui respectent la cote. Inventer un seuil à la place
    fait répondre « aucun pari » à une question qui n'en demandait pas tant."""
    from src.agents.quant.conversation.review_preference import (
        les_plus_probables, objectif_de_cote,
    )

    rangs = [_Rang(_candidat(event="a", low=0.40, odds=2.0)),
             _Rang(_candidat(event="b", low=0.75, odds=2.1)),
             _Rang(_candidat(event="c", low=0.60, odds=1.9)),
             _Rang(_candidat(event="d", low=0.99, odds=9.0))]   # hors fourchette

    ordonnes = les_plus_probables(rangs, objectif_de_cote("x2"))

    assert [r.candidate.event_id for r in ordonnes] == ["b", "c", "a"], (
        "les plus probables d'abord, et seulement dans la fourchette de cote")


def test_une_borne_basse_absente_ne_passe_pas_devant_une_mesuree():
    from src.agents.quant.conversation.review_preference import les_plus_probables

    rangs = [_Rang(_candidat(event="sans", low=None, odds=2.0)),
             _Rang(_candidat(event="avec", low=0.30, odds=2.0))]

    ordonnes = les_plus_probables(rangs)

    assert [r.candidate.event_id for r in ordonnes] == ["avec", "sans"]


def test_le_rendu_sans_seuil_ne_mentionne_aucun_seuil_impose():
    from src.agents.quant.conversation.review_preference import objectif_de_cote
    from src.agents.quant.conversation.summary import render_marches_en_revue

    revue = _Revue([_Rang(_candidat(event=f"e{i}", low=0.4 + i / 10, odds=2.0))
                    for i in range(3)])

    texte = "\n".join(render_marches_en_revue(
        revue, cible=None, objectif=objectif_de_cote("x2")))

    assert "plus probables" in texte.lower()
    assert "Aucun seuil de probabilité n'a été demandé" in texte
    assert "90 %" not in texte, "aucun seuil ne doit être inventé"


# ══ 12 · Les conseils relevés sur de vrais runs sont refusés ═══════════════
@pytest.mark.parametrize("phrase", [
    "Allonger la fenêtre temporelle (par ex. inclure les prochains jours) peut "
    "faire apparaître de nouveaux événements.",
    "les rapports de maturité sont publiés quotidiennement",
    "Augmenter le bankroll : avec plus de capital, le moteur pourra proposer des "
    "combinaisons.",
    "Surveiller les mises à jour du moteur",
    "dès qu'un des modèles passera le seuil de maturité, elles deviendront misables",
    "Abaisser la probabilité cible (ex. 80 %) permettrait de récupérer des sélections.",
    "Élargir la fourchette de cote peut faire apparaître de nouvelles opportunités.",
])
def test_les_conseils_infondes_releves_en_production_sont_bloques(phrase):
    """Aucune de ces phrases n'est vraie : la bankroll n'entre dans aucun critère
    d'éligibilité, aucun rapport n'est publié quotidiennement, allonger la fenêtre
    ajoute des candidats tous EXPERIMENTAL, et abaisser un seuil n'a jamais été
    nécessaire pour VOIR des candidats — le rendu les montre déjà."""
    from src.agents.quant.conversation.guard import enforce

    assert enforce(phrase, None).blocked
