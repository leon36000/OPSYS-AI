> **PROPOSITION (PLAN T2.3)** — document généré par un agent OPSYS-AI (M3, câblage de
> l'orchestrateur d'estimation), à valider par revue scellée multi-modèles puis par Nathan.
> **VALIDATION FINALE : Nathan ou un juriste (T3)** — aucune collecte réelle de photo de chantier
> ni usage externe avant sa validation écrite. Responsable de la protection des renseignements
> personnels (RP) : **Nathan**.

STATUT_VALIDATION: proposition

# Politique de photos non contractuelles (M3 — Estimation)

## 1. Objet et portée

Cette politique encadre les photos de propriétés clientes prises ou transmises pour l'estimation
(M3) et, plus tard, pour la documentation avant/après d'un chantier (M4, M7 avec consentement
séparé — voir `POLITIQUE-consentement-sms.md` pour la demande d'avis). Elle couvre les photos
elles-mêmes (octets d'image) et leurs métadonnées (résolution, éclairage, angle, référence
d'échelle).

**État réel du code au moment de cette proposition (mesuré, `docs/departements/M3-audit.md` §2.7,
DA-M3-04) : M3 ne lit ni ne stocke AUJOURD'HUI aucun octet d'image.** Le paquet
`m3_estimation` (`qualite_photos.py`, `hierarchie_echelle.py`) ne traite que des MÉTADONNÉES
déclarées par l'appelant (résolution, éclairage, angle, présence d'une référence d'échelle) —
jamais un pixel. Cette politique est donc écrite **par anticipation**, avant l'activation d'une
capacité qui collecterait un octet d'image réel (Phase 2 de l'audit M3 : SAM2, Grounding DINO,
OpenCV), conformément à `docs/departements/M3-audit.md` §5 point 2 : « à traiter avant la Phase 1,
tâche 10, pas après ». Une garde de code (`src/m3_estimation/politique_photos.py`,
`m3_verifier_politique_photos`) refuse fail-closed toute collecte réelle tant que le
`STATUT_VALIDATION` ci-dessus ne vaut pas exactement `valide`.

## 2. Base légale et principes

- **Non-contractuelles** : les photos de chantier documentent l'état des lieux et l'avancement du
  travail ; elles ne constituent jamais, à elles seules, un engagement contractuel envers le
  client (le devis et son acceptation restent le document contractuel, `devis_durable.py`).
- **Minimisation** (DEFINITION-PRODUIT.md §8) : seules les photos nécessaires à l'estimation ou à
  la documentation du chantier sont demandées ; aucun usage marketing ou d'entraînement de modèle
  sans consentement distinct et explicite (P8 DEFINITION-PRODUIT.md).
- **Consentement documenté** avant toute collecte réelle d'octets d'image (voir §4).
- **Rétention limitée et configurable** (voir §5), jamais indéfinie par défaut.
- **Accès journalisé et limité** aux rôles qui en ont besoin (vendeur, estimateur, employé
  assigné au chantier, Nathan).

## 3. Ce qui est collecté / ce qui ne l'est jamais

**Collecté aujourd'hui (mesuré) :**
- Métadonnées déclarées par l'appelant : résolution (largeur/hauteur en pixels), éclairage
  (échelle 0-10), angle de prise de vue, présence et type d'un objet de référence d'échelle.

**Collecté SI cette politique est validée et qu'une capacité de collecte réelle est activée
(Phase 2) :**
- Octets d'image du chantier ou de la propriété, transmis par le client ou le vendeur/employé.
- Horodatage et identifiant de la photo, lien vers le lead/devis/chantier concerné.

**Jamais collecté, quel que soit le statut de cette politique :**
- Photos de personnes identifiables sans consentement séparé et explicite.
- Photos de propriétés voisines ou hors du périmètre du chantier concerné.
- Usage marketing (avant/après, réseaux sociaux) sans le consentement distinct déjà prévu par le
  flux M7 « demande d'avis, soumise au consentement » (T1.2-c).
- Entraînement de modèle d'IA sur des photos client non anonymisées (AGENTS.md, DEFINITION-
  PRODUIT.md §8).

## 4. Consentement

- **Comment il sera demandé** : au moment de la demande de photos (vendeur via l'app, ou lien
  envoyé au client), avec explication de la finalité (estimation, puis documentation de chantier
  si le client accepte).
- **Comment il sera documenté** : [À CONCEVOIR — la table de consentement dédiée n'existe pas
  encore dans le socle ; à construire sur le même patron que `employee_consent_location`
  (`POLITIQUE-geolocalisation.md` §4) avant l'activation de la collecte réelle.]
- **Consentement à l'usage marketing d'un chantier terminé (PLAN T1.5-d)** : distinct de celui de la demande
  d'avis (`consentement_demande_avis`), il est recueilli par l'employé auprès du client à « Terminer » dans l'app
  (case non cochée par défaut, texte fr-CA versionné) et documenté dans le WCT de M4, écrit dans son registre
  immuable : la personne qui l'a recueilli, l'heure de réception du serveur et la version du texte présenté.
  Absent = non consenti. Les énoncés restent une proposition, à valider (T3) avec cette politique.
- **Comment il pourra être retiré** : le client peut demander la suppression des photos
  transmises à tout moment ; le retrait n'affecte pas une estimation déjà produite (l'estimation
  reste un fait daté, mais les images source sont détruites).

## 5. Rétention et floutage

- **Classe de données** : photos de chantier ou de propriété et leurs métadonnées.
- **Durée** : [À VÉRIFIER — juriste : durée de rétention applicable, proposée par défaut à 24 mois
  après la fin du chantier ou le refus du devis, selon le premier des deux événements — configurable
  par instance, jamais codée en dur dans `src/m3_estimation`.]
- **Floutage** : toute photo destinée à un usage externe (avis client, réseaux sociaux, portfolio —
  flux M7) doit être floutée sur les visages, plaques d'immatriculation et tout élément identifiant
  une personne ou une propriété tierce visible dans le cadre, AVANT publication — jamais après. Le
  floutage est une étape gérée par M7 au moment de la publication proposée (avec consentement,
  T1.2-c) ; ce paquet (M3) ne publie rien lui-même (SOUL.md).
- **Renvoi** : calendrier de destruction détaillé dans `../GABARIT-EFVP.md`, à remplir avant
  l'activation de la collecte réelle.

## 6. Accès et journalisation

- Accès restreint : le vendeur/estimateur assigné au lead, l'employé assigné au chantier, Nathan.
- Le client ne voit que ses propres photos et l'estimation qui en découle.
- Tout accès ou export de photos réelles est journalisé (qui, quand, pourquoi) — même discipline
  que P3 (traçabilité totale) et P8 (Loi 25) de `docs/produit/DEFINITION-PRODUIT.md`.

## 7. Droits des personnes

- Droit d'accès aux photos les concernant.
- Droit de rectification (remplacer une photo par une version plus récente ou correcte).
- Droit de retrait du consentement et de suppression, à tout moment.
- Droit à la portabilité des photos transmises.

## 8. Garde de code (fail-closed)

Tant que `STATUT_VALIDATION` ci-dessus ne vaut pas exactement `valide` :

- `src/m3_estimation/politique_photos.py::verifier_collecte_photo_autorisee` refuse
  (`REJ-PHOTO-POLITIQUE-NON-VALIDEE`) — tout futur code qui lirait ou stockerait un octet d'image
  réel DOIT appeler cette garde avant d'agir et respecter son refus.
- L'outil agent `m3_verifier_politique_photos` (lecture seule, T0) permet de constater ce statut
  à tout moment, y compris depuis le dashboard ou un agent.
- Passer `STATUT_VALIDATION` à `valide` est une décision de Nathan ou d'un juriste — jamais une
  modification faite par un agent de son propre chef.

## 9. Renvois

- `../GABARIT-EFVP.md` — calendrier de destruction et minimisation.
- `POLITIQUE-consentement-sms.md`, `POLITIQUE-geolocalisation.md` — patrons de consentement et de
  rétention déjà validés pour d'autres flux, à suivre pour la table de consentement du §4.
- `docs/departements/M3-audit.md` §5 point 2 — constat qui motive cette proposition.
- Registre d'incidents et procédure de notification CAI (Plan maître §14.2).
