"""Les gabarits de `/fiche` et `/exo` vivent dans `skills/`, sans en être.

Un skill est un guide qu'un modèle choisit de charger ; ceux-ci sont consommés
par le code. Les exposer au catalogue ferait charger 277 lignes de HTML à un
modèle croyant lire des consignes — d'où un scope qu'aucun agent ne lit.
"""

from __future__ import annotations

import pytest

from src.ui.templates import SCOPE, charger


@pytest.mark.parametrize("nom", ["fiche", "exo"])
def test_le_gabarit_se_charge(nom):
    assert len(charger(nom, content="C", lang="L", type_exo="T")) > 3000


@pytest.mark.parametrize("nom", ["fiche", "exo"])
def test_aucun_jeton_ne_survit_au_rendu(nom):
    rendu = charger(nom, content="C", lang="L", type_exo="T")

    assert "%%" not in rendu, "un jeton n'a pas été substitué"


@pytest.mark.parametrize("nom", ["fiche", "exo"])
def test_le_contenu_fourni_arrive_dans_le_prompt(nom):
    rendu = charger(nom, content="LE_COURS_ICI", lang="EN_FRANCAIS", type_exo="qcm")

    assert "LE_COURS_ICI" in rendu
    assert "EN_FRANCAIS" in rendu


def test_le_type_d_exercice_arrive_dans_le_prompt():
    assert "qcm_seulement" in charger("exo", content="C", lang="L",
                                      type_exo="qcm_seulement")


@pytest.mark.parametrize("scope", ["coding", "orchestrator"])
def test_les_gabarits_restent_hors_du_catalogue_des_modeles(scope):
    """Un modèle ne doit jamais pouvoir charger un gabarit via load_skill."""
    from src.skills import list_skills

    assert not {"fiche", "exo"} & set(list_skills(scope))


def test_le_scope_des_gabarits_n_est_lu_par_aucun_agent():
    from src.skills import list_skills

    assert set(list_skills(SCOPE)) >= {"fiche", "exo"}
    assert SCOPE not in ("coding", "orchestrator")


def test_un_gabarit_inconnu_echoue_franchement():
    """Le retriever est sémantique : sans contrôle du nom, il rendrait le gabarit
    le PLUS PROCHE — donc le mauvais prompt, silencieusement."""
    with pytest.raises(LookupError):
        charger("gabarit-qui-nexiste-pas", content="C")


def test_un_nom_voisin_ne_rend_jamais_l_autre_gabarit():
    """« fiches » ne doit pas rendre « fiche », ni « exos » rendre « exo »."""
    for voisin in ("fiches", "exos", "fich"):
        with pytest.raises(LookupError):
            charger(voisin, content="C")


@pytest.mark.parametrize("nom", ["fiche", "exo"])
def test_les_accolades_du_css_sont_ecrites_normalement(nom):
    """Le passage aux jetons `%%NOM%%` supprime l'échappement `{{` qu'imposait
    `.format()` — un piège silencieux dès qu'on éditait le HTML."""
    import pathlib

    source = pathlib.Path(f"skills/{nom}.md").read_text(encoding="utf-8")

    assert "{{" not in source


def test_streaming_ne_porte_plus_les_gabarits_en_dur():
    import inspect

    from src.ui import streaming

    source = inspect.getsource(streaming)

    assert "_FICHE_PROMPT" not in source
    assert "_EXO_PROMPT" not in source


def test_aucun_module_ne_reference_les_anciennes_constantes():
    """`study/tools.py` les importait aussi — un consommateur oublié casse
    silencieusement une commande entière."""
    import pathlib

    fautifs = [
        str(f) for f in pathlib.Path("src").rglob("*.py")
        if "_FICHE_PROMPT" in f.read_text(encoding="utf-8")
        or "_EXO_PROMPT" in f.read_text(encoding="utf-8")
    ]

    assert not fautifs, fautifs


# ── Défauts constatés sur une fiche produite ────────────────────────────────
# « ◑ Sombre » s'affichait deux fois, et la première section se collait sous le
# header. Les deux venaient du gabarit, pas du modèle.

def _fiche() -> str:
    import pathlib
    return pathlib.Path("skills/fiche.md").read_text(encoding="utf-8")


def test_le_libelle_du_bouton_a_une_seule_source():
    """Décrit à deux endroits, le modèle l'écrivait en textContent ET en ::after."""
    source = _fiche()

    assert "INTERDIT : .btn-toggle::after" in source
    assert "UNIQUEMENT dans le textContent" in source


def test_l_espace_sous_le_header_est_superieur_a_sa_hauteur():
    """Le header fixe descend à ~63px : 72px ne laissait que 9px, la première
    section venait se coller dessous."""
    import re

    source = _fiche()
    valeurs = [int(v) for v in re.findall(r"body\s*:\s*padding-top:\s*(\d+)px", source)]

    assert valeurs, "le gabarit ne fixe plus le padding-top du body"
    assert min(valeurs) >= 90, f"trop serré sous le header : {valeurs}"


def test_le_conteneur_aere_aussi_le_haut_de_page():
    assert "container: padding-top" in _fiche() or ".container: padding-top" in _fiche()


def test_le_balisage_des_tables_est_montre_pas_decrit():
    """Décrit en prose, le modèle mettait la classe SUR la table : `overflow-x`
    n'y crée aucun conteneur, la table débordait et rognait la fin de page."""
    source = _fiche()

    assert '<div class="table-wrapper">' in source
    assert 'INTERDIT : <table class="table-wrapper">' in source


def test_les_cellules_longues_ont_une_regle_de_cesure():
    """Une cellule `[(ngModel)]="value"` est insécable et élargit la table."""
    assert "overflow-wrap: anywhere" in _fiche()


def test_chaque_carte_semantique_a_sa_pastille():
    """Le gabarit définissait .card-mnemo sans pastille correspondante : le
    modèle inventait `class="label success"`, absente du CSS."""
    source = _fiche()

    for classe in ("concept", "formula", "example", "danger", "success"):
        assert f"var(--{classe})" in source or classe in source
    assert "CINQ classes sont les seules autorisées" in source
