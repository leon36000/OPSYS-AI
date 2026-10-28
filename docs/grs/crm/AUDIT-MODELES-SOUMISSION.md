# CRM07 — audit initial des modèles et clauses de soumission

Source00694797, 27 octobre2026. Le devis durable M3 calcule les lignes/prix, conserve les créations et transitions.
`devis_durable.creer_devis` ne reçoit aucune version de modèle ni clauses. `soumission.contenu_client`
partage une liste blanche HTML/PDF; aucun modèle textuel modifiable n’y est branché. Le cockpit ne fait que lire les devis.
Le registre M3 de calibration fournit des patterns de versions/empreintes; MaillonsDurables fournit CAS et transaction.

## Réutilisation examinée
Recherche GitHub et GitLab avant code :
- https://github.com/InvoicePlane/InvoicePlane : application de facturation et modèles, remplace trop de frontières M3/M5.
- https://gitlab.com/wolfenrain/okane : génération PDF depuis YAML; ne résout pas le registre de versions privé OPSYS.
Aucune adoption, copie ni licence revendiquée; licences/deps non qualifiées puisque ces candidates ne sont pas intégrées.
Réutiliser registre._encoder_canonique, devis_durable._ajouter, MaillonsDurables, identité admin et formulaires existants.

## Plan ordonné et tranche courante
1. Catalogue M3 de modèles textuels (titre, description des travaux, clauses saisies par le secrétariat), versions immuables.
2. Port console privé admin, création/révision avec CAS et intention idempotente; audit atomique sans copie du texte.
3. Catalogue paginé25 et consultation de chaque ancienne version; formulaire prérempli pour réviser la dernière.
4. Puis rattachement explicite d'une version à la création d'un devis, transmission au HTML/PDF, qualification des devis acceptés.
La tranche courante livre1–3;4 reste obligatoire pour CRM07 complet et ne sera pas présenté comme déjà opérationnel.
Aucun texte juridique généré, aucun changement de prix, aucune signature, aucun devis existant modifié ni courriel envoyé.

## Contrat partagé
`modeles_soumission.py` pur, journal `modeles_soumission`, maximum1000versions. modele_id ASCII1..100;
titre1..120, description1..4000, clauses0..12000 caractères, contrôle texte non exécutable (jamais eval/template).
API pure : enregistrer(journal, modele_id, titre, description, clauses, revision_attendue, *, auteur, mutation,
horodatage, limite_sortie=65536); lire(journal, modele_id, version=0, limite_sortie=65536);
lister(journal, decalage=0, source_attendue='', limite_sortie=65536). Réponses accepte/resultat, Refus(suffixe).
Auteur={personne,role:admin}; mutation={appareil,cle,empreinte_arguments}, SHA canonique des5arguments métier.
Rejeu rend la version originale sans nouvel audit; même clé/autre charge refusée. Chargement vérifie chaîne et sémantique.
Rendu modèle : modele_id,titre,description,clauses,revision,source_id,auteur,horodatage.
Liste : modeles (métadonnées sans textes longs),decalage,decalage_suivant,total,source_empreinte.
Lecture0dernière, versionpositiveexacte; resultat ajoute revision_courante et source de la version demandée.
Pagination25/multiple25≤1000, sourceobligatoire pour continuation; sourcechangée409.
Writer SQLite qualifié uniquement; autreswritersfermés. Aucun droit agent/appareil/vendeur ajouté.

## Preuves attendues / limites
Créer/réviser/rejouer, anciennes versions intactes, deux rédacteurs au même CAS, auditrollback, révocation,
CSRF, sortie bornée, corruption, historiqueHTTP, pagination et restart; aucune mutation des devis/approbations.
Fixtures fictives, HOME privé avantimports, QA bornée horsréseau. Navigateur, PostgreSQLwriter, mobile et M10 distincts.
CRM07 restePARTIAL jusqu'au rattachement figé au devis, renduHTML/PDF et parcours complet.
