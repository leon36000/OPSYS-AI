# Plan CMO préparatoire M7.11a

La console expose une projection interne en lecture seule : `GET /marketing/cmo` et `GET /api/marketing/cmo/plan`. L’accès est réservé aux personnes actives ayant le rôle propriétaire ou admin selon la politique de la console; le rôle est revérifié au moment de chaque lecture. La page vide affiche un formulaire sans charger de données. L’API exige toujours `date_depart`, `debut` et `fin`; les dates invalides, absentes, répétées ou les paramètres supplémentaires sont refusés.

Le formulaire demande explicitement la date de départ de l’horizon et la période des faits observés. Les fenêtres J1–30, J31–60 et J61–90 sont des périodes d’organisation, pas des prévisions. Une date d’arbitrage proposée est calculée comme la fin de chaque fenêtre, sous la règle versionnée `m7-cmo-regles.v1`; elle doit être examinée par une personne et ne constitue pas une échéance imposée.

La projection réutilise uniquement les lectures M7 `m7_lire_profil_marque_courant`, `m7_lister_calendrier` et `m7_lire_performance_campagnes`. Les faits de performance incluent les observations M2/M3/M5 déjà projetées par M7; la console n’interroge pas directement ces départements. Elle ne lit ni le moteur growth ni le plan saisonnier, et ne crée aucun outil ou registre.

Les actions affichent leur motif et leurs références sources. Les absences restent inconnues, jamais converties en zéro. Les créneaux sans `planifie_le` ne peuvent être associés à une fenêtre et déclenchent un manque explicite. La date retenue pour un créneau est le jour civil écrit dans `planifie_le`, en conservant l’offset fourni; aucune conversion automatique vers le fuseau du Québec n’est appliquée. Les références bornées indiquent les totaux et troncatures. Chaque source est lue séparément : le résultat est une projection du courant observé, pas un snapshot atomique multi-source.

Aucun score, budget, dépense, ROI futur, envoi, publication ou écriture n’est calculé ou déclenché. Une marge observée M5 ne prouve ni encaissement ni budget marketing. Toute action reste à arbitrer.
