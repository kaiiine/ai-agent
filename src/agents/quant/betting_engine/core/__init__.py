"""Contrats génériques du betting-engine, indépendants du sport et du bookmaker.

Y vivent les structures partagées par plusieurs couches (feature set, événement
canonique) : produites par une couche, consommées par une autre, elles ne
doivent appartenir ni à `bookmakers/` ni à un `sports/<sport>/` particulier.
Même rôle que `gateway/core/` côté gateway.
"""
