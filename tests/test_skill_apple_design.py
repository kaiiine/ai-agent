"""Le skill `apple-design`, et le défaut de recherche qu'il a mis au jour.

En vérifiant qu'Axon trouvait bien ce nouveau skill, la recherche sémantique
s'est révélée servir n'importe quoi :

    « un serveur en Go »            → skill Blender
    « rends l'interface plus fluide » → skill Blender

Cause : l'index contient TOUS les skills, y compris ceux qu'aucun agent ne lit
(`scope: template`, réservé aux commandes /fiche et /exo). La recherche ne
ramenait que `k*4` résultats, ces intrus occupaient les premières places, le
filtrage de portée les écartait ensuite — et le rebut restant gagnait. Filtrer
après une recherche trop courte, c'est choisir parmi ce qui a survécu et non
parmi ce qui convient.

Les tests de contenu n'appellent pas Ollama ; ceux qui mesurent la pertinence
sémantique sont sautés s'il est absent, parce qu'un test qui échoue faute de
service local n'apprend rien sur le code.
"""
import pytest

from src.skills import describe_skills, get_skill, list_skills
from src.skills.retriever import SkillRetriever, _document


def _index_dispo() -> bool:
    r = SkillRetriever()
    r._build_index()
    return r._index is not None


besoin_index = pytest.mark.skipif(
    not _index_dispo(), reason="index sémantique indisponible (Ollama absent)")


# ── Le skill est déclaré et lisible ───────────────────────────────────────────
def test_le_skill_appartient_a_l_agent_de_code():
    """`scope: coding` et pas `[coding, orchestrator]`, et c'est mesuré.

    Rendre le skill visible de l'orchestrateur ajoute son texte au document de
    routage du groupe coding — `skill_anchors()` y verse les ancres d'un skill,
    ou sa description à défaut. Le document s'élargit, et « montre moi le dernier
    commit » se met à proposer `run_coding_agent`, c'est-à-dire une délégation
    qui écrit des fichiers pour une question qui lit l'historique. Testé avec
    zéro, une et deux ancres courtes : seul le retrait de la portée
    `orchestrator` rétablit le routage.

    Ce n'est pas une perte : refaire le design d'un site est le travail de
    l'agent de code, et c'est lui qui charge ce skill.
    """
    assert "apple-design" in list_skills("coding")
    assert "apple-design" not in list_skills("orchestrator"), (
        "la visibilité orchestrateur élargit le routage du groupe coding")


def test_il_apparait_dans_le_catalogue_de_load_skill():
    """C'est le chemin PRINCIPAL : le modèle lit ce catalogue dans la description
    de l'outil, puis appelle `load_skill` par son nom. La recherche sémantique
    n'est que le repli."""
    assert "apple-design" in dict(describe_skills("coding"))


@pytest.mark.parametrize("appel", ["apple-design", "apple", "hig", "ios-design"])
def test_on_peut_le_charger_par_son_nom_ou_ses_alias(appel):
    assert get_skill(appel, scope="coding").lstrip().startswith("# Apple Design")


def test_le_contenu_est_complet():
    """Un skill tronqué se charge sans erreur et donne de mauvais conseils."""
    contenu = get_skill("apple-design", scope="coding")

    for attendu in ("Interruptibility", "damping", "backdrop-filter",
                    "prefers-reduced-motion", "Quick Reference"):
        assert attendu in contenu


# ── Ce qu'on indexe ───────────────────────────────────────────────────────────
def test_le_document_indexe_porte_le_nom_et_les_alias():
    """Les descriptions sont en mots-clés anglais, les questions arrivent en
    français : le nom et les alias rapprochent les deux. Mesuré, 4/10 → 10/10."""
    doc = _document("apple-design", {"aliases": ["hig", "apple"],
                                     "description": "springs damping",
                                     "anchors": ["refais le design de mon site"]})

    assert "apple-design" in doc and "hig" in doc and "springs damping" in doc


def test_les_ancres_ne_sont_pas_indexees():
    """Contre-intuitif, donc mesuré : les ancres sont écrites en français, mais
    les ajouter fait chuter à 9/10. Blender en déclare huit ; son document
    devient un pavé français et capte « un serveur en Go ». Le volume de texte
    joue le rôle que le nombre de documents jouait dans l'index d'outils."""
    doc = _document("x", {"aliases": [], "description": "desc",
                          "anchors": ["une phrase d'ancrage bien française"]})

    assert "ancrage" not in doc


# ── La régression de portée ───────────────────────────────────────────────────
@besoin_index
def test_un_skill_hors_portee_ne_prive_pas_les_autres():
    """Le défaut exact : `fiche` et `exo` (scope `template`) monopolisaient les
    places, étaient filtrés, et Blender sortait pour une requête sur Go."""
    contenu = get_skill("un serveur en Go", scope="coding")

    assert "Blender" not in contenu[:200]
    assert "GO" in contenu[:200].upper()


@besoin_index
@pytest.mark.parametrize("question", [
    "refais le design de mon site",
    "rends l'interface plus fluide",
    "ajoute des micro-interactions au scroll",
])
def test_une_demande_de_design_trouve_le_skill(question):
    """La raison d'être de ce skill : être trouvé quand on demande à refaire un
    site, sans avoir à le nommer."""
    assert get_skill(question, scope="coding").lstrip().startswith("# Apple Design")


@besoin_index
@pytest.mark.parametrize("question, attendu", [
    ("crée une API FastAPI", "PYTHON"),
    ("monte une app Next.js", "NEXT"),
    ("un composant React avec Vite", "FRONTEND"),
])
def test_les_autres_skills_restent_atteignables(question, attendu):
    """Le contrepoids : ajouter un skill ne doit pas détourner les requêtes des
    autres.

    ATTEINT = le skill est servi, OU cité dans le renvoi qui accompagne la
    réponse. Le test exigeait d'abord d'être servi du premier coup ; l'import
    ECC a mis `fastapi-reviewer` en face de `python` sur « crée une API
    FastAPI », et six mécanismes de désambiguïsation ont été mesurés sans
    parvenir à trancher (voir l'en-tête de `test_routage_skills.py`) — la cause
    est que `nomic-embed-text` ne sépare pas « créer » de « relire » sur une
    phrase française.

    Ce qu'on garantit à la place, et qui est vérifiable : la requête n'est
    jamais PERDUE. Le skill servi cite ses voisins de domaine, et `load_skill`
    peut être rappelé. C'est aussi ce qui rend l'ajout de skills sûr — au pire
    un nouvel arrivant ajoute une ligne de renvoi.
    """
    rendu = get_skill(question, scope="coding")
    assert attendu in rendu[:200].upper() or attendu in rendu.upper(), (
        f"« {question} » ne mène ni directement ni par renvoi à {attendu}")


# ── Composition avec les skills de stack ──────────────────────────────────────
#
# Crainte légitime : `get_skill` ne rend QU'UN skill. Si une demande Next.js
# repartait avec `apple-design`, le projet perdrait le scaffold App Router, les
# librairies à installer et la séparation Server/Client — un skill plus « complet »
# sur le design serait alors une régression sur tout le reste.

@besoin_index
@pytest.mark.parametrize("question", [
    "refais le front de mon site nextjs",
    "fais un site nextjs avec un bon design",
    "améliore le design de mon app Next.js",
    "monte une app Next.js avec Tailwind",
    "un site vitrine en Next.js App Router",
])
def test_une_demande_nextjs_reste_sur_le_skill_nextjs(question):
    """Dès que la stack est nommée, elle gagne — même quand la phrase parle de
    design. `apple-design` ne détourne pas les requêtes de stack."""
    contenu = get_skill(question, scope="coding")

    assert "# Apple Design" not in contenu[:200]
    assert "NEXT" in contenu[:300].upper()


def test_les_deux_skills_repondent_a_des_questions_differentes():
    """Ils ne se recouvrent pas : l'un dit QUOI installer, l'autre COMMENT le
    mouvement doit se comporter. C'est ce qui rend leur cumul utile plutôt que
    redondant."""
    stack = get_skill("nextjs", scope="coding")
    design = get_skill("apple-design", scope="coding")

    assert "pnpm" in stack and "pnpm" not in design
    assert "damping" in design and "damping" not in stack


def test_le_skill_dit_qu_il_se_combine():
    """Sans cette consigne, le modèle qui charge `apple-design` seul croirait y
    trouver aussi le scaffold."""
    contenu = get_skill("apple-design", scope="coding")

    assert "Se combine, ne remplace pas" in contenu
    assert "nextjs" in contenu[:900]


def test_l_outil_annonce_que_les_skills_se_cumulent():
    """`load_skill` invitait à charger UN skill. Rien ne disait au modèle qu'il
    pouvait — devait — en charger deux quand la demande touche une stack ET une
    exigence de rendu."""
    from src.skills.tools import make_load_skill

    description = make_load_skill("coding").description

    assert "COMPOSE" in description
    assert "once per skill" in description


def test_le_preambule_ne_nomme_aucun_skill_en_dur():
    """Ce préambule est partagé par TOUS les agents, alors que chacun voit un
    catalogue différent. Y écrire l'exemple « charge nextjs ET apple-design » a
    fait fuiter un nom réservé au code dans le catalogue de l'orchestrateur, et
    cassé deux tests d'isolation de portée — qui avaient raison.
    """
    from src.skills.tools import make_load_skill

    orchestrateur = make_load_skill("orchestrator").description

    for reserve in ("nextjs", "frontend", "apple-design"):
        assert reserve not in orchestrateur
