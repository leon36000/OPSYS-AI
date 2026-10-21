# Rejeu des messages de canal M1

`m1_recevoir_message_canal` dérive le signal du canal et de l'identifiant fourni. Quand un signal existe, M1 compare avant tout autre traitement le contenu filtré, l'état du filtre de provenance, le canal/source, l'identité canonisée du correspondant (via conversation_id) et l'heure normalisée. Un rejeu qui concorde rend la décision précédente sans écrire une autre ligne, un transfert ou un événement. Si l'un de ces champs diffère, l'outil refuse avec `REJ-SIGNAL-CONTRADICTOIRE` et ne touche pas au registre ni au bus.

Les UTM de formulaire sont des métadonnées d'attribution distinctes du contenu métier : un rejeu peut les présenter ou les omettre, mais elles ne remplacent ni ne modifient les UTM conservés sur le signal/lead d'origine. La réponse précise si ces UTM de rejeu sont portées par le lead, conformément au contrat existant.

Cette vérification protège le registre M1 contre une réutilisation contradictoire d'un ID. Elle ne prouve pas que les paramètres proviennent réellement d'un webhook signé ni qu'un fournisseur n'a pas usurpé le message : le transport doit encore attacher une enveloppe authentifiée hors des arguments du modèle.
