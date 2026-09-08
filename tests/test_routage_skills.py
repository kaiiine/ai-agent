"""Le catalogue des skills était dans la description de `load_skill`.

49 entrées, 2 241 tokens, à chaque tour où l'outil est lié. C'est l'inverse de ce
que la refonte du routage a fait pour les outils — et devant une liste pareille,
le modèle n'en choisissait aucune : trop de choix se comporte comme pas de choix.

Le classement est HYBRIDE, et l'ordre vient d'une mesure sur vingt requêtes dont
on connaît la bonne réponse :

    dense seul                  rappel@1 55 %   rappel@3 65 %   rappel@5 95 %
    dense + pont linguistique   rappel@1 55 %   rappel@3 70 %   rappel@5 95 %
    lexical puis dense          rappel@1 75 %   rappel@3 80 %   rappel@5 95 %

Le pont linguistique n'apporte presque rien : la langue n'était pas la cause.
`fiche` et `exo` disent « HTML/CSS » et « HTML/JS », ce qui les rapproche de
toute requête web — la largeur d'un document achète de la proximité avec tout.
Ce qui débloque, ce sont les alias curés à la main.
"""
from __future__ import annotations

import pytest

from src.skills import skills_pertinentes
from src.skills.tools import BUDGET_SKILLS, make_load_skill


# ── le classement ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("requete, attendue", [
    ("fais-moi un site vitrine en Next.js",                "nextjs"),
    ("rends ce composant accessible aux lecteurs d'écran", "a11y-architect"),
    ("améliore le référencement de ma page",               "seo-specialist"),
    ("mon projet Rust ne compile pas",                     "rust-build-resolver"),
])
def test_une_requete_qui_nomme_son_domaine_elit_sa_skill(requete, attendue):
    """Le levier qui a le mieux payé : les alias. Sans eux, ces quatre requêtes
    rendaient `fiche`, `exo` et `browser-driving`."""
    assert attendue in skills_pertinentes(requete, "coding", BUDGET_SKILLS)


def test_le_cas_vecu_des_tests_python():
    """« il ne prenait aucune skill quand je lançais les tests avec python »."""
    retenues = skills_pertinentes("lance les tests python de ce projet", "coding")

    assert "python" in retenues or "python-reviewer" in retenues


def test_le_budget_est_respecte():
    retenues = skills_pertinentes("fais-moi un site en Next.js", "coding")

    assert 0 < len(retenues) <= BUDGET_SKILLS


def test_cinq_candidats_pas_trois():
    """Mesuré : 80 % de rappel à 3, 95 % à 5, et plus rien au-delà."""
    assert BUDGET_SKILLS == 5


def test_une_portee_inconnue_ne_leve_pas():
    """La complétion et le routage tournent à chaque tour : rien ne doit lever."""
    assert skills_pertinentes("n'importe quoi", "portee-inexistante") == []


# ── le catalogue montré ───────────────────────────────────────────────────────
def _catalogue(outil) -> list[str]:
    corps = outil.description.split("Available skills:")[1]
    return [l.strip().split(":")[0].lstrip("- ").strip()
            for l in corps.splitlines() if l.strip().startswith("-")]


def test_le_catalogue_se_restreint_a_la_requete():
    large = make_load_skill("coding")
    etroit = make_load_skill("coding", "fais-moi un site vitrine en Next.js")

    assert len(_catalogue(etroit)) <= BUDGET_SKILLS < len(_catalogue(large))
    assert "nextjs" in _catalogue(etroit)


def test_la_restriction_divise_le_cout():
    large = make_load_skill("coding")
    etroit = make_load_skill("coding", "un site en Next.js")

    assert len(etroit.description) < len(large.description) / 3


def test_sans_requete_on_montre_tout():
    """Au démarrage, aucune question n'est posée : mieux vaut un catalogue large
    qu'un catalogue deviné."""
    assert len(_catalogue(make_load_skill("coding", "   "))) > BUDGET_SKILLS


def test_le_preambule_survit_a_la_restriction():
    """La consigne de composition n'est pas dans le catalogue : elle doit rester."""
    etroit = make_load_skill("coding", "un site en Next.js")

    assert "COMPOSE" in etroit.description
    assert "once per skill" in etroit.description


# ── le branchement ────────────────────────────────────────────────────────────
def test_seul_load_skill_est_remplace():
    from src.orchestrator.graph import _restreindre_les_skills

    class _Autre:
        name = "shell_run"

    autre = _Autre()
    rendus = _restreindre_les_skills([autre, make_load_skill("coding")],
                                     "un site en Next.js", "coding")

    assert rendus[0] is autre
    assert len(rendus[1].description) < 3_000


def test_une_liste_sans_load_skill_est_rendue_telle_quelle():
    from src.orchestrator.graph import _restreindre_les_skills

    class _Autre:
        name = "shell_run"

    outils = [_Autre()]

    assert _restreindre_les_skills(outils, "un site en Next.js", "coding") is outils


# ── `aliases:` désigne, `lexique:` déclenche ──────────────────────────────────
# Le vocabulaire déclencheur a d'abord été mis dans `aliases:` — donc INDEXÉ.
# Sept tournures françaises ont suffi à faire de `silent-failure-hunter` le
# document le plus proche de « refais le design de mon site » et de « un serveur
# en Go » : le volume achète de la proximité avec tout, ce qui avait déjà fait
# refuser les ancres dans `_document`. Mesuré, puis séparé.
def test_le_lexique_nentre_pas_dans_lindex():
    from src.skills.retriever import _document, _retriever

    _retriever._load()
    doc = _document("silent-failure-hunter", _retriever._skills["silent-failure-hunter"])

    assert "echec silencieux" not in doc.lower()


def test_le_lexique_ouvre_bien_la_porte_lexicale():
    from src.skills.retriever import _retriever, termes_identifiants

    _retriever._load()
    termes = termes_identifiants("silent-failure-hunter",
                                 _retriever._skills["silent-failure-hunter"])

    assert "echec silencieux" in termes


def test_une_demande_de_design_reste_au_bon_skill():
    """La régression exacte : `silent-failure-hunter` passait devant."""
    retenues = skills_pertinentes("refais le design de mon site", "coding")

    assert retenues and retenues[0] == "apple-design"


def test_un_serveur_en_go_ne_reveille_pas_le_chasseur_derreurs():
    retenues = skills_pertinentes("un serveur en Go", "coding")

    assert "silent-failure-hunter" not in retenues[:2]


# ── l'ordre du classement hybride ─────────────────────────────────────────────
def test_le_dense_mene_le_classement():
    """Les alias étaient placés DEVANT le classement dense. Refait sur les deux
    jeux de référence, l'ordre s'inverse : 18/22 contre 11/22 au rang 1, et
    strictement rien de gagné au top 5 — la seule métrique que voit le modèle,
    puisque le catalogue en montre cinq.

    Ils sont déjà dans le document indexé ; les remettre devant, c'est les
    compter deux fois."""
    from src.skills.retriever import _retriever

    _retriever._build_index()
    visible = _retriever._visible("coding")
    requete = "crée une API FastAPI"

    trouves = _retriever._index.similarity_search(requete, k=max(20, len(_retriever._skills)))
    dense = [t.metadata["name"] for t in trouves if t.metadata.get("name") in visible]

    assert skills_pertinentes(requete, "coding")[0] == dense[0]


def test_un_skill_nomme_mais_absent_du_dense_entre_quand_meme():
    """Le lexical reste un FILET : il ajoute, il ne déplace plus."""
    from src.skills.retriever import _retriever, termes_identifiants

    _retriever._load()
    visible = _retriever._visible("coding")
    nomme = next(n for n in visible if "nextjs" in n)
    terme = next(iter(termes_identifiants(nomme, visible[nomme]) - {nomme}), nomme)

    assert nomme in skills_pertinentes(f"aide-moi avec {terme}", "coding")


def test_lecart_entre_les_deux_jeux_est_documente():
    """Il vaut 20,5 points AVANT comme APRÈS le changement d'ordre : il ne venait
    pas des alias. Ce test fige le constat pour qu'une future « correction » du
    classement ne soit pas créditée de l'avoir comblé."""
    from tests.corpus_routage_skills import REGLAGE, TENU_A_L_ECART

    def top5(jeu):
        return sum(a in skills_pertinentes(q, "coding", 5) for q, a in jeu) / len(jeu)

    assert top5(REGLAGE) - top5(TENU_A_L_ECART) > 0.10
