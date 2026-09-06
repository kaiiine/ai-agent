"""L'export Langfuse : le LOT construit, jamais l'envoi.

Ce qui porte les décisions est la construction — quelle action devient quoi,
avec quel niveau, sous quel identifiant. L'envoi est un POST, et aucun Langfuse
ne tourne ici : le tester donnerait l'illusion d'une vérification sans en être
une. Ce que ces tests garantissent, c'est qu'un export relancé ne fabrique pas
de doublons et qu'un refus attendu n'est pas peint comme une panne.
"""

import json

from src.infra import langfuse_export as export
from src.infra import trace


def _ligne(**champs) -> dict:
    base = {"run_id": "abc123", "seq": 1, "at": "2026-09-02T10:00:00+00:00",
            "source": "tui", "axon_sha": "03812f6aaaaa", "genre": trace.OUTIL,
            "outil": "shell_run", "cible": "ls", "policy": trace.AUTORISE,
            "resultat": trace.OK, "verification": trace.NON_VERIFIE,
            "erreur": "", "tokens_entree": 0, "tokens_sortie": 0,
            "latence_ms": 0, "backend": "", "modele": "", "extra": {}}
    return {**base, **champs}


def test_un_run_donne_une_trace_et_ses_observations():
    evenements = export.construire([
        _ligne(seq=1, genre=trace.ROUTE, intent="liste les fichiers"),
        _ligne(seq=2),
        _ligne(seq=3),
    ])
    types = [e["type"] for e in evenements]
    assert types == ["trace-create", "span-create", "span-create", "span-create"]
    assert evenements[0]["body"]["id"] == "abc123"
    assert evenements[0]["body"]["input"] == "liste les fichiers"
    assert all(e["body"]["traceId"] == "abc123" for e in evenements[1:])


def test_deux_runs_donnent_deux_traces():
    evenements = export.construire([_ligne(run_id="a"), _ligne(run_id="b")])
    assert [e["type"] for e in evenements] == [
        "trace-create", "span-create", "trace-create", "span-create"]


def test_les_identifiants_sont_deterministes():
    """Langfuse met à jour sur l'identifiant : c'est ce qui rend un export
    rejouable sans fabriquer de doublons."""
    lignes = [_ligne(seq=1), _ligne(seq=2)]
    premier = export.construire(lignes)
    second = export.construire(lignes)
    assert [e["body"]["id"] for e in premier] == [e["body"]["id"] for e in second]
    assert [e["body"]["id"] for e in premier] == ["abc123", "abc123-1", "abc123-2"]


def test_un_appel_llm_devient_une_generation_avec_son_usage():
    evenements = export.construire([_ligne(
        genre=trace.APPEL_LLM, outil="", backend="groq", modele="gpt-oss-20b",
        tokens_entree=12_731, tokens_sortie=180, latence_ms=1_500)])
    generation = evenements[-1]
    assert generation["type"] == "generation-create"
    assert generation["body"]["model"] == "gpt-oss-20b"
    assert generation["body"]["usage"] == {"input": 12_731, "output": 180,
                                           "unit": "TOKENS"}
    # La latence donne une fin : sans elle, la durée serait inventée.
    assert generation["body"]["endTime"] > generation["body"]["startTime"]


def test_sans_latence_la_fin_vaut_le_debut():
    corps = export.construire([_ligne(latence_ms=0)])[-1]["body"]
    assert corps["endTime"] == corps["startTime"]


def test_un_refus_est_un_avertissement_pas_une_erreur():
    """Bloqué veut dire que le garde a fait son travail. Le peindre en ERROR
    noierait les vraies pannes sous des refus attendus."""
    bloque = export.construire([_ligne(
        policy=trace.REFUSE, resultat=trace.BLOQUE)])[-1]
    assert bloque["body"]["level"] == "WARNING"


def test_une_panne_et_un_fichier_casse_sont_des_erreurs():
    for ligne in (_ligne(resultat=trace.ERREUR, erreur="tool_error"),
                  _ligne(genre=trace.VERIFICATION, verification="casse")):
        assert export.construire([ligne])[-1]["body"]["level"] == "ERROR"
    assert export.construire([_ligne()])[-1]["body"]["level"] == "DEFAULT"


def test_les_colonnes_d_axon_traversent():
    """C'est tout l'intérêt de l'export : Langfuse ne saurait pas les produire."""
    corps = export.construire([_ligne(
        genre=trace.ROUTE, groupes=[["calendar", 1]],
        outils_lies=["calendar_list_events"], policy=trace.REFUSE)])[-1]["body"]
    assert corps["metadata"]["groupes"] == [["calendar", 1]]
    assert corps["metadata"]["outils_lies"] == ["calendar_list_events"]
    assert corps["metadata"]["policy"] == trace.REFUSE


def test_une_ligne_sans_run_est_ignoree():
    """Sans identifiant de trace, Langfuse n'a nulle part où ranger l'observation."""
    assert export.construire([_ligne(run_id="")]) == []


def test_le_lot_est_serialisable():
    """Un objet non JSON glissé dans une colonne ferait échouer l'envoi entier,
    et l'échec arriverait chez Langfuse plutôt qu'ici."""
    json.dumps({"batch": export.construire([_ligne(extra={"lot": 3})])})


def test_sans_cles_rien_n_est_envoye(monkeypatch, capsys):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert export.exporter([_ligne()]) == 1
    assert "LANGFUSE_PUBLIC_KEY" in capsys.readouterr().out


def test_le_repere_evite_de_tout_renvoyer(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "REPERE", tmp_path / "repere.json")
    anciennes = [_ligne(at="2026-09-01T10:00:00+00:00")]
    export._poser_le_repere(anciennes)

    nouvelles = [_ligne(at="2026-09-03T10:00:00+00:00")]
    assert export._depuis_le_repere(anciennes + nouvelles) == nouvelles


def test_sans_repere_tout_part(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "REPERE", tmp_path / "absent.json")
    lignes = [_ligne()]
    assert export._depuis_le_repere(lignes) == lignes
