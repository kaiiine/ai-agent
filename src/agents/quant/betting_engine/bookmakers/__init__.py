"""Couche d'acquisition bookmaker (§4.1 du PRD).

Un contrat commun `BookmakerConnector` + un registre ; seul Winamax est
implémenté. Ajouter un bookmaker = un nouveau sous-paquet implémentant le
protocole et une entrée dans le registre, sans toucher au reste du pipeline.
"""
