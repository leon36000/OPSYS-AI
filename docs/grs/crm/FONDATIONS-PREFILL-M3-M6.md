# Lignes de modèles et sélection de coûts M6 — composants préparés

27 octobre 2026. Suite de [l’audit préalable](AUDIT-LIGNES-PREFILL-M3-M6.md).
Statut CRM-07 : **PARTIAL**. Composants, ports privés et formulaires HTTP/SQLite sont
qualifiés localement : [parcours et limites](PREFILL-HTTP-M3-M6.md).

## Objectif et architecture

Réutiliser une liste de descriptions et d’unités sans inventer les quantités ni les coûts.
`modeles_lignes_soumission.py` (M3) conserve un journal distinct, append-only, lié au hash
exact du modèle textuel. Chaque ligne porte seulement son identifiant, sa description,
son matériau et son unité. Versions, CAS, auteur, intention et limite UTF-8 réutilisent
les mécanismes M3 existants. Réviser le texte ne transfère pas les lignes automatiquement.

`tarif_soumission.py` (M6) lit une séquence bornée de couples rang SQL/entrée de livre de
prix et un fournisseur déjà résolu. Le dernier écrit pour le matériau et le fournisseur
choisis reste la convention M6. Il doit avoir unité exacte, devise CAD, date civile non
future et coût numérique fini positif représentable sans arrondi supplémentaire.
Une identité d’entrée illisible bloque la sélection, même après un ancien tarif valide.
Le lecteur ne change pas le stock, le livre de prix, les achats ou les prix de vente.

Le résultat donne rang, empreinte, coût décimal, unité, devise, date et source déclarée.
Sans document, le marquage reste `FALLBACK_PRICE_BOOK`. Une empreinte détecte une sélection
modifiée; elle ne certifie pas l’authenticité documentaire. Aucun fournisseur moins cher,
conversion d’unité, taux de change ou quantité par défaut n’est choisi implicitement.

## Interfaces, données et permissions

Fonctions pures `enregistrer`/`lire` (M3), `selectionner_tarif` (M6); aucune nouvelle route
ni nouveau port public. Aucun droit appareil ou agent ajouté. Le raccord privé décrit plus bas contrôle désormais l’admin SQL actif, la provenance M3, les références M6, le jour serveur et la
taille SQL avant lecture, puis relit rang/empreinte dans la transaction de création.
Les fonctions pures seules ne démontrent pas les permissions; la qualification des ports est décrite plus bas.

## Vérification et limites

Tests : `test_modeles_lignes_soumission.py`, `test_tarif_soumission.py`, régressions modèles
textuels/livre de prix et conformité des deux départements. Dernière sélection locale :
257 réussis, aucun échec ni saut; Ruff et vérificateur des manifestes réussis (283 outils,
173 déclarés aux appareils, inchangés). Cette population recoupe les précédentes.

Le premier passage conserve son rouge : le harnais tentait de sérialiser un tuple avant
d’atteindre le validateur; le test corrigé appelle bien le domaine et conserve l’exigence
de refus sans écriture. Un constat de revue sur l’identité manquante du dernier tarif a
été corrigé avec huit cas de régression. Aucun changement de contrat historique M6.

Preuves locales distinctes : `work/chantier-opsys-20261010/crm-prefill-qa-20261027-r1/`,
phases `foundation-v1`, `foundation-v2`, `foundation-v3`, avec reçus, JUnit, empreintes et
limites effectives. QA sans réseau, source en lecture seule, homes/tmp privés.

## Provenance privée du devis — raccord du domaine

`provenance_tarifs.py` valide désormais une copie optionnelle fermée dans `devis_durable`.
Elle lie la source textuelle, la source/révision du jeu de lignes et les tarifs par
référence de ligne. Chaque ligne du devis sourcé est couverte une fois, avec identifiant
de modèle unique, coût décimal égal au coût calculé, unité identique, CAD et date non future
à la création. Le marquage documentaire reste déclaratif ou fallback. L’adaptateur privé
vérifie les sources réelles; le validateur ne les authentifie pas.

La provenance participe au refus de rejeu avec contenu différent, ne peut être ajoutée
rétroactivement à un devis manuel et reste copiée profondément après lecture/acceptation.
Elle ne figure pas dans les documents clients, la projection employé ou les événements
existants. Les anciens appels et rendus restent compatibles; aucun port supplémentaire
n’accepte encore cette donnée depuis un navigateur ou un agent.

Preuve locale `provenance-v2` : 534 réussites, aucun échec, un saut historique du garde
réservé à GitHub Actions. Le PDF réel a bien été généré et lu. Cas vérifiés : couverture
de 20 lignes, doublons refusés, unité/coût/date/source incohérents, changements de provenance
au rejeu, copies indépendantes, SQLite migré puis moteur fermé/rouvert, rollback, acceptation,
HTML et octets PDF identiques au devis équivalent sans provenance. Ruff et manifestes
réussis. La sélection recoupe les précédentes; ne pas additionner les populations.

## Prochaine capacité

Les formulaires et le parcours HTTP/SQLite sont désormais qualifiés dans [PREFILL-HTTP-M3-M6.md](PREFILL-HTTP-M3-M6.md).
Améliorer ensuite la sélection par libellé et qualifier le bus complet sans rejouer les anciennes intentions. Les modèles manuels restent compatibles. L’import courriel,
M10, PostgreSQL, navigateur natif et mobile restent des capacités distinctes à qualifier.

Les commandes réelles, paiements, envois externes et changements sensibles gardent les
validations Nathan prévues; ce lot n’en déclenche aucun.

## Ports console privés — qualification SQLite

Quatre ports sont maintenant raccordés au répartiteur interne `console/metier.py` :
`m3_enregistrer_lignes_modele`, `m3_lire_lignes_modele`, `m3_lire_tarif_modele` et
`m3_creer_devis_prefill`. Les passages génériques et profils runtime les refusent;
les 173 portées appareil restent inchangées, sur 287 outils enregistrés.

Le répartiteur contrôle session non expirée et admin actif en base. L’heure est fournie
par la réception serveur, même en lecture : aucun appel d’horloge dans M3. Le port de
création relit modèle exact, version des lignes, fournisseur et tarif M6 dans sa transaction.
Le navigateur futur ne fournira ni coût, ni description, ni unité résolue : seulement
quantité, choix fournisseur et références de sélection. Source modifiée, couverture
incomplète, doublon ou champ supplémentaire refusent sans effet. La copie privée fige
les sources; un rejeu identique après changement de prix restitue le reçu original,
tout en revérifiant l’autorité. Les écritures restent non qualifiées sur PostgreSQL.

Chaque ligne matériau transmet son `materiau_id` dans `reference_besoin_materiau`, selon
le contrat M3/M6 existant. À l’acceptation ultérieure, le consommateur M6 construit les
besoins et la réservation; le brouillon ne réserve et ne commande rien. La provenance
tarifaire privée n’est pas ajoutée à l’événement d’acceptation.

Preuve locale `ports-v2` : 336 réussites, aucun échec ni saut, 16,55 s; Ruff et vérificateur
réussis. Sélection non additive : ports SQL, répartiteur console réel, relecture après
fermeture du moteur, source modifiée, rejeu, révocation admin, rollback sur panne d’audit
et quota, refus des ports génériques, acceptation vers le consommateur M6 réel avec
réservation sans stock et rejeu, régressions HTTP des anciens formulaires et conformité.
Cette preuve ne couvre pas encore le bus complet ni un formulaire HTTP de préremplissage.

La revue indépendante a signalé deux défauts corrigés : horloge ambiante M3 et perte du
matériau lors du transfert au prévu M6. Le rouge `ports-v1` (conformité et lint) est conservé.
Le statut reste **PARTIAL**. Le jalon suivant HTTP/SQLite est maintenant décrit dans
[PREFILL-HTTP-M3-M6.md](PREFILL-HTTP-M3-M6.md). Aucun envoi externe effectué.
