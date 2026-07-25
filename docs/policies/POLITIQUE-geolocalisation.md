> **PROPOSITION (P0-7)** — document généré par l'équipe OPSYS-AI et validé par revue scellée
> multi-modèles. **VALIDATION FINALE : Nathan (T3)** — aucun usage externe ni engagement avant sa
> validation écrite. Responsable de la protection des renseignements personnels (RP) : **Nathan**.

# Politique de géolocalisation et punch géorépéré (M4)

## 1. Objet et portée

Cette politique s'applique au module M4 (Gestion du temps et présence) et couvre la collecte de coordonnées GPS lors du punch des employés et le partage de localisation limité au chantier pour les clients. Elle ne s'applique qu'aux employés et sous-traitants ayant consenti, et uniquement pendant les heures de travail.

## 2. Base légale et principes

- **Information préalable** : les employés sont informés par écrit de la collecte GPS avant la première utilisation.
- **Politique écrite** : le présent document constitue la politique écrite.
- **Consentement documenté** : consentement écrit ou électronique de l'employé avant activation du punch géorépéré.
- **Collecte limitée aux heures de travail** : le GPS n'est capturé qu'au moment du punch ; aucun traçage continu n'est effectué.
- **Minimisation et confidentialité par défaut** : seule la position du punch est conservée, pas de parcours ni d'historique de déplacements.
- **Accès journalisés** : tout accès aux positions est tracé.

## 3. Ce qui est collecté / ce qui ne l'est JAMAIS

**Collecté :**
- Fix GPS (latitude, longitude, précision, horodatage) au moment du punch.
- Identifiant de l'employé et du chantier associé.
- Type de punch (entrée, sortie, début/fin de tâche).

**Jamais collecté :**
- Traçage continu en arrière-plan.
- Localisation hors des heures de travail.
- Données de localisation des proches ou du personnel non consentant.

## 4. Consentement

- **Comment il est demandé** : formulaire d'onboarding M4 avec case à cocher active et explication des finalités.
- **Comment il est documenté** : enregistrement dans la table `employee_consent_location` avec version de la politique, date/heure UTC et identifiant du signataire.
- **Comment il est retiré** : l'employé peut retirer son consentement via l'app employé ou par écrit. Le retrait désactive immédiatement le punch géorépéré ; un mode manuel est proposé.

## 5. Rétention et destruction

- **Classe de données** : fixes GPS et historique de punch.
- **Durée courte définie** : 12 mois après la fin du contrat de travail ou du dernier punch, selon la plus longue des deux périodes. [À VÉRIFIER — juriste : durée applicable en droit du travail québécois.]
- **Renvoi** : calendrier de destruction `GABARIT-EFVP.md`.

## 6. Accès et journalisation

- Accès restreint à l'employé, son superviseur direct, le responsable RH et le responsable conformité.
- Le client ne voit que le lien tokenisé limité à son chantier, sans accès à l'historique complet de l'employé.
- Journal de chaque consultation ou export de données de localisation.
- Anomalie = revue humaine ; **jamais d'accusation automatique** fondée sur la seule localisation.

## 7. Droits des personnes

- Droit d'accès aux fixes GPS le concernant.
- Droit de rectification des métadonnées de punch.
- Droit de retrait du consentement à tout moment.
- Droit à la portabilité des données de présence.

## 8. Renvois

- `GABARIT-EFVP.md` — calendrier de destruction et minimisation.
- Registre d'incidents et procédure de notification CAI (Plan maître §14.2).
- Procédure de revue humaine des anomalies de punch.

