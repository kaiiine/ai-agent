"""Détecter une écriture par sa FORME, et montrer ce qui sera écrit.

L'ancienne détection était une liste de chaînes littérales — `"sed -i"`,
`"cat >"`, `"tee /"`, `"echo > /"`. Deux défauts opposés, mesurés sur le même
fichier cible à travers `ssh` :

    ssh kaine "cat > ~/.ssh/config"          BLOQUÉ
    ssh kaine "echo x > ~/.ssh/config"       passait
    ssh kaine "printf 'x' > ~/.ssh/config"   passait
    ssh kaine "tee ~/.ssh/config"            passait

Elle bloquait la tournure idiomatique et laissait les autres : ni sûre, ni
utile. Et le message de refus renvoyait vers `edit_file`, qui ne prend qu'un
chemin LOCAL — pour un fichier distant, ce n'était pas une porte manquante mais
une porte impossible. Vécu : l'agent a créé une clé SSH sur le serveur
(`ssh-keygen` passait), puis s'est heurté au mur sur `~/.ssh/config` et a rendu
un tableau d'instructions à l'utilisateur.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.shell import autorisation

from src.agents.shell.ecriture import analyser_ecriture


# ── Détection : la forme, pas la ressemblance ────────────────────────────────
@pytest.mark.parametrize("commande", [
    "sed -i 's/a/b/' f.conf",
    "cat > f.conf",
    "cat >> f.conf",
    "echo x > f.conf",
    "printf 'Host github' > f.conf",
    "tee f.conf",
    "tee -a f.conf",
    "dd if=/dev/zero of=/dev/sda",
    "mon-binaire --opt > sortie.txt",
    "Set-Content -Path f.conf",
    "Out-File f.conf",
])
def test_toute_forme_d_ecriture_est_vue(commande):
    """Le point de la refonte : `printf`, `echo`, `tee` sans slash et un binaire
    quelconque échappaient tous à la liste littérale."""
    assert analyser_ecriture(commande) is not None, f"écriture manquée : {commande}"


@pytest.mark.parametrize("commande", [
    "ls -la", "cat f.conf", "grep -r motif .", "pytest -q",
    "pytest -q 2>&1", "make 2>&1 | tee",     # `2>&1` n'est pas une écriture
    "ls > /dev/null", "curl -s url",
    "git diff", "df -h", "",
])
def test_une_lecture_n_est_jamais_prise_pour_une_ecriture(commande):
    """Le risque symétrique : bloquer une lecture rendrait le shell inutile."""
    assert analyser_ecriture(commande) is None, f"faux positif : {commande}"


# ── Cas adversariaux : un `>` n'est pas toujours un opérateur ───────────────
#
# Une regex sur `>` a ses propres pièges, et la première version y est tombée :
# trois tournures sur neuf étaient mal lues. Un faux positif ne coûte pas rien —
# il BLOQUE une commande inoffensive en local, et réclame à distance une
# confirmation pour une écriture qui n'existe pas.
@pytest.mark.parametrize("commande", [
    'echo "a > b"',                  # `>` littéral entre guillemets
    "echo 'x > y' | grep x",         # idem, apostrophes
    'grep "a>b" fichier.txt',        # sans espaces autour
    'echo "2 > 1 est vrai"',         # phrase contenant l'opérateur
    'git log --grep="fix > perf"',   # dans une option
])
def test_un_chevron_cite_n_est_pas_une_redirection(commande):
    assert analyser_ecriture(commande) is None, f"faux positif : {commande}"


@pytest.mark.parametrize("commande, cible", [
    ("make && echo ok > /tmp/f", "/tmp/f"),          # après &&
    ("test -f x || echo n > /tmp/f", "/tmp/f"),      # après ||
    ("cd /tmp; echo x > f", "f"),                    # après ;
    ("cat a.txt | tee /tmp/f", "/tmp/f"),            # derrière un tube
    ('echo "commentaire > important" > /tmp/reel', "/tmp/reel"),
])
def test_une_redirection_reelle_reste_vue_meme_entouree(commande, cible):
    """Le risque symétrique du masquage : ne pas neutraliser l'opérateur RÉEL
    d'une commande qui contient aussi un chevron cité."""
    e = analyser_ecriture(commande)
    assert e is not None and e.cible == cible, f"écriture manquée : {commande}"


@pytest.mark.parametrize("commande", [
    'ssh h "cat > f <<EOF\nligne\nEOF"',        # délimiteur NON cité
    'ssh h "cat > f <<\'EOF\'\nligne\nEOF"',  # délimiteur cité
    'ssh h "cat > f <<-EOF\nligne\nEOF"',       # variante avec tiret
])
def test_les_deux_formes_de_heredoc_sont_lues(commande):
    """`<<'EOF'` et `<<EOF` diffèrent par l'expansion des variables, pas par la
    détection : les deux écrivent, et les deux portent leur contenu."""
    e = analyser_ecriture(commande)
    assert e is not None
    assert e.contenu is not None and "ligne" in e.contenu


@pytest.mark.parametrize("commande, outil", [
    ("tee /tmp/f", "tee"),
    ("cat a | tee -a /tmp/f", "tee"),
    ("dd if=/dev/zero of=/tmp/f", "dd"),
    ("truncate -s 0 /tmp/f", "truncate"),
])
def test_un_contenu_venu_de_stdin_est_dit_inconnu_pas_absent(commande, outil):
    """`tee`, `dd` et `truncate` écrivent ce qui leur arrive par l'entrée
    standard : le contenu N'EST PAS dans la commande.

    La distinction compte : « rien à montrer » laisserait croire que la
    commande a été comprise et qu'elle n'écrit rien d'important. « contenu
    inconnu » dit à l'utilisateur qu'il doit vérifier lui-même avant de
    confirmer.
    """
    e = analyser_ecriture(commande)
    assert e is not None and e.outil == outil
    assert e.contenu is None
    assert "INDÉTERMINABLE" in e.apercu()
    assert "Vérifie toi-même" in e.apercu()


# ── Local ▸ le contenu lisible devient un diff relu ──────────────────────────
def test_une_ecriture_locale_lisible_devient_une_proposition():
    """Le refus renvoyait vers `edit_file` ; il fabrique maintenant lui-même le
    changement. L'utilisateur relit toujours un diff — mais l'agent n'a plus à
    retraduire sa commande en un autre appel pour l'obtenir."""
    from src.agents.coding.pending import pending_changes
    from src.agents.shell.tools import shell_run

    pending_changes.clear()
    r = shell_run.invoke({"command": "echo 'x' > /tmp/zzz_axon_test.conf"})

    assert r["status"] == "proposed"
    assert r["awaiting_confirmation"] is True
    [change] = pending_changes.items
    assert change.path == "/tmp/zzz_axon_test.conf"
    assert change.proposed == "x\n", "le saut de ligne d'echo fait partie du fichier"
    pending_changes.clear()


def test_une_ecriture_locale_lisible_n_execute_jamais_le_shell():
    """Aucune autorisation n'achète une exécution ici : c'est la revue qui écrit.

    La distinction n'est pas cosmétique. Exécuter la commande rendrait la main
    au shell APRÈS l'accord, avec tout ce qu'elle porte ; passer par la revue
    garantit que l'accord ne produit exactement que le diff montré."""
    from src.agents.coding.pending import pending_changes
    from src.agents.shell.tools import shell_run

    temoin = Path("/tmp/zzz_axon_jamais_ecrit.conf")
    temoin.unlink(missing_ok=True)
    pending_changes.clear()

    autorisation.accorder(f"echo 'x' > {temoin}")
    r = shell_run.invoke({"command": f"echo 'x' > {temoin}"})

    assert r["status"] == "proposed"
    assert not temoin.exists(), "la commande shell a été exécutée malgré la revue"
    pending_changes.clear()


def test_une_ecriture_locale_illisible_demande_confirmation():
    """`mycommand > f` : aucune autre porte ne le sert. `propose_file_change`
    exigerait de lancer la commande d'abord, or `_compact_shell_output` tronque
    à 80 lignes — le fichier serait amputé en silence."""
    from src.agents.shell.tools import shell_run

    r = shell_run.invoke({"command": "mycommand --long > /tmp/zzz_axon_sortie.log"})
    assert r["status"] == "requires_confirmation"
    assert "INDÉTERMINABLE" in r["preview"]


# ── Distant ▸ confirmé, avec APERÇU ──────────────────────────────────────────
@pytest.mark.parametrize("commande, hote, cible", [
    ('ssh kaine "cat > ~/.ssh/config"', "kaine", "~/.ssh/config"),
    ('ssh -i ~/.ssh/kaine.pem admin@srv "echo x > /etc/motd"', "admin@srv", "/etc/motd"),
    ("scp local.txt kaine:/tmp/distant.txt", "kaine", "/tmp/distant.txt"),
])
def test_une_ecriture_distante_est_reconnue_avec_sa_cible(commande, hote, cible):
    e = analyser_ecriture(commande)
    assert e is not None and e.distante
    assert e.hote == hote and e.cible == cible


def test_le_distant_demande_confirmation_au_lieu_de_bloquer():
    """Refuser enfermait l'agent : `edit_file` ne prend qu'un chemin local, donc
    le message de refus le renvoyait vers une porte impossible."""
    from src.agents.shell.tools import shell_run

    r = shell_run.invoke({"command": 'ssh kaine "echo x > ~/.ssh/config"'})
    assert r["status"] == "requires_confirmation"
    assert r["host"] == "kaine" and r["target"] == "~/.ssh/config"


def test_la_confirmation_montre_le_contenu_pas_seulement_la_commande():
    """L'exigence centrale : approuver une commande sans voir ce qu'elle écrit,
    c'est approuver un effet qu'on ne connaît pas."""
    from src.agents.shell.tools import shell_run

    commande = (
        'ssh kaine "cat > ~/.ssh/config <<\'EOF\'\n'
        "Host github.com\n"
        "    IdentityFile ~/.ssh/id_ed25519_kaine_remote\n"
        "    IdentitiesOnly yes\n"
        'EOF"'
    )
    r = shell_run.invoke({"command": commande})
    assert r["status"] == "requires_confirmation"
    apercu = r["preview"]
    assert "kaine:~/.ssh/config" in apercu
    assert "écrasement complet" in apercu
    assert "Host github.com" in apercu
    assert "IdentitiesOnly yes" in apercu


def test_un_contenu_illisible_est_annonce_et_jamais_invente():
    """`cat > f` sans heredoc lit son entrée standard : le contenu n'est pas
    dans la commande. Le dire vaut mieux que laisser croire qu'on l'a compris."""
    e = analyser_ecriture('ssh kaine "cat > ~/.ssh/config"')
    assert e.contenu is None
    assert "INDÉTERMINABLE" in e.apercu()


def test_un_ajout_ne_se_presente_pas_comme_un_ecrasement():
    """`>>` et `>` n'ont pas les mêmes conséquences : l'aperçu doit les
    distinguer, sinon la confirmation porte sur autre chose que l'acte."""
    ecrase = analyser_ecriture('ssh kaine "echo x > ~/.ssh/config"')
    ajoute = analyser_ecriture('ssh kaine "echo x >> ~/.ssh/authorized_keys"')
    assert not ecrase.ajoute and "écrasement complet" in ecrase.apercu()
    assert ajoute.ajoute and "ajout à la fin" in ajoute.apercu()


def test_une_connexion_ssh_sans_ecriture_passe_librement():
    """Le cas qui doit rester fluide : l'agent doit pouvoir agir à distance
    sans confirmation dès qu'il n'écrit rien."""
    for commande in ('ssh kaine "ls -la ~/.ssh"',
                     'ssh kaine "ssh-keygen -t ed25519 -f ~/.ssh/k -N \'\'"',
                     'ssh kaine "git clone git@github.com:kaiiine/axon.git"'):
        assert analyser_ecriture(commande) is None, commande


def test_la_porosite_de_l_ancienne_liste_est_fermee():
    """Les quatre contournements mesurés visant le MÊME fichier distant."""
    for commande in ('ssh kaine "cat > ~/.ssh/config"',
                     'ssh kaine "echo x > ~/.ssh/config"',
                     'ssh kaine "printf \'x\' > ~/.ssh/config"',
                     'ssh kaine "tee ~/.ssh/config"'):
        e = analyser_ecriture(commande)
        assert e is not None and e.distante, f"contournement encore ouvert : {commande}"


@pytest.mark.parametrize("commande, outil", [
    ("sed -i 's/a/b/' /tmp/zzz_axon.conf", "sed -i"),
    ("truncate -s 0 /tmp/zzz_axon.conf", "truncate"),
    ("dd if=/dev/zero of=/tmp/zzz_axon.bin", "dd"),
])
def test_une_modification_sur_place_garde_l_ancien_refus(commande, outil):
    """Le contenu y est illisible, comme pour `cmd > f` — mais la ressemblance
    s'arrête là. Ces outils modifient un fichier DÉJÀ présent, ce qu'`edit_file`
    fait mieux en montrant un diff. N'ouvrir le cas « confirme et exécute » qu'à
    la capture de sortie évite de relâcher le garde là où l'issue existe."""
    from src.agents.shell.tools import shell_run

    r = shell_run.invoke({"command": commande, "confirmed": True})
    assert r["status"] == "blocked"
    assert "edit_file" in r["message"]
