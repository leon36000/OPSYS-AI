> **PROPOSITION (P0-7)** — document généré par l'équipe OPSYS-AI et validé par revue scellée
> multi-modèles. **VALIDATION FINALE : Nathan (T3)** — aucun usage externe ni engagement avant sa
> validation écrite. Responsable de la protection des renseignements personnels (RP) : **Nathan**.

# Politique de consentement SMS/WhatsApp

## 1. Objet et portée

Cette politique s'applique à l'ensemble des communications commerciales et opérationnelles envoyées par SMS et/ou WhatsApp aux clients, prospects et employés dans le cadre des modules M1 (Front Office) et M7 (Portail client / employé). Elle couvre les messages de qualification, de rendez-vous, de suivi de chantier et de notification. Le canal est **désactivé par défaut** (feature-flag OFF — ADR-0003 Q3a) et ne peut être activé qu'après validation explicite du responsable RP et mise en place du mécanisme de consentement documenté.

## 2. Base légale et principes

- **Information préalable** : tout destinataire est informé, avant la collecte de son numéro, des finalités des messages et de son droit de retrait.
- **Politique écrite** : le présent document constitue la politique écrite applicable au canal.
- **Consentement documenté** : l'opt-in est recueilli de manière active, datée et tracée.
- **Collecte limitée** : collecte des numéros uniquement lors d'interactions initiées par la personne (demande, formulaire, opt-in) ou fournies dans le cadre d'une relation d'affaires documentée ; la notion d'heures de travail ne s'applique pas aux clients — les PLAGES D'ENVOI respectueuses (déjà présentes) demeurent la limite temporelle.
- **Minimisation et confidentialité par défaut** : seul le numéro strictement nécessaire est conservé ; aucune donnée superflue n'est collectée.
- **Accès journalisés** : tout accès aux listes de numéros et aux preuves de consentement est tracé.

## 3. Ce qui est collecté / ce qui ne l'est JAMAIS

**Collecté :**
- Numéro de téléphone mobile du destinataire.
- Date, heure et canal (SMS/WhatsApp) du consentement.
- Preuve du consentement (écran, formulaire, double opt-in selon le cas).
- Historique minimal des envois (date, contenu type, statut).

**Jamais collecté :**
- Achat de listes de numéros.
- Numéros de tiers non consentants.
- Contenus sensibles (santé, finances) transmis par SMS sans justification documentée.

## 4. Consentement

- **Comment il est demandé** : formulaire électronique ou verbal documenté, avec case à cocher active (pas de pré-cochée) et mention des finalités.
- **Comment il est documenté** : enregistrement dans la table `consent_sms` avec identifiant du destinataire, version de la politique, date/heure UTC, source (formulaire, appel, kiosque), et identifiant de l'opérateur ayant recueilli le consentement.
- **Comment il est retiré** : le destinataire peut répondre STOP ou utiliser un lien de désabonnement. Le retrait est appliqué dans les 48 heures et tracé. Une suppression définitive est effectuée selon le calendrier EFVP.

### Cas particuliers

- **Missed-call rescue (fonction M1)** : tout rappel ou message de secours suite à un appel manqué nécessite un opt-in explicite préalable ; l'absence de réponse ne constitue pas un consentement.
- **Digest quotidien** : l'envoi d'un récapitulatif quotidien par SMS/WhatsApp requiert le consentement du destinataire et offre un désabonnement simple ; les mêmes règles de rétention et de retrait s'appliquent.

## 5. Rétention et destruction

- **Classe de données** : consentements et historique d'envoi.
- **Durée courte définie** : 3 ans après le dernier envoi ou le retrait du consentement, selon la plus longue des deux périodes. [À VÉRIFIER — juriste : durée minimale requise pour preuve de consentement.]
- **Renvoi** : calendrier de destruction `GABARIT-EFVP.md`.

## 6. Accès et journalisation

- Accès restreint aux rôles : opérations M1/M7, responsable conformité, support niveau 2.
- Journalisation de chaque consultation, modification ou export de la liste de numéros.
- Authentification forte requise pour l'administration du canal.

## 7. Droits des personnes

- Droit d'accès aux preuves de consentement.
- Droit de rectification du numéro.
- Droit de retrait du consentement à tout moment (STOP / lien / écrit).
- Droit à la portabilité des preuves de consentement sur demande.

## 8. Renvois

- `GABARIT-EFVP.md` — calendrier de destruction et minimisation.
- Registre d'incidents et procédure de notification CAI (Plan maître §14.2).

### 8.1 Hors périmètre Loi 25 — cadre fédéral [À VÉRIFIER — juriste]

- Exigences A2P/CASL applicables : à vérifier par le juriste.
