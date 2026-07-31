"""Module HOCKEY sur glace (NHL) — marché « Résultat » RÉGLEMENTAIRE 3-way (1/N/2).

Winamax settle sur le résultat après 60 minutes (nul possible). L'issue réglementaire est
RECONSTRUITE des scores par période (first+second+third) — un match AOT/AP (prolongation/
tirs au but) est un NUL réglementaire. Modèle : Elo + Davidson (3-way harness générique),
JAMAIS Dixon-Coles. Skill validé hors échantillon vs base-rate. Verdict EXPERIMENTAL.
"""
