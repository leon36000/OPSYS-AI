# Contrat proposé : travaux terminés M4 vers M5

Une livraison `m4.travaux_termines` peut être consommée une fois par M5. Sans autorité qualifiée, M5 conserve le reçu et indique les coûts inconnus ; une durée scalaire ne démontre pas une équipe et ne suffit pas à établir une main-d'œuvre complète. Les devis arrivés plus tard restent partiels jusqu'à une révalidation propriétaire autorisée.

Pour une livraison qualifiée, Core lie une capacité éphémère à la transaction de livraison SQLite, à l'instance, au WCT et à une politique active ; M4 vérifie ses faits et M5 confronte les pièces reçues et ses tarifs, relit leurs snapshots et conserve une preuve de la publication. Révocation ou mutation invalide la transaction. Aucune politique n'est activée par ce contrat. La preuve historique décrit une liaison, sans attester la fraîcheur actuelle ni les tarifs M5.

Les migrations 0032 et 0033 sont proposées sous réserve de vérification des numéros et de la base de migration finale. Cette proposition est limitée à SQLite : PostgreSQL et l'exécution native n'ont pas été qualifiés. La lecture stricte et l'historique sont bornés à 1000 lignes ; cette limite doit être traitée avant exploitation à plus grande échelle. Un contrat distinct est nécessaire pour un recalcul après WCT, avec provenance appropriée.
