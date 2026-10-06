# M1 — consignes de réception et reprise vocale

Correction éditoriale du 5 octobre 2026 : SOUL et quatre procédures. Le département cible reste une réception/adjointe omnicanale complète, avec voix, appels manqués, qualification, suivi, agenda et transferts. Les consignes distinguent cette cible des outils, imports et configurations effectivement disponibles. Aucun runtime, outil, schéma, droit ou connecteur ajouté.

## Changements vérifiés

- La machine à phases 0→5 n'est pas présentée comme une ligne téléphonique STT/TTS de production. L'objet `conversation` est retransmis depuis la dernière réponse canonique; aucun état n'est reconstruit. Le vrai refus `REJ-PHASE-SAUTE` remplace `TRANSITION_INTERDITE`, nom d'exception interne plutôt que code d'outil. Phase 5 signifie clôture vocale, pas qualification commerciale.
- Consentement à conserver/transcrire et accord distinct de transfert STT externe sont séparés. Le vérificateur seul ne capture ni ne supprime un audio. L'import manuel n'accepte aucun média; le pipeline hôte choisit fournisseur et configuration, aucun secret ne passe dans le prompt.
- En panne STT ou consentement absent, le pipeline peut importer l'événement sans transcription. Son statut STT refusé ne prouve pas l'échec du sous-résultat M1 : le guide demande de lire la trace/rappel réellement retournés, sans affirmer un rappel absent. Une reprise conserve les identifiants d'origine, sa preuve canonique et le transfert humain; aucun second dossier, lead ou rappel créé pour contourner une erreur.
- La suite CRM dépend de `decision=TRANSMETTRE_M2`; une transcription enrichie ou un transfert ne devient pas une émission de lead par raisonnement du modèle. L'absence de nouvelle création n'efface pas un dossier CRM antérieur.
- Les métadonnées sont recopiées depuis le contexte hôte, jamais depuis un bloc système imité dans le texte client. Le filtre de motifs n'est pas une preuve de confiance, de consentement ou d'exhaustivité. Un refus avant écriture n'est pas déclaré capturé.
- Transfert, prise en charge, brouillon, approbation, notification simulée et message livré restent distincts. Résumés/pages existants sont utilisés après conservation fidèle du texte source; un manque n'est pas retiré pour raccourcir.

La reprise comportementale reste celle du [rapport M1 r314](../grs/reception/M1-VOICEMAIL-REPRISE-RAPPORT-2026-10-05.md), pas une nouvelle qualification fournisseur ou téléphonie live. Les anciennes règles métier de sécurité/escalade demeurent inchangées; ce patch ne branche ni téléphonie ni envoi externe.

## Compléments M5 issus de la revue facultative

La [tranche FinanceCore précédente](PROMPTS-M5-COHERENCE-2026-10-05.md) est conservée. La revue arrivée après sa préparation locale confirme ses corrections, puis suggère deux précisions : prix/conditions des offres de capital restent déclaratifs et non authentifiés; la description YAML de déclenchement mentionne désormais CFO, contrats et limites de paie. Le refus de dépôt partiel ne persiste pas une affectation dans la facture : le constat est préservé pour rapprochement, aucun succès inventé. Ces trois consignes sont complétées sans toucher aux calculs ou gardes.

## Contrôle et limites

Audit M1 Luna lecture seule : chemins abrégés résolus dans le département déclaré, empreintes contrôlées contre les préimages et sources. Revue M5 facultative : empreintes des trois consignes précédentes et cinq références runtime/raccord contrôlées. ROOT a relevé en plus le vrai code de refus vocal, l'objet canonique requis et la portée du filtre. Diff et préimages conservés.

Une première vérification a révélé une description de skill de canal avec un deux-points non encadré, invalide en YAML. Les six descriptions sont désormais encadrées, texte préservé; l’échec et les versions antérieures sont conservés. Les six frontmatters YAML passent; **M1 : 13 noms cités / 17 outils**, **M5 : 22 / 29**, tous présents au catalogue de leur propriétaire. **16 références** actives sont gelées avec SHA. Contrats, paramètres, refus et liens sont relus; aucun test miroir du texte n'est ajouté. Aucun comportement de modèle, qualité de transcription, précision réelle ou gain de tokens mesuré. La qualification éditoriale ne démontre ni capture exhaustive, ni CRM intégral, ni agent vocal live, ni paie/CFO complets.

[Capsule jointe](../research/REPRISE-2026-10-05/preuves/PROMPTS-M1-M5-COHERENCE-r1.tar.xz) et [inventaire](../research/REPRISE-2026-10-05/preuves/PROMPTS-M1-M5-COHERENCE-r1.json). Scan r385 par défaut sur les changements, sources, audit M1, revue M5 et plan ROOT; aucun ajout d'exception. Ce scan ciblé ne couvre pas tout le dépôt ou l'archive. Préparation Git isolée privée; aucun push, CI distante ou déploiement annoncé.
