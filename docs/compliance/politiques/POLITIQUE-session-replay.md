> **PROPOSITION (P0-7)** — document généré par l'équipe OPSYS-AI et validé par revue scellée
> multi-modèles. **VALIDATION FINALE : Nathan (T3)** — aucun usage externe ni engagement avant sa
> validation écrite. Responsable de la protection des renseignements personnels (RP) : **Nathan**.

# Politique de session replay et CRO (M7)

## 1. Objet et portée

Cette politique régit l'utilisation d'outils de session replay et d'optimisation du taux de conversion (CRO) dans le module M7 (Portail client / employé). Elle s'applique aux sessions des utilisateurs finaux sur les interfaces web et mobiles. La capture est **toujours conditionnelle à un consentement actif** et n'est jamais passive.

## 2. Base légale et principes

- **Information préalable** : l'utilisateur est informé, avant toute capture, des finalités d'optimisation de l'expérience utilisateur.
- **Politique écrite** : le présent document constitue la politique écrite.
- **Consentement documenté** : la capture ne démarre qu'après acceptation explicite via bandeau de consentement.
- **Collecte limitée** : la capture est limitée aux interactions nécessaires à l'analyse UX/CRO.
- **Minimisation et confidentialité par défaut** : les PII sont masquées dès la capture ; les champs sensibles sont exclus par configuration.
- **Pas de notion d'heures de travail** : le session replay est une technologie côté client ; son fondement est le **consentement actif à la capture**, qui ne doit jamais être passif. La limitation aux heures de travail ne s'applique pas ici.
- **Accès journalisés** : tout visionnage de replay est tracé.

## 3. Ce qui est collecté / ce qui ne l'est JAMAIS

**Collecté :**
- Séquence d'interactions (clics, déplacements, scrolls) sur l'interface.
- Données techniques (résolution, navigateur, OS, session ID).
- Erreurs JavaScript et temps de chargement.

**Jamais collecté :**
- Contenu des champs de mot de passe, carte de crédit ou tout champ marqué sensible.
- PII non masquées (nom, adresse, téléphone) dans les replays.
- Capture avant acceptation du bandeau.

## 4. Consentement

- **Comment il est demandé** : bandeau de consentement affiché au premier accès, avec option d'accepter ou de refuser.
- **Comment il est documenté** : enregistrement du choix dans le cookie/local storage et dans la table `consent_replay` avec version de la politique, date/heure UTC et identifiant de session.
- **Comment il est retiré** : l'utilisateur peut retirer son consentement via le bandeau réapparaissant ou la page de paramètres de confidentialité. Le retrait arrête immédiatement la capture.

## 5. Rétention et destruction

- **Classe de données** : replays de session et métadonnées associées.
- **Durée courte définie** : 6 mois après la date de capture, sauf besoin d'investigation d'incident. [À VÉRIFIER — juriste : durée maximale acceptable pour analyses CRO.]
- **Renvoi** : calendrier de destruction `GABARIT-EFVP.md`.

## 6. Accès et journalisation

- Accès restreint aux équipes produit/UX, développement et conformité.
- Journal de chaque lecture de replay.
- Pseudonymisation du session ID dans les rapports d'agrégation.

## 7. Droits des personnes

- Droit d'accès aux replays les concernant.
- Droit de rectification des métadonnées.
- Droit de retrait du consentement à tout moment.
- Droit à l'effacement des replays dans les délais du calendrier EFVP.

## 8. Renvois

- `GABARIT-EFVP.md` — calendrier de destruction et minimisation.
- Registre d'incidents et procédure de notification CAI (Plan maître §14.2).
- [À VÉRIFIER — juriste : bandeau de consentement conforme.]

