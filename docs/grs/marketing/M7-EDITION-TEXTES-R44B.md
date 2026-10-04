# R44b — corriger un texte dans le calendrier marketing

État au 2026-10-02 : implémentation locale, qualification complète et revue ROOT
en préparation. Ce lot prolonge le [raccord de la marque R44a](M7-MARQUE-USINE-R44A.md).
Il ne publie rien et ne remplace pas les décisions du propriétaire.

## Parcours humain

Le propriétaire actif ouvre `/marketing/calendrier`, puis « Modifier le texte »
sur la proposition de son choix. Les cinq variantes existantes sont concernées :
Facebook, Instagram, fiche Google, vidéo courte et demande privée de témoignage.
Le formulaire conserve le texte complet et le plafond de la plateforme.

Une correction d'une proposition proposée, approuvée ou rejetée crée une nouvelle
version proposée pour cette seule plateforme. Elle reçoit un nouvel identifiant,
une nouvelle référence UTM et l'auteur humain confirmé en base, avec l'heure du
serveur. La dernière correction est visible dans le formulaire. Les quatre autres
variantes, le texte antérieur, ses décisions et ses exports restent historiques.
Un texte identique, après retrait des espaces extérieurs, ne crée aucune version.

La nouvelle version exige sa propre décision de texte et son propre créneau.
Elle n'hérite pas des médias préparés ni de leur revue : ceux-ci sont liés à
l'ancienne proposition. Le paquet manuel n'est remis qu'après les contrôles
existants de texte, créneau, marque, consentement et médias applicables. Une
ancienne version ne devient pas à nouveau la version courante par cette édition.

## Source et enregistrement

Le [service existant](../../../departments/m07-marketing/src/m7_marketing/usine/service.py)
compose la nouvelle version par le
[préparateur de chantier](../../../departments/m07-marketing/src/m7_marketing/usine/chantier.py).
Les règles de confidentialité, d'engagement commercial et de longueur continuent
de s'appliquer ; aucun moteur parallèle ni texte de marque inventé n'est ajouté.

Le formulaire est lié à la révision, à l'empreinte du texte et à un snapshot de la
proposition entière, du WCT entier, de la preuve de marque courante et des retraits
pertinents. Le seul hash déclaré du WCT ne suffit pas. Une source changée impose
de relire avant d'enregistrer. L'auteur vient de l'identité propriétaire active,
jamais d'un champ du navigateur. Le rôle et les sources sont contrôlés de nouveau
avant l'append final, dans la transaction SQLite existante.

La lecture des trois journaux utilisés par l'édition borne leur nombre de lignes
(10 000), leur longueur SQL cumulée (8 Mio de caractères) et chaque ligne
(65 536 caractères), avant décodage. Les données non JSON fini, les erreurs de
codec et les empreintes incohérentes refusent avec un diagnostic métier fermé.
Le texte entrant est borné à 2 000 caractères dans l'adaptateur, à 8 000 octets
UTF-8 dans le service et au plafond propre à sa plateforme. Le HTML est échappé.
Ces bornes ne qualifient pas l'ensemble des lecteurs historiques M7.

## Permissions, reprises et limites

Le [port console privé](../../../src/opsys/console/metier.py) réserve lecture et
correction au propriétaire actif. Le GET privé
`/api/marketing/calendrier/textes/{contenu_id}` ne modifie aucun journal. Le POST
réutilise la page et l'API du calendrier, leurs sessions, CSRF et reçus existants.
Les champs supplémentaires, une révision booléenne ou une identité libre refusent.
Aucun nouvel outil MCP, rôle, manifeste ou catalogue appareil n'est créé.

Même clé et mêmes arguments : le reçu historique revient, sans nouvelle version.
Même clé avec d'autres arguments : conflit. Avant ce reçu, le rôle vivant, le WCT,
le consentement et la validité de la marque courante sont relus. Le CAS de la
commande originale n'est pas réappliqué à son propre reçu : un reçu historique
n'est pas une nouvelle édition ou une qualification actuelle de l'ancien texte.
Une nouvelle clé avec une révision périmée refuse.

Les mutations de ce lot sont explicitement réservées à SQLite. Le refus d'un autre
dialecte est testé avec une simulation de dialecte, pas une exécution PostgreSQL.
Aucune atomicité concurrente PostgreSQL n'est revendiquée. Le rejeu générique MCP
historique décrit dans R44a reste hors de ce port privé ; Capacites/SDK sont inchangés.

Les preuves locales utilisent HTTP TestClient, SQLite, personnes et chantiers
fictifs, avec un vrai blob PNG CAS et une revue média dans un parcours ciblé.
Elles ne qualifient ni navigateur graphique, modèle, OAuth, publication publique,
fournisseur, apprentissage M10, déploiement VPS ou département CMO complet.
