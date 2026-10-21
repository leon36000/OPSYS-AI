# Audit produit OCR M5 — première tranche (lecture seule)

Date : 2026-10-04. Périmètre : raccords produit existants, sans modification du dépôt ni commande Git. M5/Fusion reste **PARTIEL**.

> Audit initial conservé. Le stockage chiffré, le worker et la console privée proposés
> ci-dessous ont ensuite été raccordés et qualifiés **localement** :
> [stockage OCR](M5-OCR-STOCKAGE-2026-10-04.md),
> [console OCR](M5-OCR-CONSOLE-2026-10-04.md) et
> [prévol](../../ops/INGESTION-OCR-PREFLIGHT.md).
> Les mentions de ces composants « à construire » décrivent la première tranche,
> pas l'état courant. AP automatique, corpus factures réelles, installation image/VPS
> et exploitation continue restent non qualifiés.

## Recommandation

Construire une petite verticale opt-in « examiner un scan » pour administrateurs actifs : depuis un lot PDF natif refusé parce que page image, proposer une action distincte et explicite qui n’accepte que le cas conservateur PDF mono-page, image seule et non ambigu. Après revalidation du lot et de sa révision, un worker séparé rend la page puis produit TSV dans le profil exact r171, en bubblewrap sans réseau, source par stdin, artefacts en lecture seule, budgets de temps/mémoire/sortie bornés. Le parseur pur `opsys.ocr_candidat` valide le TSV et lie le candidat au hash source, révision et profil/artefacts vérifiés. Enregistrer le candidat sous chiffrement/AAD et quota dans un compartiment/table OCR neuf, puis le rendre dans une page privée `no-store` avec PDF source consultable, TSV/OCR explicitement présenté comme non fiable et à revoir, boîtes/score comme indices uniquement. Pas de correction automatique, extraction de champs AP, décision, événement de paiement, ni écriture M5. Garder la source/résultat natif et `PDF_IMAGE_OU_MIXTE` inchangés. Si le détecteur ne peut pas prouver « image seule », afficher refus/ambiguïté et rester sur la revue manuelle.

Le bénéfice produit vient de l’accès à une lecture candidate révisable, pas du seul prévol. Un prévol de déploiement doit néanmoins précéder l’activation : montrer les hashes et versions de l’environnement effectivement chargé, tester bwrap et le profil dans l’image/VPS visé, puis échouer fermé si indisponible. Le succès de r171 sur deux documents synthétiques ne qualifie ni l’image Docker ni un VPS.

## Preuves et raccords réels

- `docs/produit/DEFINITION-PRODUIT.md` §1–3 : OPSYS est un produit d’entreprise, M5 finance et décisions argent/légales/irréversibles demandent validation humaine. `docs/produit/DIRECTIVES-NATHAN.md` complète les limites durables.
- `docs/research/REPRISE-2026-10-04/M5-OCR-RUNTIME-PDFIUM-2026-10-04.md` : r171 exécuté isolément sous bwrap, pypdfium2 5.13.0 / PDFium 153.0-7999 effectifs, Tesseract 5.5.0/Leptonica 1.84.1, modèle français épinglé; 2 scans fictifs, TSV conservés, 55 tokens chacun; contrat 82/82. Scan net 10/10 lignes synthétiques, scan incliné/contraste réduit 4/10 et identifiant fictif `FACT-FICTIVE-007` lu au lieu de `...001`. Ce n’est ni précision facture ni qualification Docker/VPS.
- `src/opsys/fusion_pdf_worker.py` et `src/opsys/fusion_pdf.py` constituent le seul chemin produit actuel : pypdf natif strict, source ≤1 Mio, 1–20 pages, sorties bornées, worker Linux/bwrap, pas d’OCR. Une image XObject/inline ou une ambiguïté entraîne `PDF_IMAGE_OU_MIXTE`; aucun verdict scan-only.
- `src/opsys/console/fusion_pdf_ui.py` expose sous préfixe console `/fusion/pdf`, admission `/fusion/pdf/lots`, détail, POST `/preparer`, extraits. `src/opsys/console/fusion_ap_ui.py` expose `/ap` et `/ap/lire|enregistrer|verifier-m5|saisir-m5`. Les pages privées utilisent sessions, formulaires CSRF, échappement et `no-store`; les nouvelles actions doivent respecter ces gardes.
- `src/opsys/ocr_candidat.py` et `docs/grs/compta/M5-OCR-CONTRAT-2026-10-04.md` : frontière pure de validation JSON/TSV, profil/source/révision/pages/géométrie/tokens fermés, préserve le texte machine sans correction. Le module ne rend pas le PDF, ne prouve pas l’identité du binaire chargé, ne classifie pas scan seul, ne chiffre/persiste pas et ne présente pas le contenu à l’humain.
- `src/opsys/stockage/schema.py`: `FUSION_PDF_LOTS` impose type/classe et statuts fermés (`RECU`, `EXTRAIT_PREPARATOIRE`, `REFUSE`, `ERREUR_REPRENABLE`); extrait natif chiffré uniquement en statut préparatoire. `FUSION_AP_BROUILLONS` est un autre compartiment chiffré, unique par lot et strictement `A_REVOIR`, mais porte des champs/citations AP adossés aux fragments natifs. Aucun de ces emplacements ne doit recevoir le TSV OCR ni être détourné pour l’acceptation d’un scan. Nouveau schéma/migration/quotas/AAD et états OCR séparés requis pour une vraie fonctionnalité durable.
- `src/opsys/fusion_ap.py`, `src/opsys/console/fusion_ap_m5.py`, `src/opsys/console/fusion_ap_ui.py` sont les vrais raccords AP : proposition humaine citée, contrôles M5 en lecture seule avec rôle finance et attestation explicite, puis POST séparé de saisie interne. Le module OCR ne doit appeler aucun de ces chemins ni préremplir des montants ou identifiants.
- `docs/architecture/FUSION-AP-BROUILLONS.md` définit expressément brouillon préparatoire sans dette/paiement; `docs/architecture/FUSION-PDF-NATIF.md` exclut OCR et qualification précision/VPS. `docs/grs/memory/M10-PROVENANCE-PDF-DESIGN-2026-10-04.md` garde M10 comme provenance financière candidate sans corps, parser/OCR/worker/LLM. N’y envoyer ni TSV ni tokens OCR.

## Raster, TSV, refus, revue

1. **Classification/refus** : aujourd’hui, l’analyse native sait « image ou mixte », pas « image seule ». Ajouter une analyse structurelle conservatrice, sans appeler OCR avant verdict; tout contenu actif, objet partagé/masqué, texte natif, multi-page ou ambigu reste refusé à cette tranche. Les tests doivent prouver absence d’appel worker sur ces chemins.
2. **Raster** : un nouveau worker distinct reçoit les octets source déjà déchiffrés côté service après vérification hash/révision, par pipe uniquement; rasterisation d’une page en 150 DPI et maximum 4 Mpx avec limites source/sortie/espace d’adressage/CPU/temps mural. Identité effective PDFium/wrapper/raw/config, Tesseract/Leptonica et modèle vérifiée avant usage et exposée dans résultat lié au contexte; aucun fallback process/hôte. Le quota produit doit couvrir simultanément source, raster temporaire et résultat sans les journaliser.
3. **TSV/candidat** : capturer le TSV brut borné depuis stdout, puis le valider exclusivement par `ocr_candidat`; erreurs génériques sans fuite de texte. Score n’est pas une probabilité/calibration. Garder ordre, texte, cellules, accents et HTML littéralement comme contenu non fiable; ne pas « réparer » les chaînes.
4. **Revue humaine** : écran privé séparé affiche page source et tokens/cadres clairement candidats, texte HTML-échappé, sans formulaire de mapping de champs dans la première tranche. Une personne active doit déclencher la revue; l’accusé de revue ne transforme pas le résultat en facture ni en valeur comptable validée. L’AP commence ensuite par le flux manuel existant.

## Dépendances et déploiement

`pyproject.toml` définit actuellement l’extra `ingestion-pdf` (`cryptography==50.0.2`, `pypdf==6.19.0`); `requirements-ingestion-pdf.lock.txt`, `deploy/Dockerfile`, `deploy/docker-compose.ingestion-pdf.yml` et `install/install.sh --avec-ingestion-pdf` activent le seul PDF natif. Rien n’épingle/installe aujourd’hui l’OCR produit. Dans les tranches produit déjà autorisées par Nathan : extra/lock et choix installateur explicitement opt-in, image/overlay distincte; intégrer les packages complets du wheel (r171 a nécessité `pypdfium2_cfg`), hash RECORD, Tesseract/Leptonica système versionnés par snapshot, modèle français `fra.traineddata` SHA-256 `ced037562e8c80c13122dece28dd477d399af80911a28791a66a63ac1e3445ca`, licences/notices/SBOM et empreintes runtime. Pas de download au démarrage. Le prévol doit exécuter la sandbox dans le vrai conteneur noyau/seccomp et l’installation VPS cible; bwrap présent seul n’est pas preuve de namespaces disponibles. L’ancienne qualification Docker du PDF natif ne qualifie pas ce profil OCR.

## Premier contrat et tests nécessaires

- Contrat/classificateur fermé : `IMAGE_SEULE_CANDIDATE` possible seulement si structure vérifiée; distinguer refus `PDF_IMAGE_OU_MIXTE`, `PDF_MULTI_PAGE`, `PDF_AMBIGU` et erreur technique. Propriétaire métier du PDF natif reste l’autorité source; l’OCR garde états/résultat isolés et préfixe AAD/version/profil dédiés.
- Tests négatifs classification: mixed natif + image, texte invisible/overlay, objets image réutilisés/masqués, annotations/forms/actions, ordre/cropbox/rotation hors profil, pages >1, image encodage/dimensions excessifs et PDF malformé. N’affirmer aucune couverture universelle au-delà des fixtures et grammaire effectivement codée.
- Worker/isolation: mauvais hash/version/runtime path/module cfg/modèle/langue; net absent, mounts RO, cwd/env minimaux, input uniquement stdin; échec bwrap sans fallback; timeout, SIGKILL, CPU/RSS/AS/file size, stdout/stderr excessifs, processus descendant, sorties invalides/vides; aucun octet document dans logs/audit.
- Intégrité/métier: source/hash/révision/profil changés ou acteur révoqué pendant calcul; revalidation après worker sous transaction/CAS; rejeu/idempotence et conflit de mutation; crash/échec de chiffrement/quotas rollback complet; AAD lie lot+source+révision+configuration+profil; aucune mutation du résultat natif/AP/registre M5/provenance M10.
- Candidat/UI: tous refus du contrat TSV/JSON, contexte mismatch, texte hostile HTML/attributs, `no-store`, CSRF/session/rôle, URL/corps invalides, absence de fuite par GET ordinaire et logs, revue explicite; aucun champ AP proposé automatiquement. Conserver les suites PDF natives/M10/AP en non-régression.
- Qualification: tests produit avec faux moteur peuvent vérifier le flux et les rouges, mais ne remplacent pas une vraie exécution bornée du binaire/poids vérifiés dans l’image et VPS. Jeu métier réel représentatif, mesure d’erreur par champ (n° facture, fournisseur, dates, taxes, devise), plus revue légale/privacy restent avant toute extension commerciale.

### Conclusion de statut

r171 prouve qu’un candidat technique peut rendre et émettre du TSV dans une campagne locale bornée avec deux scans fictifs. L’écart produit reste classification conservatrice, worker raccordé, environnement déployé, stockage chiffré séparé et écran de revue. Compte tenu de l’erreur d’identifiant sur le scan dégradé, aucune confiance automatique, correction, création AP ou paiement. Le statut à conserver est **PARTIEL**.


Décision ROOT : [design de la première frontière](M5-OCR-PRODUIT-DESIGN-2026-10-04.md). Commencer la classification avant le lanceur et la revue durable, sans demander une nouvelle autorisation pour ces travaux déjà demandés.
