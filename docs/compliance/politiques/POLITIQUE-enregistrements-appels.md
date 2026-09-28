> **PROPOSITION (P0-7)** — document généré par l'équipe OPSYS-AI et validé par revue scellée
> multi-modèles. **VALIDATION FINALE : Nathan (T3)** — aucun usage externe ni engagement avant sa
> validation écrite. Responsable de la protection des renseignements personnels (RP) : **Nathan**.

# Politique d'enregistrement des appels (M1 Front Office)

## 1. Objet et portée

Cette politique régit l'enregistrement audio des appels téléphoniques entrants et sortants traités par le module M1 (Front Office). Elle s'applique aux appelants externes (clients, prospects, fournisseurs) et aux employés intervenant dans la ligne téléphonique. L'enregistrement est une fonctionnalité **sous EFVP majeure** et n'est activé qu'avec information préalable et, le cas échéant, consentement requis.

## 2. Base légale et principes

- **Information préalable** : l'appelant est informé par une annonce en début d'appel que la conversation peut être enregistrée.
- **Politique écrite** : le présent document et la notice interne aux opérateurs constituent la politique écrite.
- **Consentement documenté** : lorsque la loi l'exige, l'accord de l'appelant est recueilli avant l'enregistrement.
- **Collecte limitée** : les enregistrements ne concernent que les interactions professionnelles et sont limités aux heures de service.
- **Minimisation et confidentialité par défaut** : seule la conversation utile est conservée ; les silences et données hors sujet sont élagués si techniquement possible.
- **Accès journalisés** : tout écoute, transcription ou export est tracé.

## 3. Ce qui est collecté / ce qui ne l'est JAMAIS

**Collecté :**
- Fichier audio de la conversation.
- Métadonnées : date/heure, numéros masqués, agent, durée, motif de l'appel.
- Transcription automatique, soumise aux mêmes règles que l'audio.

**Jamais collecté :**
- Appels personnels des employés.
- Données bancaires complètes ou mots de passe prononcés à l'oral (les opérateurs doivent utiliser des canaux sécurisés).
- Enregistrement après désactivation par l'appelant.

## 4. Consentement

- **Comment il est demandé** : annonce vocale en début d'appel et, si applicable, option de désactivation (touche ou verbal).
- **Comment il est documenté** : flag `consentement_annonce` dans le CDR et, si requis, enregistrement du segment d'acceptation.
- **Comment il est retiré** : l'appelant peut demander l'arrêt de l'enregistrement pendant l'appel ou la suppression postérieure par demande écrite.

## 5. Rétention et destruction

- **Classe de données** : enregistrements audio et transcriptions.
- **Durée courte définie** : 12 mois après la date de l'appel pour les enregistrements qualité/qualification, sauf obligation légale contraire. [À VÉRIFIER — juriste : durée applicable au secteur.]
- **Renvoi** : calendrier de destruction `GABARIT-EFVP.md`.

## 6. Accès et journalisation

- Accès limité aux superviseurs M1, responsable qualité et responsable conformité.
- Journal de chaque écoute, téléchargement ou transcription.
- Pseudonymisation des numéros dans les interfaces d'écoute.

## 7. Droits des personnes

- Droit d'accès à l'enregistrement et à sa transcription.
- Droit de rectification des métadonnées.
- Droit d'opposition et de retrait.
- Droit à l'effacement dans les délais du calendrier EFVP.

## 8. Renvois

- `GABARIT-EFVP.md` — calendrier de destruction et minimisation.
- Registre d'incidents et procédure de notification CAI (Plan maître §14.2).
- Notice interne aux opérateurs M1.

