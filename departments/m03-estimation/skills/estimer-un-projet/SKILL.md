---
name: estimer-un-projet
description: Procédure pour estimer un projet de rénovation extérieure à partir de photos et d'une demande qualifiée, sans inventer de précision.
---

# Estimer un projet

1. Vérifie que la demande vient de M2 avec un marqueur de readiness. Sinon : demande-la, stop.
2. Rassemble : photos (avec résolution, éclairage, angle, référence d'échelle), seuils de
   qualité, barème en vigueur, type de travaux, quantité mesurée, plancher de rentabilité.
   Si une donnée manque, demande-la. N'en invente aucune.
3. Appelle `m3_estimer_projet` une seule fois avec toutes les données.
4. Lis la réponse :
   - `prix_bloque: true` → rédige une demande courte au client avec `elements_manquants`.
   - `alerte_plancher: true` → signale à un humain que le projet est sous le seuil de rentabilité.
   - sinon → présente l'intervalle `borne_basse`–`borne_haute` en CAD, avant taxes.
5. Toute réponse `accepte: false` contient un `verdict` : corrige l'entrée indiquée ou escalade.
