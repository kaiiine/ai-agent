"""La clé d'API doit réellement partir dans la requête.

`ChatOllama` déclare `extra="ignore"` : un `headers=…` passé à son constructeur
est silencieusement jeté. La requête partait alors sans autorisation, et le
client `ollama` signait avec l'identité machine — toujours le même compte, quel
que soit le nombre de clés. Seul `client_kwargs` atteint la requête.
"""

from __future__ import annotations

import pytest

from src.llm.models import _ollama_cloud_kwargs


def test_la_cle_voyage_dans_l_en_tete_d_autorisation():
    kwargs = _ollama_cloud_kwargs("MA-CLE")

    assert kwargs["headers"] == {"Authorization": "Bearer MA-CLE"}


def test_sans_cle_aucun_en_tete_n_est_fabrique():
    """Mieux vaut un 401 franc qu'un « Bearer None » qui ressemble à une clé."""
    assert "headers" not in _ollama_cloud_kwargs("")
    assert "headers" not in _ollama_cloud_kwargs(None)


def test_le_timeout_du_client_est_conserve():
    assert _ollama_cloud_kwargs("X")["timeout"] > 0


def test_chatollama_ignore_bel_et_bien_un_headers_direct():
    """Le piège lui-même, vérifié : si un jour ce test échoue, c'est que la
    bibliothèque accepte enfin `headers` — et la prudence de ce module pourra
    être réexaminée. Tant qu'il passe, `client_kwargs` reste le seul chemin."""
    from langchain_ollama import ChatOllama

    assert ChatOllama.model_config.get("extra") == "ignore"
    assert "headers" not in ChatOllama.model_fields

    llm = ChatOllama(model="x", base_url="https://ollama.com",
                     headers={"Authorization": "Bearer PIEGE"})

    assert not hasattr(llm, "headers")


@pytest.mark.parametrize("fabrique,args", [
    ("make_coding_llm_with_key", ("ollama_cloud", "CLE-TEST")),
    ("make_llm_ollama_cloud", ()),
])
def test_aucune_fabrique_ollama_ne_passe_headers_en_direct(fabrique, args):
    """Garde-fou de non-régression : rien ne doit revenir au chemin mort."""
    import inspect

    import src.llm.models as models

    source = inspect.getsource(getattr(models, fabrique))

    assert 'headers={"Authorization"' not in source, (
        f"{fabrique} repasse la clé par un kwarg que ChatOllama ignore"
    )


def test_le_module_entier_est_exempt_du_chemin_mort():
    import inspect

    import src.llm.models as models

    source = inspect.getsource(models)
    # La seule mention autorisée est celle de `_ollama_cloud_kwargs`, qui construit
    # le dictionnaire DESTINÉ à client_kwargs.
    lignes_fautives = [
        l.strip() for l in source.splitlines()
        if 'headers={"Authorization"' in l and "kwargs[" not in l
    ]

    assert not lignes_fautives, lignes_fautives
