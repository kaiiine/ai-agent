"""Non-régression du routage des skills (src/skills/retriever.py).

Le test qui compte est `test_le_jeu_tenu_a_l_ecart_tient_son_plancher`. Les deux
autres planchers le complètent ; la discipline des deux jeux est décrite dans
`corpus_routage_skills.py`.

Ce que les planchers valent, mesuré le 22/08/2026 :

                                          servi        atteignable
    29 skills, descriptions en mots-clés  17/22  9/16      —
    29 skills, stacks décrits par phrase  19/22 10/16      —
    46 skills (+17 importés), avec renvoi 18/22  9/16   21/22 12/16

`servi` perd deux points en passant de 29 à 46 skills, `atteignable` en gagne
deux. C'est le compromis assumé : le premier choix se trompe un peu plus souvent
de RÔLE, et ne perd plus jamais la requête. Les trois derniers imports
(performance, a11y, seo) n'ont bougé aucun des deux chiffres — l'ajout est
neutre pour tout ce qui ne les nomme pas.

SERVI = le bon skill est rendu. ATTEIGNABLE = il est rendu OU nommé dans le
renvoi qui accompagne la réponse. C'est `atteignable` qui décrit le système
réel, puisque `load_skill` peut être rappelé — et c'est lui qui MONTE quand on
ajoute des skills, là où `servi` descend de deux points.

Pourquoi le premier choix n'est pas réparable
─────────────────────────────────────────────
Six mécanismes de désambiguïsation ont été construits et mesurés. Aucun n'a
battu la baseline sur le jeu tenu à l'écart :

  1. filet lexical sur noms et alias         16/22   9/16
  2. lexique de verbes d'intention           22/22   7/16   ← surappris
  3. centroïdes d'embeddings d'intention     17/22   9/16
  4. domaine + première phrase du candidat   17/22   7/16
  5. ligne d'usage en français partout       13/22   8/16
  6. requête sans techno → rôles seulement   17/22   9/16

Le n°2 dit tout : 22/22 sur le jeu qui a servi à écrire sa regex, 7/16 dès
qu'on change de formulation. Sans le second jeu, il partait en production.

La cause commune est que `nomic-embed-text` ne sépare pas « créer » de
« relire » sur une phrase française, et que toute classification des skills en
familles que j'écris à la main est elle-même fautive — la n°6 casse
`database-reviewer` parce que « Postgres » ne figure pas dans ses alias.

Alors on ne répare pas le premier choix : on le rend RÉCUPÉRABLE. Un skill servi
cite ses voisins de domaine, et le modèle rappelle `load_skill` s'il s'est
trompé de rôle. Conséquence recherchée : un skill ajouté ne peut plus voler une
requête sans recours, au pire il ajoute une ligne de renvoi.
"""
from __future__ import annotations

import pytest

from corpus_routage_skills import REGLAGE, TENU_A_L_ECART

# Planchers de RÉGRESSION, pas des cibles. Les deux premiers ont baissé d'un
# point en passant de 29 à 43 skills : l'import a introduit `rust-reviewer`, qui
# capte « écris un CLI en Rust ». Les deux cas perdus sont des confusions de
# RÔLE dans le BON domaine, et le renvoi les nomme — c'est précisément ce que
# `_PLANCHER_*_ATTEIGNABLE` vérifie, et ces deux-là montent.
_PLANCHER_REGLAGE = 18
_PLANCHER_TENU = 9
_PLANCHER_REGLAGE_ATTEIGNABLE = 21
_PLANCHER_TENU_ATTEIGNABLE = 12


@pytest.fixture(scope="module")
def routeur():
    from src.skills import retriever as R

    r = R.SkillRetriever()
    r._load()
    r._build_index()
    if r._index is None:
        pytest.skip("index sémantique indisponible (Ollama absent)")
    return r


def _skill_rendu(routeur, requete: str) -> str:
    """Le nom du skill effectivement servi — `get` renvoie son CONTENU."""
    rendu = routeur.get(requete, k=1, scope="coding")
    # `startswith` et non `==` : la réponse peut porter un renvoi vers les
    # skills voisins du même domaine.
    return next((n for n, s in routeur._skills.items()
                 if s["content"] and rendu.startswith(s["content"][:200])), "?")


def _score(routeur, jeu) -> tuple[int, list[str]]:
    echecs = []
    for requete, attendu in jeu:
        obtenu = _skill_rendu(routeur, requete)
        if obtenu != attendu:
            echecs.append(f"« {requete} » → {obtenu} (attendu {attendu})")
    return len(jeu) - len(echecs), echecs


def test_le_jeu_de_reglage_tient_son_plancher(routeur):
    ok, echecs = _score(routeur, REGLAGE)
    assert ok >= _PLANCHER_REGLAGE, (
        f"{ok}/{len(REGLAGE)} < {_PLANCHER_REGLAGE} :\n  " + "\n  ".join(echecs))


def test_le_jeu_tenu_a_l_ecart_tient_son_plancher(routeur):
    """Le seul chiffre auquel se fier : aucun réglage n'a été fait dessus.

    Un mécanisme qui monte sur `REGLAGE` sans monter ici n'a rien appris du
    problème, il a appris le jeu.
    """
    ok, echecs = _score(routeur, TENU_A_L_ECART)
    assert ok >= _PLANCHER_TENU, (
        f"{ok}/{len(TENU_A_L_ECART)} < {_PLANCHER_TENU} :\n  " + "\n  ".join(echecs))


def _atteignable(routeur, requete: str, attendu: str) -> bool:
    """Servi, ou nommé dans le renvoi — les deux voies dont dispose le modèle."""
    rendu = routeur.get(requete, k=1, scope="coding")
    contenu_attendu = routeur._skills[attendu]["content"]
    return rendu.startswith(contenu_attendu[:200]) or f"- {attendu} :" in rendu


def test_le_jeu_de_reglage_reste_atteignable(routeur):
    ok = sum(_atteignable(routeur, q, a) for q, a in REGLAGE)
    assert ok >= _PLANCHER_REGLAGE_ATTEIGNABLE, f"{ok}/{len(REGLAGE)}"


def test_le_jeu_tenu_a_l_ecart_reste_atteignable(routeur):
    """L'invariant qui autorise à continuer d'ajouter des skills : cette mesure
    doit MONTER quand le catalogue grandit, pas descendre. Passer de 29 à 43
    skills l'a fait passer de 10/16 à 12/16."""
    ok = sum(_atteignable(routeur, q, a) for q, a in TENU_A_L_ECART)
    assert ok >= _PLANCHER_TENU_ATTEIGNABLE, f"{ok}/{len(TENU_A_L_ECART)}"


def test_deux_skills_du_meme_domaine_se_citent_mutuellement(routeur):
    """La garantie qui rend un ajout sûr. Dès que deux skills partagent un terme
    identifiant — `python` (alias `fastapi`) et `fastapi-reviewer`, `frontend`
    (alias `react`) et `react-reviewer` — une requête portant ce terme doit
    produire un renvoi vers l'autre. Sans quoi le nouvel arrivant peut voler la
    requête en silence.
    """
    from src.skills.retriever import termes_identifiants

    visible = routeur._visible("coding")
    revendique: dict[str, list[str]] = {}
    for nom, skill in visible.items():
        for terme in termes_identifiants(nom, skill):
            revendique.setdefault(terme, []).append(nom)

    partages = {t: v for t, v in revendique.items() if len(v) > 1}
    assert partages, "aucun terme partagé : le test ne vérifie plus rien"

    manquants = []
    for terme, skills in sorted(partages.items()):
        rendu = routeur.get(f"{terme} dans mon projet", k=1, scope="coding")
        servi = next((n for n in skills
                      if rendu.startswith(visible[n]["content"][:200])), None)
        if servi is None:
            continue                       # un tiers a gagné : hors sujet ici
        autres = [n for n in skills if n != servi]
        if not all(f"- {n} :" in rendu for n in autres):
            manquants.append(f"« {terme} » sert {servi} sans citer {autres}")
    assert not manquants, "renvois manquants :\n  " + "\n  ".join(manquants)


def test_les_deux_jeux_visent_des_skills_installes(routeur):
    """Un jeu qui attend un skill absent mesurerait l'absence, pas le routage."""
    installes = set(routeur._visible("coding"))
    attendus = {a for _, a in REGLAGE + TENU_A_L_ECART}
    assert attendus <= installes, f"skills attendus mais absents : {sorted(attendus - installes)}"


def test_les_deux_jeux_ne_partagent_aucune_requete():
    """Une requête commune ferait fuir le réglage dans le jeu de contrôle."""
    a = {q for q, _ in REGLAGE}
    b = {q for q, _ in TENU_A_L_ECART}
    assert not (a & b), f"requêtes présentes dans les deux jeux : {a & b}"


def test_chaque_domaine_est_demande_en_production_et_en_relecture():
    """La symétrie est ce qui rend les jeux capables de voir une confusion
    d'intention. Sans elle, un routeur qui ignore le verbe passerait."""
    par_famille = {"produit": 0, "relis": 0}
    for _, skill in REGLAGE:
        cle = "relis" if skill.endswith(("-reviewer", "-cleaner", "-simplifier",
                                         "-hunter", "-resolver")) else "produit"
        par_famille[cle] += 1
    assert par_famille["produit"] >= 8 and par_famille["relis"] >= 8, par_famille


def test_les_skills_de_stack_sont_decrits_par_une_phrase():
    """La correction qui a produit le gain : à domaine égal, le document le plus
    riche gagne. `python` décrit par sept mots-clés perdait contre
    `fastapi-reviewer` décrit par une phrase, y compris sur « crée une API
    FastAPI ». Les remettre à armes égales vaut +2 et +1 sur les deux jeux.

    Le test garde la CONVENTION, pas le texte : un skill de stack doit dire ce
    qu'il fait, pas seulement de quoi il parle.
    """
    from src.skills.retriever import SkillRetriever

    r = SkillRetriever()
    r._load()
    stacks = ("python", "go", "rust", "vue", "svelte", "nextjs", "frontend",
              "node_backend", "threedee", "blender", "systems", "angular")
    fautifs = [n for n in stacks if n in r._skills
               and not any(v in r._skills[n]["description"].lower()
                           for v in ("builds", "scaffolds", "use when"))]
    assert not fautifs, f"skills de stack sans phrase d'usage : {fautifs}"
