# Collecte CLV automatique

`positive_clv` est le dernier bloqueur commun aux quatorze modèles. Il ne se lève
ni par du code ni par un abonnement : il faut des paires décision/clôture réelles,
et elles ne s'obtiennent qu'en observant les cotes avant chaque coup d'envoi.

La commande est idempotente et sans argument de phase :

```bash
python -m src.agents.quant.betting_engine.clv.collect_cli
```

Elle situe chaque rencontre par rapport à son coup d'envoi et écrit ce qui manque :
au-delà de 30 minutes une DÉCISION, en deçà une CLÔTURE, rien après le début.

## Installation (systemd utilisateur)

```bash
mkdir -p ~/.config/systemd/user
cp ops/systemd/axon-clv-collect.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now axon-clv-collect.timer
```

Pour que la collecte tourne même session fermée :

```bash
loginctl enable-linger "$USER"
```

## Vérifier

```bash
systemctl --user list-timers axon-clv-collect.timer
journalctl --user -u axon-clv-collect.service -n 20
python -m src.agents.quant.betting_engine.clv.status_cli
```

## Variante crontab

```cron
*/5 * * * * cd ~/Documents/projets-perso/ai-agent && .venv/bin/python -m src.agents.quant.betting_engine.clv.collect_cli >> var/betting_engine/collect.log 2>&1
```

## Ce que ça ne fait pas

Aucun pari n'est placé, aucune décision d'argent n'est prise. La collecte observe
des cotes publiques et les écrit, horodatées et sourcées. Elle sert uniquement à
rendre `positive_clv` mesurable.
