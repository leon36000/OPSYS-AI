> **PROPOSITION (P0-7)** — document généré par l'équipe OPSYS-AI et validé par revue scellée
> multi-modèles. **VALIDATION FINALE : Nathan (T3)** — aucun usage externe ni engagement avant sa
> validation écrite. Responsable de la protection des renseignements personnels (RP) : **Nathan**.

# Gabarit d'Évaluation des facteurs relatifs à la vie privée (EFVP)

Version : ______ (à remplir lors de l'EFVP)
Date : ______ (à remplir lors de l'EFVP)
Module / projet couvert : ______ (à remplir lors de l'EFVP)
Responsable de la protection des RP : Nathan

> Source : Plan maître §14.2 — « EFVP obligatoire pour tout développement de système impliquant des RP (GRS entier) et avant communication hors Québec. »

## 1. Identification du projet/module

- Nom du projet ou du module : ______ (à remplir lors de l'EFVP)
- Référence dans le plan maître : ______ (à remplir lors de l'EFVP)
- Responsable RP : Nathan
- Date de l'évaluation : ______ (à remplir lors de l'EFVP)
- Version du gabarit : ______ (à remplir lors de l'EFVP)

## 2. Description du traitement

- RP traités : ______ (à remplir lors de l'EFVP)
- Finalités du traitement : ______ (à remplir lors de l'EFVP)
- Base de collecte : ______ (à remplir lors de l'EFVP)
- Source des données : ______ (à remplir lors de l'EFVP)

## 3. Nécessité et proportionnalité

- Minimisation : ______ (à remplir lors de l'EFVP)
- Confidentialité par défaut : ______ (à remplir lors de l'EFVP)
- Justification de la nécessité : ______ (à remplir lors de l'EFVP)

> Source : Plan maître §14.2 — « Minimisation, confidentialité par défaut, calendrier de destruction, droits outillés. »

## 4. Technologies sensibles en jeu

Cocher celles qui s'appliquent et renvoyer à la politique correspondante :

### Technologies employés (collecte limitée aux heures de travail)

- [ ] Punch géorépéré → Politique : ______ (à remplir lors de l'EFVP)
- [ ] GPS / géolocalisation employés → Politique : ______ (à remplir lors de l'EFVP)

### Technologies clients (consentement de la personne concernée, pas de notion d'heures de travail)

- [ ] Enregistrements d'appels → Politique : ______ (à remplir lors de l'EFVP)
- [ ] Session replay → Politique : ______ (à remplir lors de l'EFVP)
- [ ] Tracking client → Politique : ______ (à remplir lors de l'EFVP)
- [ ] Profilage → Politique : ______ (à remplir lors de l'EFVP)
- [ ] SMS / WhatsApp → Politique : ______ (à remplir lors de l'EFVP)

> Source : Plan maître §14.2 — « Technologies d'identification/localisation/profilage : information préalable, politique écrite, consentement documenté, collecte limitée aux heures de travail, rétention définie, accès journalisés. »

## 5. Flux hors Québec

- Communication hors Québec prévue : ______ (à remplir lors de l'EFVP)
- Modèle de déploiement : ______ (à remplir lors de l'EFVP) (auto-hébergement = RP locales par défaut ; cloud = données minimisées)
- CHECKLIST D-031 :
  - [ ] Anonymisation en entrée
  - [ ] Rédaction des chunks RAG récupérés
  - [ ] Mapping réversible sous clé locale
- Données minimisées transmises : ______ (à remplir lors de l'EFVP)

> Source : Plan maître §14.2 — « EFVP obligatoire [...] avant communication hors Québec (modèles cloud) — auto-hébergement = avantage : RP locales par défaut, cloud sur données minimisées. »
> Source : Plan maître §14.2 — « Rédaction PII avant le cloud (D-031) : couche de dé-identification OBLIGATOIRE sur tout flux vers un modèle cloud, les journaux et les traces. »

## 5bis. Conformité linguistique (Loi 96)

- Vérification français d'abord pour toute surface visée :
  - Contrats et adhésion proposés en français.
  - Clientèle du Québec servie en français.
  - Note de francisation OQLF (25 employés et plus depuis juin 2025).
- Source : Plan maître §14.2.

## 6. Rétention et destruction

| Classe de données | Durée de conservation | Justification | Destruction |
|---|---|---|---|
| Pièces fiscales (factures, reçus, journaux, inventaire, paie, TPS/TVQ) | Six ans après la dernière année visée | Exception légale documentée — Revenu Québec | ______ (à remplir lors de l'EFVP) |
| Enregistrements d'appels | ______ (à remplir lors de l'EFVP) | Calendrier Loi 25, durée courte définie par politique | ______ (à remplir lors de l'EFVP) |
| Traces GPS | ______ (à remplir lors de l'EFVP) | Calendrier Loi 25, durée courte définie par politique | ______ (à remplir lors de l'EFVP) |
| Session replay | ______ (à remplir lors de l'EFVP) | Calendrier Loi 25, durée courte définie par politique | ______ (à remplir lors de l'EFVP) |
| Photos non contractuelles | ______ (à remplir lors de l'EFVP) | Calendrier Loi 25, durée courte définie par politique | ______ (à remplir lors de l'EFVP) |
| Autres RP | ______ (à remplir lors de l'EFVP) | ______ (à remplir lors de l'EFVP) | ______ (à remplir lors de l'EFVP) |

> Source : Plan maître §14.2 — « Rétention par classe de données : les registres et pièces justificatives fiscales [...] sont conservés SIX ANS après la dernière année visée [...] ; le calendrier de destruction Loi 25 s'applique aux AUTRES classes [...] avec des durées courtes définies par politique. »

## 7. Droits des personnes

- Droit d'accès : ______ (à remplir lors de l'EFVP) (outillé)
- Droit de rectification : ______ (à remplir lors de l'EFVP) (outillé)
- Droit de retrait : ______ (à remplir lors de l'EFVP) (outillé)
- Droit à la portabilité : ______ (à remplir lors de l'EFVP) (outillé)

> Source : Plan maître §14.2 — « droits outillés (accès, rectification, retrait, portabilité). »

## 8. Risques et mitigations

| Risque | Gravité | Probabilité | Mitigation | Statut |
|---|---|---|---|---|
| ______ (à remplir lors de l'EFVP) | ______ | ______ | ______ | ______ |
| ______ (à remplir lors de l'EFVP) | ______ | ______ | ______ | ______ |

## 9. Décision

- [ ] Approuvé
- [ ] Approuvé avec conditions
- [ ] Refusé

Conditions éventuelles : ______ (à remplir lors de l'EFVP)

Signature du responsable RP (Nathan) : ______ (à remplir lors de l'EFVP)
Date : ______ (à remplir lors de l'EFVP)

## 10. Journal des révisions

| Version | Date | Auteur | Modifications |
|---|---|---|---|
| ______ (à remplir lors de l'EFVP) | ______ | ______ | ______ |

