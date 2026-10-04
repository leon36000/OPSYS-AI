# M5.4.a — contrat salarial horaire individuel

Cette tranche ajoute seulement le contrat horaire individuel. Elle ne calcule ni heures, ni brut, ni retenues, ni DAS, ni paie nette; elle ne modifie ni le cash libre, les obligations déclarées, les mouvements, ni les événements.

## Journal et contrat

Les outils `m5_enregistrer_contrat_horaire` et `m5_revoquer_contrat_horaire` écrivent après validation N4 humaine dans le flux durable dédié `m05-financecore/contrats_salaries_horaires`. Les maillons sont append-only et distincts de `principal` et `comptes_a_payer`. `m5_lire_contrat_horaire` ne rend le contrat courant que si une seule révision couvre toutes les dates demandées.

Chaque contrat identifie la personne OPSYS canonique active qui porte `employee`; aucun identifiant fourni par un agent ne déclare un mapping M4. Le taux est une chaîne décimale CAD positive, finie et limitée par le validateur à 999999.99 par heure. Les bornes du contrat sont ISO, début inclus et fin exclusive; le fuseau doit être IANA valide. L'humain cite une source et sa date, et chaque enregistrement porte un motif. Une révision compare le numéro et l'empreinte de la tête; une révocation exige la même tête et un motif. Un contrat révoqué ne se réactive pas sous le même identifiant.

## Accès et intégrité

Les écritures N4 suivent les approbations existantes `finance` / `nathan_owner`; l'identité humaine, le rôle canonique, la voie et, pour la file, l'identifiant de décision OPSYS sont liés au maillon. Le lecteur exige un jeton admin humain actif confirmé en base, ou `nathan_owner` via le contexte console confirmé. Les dates de lecture, début et fin inclus, peuvent être identiques pour une seule journée; elles ne peuvent être inversées. La couverture exclut la borne de fin du contrat. Les employés, vendeurs, managers, agents sans identité, identités inactives et personnes cibles non employées sont refusés avant l'ouverture du flux sensible. Aucun grant d'agent CFO n'est ajouté.

Chaque lecture/écriture valide la chaîne avant d'interpréter les maillons; une corruption est refusée sans réparation. La chaîne SHA-256 non signée signale une altération locale sans recalcul, mais ne protège pas contre un opérateur privilégié capable de réécrire et re-hacher toute la chaîne. La source humaine est une référence déclarée, pas un document authentifié par le système. Le stockage reste celui de l'instance OPSYS et ne constitue pas une isolation multi-tenant.

## Limites

Ce contrat n'établit ni statut CCQ, ni admissibilité fiscale, ni rémunération légale; l'enregistrement atteste une validation humaine d'une source citée. Les heures M4 et leur raccordement sécurisé ne sont pas encore consommés ici. Le brouillon brut, tout calcul fiscal/officiel, les règles d'overtime, vacances, avantages, retenues, coût employeur et paiements demeurent hors de cette tranche.
