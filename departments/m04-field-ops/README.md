# M4-field-ops

Field Operations OS — cedule, dispatch, GPS prive, Work Completion Trigger

Statut: PARTIAL (EPIC G — vague 1 livrée en mode ombre : encodage canonique injectif, registre
append-only hash-chaîné, contrats et frontières, machine à états 7 statuts, cédule déterministe,
pointage horodaté et géolocalisé, écarts et file pending_review, Work Completion Trigger en
maillon composite atomique, digest et gardes de conformité. 427 tests.)

PLAN T1.4-k — contrôle d'accès par personne et par intervention (`acces.py`, pur ; détail et limites
dans `docs/architecture/ROLES.md`). Pour un appel d'appareil, l'identifiant de technicien EST celui de la
personne OPSYS authentifiée (`opsys.contexte.identite_appelante()`, revérifiée en base à chaque appel).
Un `employee` n'agit que sur les interventions qui lui sont assignées (`REJ-INTERVENTION-NON-ASSIGNEE`) et
sous son propre identifiant (`REJ-IDENTITE-FOURNIE-DIFFERENTE`, jamais remplacé en silence) : `m4_pointer`,
`m4_demarrer_route`, `m4_signaler_report`, `m4_creer_demande_ecart`, `m4_completer_intervention` ;
`m4_lister_interventions` et `m4_statut_intervention` ne lui montrent que les siennes. L'`admin` garde
toutes les interventions ; un appel sans identité d'appareil (agent, console) se comporte comme avant.
L'assignation entre au registre à la planification (maillon `assignation_technicien`,
`etats.assigner_technicien`) : sans elle, aucune intervention n'était « à quelqu'un » avant son départ.
`m4_definir_consentement_gps` est ouvert à l'employé pour SA personne seulement (retrait du consentement
GPS, POLITIQUE-geolocalisation §4) ; `accede_par` de `m4_lire_position_gps` doit être la personne
authentifiée.
