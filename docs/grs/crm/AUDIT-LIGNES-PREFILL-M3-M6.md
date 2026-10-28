# Prochain raccord CRM07 : lignes réutilisables et coûts M6

Audit avant code, 27 octobre 2026, source `145404193f4203c2f3033d6b75e38f6be3960bc2`.
Revue statique indépendante : `/root/wave1_m6_contract`; rapprochement ROOT avec les fonctions ci-dessous.
Statut : conception préparée, aucune capacité supplémentaire annoncée, aucun code produit modifié.

## Besoin et réutilisation
Le secrétariat veut préparer rapidement ses soumissions et conserver ses clauses modifiables.
La tranche précédente conserve le texte choisi, mais demande de ressaisir vingt lignes manuelles.
Réutiliser le registre versionné M3, ses transactions, le calcul Decimal de devis_durable,
la liste blanche HTML/PDF et le livre de prix M6. Les recherches GitHub InvoicePlane et GitLab okane
de l’audit initial modèles restent des références de conception; aucune nouvelle dépendance adoptée.

## Constats de code
- `m3_estimation/modeles_soumission.py` : `_CLES`, `_ARGUMENTS`, `_charger`, `enregistrer` ont des
  formes et empreintes fermées. Ajouter des champs aux anciens maillons casserait leur validation.
- `devis_durable.py` : `_valider_ligne` refuse les champs supplémentaires; `creer_devis` calcule le
  prix à partir du coût et du taux fournis. `_CLES_CONTENU_DEVIS` gouverne le rejeu.
- `m6_material_control/livre_prix.py` : `prix_en_vigueur` sélectionne la dernière écriture pour
  matériau/fournisseur, jamais la date la plus récente. `date_effet` est du texte non vide;
  `unite` facultative; `source_document` est déclarative, non authentifiée.
- `resoudre_prix_po` omet l’unité. `catalogue.resoudre_prix` concerne réception et historique,
  sans même contrat fournisseur/date. Ne pas les présenter comme un tarif vérifié de devis.
- `stockage/maillons.py:copier_maillons_avec_metadonnees` fournit le rang SQL réel. Le livre M6
  n’est pas une chaîne documentaire authentifiée. Une empreinte de sélection détecte un changement,
  sans prouver l’authenticité de la facture ou du document déclaré.

## Tranche minimale à construire
Créer un registre distinct `modeles_lignes_soumission`, lié à une version exacte du modèle textuel.
Version append-only : modele_id, modele_source, revision, source_id, lignes de 1 à 20 éléments
{ligne_id, description, materiau_id, unite}; auteur admin, réception serveur, intention et CAS.
Aucune quantité, aucun coût et aucun prix de vente ne sont des défauts du modèle.
Réviser les textes exige une liaison explicite à un nouveau jeu de lignes; aucun transfert silencieux.

Le formulaire préremplit descriptions et unités. L’admin choisit un fournisseur existant, voit le coût,
la devise, l’unité, la date déclarée, le marquage SOURCE_DECLAREE/FALLBACK_PRICE_BOOK puis entre
quantité et majoration. Le serveur relit la version M3 et la sélection M6 dans la transaction.
Le formulaire transmet ligne_id, quantité, fournisseur_id, rang SQL et empreinte du tarif, jamais
un coût prétendument sourcé M6 fourni par le client HTTP.

Refuser la création sourcée si matériau/fournisseur manque, unité absente ou différente, devise
autre que CAD, date non civile ou future à la réception serveur, montant invalide ou hors bornes,
quantité absente, source modifiée. Une référence documentaire absente conserve son marquage
fallback explicite; elle ne devient pas une preuve authentifiée. Aucune conversion d’unité/de devise,
aucune moyenne ni sélection automatique du fournisseur le moins cher. Les dates désordonnées
ne doivent pas changer la convention M6 : dernier écrit, à réexaminer explicitement s’il est futur.

Conserver une provenance privée optionnelle fermée dans le devis, indexée par reference_ligne :
matériau, fournisseur, rang, empreinte, coût Decimal, devise, unité, date, marquage documentaire.
Inclure cette provenance dans l’idempotence et les copies profondes. Les anciens devis et leurs
rendus restent byte-identiques. `Decimal(str(prix_historique))` convertit les nombres historiques
sans prétendre restaurer une précision perdue. Le calcul de prix reste exclusivement M3.

## Interfaces et frontières
Nouveaux ports console privés avec schémas fermés pour les lignes et le devis sourcé, au lieu de
changer implicitement le contrat des huit arguments du parcours manuel existant. Réutiliser la
projection du lecteur M6, pas son écriture. Aucune permission appareil/agent ajoutée.
Admin SQL actif avant chaque lecture, création et rejeu; CSRF; limites source/sortie; audit atomique.
Ni commande fournisseur, ni mouvement de stock, ni facture M5, ni courriel réel.
Le parcours manuel reste disponible pour la main-d’œuvre; il ne reçoit pas le label coût sourcé M6.
Aucun coût, fournisseur ou détail de provenance privée ne franchit `soumission.contenu_client`.

## Preuves exigées avant livraison
Compatibilité des anciens modèles/devis; aucune quantité par défaut; prix absent, mauvais fournisseur,
unité/devise incohérente, date invalide/future; dates d’écriture désordonnées; prix modifié GET/POST;
source falsifiée; calcul décimal; double clic/conflit; révocation; audit rollback; redémarrage;
devis accepté inchangé après révision du modèle et du prix; absence de provenance/coûts dans HTML/PDF.
Un parcours HTTP/SQLite réel doit aller du modèle au tarif M6 sélectionné, puis au nouveau devis et
aux documents. PostgreSQL, navigateur natif, mobile, M10 et import de prix par courriel restent distincts.

## Prochaine action précise
Cet audit est intégré dans docs/grs/crm. Attribuer une surface unique au domaine de lignes M3. Implémenter ensuite le lecteur M6 borné et la projection
de provenance, puis l’adaptateur et les formulaires, avant toute qualification intégrée.
