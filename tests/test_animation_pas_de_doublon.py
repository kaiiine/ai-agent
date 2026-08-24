"""Un seul fil d'animation à la fois — sinon `thinking` s'empile.

Symptôme signalé plusieurs fois, et jamais complètement corrigé :

    thinking
    thinking..
    thinking.

Ce n'est pas un mauvais rafraîchissement. Tous les fils d'animation partagent le
MÊME `threading.Event`. Faire `clear()` puis démarrer un second fil ne tue donc
pas le premier : il voit le drapeau baissé et repart. Deux fils peignent alors la
même zone, chacun avec son propre compteur d'images — d'où des nombres de points
incohérents entre les lignes.

Sur les quatre points de redémarrage de `stream_once`, UN seul faisait la
séquence juste (`set()` → `join()` → `clear()`). Les autres l'omettaient. La
séquence vit maintenant dans `_redemarrer_animation()`, à un seul endroit.
"""
import inspect
import threading
import time

import pytest

from src.ui.streaming import _make_thinking_loop, _redemarrer_animation


class _LiveEspion:
    """Compte les images posées, et par quel fil."""

    def __init__(self):
        self.par_fil: dict[str, int] = {}
        self._verrou = threading.Lock()

    def update(self, _renderable):
        with self._verrou:
            nom = threading.current_thread().name
            self.par_fil[nom] = self.par_fil.get(nom, 0) + 1


# ── Le défaut, reproduit ──────────────────────────────────────────────────────
def test_deux_fils_sur_le_meme_evenement_peignent_tous_les_deux():
    """La cause, figée. Sans `join()`, l'ancien fil survit au `clear()`.

    Ce test décrit le comportement FAUTIF, pas celui qu'on veut : il existe pour
    qu'on reconnaisse le mécanisme si le symptôme revient.
    """
    live = _LiveEspion()
    stop = threading.Event()

    a = threading.Thread(target=_make_thinking_loop(stop, live), daemon=True, name="ancien")
    a.start()
    time.sleep(0.15)

    stop.clear()                      # le geste fautif : on ne stoppe pas `a`
    b = threading.Thread(target=_make_thinking_loop(stop, live), daemon=True, name="nouveau")
    b.start()
    time.sleep(0.25)

    stop.set()
    a.join(timeout=1); b.join(timeout=1)

    assert len(live.par_fil) == 2, "les deux fils doivent avoir peint — c'est le bug"


# ── Le correctif ──────────────────────────────────────────────────────────────
def test_le_redemarrage_arrete_vraiment_le_fil_precedent():
    live = _LiveEspion()
    stop = threading.Event()
    holder: list[threading.Thread] = []

    ancien = threading.Thread(target=_make_thinking_loop(stop, live), daemon=True, name="ancien")
    ancien.start()
    holder.append(ancien)
    time.sleep(0.15)

    _redemarrer_animation(stop, live, holder)
    time.sleep(0.25)

    assert not ancien.is_alive(), "l'ancien fil doit être mort avant le nouveau"
    stop.set()
    holder[0].join(timeout=1)


def test_le_redemarrage_rend_le_nouveau_fil_et_le_range():
    live = _LiveEspion()
    stop = threading.Event()
    holder: list[threading.Thread] = []

    fil = _redemarrer_animation(stop, live, holder)

    assert holder == [fil] and fil.is_alive()
    stop.set(); fil.join(timeout=1)


def test_un_holder_vide_ne_leve_pas():
    """Premier démarrage du tour : il n'y a rien à joindre."""
    live = _LiveEspion()
    stop = threading.Event()

    fil = _redemarrer_animation(stop, live, [])

    stop.set(); fil.join(timeout=1)


def test_le_drapeau_est_rabaisse_pour_le_nouveau_fil():
    """`join()` laisse l'événement levé : sans `clear()`, le nouveau fil sortirait
    de sa boucle immédiatement et l'écran resterait figé."""
    live = _LiveEspion()
    stop = threading.Event()
    holder: list[threading.Thread] = []

    fil = _redemarrer_animation(stop, live, holder)
    time.sleep(0.2)

    assert live.par_fil, "le nouveau fil doit peindre"
    stop.set(); fil.join(timeout=1)


# ── Plus aucun redémarrage à la main ──────────────────────────────────────────
def test_aucun_site_ne_redemarre_sans_arreter_le_precedent():
    """Le garde structurel : `clear()` suivi d'un `Thread(...)` sans `join()` est
    exactement la séquence qui a produit le symptôme."""
    source = inspect.getsource(inspect.getmodule(_redemarrer_animation))
    lignes = source.splitlines()

    fautes = []
    for i, l in enumerate(lignes):
        if "Thread(target=_make_thinking_loop" not in l:
            continue
        avant = "\n".join(lignes[max(0, i - 6):i])
        if "stop_thinking.clear()" in avant and "join(" not in avant:
            fautes.append(i + 1)

    assert not fautes, f"redémarrage sans arrêt du fil précédent, ligne(s) {fautes}"


def test_les_redemarrages_de_stream_once_passent_par_la_fonction():
    from src.ui.streaming import stream_once

    source = inspect.getsource(stream_once)

    assert source.count("_redemarrer_animation(") >= 3
    # Il reste le PREMIER démarrage du tour, qui n'a rien à joindre.
    assert source.count("Thread(target=_make_thinking_loop") <= 2
