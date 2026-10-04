# M5.4.b — brouillon de brut régulier

`m5_preparer_brut_regulier` estime un montant brut préparatoire à partir d'un contrat horaire individuel M5 courant et
d'une projection d'heures régulières complète fournie par le port M4 injecté par le serveur. Les sources de taux restent
des références humaines déclarées; elles ne sont pas authentifiées par OPSYS. La tranche ne calcule pas les retenues,
cotisations, DAS, paie nette, coûts employeur, obligations ou paiements. Elle n'écrit aucun registre et n'alimente pas le
cash libre.

## Entrées et calcul

L'appel exige une personne OPSYS active portant `employee`, des dates inclusives, un fuseau IANA et une période de 1 à
31 jours. Les minutes M4 doivent être des entiers réguliers classifiés, couvrir complètement la période demandée et
rester dans la borne physique des jours locaux, y compris les journées de 23 ou 25 heures lors des transitions d'heure.
Cette borne n'établit aucune règle d'heures supplémentaires.

Le taux horaire M5 est une chaîne décimale positive en CAD. Le brut exact est conservé comme fraction de centimes
`(centimes du taux × minutes) / 60`; seule la politique explicite `centime_demi_superieur` produit le montant arrondi.
L'appelant doit aussi fournir une hypothèse ou référence d'arrondi humaine, marquée non vérifiée. Aucun taux, calendrier,
arrondi implicite ou montant fiscal n'est ajouté.

`sources_attendues: null` demande les versions courantes. Une entrée non nulle cite les références exactes M4 et M5; tout
changement de révision ou d'empreinte est refusé, sans rafraîchissement silencieux. L'outil retourne la période, le brut,
la fraction exacte, les minutes, les références de sources, les hypothèses et les éléments non calculés. Chaque sortie
acceptée porte la mention d'analyse préparatoire et requiert une validation humaine avant tout usage officiel.

## Accès et limites

Cette première composition est réservée au propriétaire confirmé par l'identité console `nathan_owner`, car le port M4
disponible n'accepte que cette origine. Un admin d'appareil n'est pas converti en identité console; l'outil n'annonce
aucune capacité d'appareil. Le callback reste fermé côté serveur et ne révèle pas les registres bruts M4. Le nouvel outil
n'est pas ajouté aux grants CFO des agents. Il ne crée ni reçu de paie ni obligation, ne modifie pas les trois journaux
M5 et ne déclenche aucune action.

L'intégration M4 est validée par des tests de port simulé; cela ne certifie pas un flux réel M4 de bout en bout. Les
valeurs et sources des scénarios de test sont fictives. Toute réécriture privilégiée et re-hachage complet d'une chaîne
non signée reste hors de la protection de détection locale.
