# ADR-STAT-001 — `model_reliability` : reconnaissance, et report explicite

**Statut : FUTURE_STATISTICAL_ADR.** Aucune définition empirique n'est adoptée.
La valeur de policy V1 (`supported_model_reliability = 0.75`) est conservée.

## Ce que la métrique devrait être

`model_reliability` doit représenter la **confiance empirique exploitable dans la
capability** — et non recopier une métrique existante. Elle doit être hors
échantillon, point-in-time, propre au couple (sport, market_type), stable,
interprétable, et compatible avec le sizing monotone actuel : elle influence la
mise, donc une définition fragile coûte de l'argent.

Elle doit surtout être **distincte** de quatre grandeurs déjà mesurées :

| grandeur | ce qu'elle mesure | où elle vit |
|---|---|---|
| ECE | erreur de calibration | `max_calibration_error` |
| Brier | finesse hors échantillon | `must_beat_baselines` |
| `probability_low` | incertitude de CETTE prédiction | `uncertainty.py` |
| maturité | verdict de policy sur les critères | `maturity.py` |

## Candidats examinés

**CLV réalisée.** C'est le signal de confiance empirique que le projet a déjà
choisi : `positive_clv`, critère requis, avec sa borne bootstrap. En faire une
seconde métrique reviendrait à compter deux fois la même preuve — et cette preuve
n'existe pas encore : 7 rencontres indépendantes collectées sur les 30 exigées.

**Stabilité inter-folds.** Déjà mesurée, déjà exposée : `max_fold_brier_spread`,
en suivi non bloquant. La promouvoir en reliability changerait son statut sans
rien ajouter à son contenu.

**Couverture empirique de `probability_low`.** Le candidat le plus intéressant, et
le seul réellement distinct : « quand ce modèle annonce au moins X, à quelle
fréquence a-t-il raison ? ». Mesuré : NBA 100 %, MLB 80 %, Tennis ATP 83 %.
Interprétable, monotone, et propre au modèle.

Il est écarté pour une raison de méthode, pas de goût : cette couverture est
mesurée sur 7 à 109 tranches selon le sport, et sa **stabilité dans le temps
n'est pas établie**. Une métrique qui entre dans le sizing doit être stable
avant d'y entrer, pas après. L'adopter aujourd'hui reviendrait à convertir une
mesure encore bruitée en décision d'argent — exactement la fausse précision que
cette reconnaissance devait éviter.

## Décision

Conserver `supported_model_reliability` comme valeur de policy explicite. La
politique de décision le documentait déjà comme une dette de données, « en
attendant une vraie reliability dérivée de calibration/ par (sport,
market_type) — JAMAIS une formule fabriquée type 1-ECE ». Cette reconnaissance
confirme ce cadrage plutôt qu'elle ne le lève.

## Ce qui débloquerait la décision

La couverture de `probability_low`, mesurée sur plusieurs saisons et plusieurs
sports, avec une stabilité démontrée fold à fold. C'est la même accumulation qui
débloque `positive_clv` : le temps, pas le code.
