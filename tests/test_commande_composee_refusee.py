"""Une validation ne doit couvrir qu'UN acte — donc pas de commande composée.

Le HITL d'écriture shell montre une cible, un mode, parfois un diff. Si la
commande enchaîne autre chose, l'accord porte sur un effet que la revue n'a pas
montré. Mesuré avant d'écrire ces tests :

    echo x > /etc/motd && systemctl restart nginx   → « écrit /etc/motd »
    curl -s url > f.json; rm -rf /tmp/cache         → « écrit f.json »
    rm -rf /tmp/cache | tee log.txt                 → « écrit log.txt »

Le troisième est celui qui décide de tout : il ne contient AUCUN opérateur de
chaînage. Un garde qui ne connaîtrait que `&&`, `;` et `||` le laisserait passer
pour une écriture simple, et approuver « écrire log.txt » lancerait le `rm`. Le
tube entre donc dans « composée » au même titre que le reste — le traiter à part
rouvrirait le trou avec un autre séparateur.

Le coût est assumé : `curl url | tee f` est refusé aussi. Il se réécrit
`curl url > f`, que le second cas du HITL sert nativement. On préfère refuser
une commande inoffensive que d'exécuter un acte non montré.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.shell.ecriture import analyser_ecriture


# ── Ce qui doit être vu comme composé ────────────────────────────────────────
@pytest.mark.parametrize("commande, operateur", [
    # Chaînage classique après l'écriture.
    ("echo x > /etc/motd && systemctl restart nginx", "&&"),
    ("curl -s url > f.json; rm -rf /tmp/cache", ";"),
    ("make build > log.txt && ./deploy.sh", "&&"),
    ("echo x > f || rm -rf /tmp", "||"),
    # Le tube SEUL suffit : la scène destructrice est en amont de l'écriture.
    ("rm -rf /tmp/cache | tee log.txt", "|"),
    ("dd if=/dev/zero of=/dev/sda | tee rapport.txt", "|"),
    # Tube ET chaînage : le cas qui combine les deux.
    ("curl url | tee f.json && rm -rf /tmp", "|"),
    # À travers ssh, chaînage INTERNE (caché par les guillemets).
    ('ssh vps "echo x > /etc/motd && rm -rf /tmp"', "&&"),
    # À travers ssh, chaînage EXTERNE. Le fragment ne se termine plus par le
    # guillemet fermant : sans déshabillage correct, l'écriture devenait
    # invisible et la commande passait le garde SANS confirmation — `rm` inclus.
    ('ssh vps "echo x > /f" && rm -rf /tmp', "&&"),
    ('ssh vps "cat > /f" | tee log', "|"),
])
def test_une_commande_composee_est_reconnue(commande, operateur):
    e = analyser_ecriture(commande)
    assert e is not None, "l'écriture elle-même n'est plus vue"
    assert e.composee == operateur, (
        f"{commande!r} enchaîne un second acte ; le garde ne le voit pas")


def test_le_tube_compte_autant_que_le_chainage():
    """Formulé à part parce que c'est l'invariant qui se perdrait le plus vite :
    un garde ne connaissant que `&&`/`;`/`||` laisserait passer le `rm` ci-dessous."""
    sans_chainage = "rm -rf /tmp/cache | tee log.txt"
    assert not any(op in sans_chainage for op in ("&&", ";", "||")), \
        "ce cas doit rester dépourvu d'opérateur de chaînage"
    assert analyser_ecriture(sans_chainage).composee == "|"


# ── Ce qui NE doit PAS l'être ────────────────────────────────────────────────
@pytest.mark.parametrize("commande", [
    # Un `|` ou un `;` DANS le texte à écrire n'enchaîne rien. Le corps d'un
    # heredoc n'est pas cité : sans masquage dédié, le meilleur cas de tous —
    # contenu intégralement lisible — serait refusé à tort.
    "cat > f.txt <<'EOF'\na | b ; c\nd || e\nEOF",
    'echo "a; b | c" > f.txt',
    "echo 'x || y' >> f.txt",
    # `2>&1` porte un `&` isolé, pas un `&&`.
    "mycommand > out.log 2>&1",
])
def test_une_commande_simple_reste_simple(commande):
    e = analyser_ecriture(commande)
    assert e is not None
    assert e.composee is None, f"{commande!r} refusé à tort comme composé"


# ── Le refus, bout en bout ───────────────────────────────────────────────────
def test_shell_run_refuse_et_demande_le_decoupage():
    from src.agents.shell.tools import shell_run

    r = shell_run.invoke({"command": "echo x > /tmp/zzz_axon_compose.txt && echo suite",
                          "confirmed": True})
    assert r["status"] == "blocked"
    assert r["operator"] == "&&"
    assert "Découpe" in r["message"]


def test_un_refus_n_ecrit_ni_n_execute_rien():
    """Le point entier de ce garde : ni le fichier, ni l'acte enchaîné."""
    from src.agents.coding.pending import pending_changes
    from src.agents.shell.tools import shell_run

    cible = Path("/tmp/zzz_axon_compose_temoin.txt")
    trace = Path("/tmp/zzz_axon_compose_trace.txt")
    for f in (cible, trace):
        f.unlink(missing_ok=True)
    pending_changes.clear()

    r = shell_run.invoke({"command": f"echo x > {cible} && touch {trace}",
                          "confirmed": True})

    assert r["status"] == "blocked"
    assert not cible.exists(), "l'écriture a eu lieu malgré le refus"
    assert not trace.exists(), "l'acte enchaîné a eu lieu malgré le refus"
    assert not pending_changes.items, \
        "un refus ne doit rien laisser à valider : le diff ne représenterait " \
        "qu'une partie de la commande"


def test_le_refus_de_composition_passe_avant_la_confirmation_destructive():
    """L'ordre des gardes est lui-même un invariant.

    `rm -rf /tmp/cache | tee log.txt` commence par `rm` : le garde des commandes
    destructives le voyait en premier et répondait « demande confirmation ».
    L'issue restait sûre — la composition était refusée au second tour — mais
    l'utilisateur se voyait demander d'approuver une commande qui allait être
    refusée ensuite. On ne demande pas d'approuver ce qu'on ne peut pas montrer.
    """
    from src.agents.shell.tools import shell_run

    r = shell_run.invoke({"command": "rm -rf /tmp/zzz_axon_cache | tee /tmp/zzz_axon.log"})
    assert r["status"] == "blocked", (
        "le garde destructif répond avant celui de la composition")
    assert r["operator"] == "|"
