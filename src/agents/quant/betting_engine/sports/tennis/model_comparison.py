"""Tennis — COMPARAISON OBJECTIVE de systèmes de rating (Phase 3).

On ne suppose PAS qu'Elo est le meilleur : plusieurs systèmes candidats traversent
EXACTEMENT le même walk-forward point-in-time, sur EXACTEMENT le même sous-ensemble de
matchs éligibles, et sont jugés sur les mêmes métriques (Brier, logloss, ECE, accuracy).

Candidats (paramètres FIXES issus de la littérature, JAMAIS fités sur l'évaluation) :
  - `rank_favorite`   : baseline — taux de victoire point-in-time du mieux classé ;
  - `rank_logistic`   : baseline forte — Bradley-Terry/logistique sur l'écart de log-rang,
                        coefficient réestimé UNIQUEMENT sur les saisons antérieures ;
  - `elo`             : Elo classique, K constant ;
  - `elo_538`         : Elo à K DYNAMIQUE K=250/(n+5)^0.4 (formulation FiveThirtyEight,
                        standard en tennis : apprend vite sur un joueur peu observé) ;
  - `elo_surface`     : elo_538 + note PAR SURFACE, mélange blend·surface+(1-blend)·global ;
  - `glicko`          : Glicko (note + déviation RD, RD croît avec l'inactivité) ;
  - `glicko2`         : Glicko-2 (note + RD + volatilité σ, τ standard).

Anti-fuite par construction : chaque prédiction n'utilise que l'état ANTÉRIEUR au match ;
l'étiquette est l'ordre CANONIQUE des noms (jamais « la colonne vainqueur »).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

_Q = math.log(10) / 400.0


# ── Métriques ────────────────────────────────────────────────────────────────────
def brier(pairs) -> float:
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def logloss(pairs) -> float:
    return -sum(math.log(max(p if y else 1 - p, 1e-12)) for p, y in pairs) / len(pairs)


def accuracy(pairs) -> float:
    return sum(1 for p, y in pairs if (p > 0.5) == (y > 0.5)) / len(pairs)


def ece(pairs, n_bins: int = 10) -> float:
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, y in pairs:
        bins[min(int(p * n_bins), n_bins - 1)].append((p, y))
    n = len(pairs)
    return round(sum((len(b) / n) * abs(sum(p for p, _ in b) / len(b) - sum(y for _, y in b) / len(b))
                     for b in bins if b), 6)


def metrics(pairs) -> dict:
    return {"n": len(pairs), "brier": round(brier(pairs), 6), "logloss": round(logloss(pairs), 6),
            "ece": ece(pairs), "accuracy": round(accuracy(pairs), 4)}


# ── Systèmes de rating (chacun expose predict(a,b,surface) et update(...)) ───────
class EloSystem:
    """Elo. `dynamic_k=True` -> K=250/(n+5)^0.4 (FiveThirtyEight) ; sinon K constant.
    `surface_blend>0` -> note additionnelle par surface, mélangée à la note globale."""

    def __init__(self, *, k: float = 24.0, dynamic_k: bool = False, surface_blend: float = 0.0,
                 init: float = 1500.0):
        self.k, self.dynamic_k, self.blend, self.init = k, dynamic_k, surface_blend, init
        self.g: dict[str, float] = {}
        self.s: dict[tuple[str, str], float] = {}
        self.n: Counter = Counter()
        self.ns: Counter = Counter()

    def _rating(self, p: str, surface: str) -> float:
        rg = self.g.get(p, self.init)
        if self.blend <= 0:
            return rg
        rs = self.s.get((p, surface), self.init)
        return self.blend * rs + (1 - self.blend) * rg

    def predict(self, a: str, b: str, surface: str) -> float:
        return 1.0 / (1.0 + 10 ** (-(self._rating(a, surface) - self._rating(b, surface)) / 400.0))

    def _k_for(self, p: str, counter: Counter) -> float:
        return 250.0 / ((counter[p] + 5) ** 0.4) if self.dynamic_k else self.k

    def update(self, winner: str, loser: str, surface: str, days: int) -> None:
        eg = 1.0 / (1.0 + 10 ** (-(self.g.get(winner, self.init) - self.g.get(loser, self.init)) / 400.0))
        kw, kl = self._k_for(winner, self.n), self._k_for(loser, self.n)
        self.g[winner] = self.g.get(winner, self.init) + kw * (1.0 - eg)
        self.g[loser] = self.g.get(loser, self.init) - kl * (1.0 - eg)
        self.n[winner] += 1
        self.n[loser] += 1
        if self.blend > 0:
            rw, rl = self.s.get((winner, surface), self.init), self.s.get((loser, surface), self.init)
            es = 1.0 / (1.0 + 10 ** (-(rw - rl) / 400.0))
            kws, kls = self._k_for(winner, self.ns), self._k_for(loser, self.ns)
            self.s[(winner, surface)] = rw + kws * (1.0 - es)
            self.s[(loser, surface)] = rl - kls * (1.0 - es)
            self.ns[winner] += 1
            self.ns[loser] += 1


class GlickoSystem:
    """Glicko (Glickman). RD croît avec l'inactivité : RD = min(sqrt(RD²+c²·t), RD_max)."""

    def __init__(self, *, init: float = 1500.0, rd_init: float = 350.0, c: float = 0.7,
                 rd_max: float = 350.0):
        self.init, self.rd_init, self.c, self.rd_max = init, rd_init, c, rd_max
        self.r: dict[str, float] = {}
        self.rd: dict[str, float] = {}
        self.last: dict[str, int] = {}

    def _state(self, p: str, day: int) -> tuple[float, float]:
        r = self.r.get(p, self.init)
        rd = self.rd.get(p, self.rd_init)
        elapsed = max(0, day - self.last.get(p, day))
        rd = min(math.sqrt(rd * rd + (self.c ** 2) * elapsed), self.rd_max)
        return r, rd

    @staticmethod
    def _g(rd: float) -> float:
        return 1.0 / math.sqrt(1.0 + 3.0 * (_Q ** 2) * rd * rd / (math.pi ** 2))

    def expect(self, r: float, r_opp: float, rd_opp: float) -> float:
        return 1.0 / (1.0 + 10 ** (-self._g(rd_opp) * (r - r_opp) / 400.0))

    def predict(self, a: str, b: str, surface: str, day: int = 0) -> float:
        ra, rda = self._state(a, day)
        rb, rdb = self._state(b, day)
        # Incertitude COMBINÉE des deux joueurs (prédiction, pas mise à jour).
        g = self._g(math.sqrt(rda ** 2 + rdb ** 2))
        return 1.0 / (1.0 + 10 ** (-g * (ra - rb) / 400.0))

    def update(self, winner: str, loser: str, surface: str, day: int) -> None:
        rw, rdw = self._state(winner, day)
        rl, rdl = self._state(loser, day)
        for p, (r, rd), (r_o, rd_o), s in ((winner, (rw, rdw), (rl, rdl), 1.0),
                                           (loser, (rl, rdl), (rw, rdw), 0.0)):
            e = self.expect(r, r_o, rd_o)
            g = self._g(rd_o)
            d2 = 1.0 / ((_Q ** 2) * (g ** 2) * e * (1 - e)) if 0 < e < 1 else 1e6
            denom = 1.0 / (rd * rd) + 1.0 / d2
            self.r[p] = r + (_Q / denom) * g * (s - e)
            self.rd[p] = math.sqrt(1.0 / denom)
            self.last[p] = day


class Glicko2System:
    """Glicko-2 (Glickman) : note, RD et VOLATILITÉ σ ; τ contraint la dérive de σ."""

    SCALE = 173.7178

    def __init__(self, *, init: float = 1500.0, rd_init: float = 350.0, sigma_init: float = 0.06,
                 tau: float = 0.5, c: float = 0.7, rd_max: float = 350.0):
        self.init, self.rd_init, self.sigma_init = init, rd_init, sigma_init
        self.tau, self.c, self.rd_max = tau, c, rd_max
        self.r: dict[str, float] = {}
        self.rd: dict[str, float] = {}
        self.sig: dict[str, float] = {}
        self.last: dict[str, int] = {}

    def _state(self, p: str, day: int):
        r = self.r.get(p, self.init)
        rd = self.rd.get(p, self.rd_init)
        elapsed = max(0, day - self.last.get(p, day))
        rd = min(math.sqrt(rd * rd + (self.c ** 2) * elapsed), self.rd_max)
        return r, rd, self.sig.get(p, self.sigma_init)

    @staticmethod
    def _g(phi: float) -> float:
        return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi ** 2))

    def predict(self, a: str, b: str, surface: str, day: int = 0) -> float:
        ra, rda, _ = self._state(a, day)
        rb, rdb, _ = self._state(b, day)
        mu_a, mu_b = (ra - 1500) / self.SCALE, (rb - 1500) / self.SCALE
        phi = math.sqrt(rda ** 2 + rdb ** 2) / self.SCALE
        return 1.0 / (1.0 + math.exp(-self._g(phi) * (mu_a - mu_b)))

    def _new_sigma(self, phi: float, sigma: float, delta: float, v: float) -> float:
        """Itération d'Illinois sur f(x) (algorithme Glicko-2 standard)."""
        a = math.log(sigma ** 2)
        eps, tau2 = 1e-6, self.tau ** 2

        def f(x):
            ex = math.exp(x)
            num = ex * (delta ** 2 - phi ** 2 - v - ex)
            den = 2.0 * ((phi ** 2 + v + ex) ** 2)
            return num / den - (x - a) / tau2

        A, B = a, (math.log(delta ** 2 - phi ** 2 - v) if delta ** 2 > phi ** 2 + v
                   else a - self.tau)
        if delta ** 2 <= phi ** 2 + v:
            k = 1
            while f(a - k * self.tau) < 0 and k < 100:
                k += 1
            B = a - k * self.tau
        fA, fB = f(A), f(B)
        for _ in range(100):
            if abs(B - A) <= eps:
                break
            C = A + (A - B) * fA / (fB - fA) if fB != fA else (A + B) / 2
            fC = f(C)
            if fC * fB <= 0:
                A, fA = B, fB
            else:
                fA /= 2.0
            B, fB = C, fC
        return math.exp(A / 2.0)

    def update(self, winner: str, loser: str, surface: str, day: int) -> None:
        states = {winner: self._state(winner, day), loser: self._state(loser, day)}
        for p, opp, s in ((winner, loser, 1.0), (loser, winner, 0.0)):
            r, rd, sigma = states[p]
            r_o, rd_o, _ = states[opp]
            mu, phi = (r - 1500) / self.SCALE, rd / self.SCALE
            mu_o, phi_o = (r_o - 1500) / self.SCALE, rd_o / self.SCALE
            g = self._g(phi_o)
            e = 1.0 / (1.0 + math.exp(-g * (mu - mu_o)))
            e = min(max(e, 1e-9), 1 - 1e-9)
            v = 1.0 / ((g ** 2) * e * (1 - e))
            delta = v * g * (s - e)
            sigma_new = self._new_sigma(phi, sigma, delta, v)
            phi_star = math.sqrt(phi ** 2 + sigma_new ** 2)
            phi_new = 1.0 / math.sqrt(1.0 / (phi_star ** 2) + 1.0 / v)
            mu_new = mu + (phi_new ** 2) * g * (s - e)
            self.r[p] = mu_new * self.SCALE + 1500
            self.rd[p] = min(phi_new * self.SCALE, self.rd_max)
            self.sig[p] = sigma_new
            self.last[p] = day


class RankLogistic:
    """Bradley-Terry/logistique sur l'écart de log-rang. Coefficient RÉESTIMÉ chaque
    saison sur les SEULES saisons antérieures (point-in-time, jamais sur l'éval)."""

    def __init__(self):
        self.beta = 0.0
        self.intercept = 0.0
        self._hist: list[tuple[float, float]] = []      # (x = log rank_b - log rank_a, y)

    @staticmethod
    def _x(rank_a: int, rank_b: int) -> float:
        return math.log(rank_b) - math.log(rank_a)

    def predict_x(self, x: float) -> float:
        return 1.0 / (1.0 + math.exp(-(self.intercept + self.beta * x)))

    def observe(self, x: float, y: float) -> None:
        self._hist.append((x, y))

    def refit(self, iterations: int = 300, lr: float = 0.5) -> None:
        """Descente de gradient (2 paramètres) sur l'historique ANTÉRIEUR uniquement."""
        if len(self._hist) < 500:
            return
        b, c = self.beta, self.intercept
        n = len(self._hist)
        for _ in range(iterations):
            gb = gc = 0.0
            for x, y in self._hist:
                p = 1.0 / (1.0 + math.exp(-(c + b * x)))
                gb += (p - y) * x
                gc += (p - y)
            b -= lr * gb / n
            c -= lr * gc / n
        self.beta, self.intercept = b, c


# ── Walk-forward COMMUN ──────────────────────────────────────────────────────────
@dataclass
class ComparisonResult:
    per_model: dict = field(default_factory=dict)
    n_eligible: int = 0
    n_total: int = 0
    # Prédictions brutes alignées : {modèle: [(p, y, year), …]} — permet la découpe
    # DEV/HOLDOUT et les comparaisons APPARIÉES (même match, deux modèles).
    raw: dict = field(default_factory=dict)


def segment(raw_list, *, max_year=None, min_year=None):
    return [(p, y) for p, y, yr, _mid in raw_list
            if (max_year is None or yr <= max_year) and (min_year is None or yr >= min_year)]


def paired_brier_delta(raw_a, raw_b, *, min_year=None, max_year=None,
                       resamples: int = 2000, seed: int = 20260801) -> dict:
    """Différence de Brier APPARIÉE (a - b) sur les matchs COMMUNS, avec IC bootstrap.

    Deux systèmes prédisent le MÊME match : comparer leurs Brier moyens indépendamment
    ignore cette corrélation. L'appariement se fait sur l'IDENTIFIANT DE MATCH (et non par
    position : les baselines sautent les matchs sans classement/cote, donc un `zip` de
    positions comparerait des matchs différents). Si l'IC contient 0, l'écart n'est PAS
    démontré — on ne « choisit » jamais un gagnant sur un écart non significatif."""
    import random
    def keyed(raw):
        return {mid: (p, y) for p, y, yr, mid in raw
                if (min_year is None or yr >= min_year) and (max_year is None or yr <= max_year)}
    A, B = keyed(raw_a), keyed(raw_b)
    common = A.keys() & B.keys()
    diffs = [(A[k][0] - A[k][1]) ** 2 - (B[k][0] - B[k][1]) ** 2 for k in sorted(common)]
    n = len(diffs)
    if n == 0:
        return {"n": 0}
    mean = sum(diffs) / n
    rng = random.Random(seed)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    lo, hi = means[int(0.025 * (resamples - 1))], means[int(0.975 * (resamples - 1))]
    return {"n": n, "mean_delta": round(mean, 6), "ci95": (round(lo, 6), round(hi, 6)),
            "significant": (lo > 0) or (hi < 0)}


def compare_models(matches, *, min_prior: int = 20, surface_blend: float = 0.5) -> ComparisonResult:
    """Rejoue la chronologie UNE fois en maintenant tous les systèmes ; chaque système
    prédit le MÊME match éligible, à partir de son seul état antérieur."""
    systems = {
        "elo": EloSystem(k=24.0),
        "elo_538": EloSystem(dynamic_k=True),
        "elo_surface": EloSystem(dynamic_k=True, surface_blend=surface_blend),
        "glicko": GlickoSystem(),
        "glicko2": Glicko2System(),
    }
    rank_logit = RankLogistic()
    preds: dict[str, list[tuple[float, float]]] = {k: [] for k in systems}
    preds["rank_favorite"] = []
    preds["rank_logistic"] = []
    preds["market"] = []                                 # CONTEXTE (cote implicite dé-viggée)

    fav_wins = fav_total = 0
    n_eligible = 0
    played: Counter = Counter()
    current_year = None
    day0 = matches[0].tourney_date.toordinal() if matches else 0

    for m in matches:
        w, l = m.p1_name, m.p2_name
        surface = m.surface or "?"
        day = m.tourney_date.toordinal() - day0
        year = m.tourney_date.year
        if current_year is None:
            current_year = year
        elif year != current_year:                       # frontière de saison -> refit point-in-time
            rank_logit.refit()
            current_year = year

        # Ordre CANONIQUE (par nom) + étiquette : MÊME convention pour prédire ET pour
        # entraîner la baseline logistique — sinon l'échantillon d'entraînement est
        # dégénéré (toutes les lignes « vainqueur d'abord », y=1) et le modèle est cassé.
        a, b = (w, l) if w < l else (l, w)                # anti-fuite d'étiquette
        y = 1.0 if a == w else 0.0

        eligible = played[w] >= min_prior and played[l] >= min_prior
        if eligible:
            mid = n_eligible                          # identifiant de match (appariement)
            n_eligible += 1
            for name, sysm in systems.items():
                p = (sysm.predict(a, b, surface, day) if isinstance(sysm, (GlickoSystem, Glicko2System))
                     else sysm.predict(a, b, surface))
                preds[name].append((min(max(p, 1e-9), 1 - 1e-9), y, year, mid))
            if m.p1_rank and m.p2_rank and fav_total >= 100:
                rate = fav_wins / fav_total
                a_is_fav = (m.p1_rank < m.p2_rank) == (a == w)
                preds["rank_favorite"].append((rate if a_is_fav else 1 - rate, y, year, mid))
            if m.p1_rank and m.p2_rank and rank_logit.beta != 0.0:
                ra, rb = (m.p1_rank, m.p2_rank) if a == w else (m.p2_rank, m.p1_rank)
                preds["rank_logistic"].append((rank_logit.predict_x(RankLogistic._x(ra, rb)), y, year, mid))
            if m.p1_close_odds and m.p2_close_odds:
                iw, il = 1 / m.p1_close_odds, 1 / m.p2_close_odds
                pw = iw / (iw + il)
                preds["market"].append((pw if a == w else 1 - pw, y, year, mid))

        # Mises à jour (après prédiction — jamais avant).
        for sysm in systems.values():
            sysm.update(w, l, surface, day)
        if m.p1_rank and m.p2_rank:
            # Entraînement dans l'ordre CANONIQUE (comme la prédiction) : l'échantillon
            # contient donc des y=0 ET des y=1 (symétrique), jamais que des victoires.
            ra, rb = (m.p1_rank, m.p2_rank) if a == w else (m.p2_rank, m.p1_rank)
            rank_logit.observe(RankLogistic._x(ra, rb), y)
            fav_total += 1
            fav_wins += 1 if m.p1_rank < m.p2_rank else 0
        played[w] += 1
        played[l] += 1

    return ComparisonResult(
        per_model={k: metrics([(p, y) for p, y, _yr, _mid in v]) for k, v in preds.items() if v},
        n_eligible=n_eligible, n_total=len(matches), raw={k: v for k, v in preds.items() if v})
