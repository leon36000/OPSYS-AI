---
name: optimiser-la-cedule
description: Procédure pour proposer puis appliquer une cédule par tournées (chantiers proches regroupés, fenêtres du client, quarts, compétences, créneaux déjà confirmés), à partir du profil des équipes de l'entreprise, sans jamais deviner une donnée d'entreprise, une position ou un niveau d'urgence, sans déplacer un créneau confirmé au client, et en faisant sortir de a_planifier seulement ce qui est prêt.
---

# Optimiser la cédule

Le solveur PROPOSE, un humain APPLIQUE. Rien n'est assigné avant `m4_appliquer_cedule`. Le tourniquet de
`m4_planifier_intervention` reste le repli « mode bridé », sans géographie : il ne sert plus à ordonner une
journée dès que les chantiers ont des coordonnées confirmées.

1. Vérifie les coordonnées. Chaque chantier à céduler doit avoir été localisé et CONFIRMÉ par un humain
   (skill `localiser-un-chantier`). Sans cela il sort en `non_cedulees` avec « coordonnées manquantes : à
   confirmer » : ne propose jamais le centre d'une ville, demande la confirmation.
2. Ne fournis rien que le profil des équipes de l'entreprise sait déjà. Équipes (membres, compétences, dépôt, quarts),
   durée et compétences par service, réglages de la cédule et fenêtre par défaut d'un chantier à planifier se
   déclarent UNE fois (`opsys equipes declarer`, le propriétaire) et `m4_proposer_cedule` les lit seul : appelle-le avec
   le seul `horodatage`. Un argument REMPLACE la clé entière du profil (surcharge, tracée dans `provenance`) : ne
   surcharge que sur demande de l'admin, jamais « pour voir », et ne reprends pas un ancien chiffre. Sans profil, le
   verdict dit quoi déclarer : dis-le à l'admin, ne devine ni équipe, ni durée, ni quart.
   Ce qui reste à fournir seulement dans ces cas :
   - `chantiers` : une entrée par intervention `planifiee`, avec la `fenetre` du client (`jours`, `debut_min`,
     `fin_min`) et `creneau_fige`. Écris `null` seulement si AUCUN créneau n'a été confirmé au client ; sinon
     `{equipe, jour, debut_min}` exactement comme promis : un créneau confirmé n'est jamais déplacé. Une intervention
     `a_planifier` sans entrée prend la fenêtre par défaut du profil, sans créneau figé.
   - `durees_par_type_travaux` et `competences_par_type_travaux` : une clé par type de travaux pour CHAQUE type à
     planifier, seulement pour les interventions d'un lead v1 (gelé : le profil est par service). N'envoie rien si le
     lot n'en contient aucune. Ne range jamais un service sous ces tables, ni l'inverse.
   - `equipes`, `durees_par_service`, `competences_par_service`, `parametres` : seulement pour surcharger le profil.
3. Appelle `m4_proposer_cedule`. L'urgence n'est pas un argument : elle est lue au registre
   (`urgence_declaree` vrai vaut 1, faux vaut 0, règle citée dans `regle_urgence`).
   - `REJ-CHAMP-MANQUANT` → le détail liste TOUT ce qu'il faut fournir et où le déclarer : redemande-le en une fois.
   - `REJ-PROFIL-INVALIDE` → le profil des équipes est écrit mais invalide : le détail dit pourquoi ; c'est au
     propriétaire de le corriger, ne le remplace pas par des arguments à ta façon.
   - `REJ-CEDULE-RIEN-A-PLANIFIER` → aucune intervention `planifiee` ni `a_planifier` prête ; le détail nomme les
     `a_planifier` non prêtes et leurs volets manquants (`m4_verifier_preparation` dit quoi faire).
   - `REJ-CEDULE-PREPARATION-NON-PRETE` → une intervention demandée par `intervention_ids` n'est pas prête : dis ce
     qui lui manque, ne la force pas. Le matériel se lit chez M6 (`materiel` : prêt, partiel ou à commander) et la météo
     dans les règles que le propriétaire a déclarées pour le service (`meteo` : « seuil à configurer ») : dis lequel manque.
   - `REJ-TOURNEES-CRENEAU-FIGE-INCOMPATIBLE` → un créneau confirmé ne peut pas être tenu (équipe sans
     quart ce jour, compétence manquante, fenêtre, conflit) : dis lequel à l'admin. Ne retire pas le créneau
     pour « faire passer » la cédule.
   - `REJ-TOURNEES-SOLVEUR-ABSENT` → installer l'extra `tournees` (au-delà de 12 chantiers).
   - `accepte: true` → montre à l'admin `plan_id`, `mode_distance`, `avertissement` (si `mode_bride`, dis-lui
     que les distances sont approximatives), les routes (`plan`), `totaux` et surtout `non_cedulees` avec leur
     `raison` et leur `action`. Ne reformule pas une durée, un trajet ou un kilométrage : cite-les.
4. L'admin décide. Pour appliquer, appelle `m4_appliquer_cedule` avec le `plan_id`, `horodatage` et
   `confirme_par` (son nom). En mode ombre, ton appel attend une personne ; n'insiste pas.
   - `REJ-CEDULE-ENTREE-CHANGEE` → une intervention, un technicien assigné, une coordonnée ou le profil des équipes a
     changé depuis la proposition : ne force rien, propose de nouveau et redemande.
   - `REJ-CEDULE-PREPARATION-NON-PRETE` → une préparation n'est plus prête depuis la proposition (adresse retirée…) :
     rien n'a été écrit ; dis laquelle.
   - `REJ-TOURNEES-PLAN-INVALIDE` → le plan ne repasse pas la vérification, ou l'équipe d'une intervention qui sort de
     `a_planifier` n'est pas admissible selon le profil : n'essaie pas de le réparer, propose de nouveau.
   - `deja_appliquee: true` → le plan l'était déjà : rien n'a été réécrit.
5. Après l'application, dis quelles interventions ont changé d'équipe (`effet: assignee`) et lesquelles gardaient
   déjà la bonne (`deja_assignee`) ; celles dont `transition` vaut `a_planifier->planifiee` viennent de sortir de
   `a_planifier` (une intervention que le plan laisse de côté reste `a_planifier`). Une intervention `non_cedulee` garde l'assignation qu'elle avait, s'il y en
   avait une (`assignation_conservee`) : signale-la à l'admin, aucun outil ne la retire.
6. La météo. Pour un plan proposé ou appliqué, appelle `m4_verifier_meteo_creneau` (lecture seule) avec le `plan_id`
   et le `calendrier` `{jour: date AAAA-MM-JJ}` : M4 n'a pas de calendrier, demande à l'admin la date de chaque jour
   numéroté, ne la devine jamais. Sans fournisseur de prévisions ouvert, l'admin te dicte la prévision : passe-la telle
   quelle dans `previsions_saisies` (`saisi_par` : son nom, `source`, `emise_le`, `points` horaires) ; n'arrondis, ne
   complète ni ne devine aucune mesure (une mesure absente reste absente).
   - Rapporte chaque créneau : `bloquant`, `validation_requise`, `ok` ou `inconnu`, avec la valeur, le seuil, la source
     et l'heure de la prévision que la réponse cite. `inconnu` n'est jamais un « ok » : dis ce qui manque (seuil à
     configurer, prévision absente ou incomplète, jour sans date, fournisseur en panne).
   - Un créneau `bloquant` donne un report PROPOSÉ (`reports_proposes`, motif `meteo`) et une nouvelle cédule pour les
     jours restants (`cedule_relancee` : arguments et aperçu). Montre-les, l'admin décide ; tu n'appliques rien :
     `m4_signaler_report` et `m4_appliquer_cedule` sont N3. Le report d'un chantier déjà confirmé au client se
     prévient par M1, jamais d'ici.
   - `plan_perime` : un autre plan appliqué tient déjà l'intervention (`perimes`, `tenu_par`) : vérifie ce plan-là.
   - `detail_reduit` : la réponse a été résumée pour tenir dans un appareil ; refusée pour sa taille, redemande un
     jour à la fois avec `jours`.
7. Un refus nomme la faute : corrige la saisie ou demande à l'humain, ne réessaie pas en changeant une valeur au
   hasard. Le jour et l'heure de chaque visite sont dans le plan : ne les recopie pas comme une promesse au
   client (« ne jamais promettre une date sans la confirmation de M4 » : l'admin la confirme).
