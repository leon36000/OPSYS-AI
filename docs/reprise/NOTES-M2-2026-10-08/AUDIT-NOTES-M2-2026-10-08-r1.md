# Notes M2 — T4.8-b, Toronto 2026-10-08

OPSYS-AI reste **PARTIEL**. Parent publié : `cc9d50ce5715d27ffbc729434fe25b477e55c393`. Quatre sources ont été rapprochées de leurs préimages dans un workspace isolé puis intégrées au principal. Date de rédaction : 2026-10-08T00:20:31.571636-04:00. Publication privée et CI exacte suivantes restent à obtenir.

La façade `m2_enregistrer_interaction` refuse un champ `resume` non vide de plus de300pointsUnicode reçus, sans troncature. Identité courante, auteur effectif et propriété du lead précèdent ce contrôle. Le schéma canonique publie `maxLength:300`; son validateur générique minimal ne l’applique pas, donc la façade garantit la borne. Le verdict existant `REJ-CONTRAT-INVALIDE` demande de raccourcir la note sans recopier son texte. Types/vide/date dans la borne gardent leur contrat; une note longue non vide est refusée avant la validation de date de la primitive.

L’app envoie le texte épuré et compte300unitésUTF16 : une valeur admise par le mobile reste sous la borne Python. Les astrales et l’échappement sont qualifiés explicitement, sans présenter ces deux comptages comme identiques. La primitive interne `interactions.enregistrer` reste inchangée : quatre cascades M3/M4 produisent des traces, dont une fixture d’affaire répétée de326pointsUnicode. Les historiques longs ne sont ni tronqués ni réécrits, et leur lecture ne mute rien. Un auteur `system:m3` revendiqué via la façade ne contourne pas la borne.

## Preuves

- Rouge initial :18cas,10échecs,8réussites; HTTP :2échecs. La garde et le schéma absents sont ainsi reproduits.
- Premier essai de garde :19réussites/1échec. L’oracle supposait à tort zéro trace HTTP pour un refus métier. Il est corrigé, sans changement du protocole : registre/événements inchangés, une approbation, une mutation d’idempotence et une trace de journal attendues. Rejeu du refus identique sans nouvel effet; payload changé sous même clé refusé en conflit; note corrigée avec une nouvelle clé.
- Deux fichiers complets :**121réussites,aucun skip**, puis requalification sur le principal avec les quatre empreintes courantes :**121réussites**,28,892s.
- Département M2 entier et parcours UTM M7→M1→M2, vendeur, acceptation de devis et relances :**1849réussites,aucun skip**,149,627s; imports du workspace attestés, digest stable `4285077bf9f6e54c9439bd8d272857841c69dee150ace29b215336fd86477a48`.
- Ruff initial :troisE501; réparations de format seulement, AST identique attesté. Ruffr2 et vérificateur verts :10départements/219outils/127déclarations d’appareil. Requalification principale stable `ed340130ecfbcbd7841b364827d094e213138112afea7c8b48f4bfd97b258ea1`.
- Revue indépendante :30cas verts,aucun finding matériel; reçu r1 conservé puis r2 confirme les quatre empreintes après réparations AST identiques.

Ces campagnes se recouvrent et ne s’additionnent pas. Les appels HTTP MCP/SQLite de ce lot passent par la porte Python du harnais : aucune nouvelle qualification Gateway TypeScript ou téléphone n’en est déduite. Le comportement mobile ne change pas; son commentaire est actualisé. Les preuves Core/CI des parents restent distinctes du futur HEAD.

## Limites et continuité

La borne des notes nouvelles ne garantit pas toute réponse Client360 sous6000caractères : textes historiques, contacts, nombre d’opportunités et échappement peuvent encore peser. Aucun GET migratoire, changement financier, relance, réassignation ou envoi externe. La suggestion `doublon_en_attente` pour le vendeur et la décision de marge restent des sous-tranches ouvertes de T4.8-b. Les104preuves exclues et le supplément généré restent absents; le registre exhaustif de la reprise précédente conserve leurs références.

La suite M3 doit joindre la readiness et l’estimation déterministe à la verticale durable sous les mêmes identifiants, avec ses contrôles et limites, sans prix réel ni promotion de barème. M2profond et les dix départements restent requis.
