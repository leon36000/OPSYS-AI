# M3 — inventaire de devis dans l’app vendeur

L’écran Soumissions utilise maintenant `m3_lister_devis` : brouillons, devis approuvés pour
envoi et devis acceptés du vendeur, même lorsqu’aucun segment M2 ne les cite. Le
[backend qualifié](M3-INVENTAIRE-VENDEUR-RAPPORT-2026-10-05.md) relit les droits et la propriété
actuelle; aucun rôle ni propriétaire n’est envoyé en argument par le téléphone.

Chaque réponse est bornée à dix devis avant projection. La liste blanche garde statut,
prix et lignes, sans coûts ni marges dans affichage/cache. Page illisible, refus ou panne
ne montrent pas un ancien inventaire. Les curseurs vides/sans progression sont refusés.
La liste n’est pas persistée hors ligne; l’ouverture manuelle d’un numéro conserve une
copie individuelle explicitement ancienne lorsque le serveur est injoignable. Un refus
connu purge les copies concernées via les fonctions existantes.

L’écran relit l’identité confirmée et remonte son corps à changement appareil/personne.
La garde de visibilité rejette un inventaire possédé par une autre personne, la séquence
invalide une réponse dépassée, et le service contrôle URL/jeton/personne après réponse.
Les valeurs et instructions de la réponse serveur n’accordent aucune autorisation.

ROOT a vérifié deux chaînes de préimages : dépôt→stage r1, puis stage r1→stage r2. Les
fichiers readiness ajoutés à r2 partent du dépôt; les deux nouveaux fichiers de visibilité
n’existaient pas. L’erratum du worker est conservé. L’import manquant de `lireDevisVendeur`
dans un nouveau test a causé r315 (367 réussis, 9 échecs), puis a été corrigé sans retirer
aucun test. **r316 passe 376/376 dans treize fichiers complets, puis TypeScript**, avec
372 sources gelées et compteurs OOM inchangés.

La preuve couvre parseur, chargeurs, faux transport des vrais contrats, caches par personne,
visibilité/différés, devis connus, traduction et projection écran. Elle ne prouve pas un
rendu React Native sur téléphone, la SQLite native, un appel réseau mobile vers le vrai
Core ni un envoi client. Les coûts/marges existent encore dans la vue serveur interne
vendue au profil vendeur : la liste blanche locale ne protège pas un appareil compromis.
Le scan complet sous-jacent du registre M3 reste non benchmarké. Aucun statut global
FAIT_VÉRIFIÉ ni gain de tokens/précision du modèle n’est attribué à cette tranche.

## Sources et reçus

[Capsule](../../research/REPRISE-2026-10-05/preuves/RECEPTION-VENDEUR-PROMPTS-r1.tar.xz)
— SHA-256 618b58912bca71acc16abc5ec1639c502141414e2b468dea35128a5ac36f5f75.
[Inventaire et limites](../../research/REPRISE-2026-10-05/preuves/RECEPTION-VENDEUR-PROMPTS-r1.json).
La capsule conserve les rapports avant ces liens; r317 scanne 31 chemins et ne trouve aucun secret.
