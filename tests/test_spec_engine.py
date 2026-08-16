"""Le moteur de spécification : poser les bonnes questions, refuser les mauvaises specs.

Le générateur précédent posait CINQ questions fixes, écrites pour des projets web
créatifs. Il demandait une palette de couleurs à un pipeline de données et ne lui
demandait jamais sa politique de reprise — le défaut n'était pas le nombre de
questions, c'était qu'elles venaient du template et non du projet.

Ces tests portent quatre garanties :

1. les catégories dépendent de la NATURE du projet, et le socle ne peut pas
   étouffer les catégories propres au profil ;
2. une catégorie déjà tranchée par le descriptif ne produit aucune question ;
3. l'analyse d'une spec est DÉTERMINISTE — aucun appel de modèle, deux passes
   rendent la même liste ;
4. une spec correcte ne remonte AUCUN constat : un vérificateur qui crie sur du
   bon travail est un vérificateur qu'on désactive.
"""

from __future__ import annotations

import pytest

from src.agents.spec.analyze import CRITIQUE, analyser, bloquant, resume
from src.agents.spec.coverage import Lecture, a_demander, scanner
from src.agents.spec.taxonomy import (
    LIBELLES_PROFIL, PROFILS, SOCLE, categories_du_profil,
)


class _LLMMuet:
    """Aucun réseau. Le repli prudent doit tout classer ABSENT."""

    def invoke(self, _messages):
        raise RuntimeError("hors ligne")


class _LLMScripte:
    """Rend une carte de couverture décidée par le test."""

    def __init__(self, carte: dict):
        self._carte = carte

    def invoke(self, _messages):
        import json

        class _R:
            content = json.dumps({"categories": self._carte})
        return _R()


# ══ 1 · Les catégories viennent du projet ═════════════════════════════════
def test_le_socle_vaut_pour_tout_projet():
    for profil in LIBELLES_PROFIL:
        ids = {c.id for c in categories_du_profil(profil)}
        assert {c.id for c in SOCLE} <= ids, profil


@pytest.mark.parametrize("profil, attendu", [
    ("pipeline_donnees", "reprise"),
    ("cli", "ergonomie_cli"),
    ("api_service", "contrat_api"),
    ("site_web", "direction_artistique"),
    ("mobile", "hors_ligne"),
])
def test_chaque_profil_apporte_ses_propres_categories(profil, attendu):
    ids = {c.id for c in categories_du_profil(profil)}

    assert attendu in ids


def test_un_pipeline_ne_se_voit_jamais_demander_une_palette():
    """Le défaut d'origine, en un test."""
    ids = {c.id for c in categories_du_profil("pipeline_donnees")}

    assert "systeme_visuel" not in ids
    assert "direction_artistique" not in ids


def test_le_profil_generique_ne_pose_que_le_socle():
    """Quand la nature du projet n'est pas sûre, poser des questions hors sujet
    coûte plus cher que de n'en poser aucune."""
    assert categories_du_profil("generique") == SOCLE


def test_tout_profil_declare_est_libelle():
    """Un profil sans libellé serait choisissable sans être compréhensible."""
    assert set(PROFILS) <= set(LIBELLES_PROFIL)


@pytest.mark.parametrize("categorie", SOCLE)
def test_chaque_categorie_dit_pourquoi_elle_compte(categorie):
    """Le « pourquoi » n'est pas décoratif : il est donné au modèle qui rédige
    la question. Sans lui, la question produite est polie et sans conséquence."""
    assert categorie.pourquoi.strip()
    assert categorie.couvre
    assert 1 <= categorie.impact <= 3


# ══ 2 · La priorisation ═══════════════════════════════════════════════════
def test_sans_modele_tout_est_absent():
    """Le repli prudent : on redemandera des choses déjà dites plutôt que
    d'oublier une question décisive."""
    lectures = scanner("peu importe", "cli", _LLMMuet())

    assert lectures
    assert all(l.statut == "ABSENT" for l in lectures)


def test_une_categorie_claire_ne_produit_aucune_question():
    carte = {c.id: {"statut": "CLAIR"} for c in categories_du_profil("cli")}
    lectures = scanner("descriptif complet", "cli", _LLMScripte(carte))

    assert a_demander(lectures) == ()


def test_l_ordre_suit_impact_fois_incertitude():
    fort_absent = Lecture(_cat("objectif"), "ABSENT")      # 3 × 2 = 6
    fort_partiel = Lecture(_cat("donnees"), "PARTIEL")     # 3 × 1 = 3
    faible_absent = Lecture(_cat("parcours"), "ABSENT")    # 2 × 2 = 4

    ordre = a_demander((fort_partiel, faible_absent, fort_absent))

    assert [l.priorite for l in ordre] == [6, 4, 3]


def _cat(id):
    return next(c for c in SOCLE if c.id == id)


def test_le_socle_ne_peut_pas_etouffer_les_categories_du_profil():
    """Sur un pipeline, quatre catégories de socle à priorité 6 remplissaient le
    budget et « Idempotence & reprise » — ce qui décide du comportement au
    redémarrage — n'était jamais posée. C'est le travers que ce module corrige,
    reproduit un cran plus bas."""
    carte = {c.id: {"statut": "ABSENT"} for c in categories_du_profil("pipeline_donnees")}
    lectures = scanner("x", "pipeline_donnees", _LLMScripte(carte))

    demandees = {l.categorie.id for l in a_demander(lectures)}
    propres = {c.id for c in PROFILS["pipeline_donnees"]}

    assert propres <= demandees, "les catégories du profil doivent toutes passer"


def test_une_question_decisive_ne_cede_pas_sa_place_a_l_alternance():
    """L'alternance départage à priorité ÉGALE. Elle ne doit jamais faire passer
    une question mineure devant une question décisive."""
    carte = {c.id: {"statut": "ABSENT"} for c in categories_du_profil("cli")}
    carte["objectif"] = {"statut": "ABSENT"}          # socle, impact 3 -> 6
    carte["sorties"] = {"statut": "CLAIR"}            # profil, écarté
    lectures = scanner("x", "cli", _LLMScripte(carte))

    premiers = [l.priorite for l in a_demander(lectures)]

    assert premiers == sorted(premiers, reverse=True)


def test_l_ordre_est_reproductible():
    carte = {c.id: {"statut": "PARTIEL"} for c in categories_du_profil("site_web")}
    lectures = scanner("x", "site_web", _LLMScripte(carte))

    premier = [l.categorie.id for l in a_demander(lectures)]
    second = [l.categorie.id for l in a_demander(lectures)]

    assert premier == second


def test_le_budget_est_respecte():
    carte = {c.id: {"statut": "ABSENT"} for c in categories_du_profil("site_web")}
    lectures = scanner("x", "site_web", _LLMScripte(carte))

    assert len(a_demander(lectures, budget=3)) == 3


# ══ 3 · L'analyse est déterministe ════════════════════════════════════════
_BONNE = """\
# Gestionnaire

## Périmètre
### Dans la v1
- Créer et clôturer une tâche

### HORS périmètre v1
- Notifications e-mail : coût disproportionné pour la v1

## Histoires utilisateur

### P1 — Créer une tâche
Un membre crée une tâche.

**Livrable seul** : l'équipe peut suivre son travail.

**Critères d'acceptation**
1. **Étant donné** une liste vide, **quand** je crée une tâche,
   **alors** elle apparaît avec le statut « à faire »

## Exigences fonctionnelles
- **EF-001** : Une tâche porte un titre et un statut

## Contraintes techniques
- Next.js 15 + PostgreSQL sur Vercel

## Definition of Done
- L'histoire P1 passe ses critères
"""


def test_une_spec_correcte_ne_remonte_aucun_constat():
    """Un vérificateur qui crie sur du bon travail est un vérificateur qu'on
    désactive."""
    constats = analyser(_BONNE)

    assert constats == [], [str(c) for c in constats]
    assert not bloquant(constats)
    assert "aucun constat" in resume(constats)


def test_l_analyse_ne_depend_d_aucun_modele():
    """Aucun appel réseau : on ne demande pas à un LLM si le texte qu'il vient
    d'écrire est bon."""
    import inspect

    from src.agents.spec import analyze

    source = inspect.getsource(analyze)
    for interdit in ("invoke", "SystemMessage", "llm", "openai"):
        assert interdit not in source


def test_deux_analyses_rendent_la_meme_liste():
    assert [str(c) for c in analyser(_BONNE)] == [str(c) for c in analyser(_BONNE)]


@pytest.mark.parametrize("fragment, categorie", [
    ("- Base de données : à définir", "non-tranché"),
    ("- Framework : React ou bien Vue", "non-tranché"),
    ("- Stack : Next.js, selon les besoins", "non-tranché"),
])
def test_une_decision_annoncee_mais_non_prise_est_signalee(fragment, categorie):
    constats = analyser(_BONNE.replace("- Next.js 15 + PostgreSQL sur Vercel", fragment))

    assert any(c.categorie == categorie for c in constats)


def test_un_gabarit_laisse_en_place_est_critique():
    constats = analyser(_BONNE.replace("### P1 — Créer une tâche",
                                       "### P1 — [titre court]"))

    assert any(c.severite == CRITIQUE and c.categorie == "gabarit" for c in constats)


def test_une_ligne_entierement_en_gabarit_est_detectee_meme_en_majuscule():
    constats = analyser(_BONNE.replace("Un membre crée une tâche.",
                                       "[Le parcours en langage courant]"))

    assert any(c.categorie == "gabarit" for c in constats)


def test_un_adjectif_sans_chiffre_est_intestable():
    constats = analyser(_BONNE.replace("- **EF-001** : Une tâche porte un titre et un statut",
                                       "- **EF-001** : Le système doit être performant"))

    assert any(c.categorie == "non-mesurable" for c in constats)


def test_l_identifiant_d_exigence_ne_compte_pas_comme_une_quantification():
    """« EF-002 » contient trois chiffres. Les compter faisait passer
    « le système doit être performant » pour une exigence mesurée."""
    constats = analyser(_BONNE.replace("- **EF-001** : Une tâche porte un titre et un statut",
                                       "- **EF-001** : Une interface intuitive"))

    assert any(c.categorie == "non-mesurable" for c in constats)


def test_un_critere_replie_sur_plusieurs_lignes_reste_valide():
    """Un critère long est replié par n'importe quel formateur markdown. Sans
    lecture multiligne, la spec la mieux écrite se voyait reprocher son absence."""
    constats = analyser(_BONNE)

    assert not any(c.categorie == "critères" for c in constats)


def test_une_histoire_sans_critere_bloque():
    sans = _BONNE.split("**Critères d'acceptation**")[0] + "\n## Exigences fonctionnelles\n"
    constats = analyser(sans)

    assert bloquant(constats)
    assert any(c.categorie == "critères" for c in constats)


def test_un_hors_perimetre_vide_est_signale():
    constats = analyser(_BONNE.replace(
        "- Notifications e-mail : coût disproportionné pour la v1", ""))

    assert any(c.categorie == "périmètre" for c in constats)


def test_un_identifiant_d_exigence_duplique_est_signale():
    constats = analyser(_BONNE.replace(
        "- **EF-001** : Une tâche porte un titre et un statut",
        "- **EF-001** : Une tâche porte un titre\n- **EF-001** : Une tâche a un statut"))

    assert any(c.categorie == "doublon" for c in constats)


def test_une_section_structurante_absente_est_critique():
    constats = analyser(_BONNE.replace("## Contraintes techniques", "## Divers"))

    assert any(c.severite == CRITIQUE and c.categorie == "section-absente"
               for c in constats)


# ══ 4 · Le gabarit de spec ════════════════════════════════════════════════
def test_le_gabarit_impose_des_tranches_priorisees():
    from src.agents.spec.template import structure_pour

    for profil in LIBELLES_PROFIL:
        plan = structure_pour(profil)
        assert "### P1" in plan and "### P2" in plan, profil
        assert "Livrable seul" in plan, profil
        assert "Étant donné" in plan, profil


def test_le_gabarit_impose_un_hors_perimetre():
    from src.agents.spec.template import structure_pour

    assert "HORS périmètre" in structure_pour("generique")


def test_les_profils_visuels_placent_la_direction_artistique_avant_les_histoires():
    """Elle conditionne la façon de les écrire."""
    from src.agents.spec.template import structure_pour

    plan = structure_pour("site_web")

    assert plan.index("Direction artistique") < plan.index("Histoires utilisateur")


def test_le_journal_des_clarifications_reproduit_les_reponses_telles_quelles():
    """Une décision arbitrée en trente secondes devient sinon une ligne dont
    personne ne sait si elle a été choisie ou subie."""
    from src.agents.spec.template import journal_des_clarifications

    texte = journal_des_clarifications([
        {"q": "Quelle base ?", "a": "PostgreSQL"},
    ])

    assert "Quelle base ?" in texte
    assert "PostgreSQL" in texte


def test_un_journal_vide_n_ajoute_aucune_section():
    from src.agents.spec.template import journal_des_clarifications

    assert journal_des_clarifications([]) == ""


# ══ 5 · Ne pas crier sur du bon travail ═══════════════════════════════════
#
# Quatre faux positifs relevés sur une VRAIE spec générée (axon-landing). Les
# six constats du fichier étaient tous faux : aucun ne portait sur une promesse.
# Un vérificateur bruyant est un vérificateur qu'on désactive, donc chacun est
# ancré ici.
def test_un_mot_cite_n_est_pas_un_mot_laisse():
    """« aucune règle "TODO" dans le code » est un critère de fini valide."""
    spec = _BONNE.replace(
        "- L'histoire P1 passe ses critères",
        '- Aucune règle "TODO" ne subsiste dans le code')

    constats = analyser(spec)

    assert not any(c.categorie == "non-tranché" for c in constats)


def test_le_recit_d_une_histoire_peut_employer_un_adjectif():
    """Le récit EXPLIQUE ; ce qui engage, ce sont les critères d'acceptation —
    et ceux-là sont vérifiés séparément."""
    spec = _BONNE.replace(
        "Un membre crée une tâche.",
        "Un membre crée une tâche, ce qui rend la lecture fluide et moderne.")

    constats = analyser(spec)

    assert not any(c.categorie == "non-mesurable" for c in constats)


def test_la_justification_d_un_choix_technique_n_est_pas_une_exigence():
    """« HMR rapide en dev, build optimisé » est la colonne « pourquoi ce
    choix » d'un tableau de stack, pas une promesse de performance."""
    spec = _BONNE.replace(
        "- Next.js 15 + PostgreSQL sur Vercel",
        "| **Bundler** | **Vite** | HMR rapide en dev, build optimisé. |")

    constats = analyser(spec)

    assert not any(c.categorie == "non-mesurable" for c in constats)


def test_une_alternative_rejetee_peut_etre_justifiee_en_prose():
    spec = _BONNE.replace(
        "- Next.js 15 + PostgreSQL sur Vercel",
        "- Next.js 15 + PostgreSQL sur Vercel\n"
        "- *Gatsby* – trop lourd pour un simple site one-page.")

    constats = analyser(spec)

    assert not any(c.categorie == "non-mesurable" for c in constats)


def test_mais_une_exigence_floue_reste_signalee():
    """La contrepartie : restreindre le contrôle aux sections engageantes ne
    doit pas le rendre inoffensif là où il compte."""
    spec = _BONNE.replace(
        "- **EF-001** : Une tâche porte un titre et un statut",
        "- **EF-001** : L'affichage doit être rapide")

    constats = analyser(spec)

    assert any(c.categorie == "non-mesurable" for c in constats)


def test_une_definition_of_done_floue_reste_signalee():
    spec = _BONNE.replace("- L'histoire P1 passe ses critères",
                          "- L'application est robuste")

    constats = analyser(spec)

    assert any(c.categorie == "non-mesurable" for c in constats)


# ══ 6 · La relecture sémantique ═══════════════════════════════════════════
#
# Six défauts relevés par une relecture humaine sur une vraie spec, dont aucun
# n'a de forme détectable : deux contradictions internes, deux combinaisons
# techniques impossibles, deux cibles chiffrées arbitraires. Ils demandent du
# SENS. La contrepartie est qu'un modèle peut en inventer — d'où le contrat de
# citation, qui est ce que ces tests protègent.
class _LLMConstats:
    def __init__(self, charge):
        self._charge = charge

    def invoke(self, _messages):
        import json

        class _R:
            content = json.dumps(self._charge)
        return _R()


_SPEC_COURTE = """\
# Projet
- **EF-001** : Le site est généré statiquement via **Next.js**
- **EF-002** : L'interface est en français + anglais
- Aucun i18n — texte en anglais uniquement
"""


def _constat(**kw):
    base = {"famille": "IMPOSSIBLE", "severite": "HAUTE",
            "citation": "Le site est généré statiquement via Next.js",
            "citation_opposee": "", "probleme": "x", "correction": "y"}
    base.update(kw)
    return {"constats": [base]}


def test_une_citation_absente_du_fichier_fait_rejeter_le_constat():
    """Un modèle qui hallucine produit ZÉRO constat, pas un faux constat. C'est
    la seule façon de faire confiance à une relecture automatique."""
    from src.agents.spec.review import relire

    llm = _LLMConstats(_constat(citation="Une phrase qui n'existe nulle part ici"))

    assert relire(_SPEC_COURTE, llm) == []


def test_une_citation_sans_son_emphase_markdown_reste_reconnue():
    """Le modèle cite le TEXTE qu'il lit ; le fichier porte des astérisques.
    Exiger la décoration faisait rejeter une contradiction réelle."""
    from src.agents.spec.review import relire

    llm = _LLMConstats(_constat())
    constats = relire(_SPEC_COURTE, llm)

    assert len(constats) == 1
    assert constats[0].ligne == 2


def test_une_contradiction_sans_ses_deux_bords_est_rejetee():
    """Une contradiction dont un seul côté est cité n'est qu'une opinion."""
    from src.agents.spec.review import relire

    llm = _LLMConstats(_constat(famille="CONTRADICTION", citation_opposee=""))

    assert relire(_SPEC_COURTE, llm) == []


def test_une_contradiction_avec_ses_deux_bords_est_retenue():
    from src.agents.spec.review import relire

    llm = _LLMConstats(_constat(
        famille="CONTRADICTION",
        citation="L'interface est en français + anglais",
        citation_opposee="Aucun i18n — texte en anglais uniquement"))

    constats = relire(_SPEC_COURTE, llm)

    assert len(constats) == 1
    assert constats[0].ligne_opposee == 4


def test_une_panne_de_modele_ne_valide_pas_la_spec():
    """La relecture sémantique est un BONUS au-dessus des contrôles
    déterministes, jamais leur remplacement."""
    from src.agents.spec.review import relire

    assert relire(_SPEC_COURTE, _LLMMuet()) == []


def test_les_deux_passes_se_fusionnent_par_gravite():
    from src.agents.spec.review import fusionner, relire

    llm = _LLMConstats(_constat(severite="CRITIQUE"))
    fusion = fusionner(analyser(_BONNE), relire(_SPEC_COURTE, llm))

    assert fusion[0].severite == "CRITIQUE"


# ══ 7 · « Questions ouvertes : aucune » est vérifiable ════════════════════
def test_aucune_question_ouverte_est_dementi_par_une_valeur_a_confirmer():
    """Le défaut le moins visible et le plus coûteux : la spec affirme que tout
    est tranché alors que deux valeurs portent « à confirmer »."""
    spec = _BONNE + (
        "\n- **EF-002** : Réponse sous 200 ms (valeur proposée, à confirmer)\n"
        "\n## Questions ouvertes\n- Aucune\n")

    constats = analyser(spec)

    assert any(c.categorie == "contradiction" for c in constats)


def test_des_questions_ouvertes_reellement_listees_ne_sont_pas_signalees():
    spec = _BONNE + (
        "\n- **EF-002** : Réponse sous 200 ms (valeur proposée, à confirmer)\n"
        "\n## Questions ouvertes\n- Le seuil de 200 ms reste à valider\n")

    constats = analyser(spec)

    assert not any(c.categorie == "contradiction" for c in constats)


def test_aucune_question_ouverte_sans_reserve_dans_le_corps_est_correct():
    spec = _BONNE + "\n## Questions ouvertes\n- Aucune\n"

    constats = analyser(spec)

    assert not any(c.categorie == "contradiction" for c in constats)


# ══ 8 · Le gabarit prévient plutôt que de détecter ════════════════════════
def test_le_gabarit_exige_que_la_differenciation_soit_la_partie_la_plus_detaillee():
    """« Si la différenciation est une démo qu'on peut essayer, son protocole
    mérite autant de place que le reste du site. »"""
    from src.agents.spec.template import REGLES_DE_REDACTION

    assert "DIFFÉRENCIATION" in REGLES_DE_REDACTION
    assert "sa propre section" in REGLES_DE_REDACTION


def test_le_gabarit_decourage_de_figer_une_version_sans_raison():
    from src.agents.spec.template import REGLES_DE_REDACTION

    assert "NE FIGE PAS UNE VERSION" in REGLES_DE_REDACTION


def test_le_gabarit_exige_une_verification_de_coherence():
    from src.agents.spec.template import REGLES_DE_REDACTION

    assert "COHÉRENCE" in REGLES_DE_REDACTION


# ══ 9 · Une source référencée fait foi — et son silence aussi ═════════════
#
# « Regarder dans le repo ai-agent, il y a toute la DA dedans », répondu DEUX
# fois pendant un wizard. La spec produite a inventé une palette cyan/corail et
# trois références (Vercel, Stripe, OpenAI), alors que l'identité réelle est
# ambre + violet sur fond GitHub sombre, déclarée dans assets/banner.svg.
#
# Deux défauts : on ne lisait que le README (où une charte n'est jamais), et
# n'ayant rien trouvé le modèle inventait au lieu de le dire.
def test_la_palette_est_extraite_la_ou_elle_vit_vraiment(tmp_path):
    """Pas dans le README — dans un SVG, une config Tailwind, un globals.css."""
    from src.agents.spec.sources import extraire_design

    (tmp_path / "README.md").write_text("# Projet\nUn agent.")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "banner.svg").write_text(
        '<svg><rect fill="#f59e0b"/><rect fill="#f59e0b"/><rect fill="#0d1117"/>'
        '<text font-family="Inter, sans-serif">x</text></svg>')

    design = extraire_design(tmp_path)

    assert not design.vide
    assert design.couleurs[0][0] == "#f59e0b", "la plus fréquente d'abord"
    assert any("Inter" in p for p in design.polices)


def test_les_neutres_ne_noient_pas_les_couleurs_de_marque(tmp_path):
    from src.agents.spec.sources import extraire_design

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "a.svg").write_text(
        '<svg>' + '<rect fill="#ffffff"/>' * 20 + '<rect fill="#7c3aed"/></svg>')

    design = extraire_design(tmp_path)

    assert [c for c, _ in design.couleurs] == ["#7c3aed"]


def test_une_source_muette_le_dit_au_lieu_de_se_taire(tmp_path):
    """Le point décisif : sans aveu explicite, le modèle reçoit un silence et le
    comble. Avec, il reçoit un FAIT dont il peut rendre compte."""
    from src.agents.spec.sources import extraire_design

    (tmp_path / "README.md").write_text("# Projet sans aucune charte visuelle")

    rendu = extraire_design(tmp_path).rendu("mon-repo")

    assert "DESIGN NON TROUVÉ" in rendu
    assert "NE PAS INVENTER" in rendu
    assert "Questions ouvertes" in rendu


def test_une_source_renseignee_impose_ses_valeurs(tmp_path):
    from src.agents.spec.sources import extraire_design

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "b.svg").write_text('<svg><rect fill="#f59e0b"/></svg>')

    rendu = extraire_design(tmp_path).rendu("mon-repo")

    assert "CES VALEURS FONT FOI" in rendu
    assert "#f59e0b" in rendu


def test_un_dossier_inexistant_ne_casse_rien(tmp_path):
    from src.agents.spec.sources import extraire_design

    assert extraire_design(tmp_path / "absent").vide


def test_le_gabarit_interdit_de_substituer_une_invention_a_une_source():
    from src.agents.spec.template import REGLES_DE_REDACTION

    assert "UNE SOURCE RÉFÉRENCÉE FAIT FOI" in REGLES_DE_REDACTION
    assert "NE FABRIQUE RIEN" in REGLES_DE_REDACTION


def test_la_resolution_de_reference_injecte_le_design_du_projet():
    """Bout en bout, sur le cas réel : « regarder dans le repo ai-agent »."""
    from src.ui.spec import _resolve_file_refs

    resolu = _resolve_file_refs("Regarder dans le repo ai-agent pour la DA")

    assert "[DESIGN" in resolu


# ══ 10 · Une source référencée est lue EN ENTIER ══════════════════════════
#
# Le README d'ai-agent fait 19 196 caractères ; l'injection en coupait 6 000.
# 69 % du produit disparaissait — `/build`, la mémoire de projet, les fiches,
# les présentations, l'intégration IDE, MCP, le serveur d'API. La spec produite
# listait TROIS fonctionnalités : exactement les trois qui survivaient à la coupe.
def test_le_sommaire_est_complet_meme_quand_le_corps_est_tronque(tmp_path):
    """Un modèle qui voit toute la liste peut en parler ; un modèle qui n'en voit
    que le premier tiers croit que le produit s'y arrête."""
    from src.agents.spec.sources import resumer_source

    corps = "\n".join(f"## Fonctionnalité {i}\n" + "x" * 400 for i in range(40))
    (tmp_path / "README.md").write_text("# Projet\n" + corps)

    resume = resumer_source(tmp_path, budget=2000)

    for i in range(40):
        assert f"Fonctionnalité {i}" in resume, f"titre {i} perdu"


def test_la_troncature_est_annoncee(tmp_path):
    """Couper en silence laisse croire au modèle qu'il a tout lu."""
    from src.agents.spec.sources import resumer_source

    (tmp_path / "README.md").write_text("# P\n" + "x" * 30_000)

    resume = resumer_source(tmp_path, budget=1000)

    assert "CORPS TRONQUÉ" in resume
    assert "SOMMAIRE ci-dessus est COMPLET" in resume


def test_un_readme_court_passe_sans_troncature(tmp_path):
    from src.agents.spec.sources import resumer_source

    (tmp_path / "README.md").write_text("# P\n## A\ncontenu")

    resume = resumer_source(tmp_path)

    assert "CORPS TRONQUÉ" not in resume


def test_le_sommaire_conserve_la_hierarchie(tmp_path):
    from src.agents.spec.sources import sommaire

    niveaux = sommaire("# Un\n## Deux\n### Trois\n")

    assert niveaux == [(1, "Un"), (2, "Deux"), (3, "Trois")]


def test_le_repo_reel_livre_tout_son_sommaire():
    """Cas mesuré : 9 titres passaient, 37 existent."""
    from pathlib import Path

    from src.agents.spec.sources import resumer_source

    resume = resumer_source(Path(__file__).resolve().parents[1])

    for attendu in ("Features", "Commands", "Configuration", "Architecture"):
        assert attendu in resume


# ══ 11 · Une demande explicite doit survivre jusqu'à la spec ══════════════
@pytest.mark.parametrize("demande, attendu", [
    ("Je veux de la 3D", "3d"),
    ("avec Three.js", "three.js"),
    ("un dark mode", "dark mode"),
    ("du parallaxe", "parallaxe"),
    ("en PostgreSQL", "postgresql"),
])
def test_les_demandes_explicites_sont_extraites(demande, attendu):
    from src.agents.spec.analyze import demandes_explicites

    assert attendu in demandes_explicites(demande)


def test_une_demande_absente_de_la_spec_est_signalee():
    """« Inclus de la 3D » suivi d'une spec sans une mention de 3D est un défaut
    qu'aucun contrôle interne ne voit : le document est cohérent, il répond
    simplement à une autre question."""
    constats = analyser(_BONNE, demande="Je veux une landing avec de la 3D")

    assert any(c.categorie == "demande-perdue" and "3d" in c.extrait
               for c in constats)


def test_une_demande_honoree_ne_produit_aucun_constat():
    spec = _BONNE.replace("- **EF-001** : Une tâche porte un titre et un statut",
                          "- **EF-001** : Une scène 3D en Three.js sur le hero")

    constats = analyser(spec, demande="Je veux de la 3D en Three.js")

    assert not any(c.categorie == "demande-perdue" for c in constats)


def test_sans_demande_fournie_aucun_controle_n_est_fait():
    """Non-régression : l'analyse d'une spec seule ne change pas."""
    assert not any(c.categorie == "demande-perdue" for c in analyser(_BONNE))


def test_un_terme_redondant_n_est_signale_qu_une_fois():
    """« three » et « three.js » désignent la même demande."""
    from src.agents.spec.analyze import demandes_explicites

    termes = demandes_explicites("avec Three.js")

    assert "three" not in termes or "three.js" not in termes
