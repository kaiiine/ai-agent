"""`download_asset` : ce qu'il télécharge, et ce qu'il en DIT.

Ce fichier n'existait pas. Le module était le dernier du chantier de l'agent code
à n'avoir jamais été audité, et il portait quatre défauts, tous mesurés avant
correction sur un réseau simulé :

    1. un `dest` absolu hors du cwd levait une ValueError APRÈS avoir écrit le
       fichier — l'agent recevait une exception sur un téléchargement réussi ;
    2. `count=3` vers « img/hero.jpg » annonçait trois assets et n'écrivait qu'un
       fichier, chaque téléchargement écrasant le précédent ;
    3. une page HTML était enregistrée en `.glb` avec `status: ok` : la seule
       validation était `taille > 1024`, qu'une page passe sans peine ;
    4. tout modèle 3D repartait sous « CC0 (Poly Pizza) », repli compris — donc
       `Astronaut.glb` de Google sous une licence qui n'est pas la sienne.

Le troisième et le quatrième se combinaient : un fichier HTML servi comme modèle
3D, sous une licence fausse, dans un projet destiné à la production.
"""
from pathlib import Path
from unittest.mock import patch

import pytest


JPEG = b"\xff\xd8\xff" + b"J" * 5000
PNG = b"\x89PNG\r\n\x1a\n" + b"P" * 5000
GLB = b"glTF" + b"x" * 5000
HTML = b"<!DOCTYPE html><html><body>" + b"x" * 3000 + b"</body></html>"


class _Reponse:
    status_code = 200

    def __init__(self, corps: bytes):
        self._corps = corps

    def iter_content(self, taille):
        yield self._corps


@pytest.fixture
def telecharge(tmp_path, monkeypatch):
    """Appelle l'outil avec un cwd maîtrisé et un réseau simulé."""
    from src.agents.coding import asset_downloader as AD

    def _appel(corps: bytes, candidats: list[dict], **kwargs):
        type_ = kwargs.get("asset_type", "photo")
        cle = "_search_3d" if type_ == "3d" else "_search_photos"
        with patch.object(AD, "get_cwd", lambda: tmp_path), \
             patch.object(AD, cle, lambda q, c: candidats), \
             patch("requests.get", lambda *a, **k: _Reponse(corps)), \
             patch("time.sleep", lambda _: None):
            return AD.download_asset.invoke({"query": "un objet", **kwargs})

    return _appel


# ── 1 · Un dest hors du projet ne casse plus l'appel ──────────────────────────
def test_un_dest_hors_du_projet_ne_leve_plus(telecharge, tmp_path):
    """`out.relative_to(get_cwd())` levait une ValueError sur un dest absolu hors
    du cwd, APRÈS l'écriture. L'agent voyait une exception là où le
    téléchargement avait réussi."""
    ailleurs = tmp_path.parent / "hors-projet" / "img.jpg"
    r = telecharge(JPEG, [{"url": "http://x/a.jpg", "title": "t", "source": "s"}],
                   dest=str(ailleurs), count=1)

    assert r["status"] == "ok"


def test_un_asset_hors_du_projet_n_annonce_aucune_url(telecharge, tmp_path):
    """Et il le DIT : proposer un `src` vers un fichier que rien ne sert
    donnerait un 404 que l'agent ne peut pas prévoir."""
    ailleurs = tmp_path.parent / "hors-projet" / "img.jpg"
    r = telecharge(JPEG, [{"url": "http://x/a.jpg", "title": "t", "source": "s"}],
                   dest=str(ailleurs), count=1)

    assert r["assets"][0]["url"] == ""
    assert "HORS du projet" in r["usage"]


def test_un_asset_dans_le_projet_garde_son_url_web(telecharge):
    r = telecharge(PNG, [{"url": "http://x/a.png", "title": "t", "source": "s"}],
                   dest="public/images/hero.png", count=1)

    assert r["assets"][0]["url"] == "/public/images/hero.png"


# ── 2 · Autant de fichiers que d'assets annoncés ──────────────────────────────
def test_plusieurs_assets_vers_un_dest_nomme_ne_s_ecrasent_pas(telecharge):
    """Mesuré avant : trois assets annoncés, un seul fichier sur le disque. Le
    nom donné sert de tige — hero.jpg devient hero-1, hero-2, hero-3."""
    candidats = [{"url": f"http://x/{i}.jpg", "title": "t", "source": "s"}
                 for i in range(6)]
    r = telecharge(JPEG, candidats, dest="img/hero.jpg", count=3)

    chemins = {a["path"] for a in r["assets"]}
    assert r["count"] == 3
    assert len(chemins) == 3
    assert {Path(p).name for p in chemins} == {"hero-1.jpg", "hero-2.jpg", "hero-3.jpg"}
    assert all(Path(p).exists() for p in chemins)


def test_un_seul_asset_garde_le_nom_demande(telecharge):
    """Non-régression : la numérotation ne doit pas s'appliquer au cas simple."""
    r = telecharge(JPEG, [{"url": "http://x/a.jpg", "title": "t", "source": "s"}],
                   dest="img/hero.jpg", count=1)

    assert Path(r["assets"][0]["path"]).name == "hero.jpg"


def test_un_dest_dossier_derive_les_noms_de_la_query(telecharge):
    candidats = [{"url": f"http://x/{i}.jpg", "title": "t", "source": "s"}
                 for i in range(4)]
    r = telecharge(JPEG, candidats, dest="img/", count=2)

    assert len({a["path"] for a in r["assets"]}) == 2


# ── 3 · Un fichier doit être du type qu'il prétend ────────────────────────────
def test_une_page_html_n_est_pas_un_modele_3d(telecharge):
    """Le défaut le plus grave. `taille > 1024` ne validait rien, et une page
    HTML était enregistrée en `.glb` avec `status: ok` — l'agent câblait ensuite
    `<model-viewer src="…glb">` dessus."""
    r = telecharge(HTML, [{"url": "http://x/m.glb", "title": "p", "author": "a"}],
                   dest="models/", asset_type="3d", count=1)

    assert r["status"] == "error"


def test_un_leurre_ne_reste_pas_sur_le_disque(telecharge, tmp_path):
    """Refuser l'asset ne suffit pas : le fichier écrit avant contrôle doit
    partir, sinon un `.glb` de HTML traîne dans public/ et sera référencé un
    jour."""
    telecharge(HTML, [{"url": "http://x/m.glb", "title": "p", "author": "a"}],
               dest="models/", asset_type="3d", count=1)

    assert list((tmp_path / "models").glob("*")) == []


def test_une_photo_qui_n_est_pas_une_image_est_refusee(telecharge):
    r = telecharge(HTML, [{"url": "http://x/a.jpg", "title": "t", "source": "s"}],
                   dest="img/hero.jpg", count=1)

    assert r["status"] == "error"


def test_un_vrai_glb_passe(telecharge):
    """Le contrepoids : le contrôle ne doit pas tout refuser."""
    r = telecharge(GLB, [{"url": "http://x/m.glb", "title": "p", "author": "a"}],
                   dest="models/chaise.glb", asset_type="3d", count=1)

    assert r["status"] == "ok"


# ── 4 · Une licence se porte, elle ne s'affirme pas ───────────────────────────
def test_le_repli_n_usurpe_pas_la_licence_de_poly_pizza(telecharge):
    """Mesuré avant : `Astronaut.glb` de Google repartait sous « CC0 (Poly
    Pizza) ». Une licence fausse sur un asset qui part en production n'est pas
    une imprécision de log."""
    from src.agents.coding.asset_downloader import _LICENCE_A_VERIFIER

    r = telecharge(GLB, [], dest="models/", asset_type="3d", count=1)

    asset = r["assets"][0]
    assert asset["license"] == _LICENCE_A_VERIFIER
    assert "Poly Pizza" not in asset["license"]
    assert "Google" in asset["author"] or "Three.js" in asset["author"]


def test_le_repli_est_annonce_comme_tel(telecharge):
    """Un asset de démonstration servi en silence finirait dans un site livré."""
    r = telecharge(GLB, [], dest="models/", asset_type="3d", count=1)

    assert "avertissement" in r
    assert "DÉMONSTRATION" in r["avertissement"]


def test_un_modele_de_poly_pizza_garde_sa_licence_cc0(telecharge):
    """L'API Poly Pizza, elle, expose bien un catalogue CC0 : la correction ne
    doit pas effacer une licence exacte."""
    r = telecharge(GLB, [{"url": "http://x/m.glb", "title": "chaise", "author": "qqn"}],
                   dest="models/", asset_type="3d", count=1)

    assert r["assets"][0]["license"] == "CC0 (Poly Pizza)"
    assert "avertissement" not in r


def test_la_recherche_ddg_de_modeles_a_bien_disparu():
    """Elle cherchait « site:poly.pizza … glb download » et rendait des URL de
    PAGES. Le contrôle de signature les rejette toutes : elle ne pouvait plus
    produire un seul modèle, elle ne faisait que retarder le repli."""
    from src.agents.coding import asset_downloader as AD

    assert not hasattr(AD, "_search_3d_ddg")
