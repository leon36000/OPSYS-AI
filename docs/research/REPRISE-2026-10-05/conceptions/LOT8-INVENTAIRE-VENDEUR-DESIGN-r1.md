# Design proposé — `m3_lister_devis` (avant implémentation)

L'outil exige une identité d'appareil active dont le rôle vérifié est `seller`; il refuse l'appel sans appareil et les rôles non vendeur. L'identité de propriétaire provient uniquement de cette identité vérifiée et de `_proprietaire_du_lead`, qui relit le fait d'assignation M2 courant dans la transaction.

La source est le registre de devis durable `registre_devis_production()` et le réducteur déjà existant `devis_durable.lister_devis()`, qui fusionne création et transitions et trie par `devis_id`. Chaque élément est filtré par propriétaire courant avant projection via `devis_durable.projeter_devis(..., "interne")`; les brouillons, envoyés et acceptés restent visibles selon leur état effectif. Aucun argument de propriétaire, lead, statut ni projection n'est accepté.

Pagination par clé sur l'ordre stable `devis_id`, avec limite bornée (défaut 20, maximum 50), curseur lié à la personne authentifiée et au dernier identifiant rendu. Un curseur ne confère aucun droit : on revalide la personne, le rôle et l'appartenance du repère au vendeur courant à chaque page. Toute forme invalide ou repère absent/hors portée donne un refus générique sans détail d'existence. La réponse porte seulement les devis de cette page et un curseur suivant ou `null`; aucun total, compte global, ni identifiant d'un autre vendeur n'est rendu.

L'outil est T0 en lecture seule et sa portée d'appareil est seller uniquement. Le test de contrat couvrira l'enregistrement réel, appels authentifiés, rôles, filtres, pages stables, curseur invalide, et absence d'écritures. Aucun manifeste ne devrait changer: la découverte est le registre runtime existant.
