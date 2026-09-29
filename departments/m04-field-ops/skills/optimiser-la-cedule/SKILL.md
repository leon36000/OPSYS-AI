---
name: optimiser-la-cedule
description: Procédure pour proposer puis appliquer une cédule par tournées (chantiers proches regroupés, fenêtres du client, quarts, compétences, créneaux déjà confirmés) sans jamais deviner une donnée d'entreprise, une position ou un niveau d'urgence, et sans déplacer un créneau confirmé au client.
---

# Optimiser la cédule

Le solveur PROPOSE, un humain APPLIQUE. Rien n'est assigné avant `m4_appliquer_cedule`. Le tourniquet de
`m4_planifier_intervention` reste le repli « mode bridé », sans géographie : il ne sert plus à ordonner une
journée dès que les chantiers ont des coordonnées confirmées.

1. Vérifie les coordonnées. Chaque chantier à céduler doit avoir été localisé et CONFIRMÉ par un humain
   (skill `localiser-un-chantier`). Sans cela il sort en `non_cedulees` avec « coordonnées manquantes : à
   confirmer » : ne propose jamais le centre d'une ville, demande la confirmation.
2. Rassemble ce que M4 ne sait pas encore. Demande-le à l'admin, n'invente rien, ne reprends pas un ancien
   chiffre « pour voir » :
   - `equipes` : `id` (c'est le `technicien_id` de l'assignation : l'identifiant d'une personne OPSYS pour
     qu'un employé voie ses chantiers), `competences`, `depot` (`id`, `latitude_microdegres`,
     `longitude_microdegres` : un lieu de l'entreprise), `quarts` (`jour`, `debut_min`, `fin_min`, en minutes
     depuis minuit). `jour` est un numéro que tu choisis et gardes cohérent (0, 1, 2 …).
   - `durees_par_type_travaux` et `competences_par_type_travaux` : une clé par type de travaux, pour CHAQUE
     type à planifier (liste de compétences vide si aucune).
   - `chantiers` : une entrée par intervention, avec la `fenetre` du client (`jours`, `debut_min`, `fin_min`) et
     `creneau_fige`. Écris `null` seulement si AUCUN créneau n'a été confirmé au client ; sinon
     `{equipe, jour, debut_min}` exactement comme promis : un créneau confirmé n'est jamais déplacé.
   - `parametres` : `facteur_detour_milliemes`, `vitesse_moyenne_kmh`, `marge_par_trajet_secondes`,
     `iterations`, `cout_non_cedule_m`. Ce sont des paramètres d'entreprise, sans valeur par défaut.
3. Appelle `m4_proposer_cedule`. L'urgence n'est pas un argument : elle est lue au registre
   (`urgence_declaree` vrai vaut 1, faux vaut 0, règle citée dans `regle_urgence`).
   - `REJ-CHAMP-MANQUANT` → le détail liste TOUT ce qu'il faut fournir : redemande-le en une fois.
   - `REJ-CEDULE-RIEN-A-PLANIFIER` → aucune intervention au statut planifiee.
   - `REJ-TOURNEES-CRENEAU-FIGE-INCOMPATIBLE` → un créneau confirmé ne peut pas être tenu (équipe sans
     quart ce jour, compétence manquante, fenêtre, conflit) : dis lequel à l'admin. Ne retire pas le créneau
     pour « faire passer » la cédule.
   - `REJ-TOURNEES-SOLVEUR-ABSENT` → installer l'extra `tournees` (au-delà de 12 chantiers).
   - `accepte: true` → montre à l'admin `plan_id`, `mode_distance`, `avertissement` (si `mode_bride`, dis-lui
     que les distances sont approximatives), les routes (`plan`), `totaux` et surtout `non_cedulees` avec leur
     `raison` et leur `action`. Ne reformule pas une durée, un trajet ou un kilométrage : cite-les.
4. L'admin décide. Pour appliquer, appelle `m4_appliquer_cedule` avec le `plan_id`, `horodatage` et
   `confirme_par` (son nom). En mode ombre, ton appel attend une personne ; n'insiste pas.
   - `REJ-CEDULE-ENTREE-CHANGEE` → une intervention, un technicien assigné ou une coordonnée a changé depuis la
     proposition : ne force rien, propose de nouveau et redemande.
   - `REJ-TOURNEES-PLAN-INVALIDE` → le plan ne repasse pas la vérification : n'essaie pas de le réparer, propose
     de nouveau.
   - `deja_appliquee: true` → le plan l'était déjà : rien n'a été réécrit.
5. Après l'application, dis quelles interventions ont changé d'équipe (`effet: assignee`) et lesquelles gardaient
   déjà la bonne (`deja_assignee`). Une intervention `non_cedulee` garde l'assignation qu'elle avait, s'il y en
   avait une (`assignation_conservee`) : signale-la à l'admin, aucun outil ne la retire.
6. Un refus nomme la faute : corrige la saisie ou demande à l'humain, ne réessaie pas en changeant une valeur au
   hasard. Le jour et l'heure de chaque visite sont dans le plan : ne les recopie pas comme une promesse au
   client (« ne jamais promettre une date sans la confirmation de M4 » : l'admin la confirme).
