# Documents internes d’une affaire — interface admin

Le panneau « Documents internes de l’affaire » appartient à la page Mémoire existante.
Ouvrir explicitement une affaire depuis la recherche ou un signal cible à la fois son paquet
informatif et ses documents. Changer le texte de recherche ou rafraîchir le paquet ne change
pas la cible documentaire ni son brouillon. Les autres volets de mémoire et l’arbitrage
conservent leurs contrats.

## Lectures et provenance

L’index T0 contient seulement les métadonnées, une version par page. Chaque page remplace la
précédente ; aucun instantané figé entre pages, aucune concaténation ni totalité supposée.
Une sélection explicite lit la référence exacte d’une version. Les titres, statuts, auteurs
historiques, dates source, références et empreintes proviennent du lecteur strict. Le statut
« courante » est celui de la lecture. Aucune heure client n’est présentée comme date source.
Les références CAS restent dans le contrôleur et sont renouvelées par une lecture puis une
resélection. Un document retiré ne fournit aucun corps ni geste d’activation ou de nouveau dépôt.

Ni index ni corps ne sont mis en cache. Hors ligne, après refus ou après invalidation de
session, les contenus précédents ne sont pas repris. Le focus et la reconnexion relisent
uniquement les informations ; ils ne soumettent aucune mutation. Les callbacks d’un ancien
rendu ne peuvent agir sur une autre sélection ou une session remplacée.

## Brouillon et intentions

Le brouillon est explicitement non sauvegardé, en RAM dans le panneau. Sa cible est séparée
des lectures courantes : une déconnexion conserve la saisie et la cible, mais ferme les
lectures et suspend les actions. La fermeture du panneau ou le changement de session perd
le brouillon. Aucun brouillon ne devient automatiquement une intention.

Le titre est limité par le modèle à 120 points Unicode et le corps à 2000 points (8000 octets
UTF-8 maximum dans le contrat). L’interface conserve exactement la saisie, y compris les
retours de ligne, et bloque le dépôt invalide ; elle ne tronque, ne normalise ni ne nettoie
silencieusement le contenu.

Trois gestes distincts passent par le contrôleur : déposer une version INTERNAL, activer
une version sélectionnée, retirer l’accès au document. Déposer n’active rien. Le contrôleur
persiste l’intention avant le réseau et réutilise son UUID à chaque reprise explicite. Un
reçu propre confirme l’intention exacte, pas l’état actuel du document. Les intentions
inconnues, permanentes ou munies d’un reçu invalide continuent à bloquer leur série ; l’écran
n’offre aucun abandon ni remplacement d’UUID. Les identifiants et statuts durables sont
visibles séparément des corps documentaires.

## Qualification et limites

Les tests du panneau utilisent ReactTestRenderer, le contrôleur réel et le dépôt RAM réel ;
focus, session et transport sont contrôlés. Les fixtures de rendu sont fictives et ne prouvent
ni transport authentifié, ni téléphone, ni pont Expo SQLite. La qualification des lecteurs
sur captures Cap et celle du backend SQLite sont distinctes. Cette tranche ne fournit ni
import de fichier, ni OCR, ni RAG, ni accès client. Le produit demeure PARTIEL.
