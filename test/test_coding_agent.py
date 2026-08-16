"""Tests for new coding-agent invariants: inline spec detection, proof type guards,
and repetition-exempt set membership."""
import pytest
from src.agents.coding.pending import recent_tools


@pytest.fixture(autouse=True)
def reset_recent_tools():
    recent_tools.clear()
    yield
    recent_tools.clear()


# ── _extract_inline_spec ──────────────────────────────────────────────────────

BRIEF_SAMPLE = """\
## Visual direction
Background: #ffffff  Text: #111111  Accent: #c0392b
No UI library. Custom components only.
No animations. Sharp edges. No border-radius. No box-shadow.

## Section structure

### 01 — Hero
Titre : "Communiquer comme une grande équipe."
Sous-titre : CRM, newsletter, veille — unifiés.
CTA : lien texte uniquement, jamais un bouton.
Colonne droite : modules en rotation géométrique — noms en gris.

### 02 — La plateforme
8 modules réels : Dashboard, CRM, Newsletter, Terrain, Mémoire, Veille,
Réseaux sociaux, Analytics. Grille 4×2 avec hover rouge sur le numéro.

### 03 — Milo IA
3 échanges Q&A en langage naturel. Fond noir, monospace.

### 04 — Contact
Formulaire : Prénom, Email, Rôle (select), Message.
Bouton submit : texte seul "Envoyer →", aucun fond.
"""


def test_spec_detected_in_brief():
    from src.agents.coding.task_enricher import _extract_inline_spec
    result = _extract_inline_spec("Créer un site.\n" + BRIEF_SAMPLE)
    assert result is not None
    preview, path = result
    assert "Visual direction" in preview


def test_spec_preview_contains_first_section():
    from src.agents.coding.task_enricher import _extract_inline_spec
    preview, _ = _extract_inline_spec("Build this.\n" + BRIEF_SAMPLE)
    assert "No UI library" in preview


def test_spec_not_detected_in_short_task():
    from src.agents.coding.task_enricher import _extract_inline_spec
    result = _extract_inline_spec("Crée-moi une app Next.js avec une page d'accueil.")
    assert result is None


def test_spec_not_detected_single_section():
    from src.agents.coding.task_enricher import _extract_inline_spec
    single = "## Section\n" + "x" * 600
    result = _extract_inline_spec(single)
    assert result is None


def test_spec_writes_temp_file(tmp_path, monkeypatch):
    import hashlib
    from src.agents.coding.task_enricher import _extract_inline_spec, _SPEC_FILE_PREFIX
    result = _extract_inline_spec("Task.\n" + BRIEF_SAMPLE)
    assert result is not None
    _, path = result
    if path:
        from pathlib import Path
        assert Path(path).exists()
        assert Path(path).read_text(encoding="utf-8").startswith("## Visual direction")


# ── enrich_task with spec ──────────────────────────────────────────────────────

def test_enrich_task_with_spec_adds_label():
    from src.agents.coding.task_enricher import enrich_task
    enriched = enrich_task("Crée un site.\n" + BRIEF_SAMPLE)
    assert "SPEC PERMANENTE" in enriched


def test_enrich_task_spec_prefix_before_task():
    from src.agents.coding.task_enricher import enrich_task
    enriched = enrich_task("Crée un site.\n" + BRIEF_SAMPLE)
    spec_pos = enriched.index("SPEC PERMANENTE")
    task_pos = enriched.index("Crée un site.")
    assert spec_pos < task_pos


def test_enrich_task_without_spec_unchanged():
    from src.agents.coding.task_enricher import enrich_task
    task = "Corrige le bug dans src/app.py ligne 42."
    # No ## sections, no refs → must come back unchanged
    assert enrich_task(task) == task


# ── proof type guards ──────────────────────────────────────────────────────────

def test_analysis_proof_fails_when_no_read_tool():
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    dev_plan_create.invoke({"steps": ["Analyser le projet"]})
    # recent_tools already cleared by fixture
    result = dev_plan_step_done.invoke({"step_index": 0, "proof_type": "analysis"})
    assert result["status"] == "error"
    assert "analyse" in result["error"].lower() or "outil" in result["error"].lower()


def test_analysis_proof_passes_after_read_tool():
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    from src.agents.coding.pending import recent_tools
    dev_plan_create.invoke({"steps": ["Analyser le projet"]})
    recent_tools.record("local_read_file", {"path": "/tmp/x.py"}, {"content": "ok"})
    result = dev_plan_step_done.invoke({"step_index": 0, "proof_type": "analysis"})
    assert result["status"] == "ok"


def test_file_written_proof_fails_when_not_written(tmp_path):
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    dev_plan_create.invoke({"steps": ["Créer composant"]})
    fake_path = str(tmp_path / "component.tsx")
    result = dev_plan_step_done.invoke({
        "step_index": 0, "proof_type": "file_written", "proof_path": fake_path
    })
    assert result["status"] == "error"
    assert "propose_file_change" in result["error"]


def test_file_written_proof_passes_after_propose(tmp_path):
    from src.agents.coding.tools import dev_plan_create, dev_plan_step_done
    from src.agents.coding.pending import recent_tools
    dev_plan_create.invoke({"steps": ["Créer composant"]})
    written = tmp_path / "component.tsx"
    written.write_text("export default function Comp() { return <div>ok</div>; }")
    recent_tools.record(
        "propose_file_change",
        {"path": str(written)},
        {"status": "accepted", "path": str(written)},
    )
    result = dev_plan_step_done.invoke({
        "step_index": 0, "proof_type": "file_written", "proof_path": str(written)
    })
    assert result["status"] == "ok"


# ── _REPETITION_EXEMPT membership ─────────────────────────────────────────────

def test_repetition_exempt_excludes_read_tools():
    """Read tools must NOT be in _REPETITION_EXEMPT — that's what the guard is for."""
    from src.agents.coding.specialist import _REPETITION_EXEMPT
    read_tools = {"local_read_file", "notebook_read", "local_grep", "local_glob"}
    overlap = read_tools & _REPETITION_EXEMPT
    assert not overlap, f"Read tools in exempt set (would bypass guard): {overlap}"


def test_repetition_exempt_contains_write_tools():
    """Write/plan tools must be in _REPETITION_EXEMPT — blocking them would break the agent."""
    from src.agents.coding.specialist import _REPETITION_EXEMPT
    required = {"dev_plan_create", "dev_plan_step_done", "propose_file_change", "shell_run"}
    missing = required - _REPETITION_EXEMPT
    assert not missing, f"Write/plan tools missing from exempt set: {missing}"


# ── Épuiser toutes les clés d'un fournisseur AVANT d'en changer ─────────────
# Un quota Ollama se compte PAR COMPTE : plusieurs clés valent plusieurs essais.
# Ce n'est qu'une fois toutes les clés d'un fournisseur mortes qu'on bascule —
# annoncé à l'écran, et inscrit dans `settings.llm_backend` pour que /config et
# /backend ne mentent pas sur le fournisseur réellement utilisé.

class _LLMToujours429:
    def __init__(self):
        self.appels = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.appels += 1
        raise RuntimeError("429 you have reached your weekly usage limit")


def test_une_erreur_de_quota_n_est_jamais_lue_comme_un_probleme_de_contexte():
    """La cause du bug : le message de Gemini contient `token` et `exceed`, mots
    du filtre « contexte ». Testé en second, ce filtre confisquait l'erreur et
    interrompait la rotation des clés."""
    from src.llm.rotation import classer_erreur

    gemini = RuntimeError(
        "429 RESOURCE_EXHAUSTED ... generate_content_free_tier_input_token_count"
        " ... You exceeded your current quota")

    # Les deux familles de marqueurs matchent ce message : seul l'ordre tranche.
    assert any(k in str(gemini).lower() for k in ("context", "length", "token", "exceed"))
    assert classer_erreur(gemini) == "quota"


def test_un_401_n_est_pas_lu_comme_un_depassement_de_contexte():
    """« 400 » est un marqueur de contexte et happerait « 401 » sans l'ordre."""
    from src.llm.rotation import classer_erreur

    assert classer_erreur(RuntimeError("401 Unauthorized")) == "cle_morte"


def test_le_specialist_ne_reclasse_pas_les_erreurs_lui_meme():
    """Une seconde table de marqueurs re-divergerait de src/llm/rotation.py."""
    import inspect

    from src.agents.coding import specialist

    source = inspect.getsource(specialist)

    assert "rotation.classer_erreur" in source
    for disparu in ("_RATE_LIMIT_MARKERS", "_BAD_KEY_MARKERS", "_SERVER_ERR_MARKERS"):
        assert disparu not in source, f"{disparu} recopié dans le specialist"


# ── Une question ne doit PAS terminer le run ─────────────────────────────────
# Le spécialiste posait ses questions en texte, ce qui terminait le run : la
# réponse de l'utilisateur arrivait à un run NEUF, plan vide et fichiers déjà
# écrits oubliés. `ask_clarification` bloque, ATTEND, et rend la main à la MÊME
# boucle avec tout son contexte.

class _FauxLLM:
    """Rejoue une suite de réponses ; la dernière est répétée indéfiniment."""

    def __init__(self, reponses):
        self._reponses = list(reponses)
        self.appels = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        from langchain_core.messages import AIMessage
        self.appels += 1
        reponse = self._reponses[min(self.appels - 1, len(self._reponses) - 1)]
        if isinstance(reponse, str):
            return AIMessage(content=reponse)
        message = AIMessage(content="")
        message.tool_calls = reponse
        return message


class _FauxOutil:
    def __init__(self, name, resultat):
        self.name = name
        self._resultat = resultat
        self.appels = []

    def invoke(self, args):
        self.appels.append(args)
        return self._resultat


@pytest.fixture
def agent_isole(monkeypatch):
    """Fait tourner la vraie boucle sans LLM, sans Chroma et sans disque."""
    from src.agents.coding import specialist
    from src.agents.coding import tool_retriever as retriever_mod
    from src.agents.coding.pending import dev_plan
    from src.llm import key_pool

    class _FauxRetriever:
        def __init__(self, tools, k=8):
            self._tools = list(tools)

        def get(self, query):
            return self._tools

    class _PoolVide:
        def next_healthy(self, provider):
            return ""

        def keys_for(self, provider):
            return []

        def mark_rate_limited(self, provider, key):
            pass

        def mark_bad_key(self, provider, key):
            pass

    monkeypatch.setattr(retriever_mod, "CodingToolRetriever", _FauxRetriever)
    monkeypatch.setattr(specialist, "_retriever_cache", None)
    monkeypatch.setattr(specialist, "_persist_session_memory", lambda *a, **k: None)
    monkeypatch.setattr(key_pool, "get_pool", lambda: _PoolVide())
    dev_plan._steps = []

    def _lancer(llm, outils=()):
        monkeypatch.setattr(specialist, "_get_coding_llm", lambda: llm)
        monkeypatch.setattr(specialist, "_get_coding_tools", lambda: list(outils))
        return specialist._run("crée un site next js complet")

    return _lancer


def test_une_question_ne_termine_pas_le_run(agent_isole):
    """Le run se poursuit avec les réponses, dans la MÊME boucle."""
    questionnaire = _FauxOutil("ask_clarification",
                               {"status": "answered",
                                "answers": {"Quelles dépendances ?": "toutes"}})
    llm = _FauxLLM([
        [{"name": "ask_clarification",
          "args": {"questions": [{"question": "Quelles dépendances ?",
                                  "choices": ["toutes", "minimales"]}]},
          "id": "1"}],
        "Dépendances retenues : toutes. Suite du plan.",
    ])

    resultat = agent_isole(llm, [questionnaire])

    assert questionnaire.appels, "le questionnaire n'a pas été appelé"
    assert llm.appels == 2, "la boucle ne s'est pas poursuivie après la réponse"
    assert "Suite du plan" in resultat


def test_l_outil_de_question_est_disponible_pour_le_specialiste():
    """Sans lui, le modèle n'a d'autre choix que le texte libre — le bug d'origine."""
    from src.agents.coding.specialist import _get_coding_tools

    assert "ask_clarification" in {t.name for t in _get_coding_tools()}


def test_l_outil_de_question_est_toujours_propose_au_modele():
    """Le retriever ne sélectionne que quelques outils par tour : si celui-ci peut
    disparaître, le modèle retombe sur le texte libre au pire moment."""
    from src.agents.coding.tool_retriever import _ALWAYS_INCLUDED

    assert "ask_clarification" in _ALWAYS_INCLUDED


def test_le_prompt_dirige_vers_l_outil_et_interdit_le_texte_libre():
    """Trois propriétés, pas une tournure : le prompt a été réécrit une fois et
    ce test tombait sur la reformulation alors que la consigne était intacte."""
    from src.agents.coding.prompts.base import BASE_PROMPT

    assert "ask_clarification" in BASE_PROMPT
    assert "BLOQUE" in BASE_PROMPT and "ATTEND" in BASE_PROMPT
    assert "TERMINE le run" in BASE_PROMPT       # pourquoi le texte libre est interdit
    assert "JAMAIS une question en texte libre" in BASE_PROMPT


def test_l_ui_bloque_et_rend_les_reponses_a_la_boucle():
    """Le handler doit appeler le questionnaire ET renvoyer les réponses comme
    résultat d'outil — sinon la boucle repart sans savoir ce qui a été répondu."""
    import inspect

    from src.ui import streaming

    source = inspect.getsource(streaming)
    bloc = source[source.index('elif tool_name == "ask_clarification"'):]
    bloc = bloc[:bloc.index("elif tool_name ==", 10)]

    assert "ask_user_questions" in bloc
    assert '"answers": _answers' in bloc


# ── Une chaîne n'est pas une liste de questions ──────────────────────────────
# Le modèle a passé `questions="Toutes les sections…"`. `ask_user_questions`
# itère sur son argument : Python itère volontiers sur une chaîne, et le
# terminal s'est retrouvé à poser 1312 questions d'UN CARACTÈRE chacune.
# La validation appartient à la frontière — là où le terminal se bloque —
# jamais au consommateur.

def test_une_chaine_devient_une_seule_question():
    from src.agents.coding.tools import normaliser_questions

    assert normaliser_questions("Toutes les sections ?") == [
        {"question": "Toutes les sections ?"}]


def test_une_chaine_ne_produit_jamais_une_question_par_caractere():
    """Le bug exact : 19 caractères devenaient 19 questions."""
    from src.agents.coding.tools import normaliser_questions

    assert len(normaliser_questions("Toutes les sections")) == 1


@pytest.mark.parametrize("brut", [None, 42, 3.5, {"question": "x"}])
def test_un_type_impossible_est_refuse_avec_le_format_attendu(brut):
    from src.agents.coding.tools import normaliser_questions

    with pytest.raises(ValueError, match="liste"):
        normaliser_questions(brut)


@pytest.mark.parametrize("brut", [[], [{}], [""], [{"question": "  "}]])
def test_une_liste_sans_question_exploitable_est_refusee(brut):
    from src.agents.coding.tools import normaliser_questions

    with pytest.raises(ValueError, match="Aucune question"):
        normaliser_questions(brut)


def test_le_nombre_de_questions_est_plafonne():
    """1312 questions n'est pas une clarification, c'est un blocage."""
    from src.agents.coding.tools import MAX_QUESTIONS, normaliser_questions

    # À la limite exacte : passe.
    normaliser_questions([f"q{i} ?" for i in range(MAX_QUESTIONS)])
    with pytest.raises(ValueError, match="maximum"):
        normaliser_questions([f"q{i} ?" for i in range(MAX_QUESTIONS + 1)])


def test_les_formes_valides_traversent_sans_perte():
    from src.agents.coding.tools import normaliser_questions

    assert normaliser_questions(["A ?", "B ?"]) == [{"question": "A ?"}, {"question": "B ?"}]
    assert normaliser_questions([{"question": "X ?", "choices": ["1", "2"]}]) == [
        {"question": "X ?", "choices": ["1", "2"]}]


def test_l_outil_rend_une_erreur_exploitable_au_lieu_de_bloquer():
    from src.agents.coding.tools import ask_clarification

    resultat = ask_clarification.invoke({"questions": []})

    assert resultat["status"] == "error"
    assert "question" in resultat["reason"].lower()


def test_l_ui_valide_avant_d_ouvrir_le_questionnaire():
    """La garde doit précéder `ask_user_questions` : après, le terminal est pris."""
    import inspect

    from src.ui import streaming

    source = inspect.getsource(streaming)
    bloc = source[source.index('elif tool_name == "ask_clarification"'):]
    bloc = bloc[:bloc.index("elif tool_name ==", 10)]

    assert bloc.index("normaliser_questions") < bloc.index("ask_user_questions")


# ── Un refus doit venir de l'utilisateur, jamais d'une pile vide ─────────────
# `propose_file_change` échoue SANS rien déposer quand aucun plan n'est actif.
# La revue trouvait alors la pile vide et rendait ("reject") — donc l'agent
# recevait « L'utilisateur a refusé ce changement ». Il a réessayé huit fois,
# avec des contenus différents, contre un utilisateur qui n'avait rien vu.

def test_une_pile_vide_ne_produit_pas_un_refus_utilisateur():
    from src.agents.coding.pending import pending_changes
    from src.ui.review import review_single_latest

    pending_changes.clear()
    action, _ = review_single_latest()

    assert action == "nothing", "une pile vide ne doit jamais valoir un refus"
    assert action != "reject"


def test_proposer_sans_plan_ne_depose_rien_et_le_dit():
    """La cause : l'outil rend une erreur, et rien n'entre dans la pile."""
    from src.agents.coding.pending import dev_plan, pending_changes
    from src.agents.coding.tools import propose_file_change

    dev_plan._steps = []
    pending_changes.clear()

    resultat = propose_file_change.invoke(
        {"path": "/tmp/x.ts", "content": "x", "description": "d"})

    assert resultat["status"] == "error"
    assert "dev_plan_create" in resultat["error"]
    assert len(pending_changes) == 0


def test_l_ui_ne_relit_pas_une_proposition_en_erreur():
    """Relire une erreur, c'est chercher dans une pile vide — et fabriquer un refus."""
    import inspect

    from src.ui import streaming

    source = inspect.getsource(streaming)
    bloc = source[source.index('elif tool_name in ("propose_file_change", "edit_file")'):]
    bloc = bloc[:bloc.index("elif tool_name ==", 10)]

    assert 'result.get("status") == "error"' in bloc
    assert bloc.index('status") == "error"') < bloc.index("review_single_latest")


def test_le_message_d_absence_dit_que_l_utilisateur_n_a_rien_refuse():
    import inspect

    from src.ui import streaming

    source = inspect.getsource(streaming)
    bloc = source[source.index('elif action == "nothing"'):][:800]

    assert "RIEN refusé" in bloc
    assert "dev_plan_create" in bloc


# ── Budget d'itérations ──────────────────────────────────────────────────────
# Une landing page de 30 fichiers coûte ~55 itérations : 11 d'audit, 5 de
# scaffold, 30 écritures, 8 validations d'étape, 1 build. À 35, la tâche
# mourait avant le premier dev_plan_step_done — donc sans cocher une seule
# étape, et la reprise repartait de zéro.

def test_le_budget_couvre_un_projet_reel():
    from src.agents.coding.specialist import _MAX_ITERATIONS

    assert _MAX_ITERATIONS >= 60, (
        "budget insuffisant : un projet de 30 fichiers en demande ~55")


def test_le_chat_libre_n_est_pas_moins_doté_qu_une_phase_de_build():
    """`/build` accorde 80 itérations PAR PHASE ; le chat libre reçoit la tâche
    ENTIÈRE. Lui en donner moins qu'à une seule phase n'a aucun sens."""
    from src.agents.coding.build_runner import _PHASE_ITER_BUDGET
    from src.agents.coding.specialist import _MAX_ITERATIONS

    assert _MAX_ITERATIONS >= _PHASE_ITER_BUDGET["ollama_cloud"]


def test_l_override_de_phase_reste_prioritaire():
    """`/build` doit continuer à imposer SON budget, plus petit ou plus grand."""
    import inspect

    from src.agents.coding import specialist

    source = inspect.getsource(specialist._run)

    assert "_phase_max_iterations if _phase_max_iterations is not None" in source


# ── /build : pré-scaffold et détection d'échec ───────────────────────────────
# Le dossier de transit s'appelait `.scaffold`. npm refuse tout nom de paquet
# commençant par un point : les CINQ commandes échouaient systématiquement, le
# specialist devait tout refaire à la main, et la détection de boucle finissait
# par abattre la phase.

@pytest.mark.parametrize("framework", ["next", "vite-react", "svelte", "astro", "vue"])
def test_le_dossier_de_transit_est_un_nom_npm_valide(framework):
    import re

    from src.agents.coding.build_runner import _FRAMEWORK_SCAFFOLD_CMD, SCAFFOLD_DIRNAME

    assert re.fullmatch(r"[a-z0-9][a-z0-9._-]*", SCAFFOLD_DIRNAME), (
        f"{SCAFFOLD_DIRNAME!r} sera refusé par npm (ni point ni underscore en tête)")
    assert SCAFFOLD_DIRNAME in _FRAMEWORK_SCAFFOLD_CMD[framework]


def test_aucune_commande_ne_scaffolde_dans_un_dossier_cache():
    from src.agents.coding.build_runner import _FRAMEWORK_SCAFFOLD_CMD

    for framework, cmd in _FRAMEWORK_SCAFFOLD_CMD.items():
        assert ".scaffold" not in cmd, f"{framework} repasse par un nom interdit"


def test_un_echec_du_specialist_est_reconnu_par_build():
    """La sentinelle, pas une phrase. Reformuler un message rendait `/build`
    aveugle : il a compté 4 phases réussies dont 3 n'avaient rien écrit."""
    from src.agents.coding.build_runner import _PHASE_FAILED_MARKERS
    from src.agents.coding.specialist import ECHEC_PREFIXE

    for message in [
        ECHEC_PREFIXE + " Toutes les clés de « ollama_cloud » sont épuisées.",
        ECHEC_PREFIXE + " Aucun fournisseur LLM n'a répondu après 3 tentatives.",
        ECHEC_PREFIXE + " Tâche interrompue (boucle détectée).",
    ]:
        assert any(m in message.lower() for m in _PHASE_FAILED_MARKERS), message


def test_un_resultat_normal_n_est_pas_pris_pour_un_echec():
    from src.agents.coding.build_runner import _PHASE_FAILED_MARKERS

    succes = "Composants créés : Hero.tsx, Navbar.tsx, Footer.tsx. Build vert."

    assert not any(m in succes.lower() for m in _PHASE_FAILED_MARKERS)


def test_tous_les_echecs_durs_portent_la_sentinelle():
    """Un retour d'échec sans sentinelle serait compté comme une phase réussie."""
    import inspect

    from src.agents.coding import specialist

    source = inspect.getsource(specialist)
    # TOUTES les lignes, pas la première : le premier `return` portait la
    # sentinelle et le second non — le test passait, et `/build` comptait
    # toujours des phases mortes comme réussies.
    fautives = [
        l.strip() for l in source.splitlines()
        if l.lstrip().startswith(("return (", "return \""))
        and any(x in l for x in ("Toutes les clés de", "Aucun fournisseur LLM",
                                 "Tâche interrompue", "Le modèle a refusé"))
        and "ECHEC_PREFIXE" not in l
    ]

    assert not fautives, f"retours d'échec sans sentinelle : {fautives}"


def test_le_message_reel_d_epuisement_porte_la_sentinelle():
    """Le cas exact vécu : phases 3 et 4 mortes, comptées comme réussies."""
    from src.agents.coding.build_runner import _PHASE_FAILED_MARKERS
    from src.agents.coding.specialist import ECHEC_PREFIXE

    reel = (ECHEC_PREFIXE + " Toutes les clés de « ollama_cloud » sont "
            "épuisées ou en cooldown (6 clé(s) configurée(s)).")

    assert any(m in reel.lower() for m in _PHASE_FAILED_MARKERS)


# ── Bascule de fournisseur : annoncée, automatique, et persistée ─────────────
# Toutes les clés d'un fournisseur sont épuisées AVANT d'en changer — un quota
# Ollama se compte par compte, donc plusieurs clés valent plusieurs essais.
# Ensuite on bascule sans demander, mais en l'annonçant, et `settings.llm_backend`
# suit : sans ça `/config` et `/backend` afficheraient le fournisseur mort.

@pytest.fixture
def pool_multi(monkeypatch):
    from src.llm import key_pool

    class _Pool:
        def __init__(self):
            self.cles = {"ollama_cloud": ["o1", "o2"], "gemini": ["g1"], "mistral": ["m1"]}
            self.mortes: set[str] = set()

        def keys_for(self, p):
            return list(self.cles.get(p, []))

        def all_healthy(self, p):
            return [k for k in self.cles.get(p, []) if k not in self.mortes]

        def next_healthy(self, p):
            saines = self.all_healthy(p)
            return saines[0] if saines else ""

        def mark_rate_limited(self, p, k):
            self.mortes.add(k)

        def mark_bad_key(self, p, k):
            self.mortes.add(k)

    pool = _Pool()
    monkeypatch.setattr(key_pool, "get_pool", lambda: pool)
    monkeypatch.setattr(key_pool, "get_fallback_order",
                        lambda: ["ollama_cloud", "gemini", "mistral"])
    from src.infra.settings import settings
    monkeypatch.setattr(settings, "llm_backend", "ollama_cloud")
    return pool


def _lancer_epuise(monkeypatch, pool, evenements):
    from src.agents.coding import specialist
    from src.agents.coding import tool_retriever as retriever_mod
    from src.agents.coding.pending import dev_plan

    class _Retriever:
        def __init__(self, tools, k=8):
            self._t = list(tools)

        def get(self, q):
            return self._t

    llm = _LLMToujours429()
    monkeypatch.setattr(retriever_mod, "CodingToolRetriever", _Retriever)
    monkeypatch.setattr(specialist, "_retriever_cache", None)
    monkeypatch.setattr(specialist, "_persist_session_memory", lambda *a, **k: None)
    monkeypatch.setattr(specialist, "_get_coding_llm", lambda: llm)
    monkeypatch.setattr(specialist, "_get_coding_tools", lambda: [])
    import src.llm.models as models
    monkeypatch.setattr(models, "make_coding_llm_with_key", lambda p, k: llm)
    specialist.set_progress_callback(
        lambda nom, args, res=None: evenements.append((nom, args)) or None)
    dev_plan._steps = []
    try:
        return specialist._run("corrige un bug")
    finally:
        specialist.set_progress_callback(None)


def test_toutes_les_cles_avant_de_changer_de_fournisseur(monkeypatch, pool_multi):
    evenements: list = []
    _lancer_epuise(monkeypatch, pool_multi, evenements)

    assert {"o1", "o2"} <= pool_multi.mortes, "les 2 clés ollama doivent être tentées"
    bascules = [a for n, a in evenements if n == "specialist:backend_switch"]
    assert bascules, "aucune bascule de fournisseur"
    assert bascules[0]["from"] == "ollama_cloud"


def test_la_bascule_est_annoncee(monkeypatch, pool_multi):
    """Automatique, mais jamais silencieuse."""
    evenements: list = []
    _lancer_epuise(monkeypatch, pool_multi, evenements)

    assert any(n == "specialist:backend_switch" for n, _ in evenements)


def test_le_backend_courant_suit_la_bascule(monkeypatch, pool_multi):
    """`/config` et `/backend` doivent refléter le fournisseur réellement utilisé."""
    from src.infra.settings import settings

    _lancer_epuise(monkeypatch, pool_multi, [])

    assert settings.llm_backend != "ollama_cloud"
    assert settings.llm_backend in ("gemini", "mistral")


def test_l_ui_affiche_la_bascule_et_la_rotation():
    """Les deux événements existaient et n'étaient rendus nulle part."""
    import inspect

    from src.ui import streaming

    source = inspect.getsource(streaming)

    assert 'tool_name == "specialist:backend_switch"' in source
    assert 'tool_name == "specialist:key_rotate"' in source


def test_la_revue_notebook_ne_fabrique_pas_non_plus_de_refus():
    """Même contrat que la revue de fichier : pile vide ≠ refus utilisateur."""
    from src.agents.notebook.tools import pending_cell_changes
    from src.ui.review import review_latest_cell_change

    while pending_cell_changes.pop_latest() is not None:
        pass
    action, _ = review_latest_cell_change()

    assert action == "nothing"
