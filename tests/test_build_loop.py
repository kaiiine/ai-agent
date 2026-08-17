"""La boucle de build : explorer n'est pas boucler, et échouer se dit.

Quatre défauts relevés sur un vrai build (`/build axon-landing`), enchaînés :

1. le détecteur de boucle comptait les appels par NOM D'OUTIL. Lire sept
   fichiers DIFFÉRENTS avant d'écrire une page qui les compose était donc traité
   comme une boucle, et la phase tuée ;
2. la tâche de phase ne disait pas quels fichiers existaient — l'agent DEVAIT
   explorer pour connaître la surface du projet, ce qui déclenchait (1) ;
3. le retry renvoyait la tâche identique, sans dire ce qui avait échoué : même
   exploration, même mort ;
4. le statut d'une phase antérieure se déduisait de son NUMÉRO. Une phase morte
   deux fois était donc annoncée « ✓ faite » à la suivante, qui a validé une
   page jamais écrite.

Résultat mesuré : phases 3 et 4 mortes deux fois chacune, et un site livré à
l'état de squelette — `page.tsx` de 27 lignes disant lui-même « Phase 2
placeholder, real sections land in Phase 3 ».
"""

from __future__ import annotations

from collections import Counter

import pytest

from src.agents.coding.build_runner import (
    _is_scaffold_phase,
    _build_phase_task, _cible_de, _compress_spec_for_phase, _inventaire_du_projet,
)
from src.agents.coding.task_decomposer import Phase

_PHASES = [Phase(1, "Setup", "scaffold"), Phase(2, "Composants", "ui"),
           Phase(3, "Pages", "sections"), Phase(4, "Polish", "vérif")]


# ══ 1 · Explorer n'est pas boucler ════════════════════════════════════════
def test_lire_sept_fichiers_differents_n_est_pas_une_boucle():
    """Le défaut central. C'est exactement ce que fait une phase « Pages » avant
    d'écrire : lire les composants qu'elle va assembler."""
    appels = [_cible_de("local_read_file", {"path": f"/p/src/C{i}.tsx"})
              for i in range(7)]

    assert Counter(appels).most_common(1)[0][1] == 1


def test_lire_sept_fois_le_meme_fichier_reste_une_boucle():
    appels = [_cible_de("local_read_file", {"path": "/p/src/Header.tsx"})
              for _ in range(7)]

    assert Counter(appels).most_common(1)[0][1] == 7


@pytest.mark.parametrize("event, data, attendu_distinct", [
    ("shell_run", [{"cmd": "pnpm build"}, {"cmd": "pnpm test"}], 2),
    ("shell_run", [{"cmd": "pnpm build"}, {"cmd": "pnpm build"}], 1),
    ("local_grep", [{"pattern": "Button"}, {"pattern": "Header"}], 2),
    ("local_find_file", [{"name": "a.ts"}, {"name": "b.ts"}], 2),
])
def test_la_cible_distingue_les_appels(event, data, attendu_distinct):
    cibles = {_cible_de(event, d) for d in data}

    assert len(cibles) == attendu_distinct


def test_un_appel_sans_argument_reconnaissable_garde_son_nom():
    """Pas de faux distinguo : sans cible lisible, deux appels restent
    identiques et la détection de boucle continue de s'appliquer."""
    a = _cible_de("un_outil", {})
    b = _cible_de("un_outil", {"autre": "chose"})

    assert a == b == "un_outil"


# ══ 2 · La phase sait ce qui existe déjà ══════════════════════════════════
def test_l_inventaire_liste_les_fichiers_et_leurs_exports(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Button.tsx").write_text(
        "export function Button() {}\nexport const LinkButton = () => {}\n")

    inv = _inventaire_du_projet(tmp_path)

    assert "src/Button.tsx" in inv
    assert "Button" in inv and "LinkButton" in inv


def test_l_inventaire_ignore_les_dossiers_de_dependances(tmp_path):
    """`node_modules` ferait exploser l'inventaire et noierait le projet."""
    for dossier in ("node_modules", ".next", "dist"):
        (tmp_path / dossier).mkdir()
        (tmp_path / dossier / "x.ts").write_text("export const x = 1")
    (tmp_path / "vrai.ts").write_text("export const vrai = 1")

    inv = _inventaire_du_projet(tmp_path)

    assert "vrai.ts" in inv
    for dossier in ("node_modules", ".next", "dist"):
        assert dossier not in inv


def test_l_inventaire_est_borne(tmp_path):
    """Un gros projet ne doit pas remplir la fenêtre de contexte."""
    for i in range(80):
        (tmp_path / f"f{i}.ts").write_text("export const x = 1")

    inv = _inventaire_du_projet(tmp_path, max_fichiers=10)

    assert inv.count("\n") <= 10
    assert "tronqué" in inv


def test_un_projet_inexistant_ne_casse_pas_l_inventaire(tmp_path):
    assert _inventaire_du_projet(tmp_path / "absent") == ""


def test_la_tache_porte_l_inventaire_et_decourage_les_lectures(tmp_path):
    (tmp_path / "Button.tsx").write_text("export function Button() {}")

    task = _build_phase_task(_PHASES[2], "SPEC", "p", tmp_path, _PHASES)

    assert "FICHIERS DÉJÀ PRÉSENTS" in task
    assert "Button" in task
    assert "N'ouvre un fichier que si tu as besoin de son CONTENU" in task


def test_la_tache_exige_d_ecrire_tot(tmp_path):
    """« Une phase qui n'a produit aucun fichier n'a rien livré. »"""
    task = _build_phase_task(_PHASES[2], "SPEC", "p", tmp_path, _PHASES)

    assert "ÉCRIS TÔT" in task


# ══ 3 · Un retry aveugle reproduit l'échec ════════════════════════════════
def test_le_motif_d_echec_entre_dans_la_tache_du_retry(tmp_path):
    task = _build_phase_task(_PHASES[2], "SPEC", "p", tmp_path, _PHASES,
                             echec_precedent="boucle détectée")

    assert "TENTATIVE PRÉCÉDENTE ÉCHOUÉE" in task
    assert "boucle détectée" in task
    assert "Ne recommence pas la même approche" in task


def test_une_premiere_tentative_ne_porte_aucun_motif(tmp_path):
    task = _build_phase_task(_PHASES[2], "SPEC", "p", tmp_path, _PHASES)

    assert "TENTATIVE PRÉCÉDENTE" not in task


# ══ 4 · Une phase échouée est dite échouée ════════════════════════════════
def test_une_phase_anterieure_echouee_n_est_pas_annoncee_faite():
    """La phase 4 a validé une page que la phase 3 n'avait jamais écrite."""
    bloc = _compress_spec_for_phase("SPEC", _PHASES, _PHASES[3], echouees={3})

    assert "✗ ÉCHOUÉE" in bloc
    assert "N'EXISTE PAS" in bloc


def test_le_travail_manquant_est_nomme():
    bloc = _compress_spec_for_phase("SPEC", _PHASES, _PHASES[3], echouees={3})

    assert "[3]" in bloc
    assert "ne valide pas un résultat qui en dépend" in bloc


def test_sans_echec_le_statut_reste_inchange():
    """Non-régression : le comportement nominal ne bouge pas."""
    bloc = _compress_spec_for_phase("SPEC", _PHASES, _PHASES[3])

    assert "✓ faite" in bloc
    assert "ÉCHOUÉE" not in bloc


def test_la_phase_un_recoit_toujours_la_spec_entiere():
    bloc = _compress_spec_for_phase("X" * 9000, _PHASES, _PHASES[0], echouees=set())

    assert len(bloc) == 6000


def test_la_tache_transmet_les_phases_echouees(tmp_path):
    task = _build_phase_task(_PHASES[3], "SPEC", "p", tmp_path, _PHASES,
                             echouees={3})

    assert "ÉCHOUÉE" in task


# ══ 5 · Les serveurs MCP sont utilisables depuis /build ═══════════════════
#
# Le graphe conversationnel branchait MCP depuis toujours ; le specialist non.
# `/build` était donc le SEUL chemin d'AXON aveugle à MCP : un projet 3D pouvait
# demander Blender dans sa spec, l'agent de build ne pouvait pas le joindre et
# écrivait du code à la place — sans jamais signaler que l'outil lui manquait.
class _FauxOutil:
    def __init__(self, name):
        self.name = name


class _FauxConfig:
    def __init__(self, hint, enabled=True):
        self.capabilities_hint = hint
        self.enabled = enabled


class _FauxRuntime:
    def __init__(self, serveurs, outils):
        self._serveurs = serveurs
        self.tools = [_FauxOutil(n) for n in outils]

    def servers(self):
        return self._serveurs


def test_les_outils_mcp_sont_lies_au_specialist(monkeypatch):
    from src.agents.coding import specialist

    monkeypatch.setattr(specialist, "_outils_mcp",
                        lambda: [_FauxOutil("blender__get_scene_info")])
    noms = {t.name for t in specialist._get_coding_tools()}

    assert "blender__get_scene_info" in noms
    assert "propose_file_change" in noms, "les outils natifs restent présents"


def test_une_panne_mcp_ne_coute_jamais_le_build(monkeypatch):
    """Sans serveur joignable, le specialist travaille comme avant."""
    import src.mcp_client.runtime as runtime
    from src.agents.coding import specialist

    def _explose():
        raise RuntimeError("MCP indisponible")

    monkeypatch.setattr(runtime, "mcp_runtime", _explose)

    assert specialist._outils_mcp() == []
    assert len(specialist._get_coding_tools()) > 20


def test_la_phase_annonce_les_capacites_mcp(monkeypatch):
    """Brancher les outils ne suffit pas : le specialist ne lie que les huit
    outils les plus proches de sa requête. Sans annonce, Blender est présent,
    joignable, et jamais sélectionné."""
    import src.mcp_client.runtime as runtime
    from src.agents.coding import build_runner

    monkeypatch.setattr(runtime, "mcp_runtime", lambda: _FauxRuntime(
        {"blender": _FauxConfig("3D modeling, rendering, GLB export")},
        ["blender__render", "blender__scene"]))

    bloc = build_runner._capacites_mcp()

    assert "blender" in bloc
    assert "3D modeling" in bloc
    assert "PASSE PAR L'OUTIL" in bloc


def test_un_serveur_desactive_n_est_pas_annonce(monkeypatch):
    import src.mcp_client.runtime as runtime
    from src.agents.coding import build_runner

    monkeypatch.setattr(runtime, "mcp_runtime", lambda: _FauxRuntime(
        {"eteint": _FauxConfig("hors service", enabled=False)}, []))

    assert build_runner._capacites_mcp() == ""


def test_sans_serveur_mcp_la_tache_reste_inchangee(monkeypatch, tmp_path):
    import src.mcp_client.runtime as runtime
    from src.agents.coding import build_runner

    monkeypatch.setattr(runtime, "mcp_runtime", lambda: _FauxRuntime({}, []))
    task = build_runner._build_phase_task(_PHASES[2], "SPEC", "p", tmp_path, _PHASES)

    assert "OUTILS MCP" not in task


def test_la_tache_porte_les_capacites_quand_un_serveur_existe(monkeypatch, tmp_path):
    import src.mcp_client.runtime as runtime
    from src.agents.coding import build_runner

    monkeypatch.setattr(runtime, "mcp_runtime", lambda: _FauxRuntime(
        {"blender": _FauxConfig("3D, rendering")}, ["blender__x"]))

    task = build_runner._build_phase_task(_PHASES[2], "SPEC", "p", tmp_path, _PHASES)

    assert "OUTILS MCP CONNECTÉS" in task
    assert "3D, rendering" in task


# ══ 6 · Un scope revient toujours en chaîne ═══════════════════════════════
#
# Plantage vécu sur `/build axon-landing`, à la reprise d'un build existant :
#
#     File "build_runner.py", line 81, in _is_scaffold_phase
#       text = (phase.title + " " + phase.scope).lower()
#     TypeError: can only concatenate str (not "list") to str
#
# `Phase.scope` est annoté `str`, mais une dataclass annote sans imposer. Deux
# producteurs l'alimentent — le modèle qui décompose la spec, et le rechargement
# de `build-state.json` — et le premier a rendu un TABLEAU JSON. La consigne l'y
# invitait : l'exemple montrait une chaîne, la règle disait « scope = liste
# exhaustive ». La liste a été persistée, et toute reprise plantait ensuite.

def test_un_scope_en_liste_devient_une_chaine():
    """Le cas exact du fichier d'état d'axon-landing."""
    phase = Phase(1, "Setup", ["Initialiser Vite", "Configurer Tailwind"])

    assert isinstance(phase.scope, str)
    assert "- Initialiser Vite" in phase.scope
    assert "- Configurer Tailwind" in phase.scope


def test_une_phase_rechargee_passe_le_test_de_scaffold():
    """La fonction qui plantait, sur la donnée qui la faisait planter."""
    phase = Phase(1, "Setup & Scaffold",
                  ["Initialize project with Vite", "Install Tailwind CSS"])

    assert _is_scaffold_phase(phase) is True


def test_un_scope_en_chaine_n_est_pas_touche():
    """Non-régression : le cas nominal ne doit pas être reformaté."""
    phase = Phase(2, "Composants", "Layout, header, footer")

    assert phase.scope == "Layout, header, footer"


@pytest.mark.parametrize("brut, attendu", [
    (None, ""),
    ([], ""),
    (["  ", ""], ""),
    (42, "42"),
])
def test_un_scope_incongru_ne_fait_pas_planter(brut, attendu):
    """Normaliser au lieu de lever : un plan mal formé doit dégrader le build,
    pas l'interrompre avant la première phase."""
    assert Phase(1, "T", brut).scope == attendu


def test_la_tache_de_phase_accepte_un_scope_recharge(tmp_path):
    """Le second appelant qui aurait eu besoin du même correctif : il interpole
    le scope au lieu de le concaténer, donc il ne plantait pas — il aurait
    simplement écrit « ['a', 'b'] » dans la tâche envoyée au modèle."""
    phase = Phase(3, "Pages", ["Écrire la home", "Écrire le footer"])

    task = _build_phase_task(phase, "SPEC", "p", tmp_path, [phase])

    assert "- Écrire la home" in task
    assert "['Écrire la home'" not in task


# ══ 7 · Le préfixe de pré-scaffold est appliqué, pas orphelin ═════════════
#
# Second plantage vécu sur `/build axon-landing`, juste après le premier :
#
#     File "build_runner.py", line 768, in run_build
#       + task
#     UnboundLocalError: cannot access local variable 'task'
#
# Le préfixe vivait AU-DESSUS de la boucle de retry, du temps où la tâche s'y
# construisait aussi. Quand elle a été déplacée dans la boucle — « reconstruite à
# CHAQUE tentative » — le préfixe est resté derrière et lisait un `task` pas
# encore assigné. Il plantait donc à tout pré-scaffold réussi, c'est-à-dire à
# toute phase 1 d'un projet dont le framework est détecté.

def test_le_prefixe_de_prescaffold_dit_de_ne_pas_recommencer():
    from src.agents.coding.build_runner import _prefixe_prescaffold

    prefixe = _prefixe_prescaffold("next")

    assert "next" in prefixe
    assert "NE PAS relancer" in prefixe
    assert prefixe.endswith("\n\n"), "il se colle devant une tâche, pas dedans"


def test_le_prefixe_precede_la_tache_de_phase(tmp_path):
    """L'ordre est ce qui plantait : le préfixe s'applique APRÈS la construction."""
    from src.agents.coding.build_runner import _prefixe_prescaffold

    task = _build_phase_task(_PHASES[0], "SPEC", "p", tmp_path, _PHASES)
    complet = _prefixe_prescaffold("next") + task

    assert complet.startswith("[PRÉ-SCAFFOLD EFFECTUÉ AUTOMATIQUEMENT]")
    assert "SCOPE DE CETTE PHASE" in complet


def test_run_build_n_utilise_plus_task_avant_de_l_avoir_construit():
    """Le défaut était un ORDRE, pas une valeur : dans le source de `run_build`,
    la première mention de `task` doit être son affectation."""
    import inspect

    from src.agents.coding import build_runner

    # `_run_build` et non `run_build` : ce dernier n'est plus qu'une enveloppe
    # qui décide d'ancrer l'aperçu à droite, et délègue le travail.
    source = inspect.getsource(build_runner._run_build)
    affectation = source.index("task = _build_phase_task")
    lecture = source.index("+ task")

    assert affectation < lecture, "le préfixe lit `task` avant son affectation"
