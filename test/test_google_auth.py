"""Les secrets Google : qui peut les lire.

Ce fichier n'existait pas. Mesuré sur la machine avant correction :

    0644  autrui peut lire  ~/.ai-agent/google_token.pickle
    0755  autrui peut lire  ~/.ai-agent/
    0644  autrui peut lire  gcp-oauth.keys.json
    0600  autrui NE PEUT PAS  ~/.axon/mcp_servers.json

Le dernier montre que la convention existait déjà dans le projet ; ce module ne
la suivait pas. Ce n'était pas un choix mais l'umask par défaut appliqué à un
`open(..., "wb")` sans mode.

Le jeton porte `gmail.send`, `documents`, `spreadsheets`, `drive.file` et
`calendar` : le laisser lisible revient à exposer la boîte mail et le Drive, pas
seulement une session. Le fichier de clés client, lui, est bien gitignoré et non
suivi — le dépôt était propre, le défaut était local.
"""
import os
import stat

import pytest


def _mode(chemin) -> int:
    return chemin.stat().st_mode & 0o777


def test_un_secret_est_ecrit_en_0600_des_la_creation(tmp_path):
    """Écrire puis `chmod` laisserait le secret lisible entre les deux appels ;
    le mode est donné à `os.open`, donc appliqué à la création."""
    from src.infra.google_auth import _ouvrir_prive

    cible = tmp_path / "jeton.pickle"
    with _ouvrir_prive(cible) as f:
        f.write(b"secret")

    assert _mode(cible) == 0o600
    assert cible.read_bytes() == b"secret"


def test_un_secret_deja_trop_ouvert_est_resserre(tmp_path):
    """Le rattrapage est ce qui compte pour l'existant : sans lui, le fichier
    écrit en 0644 avant la correction le resterait indéfiniment."""
    from src.infra.google_auth import _restreindre

    cible = tmp_path / "jeton.pickle"
    cible.write_bytes(b"secret")
    cible.chmod(0o644)

    _restreindre(cible)

    assert _mode(cible) == 0o600


@pytest.mark.parametrize("mode_initial", [0o644, 0o664, 0o666, 0o604, 0o640])
def test_tous_les_droits_de_groupe_et_d_autrui_tombent(tmp_path, mode_initial):
    from src.infra.google_auth import _restreindre

    cible = tmp_path / "jeton"
    cible.write_bytes(b"x")
    cible.chmod(mode_initial)

    _restreindre(cible)

    assert not _mode(cible) & (stat.S_IRWXG | stat.S_IRWXO)


def test_les_droits_du_proprietaire_sont_conserves(tmp_path):
    """Resserrer ne doit pas rendre le fichier illisible par AXON lui-même."""
    from src.infra.google_auth import _restreindre

    cible = tmp_path / "jeton"
    cible.write_bytes(b"x")
    cible.chmod(0o644)

    _restreindre(cible)

    assert _mode(cible) & stat.S_IRUSR


def test_un_fichier_deja_prive_n_est_pas_touche(tmp_path):
    from src.infra.google_auth import _restreindre

    cible = tmp_path / "jeton"
    cible.write_bytes(b"x")
    cible.chmod(0o600)
    avant = cible.stat().st_mtime_ns

    _restreindre(cible)

    assert _mode(cible) == 0o600
    assert cible.stat().st_mtime_ns == avant


def test_un_fichier_absent_ne_fait_pas_echouer_le_demarrage(tmp_path):
    """`_restreindre` est appelé sur le chemin des identifiants avant lecture :
    il ne doit jamais transformer une absence en exception."""
    from src.infra.google_auth import _restreindre

    _restreindre(tmp_path / "jamais-cree")


def test_le_repertoire_du_jeton_n_est_pas_ouvert_a_autrui():
    """Un fichier en 0600 dans un répertoire listable reste protégé, mais le
    répertoire est créé en 0700 pour ne pas exposer l'existence des comptes
    branchés."""
    from src.infra.google_auth import TOKEN_PATH

    if not TOKEN_PATH.parent.exists():
        pytest.skip("aucun compte Google branché sur cette machine")

    assert not TOKEN_PATH.parent.stat().st_mode & stat.S_IRWXO


def test_le_jeton_reel_n_est_plus_lisible_par_autrui():
    """Le rattrapage ne s'applique qu'à l'usage ; ce test dit si la machine est
    encore exposée aujourd'hui."""
    from src.infra.google_auth import TOKEN_PATH, _restreindre

    if not TOKEN_PATH.exists():
        pytest.skip("aucun jeton Google sur cette machine")

    _restreindre(TOKEN_PATH)
    assert not TOKEN_PATH.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO)
