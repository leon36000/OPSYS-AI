# BMAD M1 — PRD (PM)

> Rédigé par crew-coder-bulk/DeepSeek-V4-Pro (PM, LiteLLM) le 2026-07-26, après relecture du brief.

1. Personas et parcours

(a) Le client entrant (appel manqué, courriel, formulaire) : en mode ombre, le client fictif interagit via des fixtures de courriels, de transcriptions vocales ou de soumissions de formulaires. M1 détecte le signal, applique le filtre de provenance pour écarter toute injection, puis exécute la machine à états voix 0→5 sans jamais sauter de phase. Le client obtient un accusé de réception horodaté, une qualification minimale (type de travaux, ville, urgence déclarée) et une redirection vers le propriétaire humain ou le module aval compétent. Il ne doit JAMAIS obtenir de prix, de date de chantier, d’engagement ferme, d’aveu de responsabilité, ni de silence.

(b) Nathan propriétaire (digest quotidien) : Nathan consulte un digest produit de manière déterministe à partir du registre anti-perte. Le digest liste les signaux entrants de la journée, leur statut de qualification, et les alertes éventuelles (missed call non traité, tentative d’injection détectée). Nathan ne reçoit aucune information inventée, aucun chiffrage, aucun engagement implicite.

(c) Le module aval M2 (lead qualifié) : M1 transmet au module commercial un lead qualifié via un contrat d’interface gelé sha256. Ce contrat contient les données factuelles strictement nécessaires : coordonnées de contact, type de travaux, ville, urgence déclarée, canal d’entrée. M2 ne reçoit jamais de prix, de date, ni d’interprétation M1.

2. Périmètre v1 (mode ombre, prouvable par CI Python)

Seules les capacités prouvables maintenant, sans réseau ni téléphonie, sont incluses. Chaque capacité est livrée avec un test automatisé en CI.

1. Contrat d’interface gelé sha256 entre M1 et M2 (lead qualifié) et entre M1 et M3 (demande de chiffrage). Critère : étant donné une fixture de signal entrant qualifié, quand M1 tente d’émettre un lead vers M2 ou une demande de chiffrage vers M3, alors la structure des données respecte exactement le schéma haché, et toute déviation est rejetée.
2. Machine à états des phases voix 0→5. Critère : étant donné une transcription d’appel fixture (texte), quand M1 traite l’appel, alors chaque transition respecte le graphe d’états prévu, aucune phase n’est sautée, et la séquence des phases est tracée dans le registre.
3. Garde-fou déterministe des interdits absolus. Critère : étant donné un corpus de 200 prompts adversariaux tentant d’injecter un prix, une date, un engagement ou un aveu, quand le garde-fou est invoqué avant tout appel LLM, alors 100 % des tentatives sont bloquées et l’appel LLM n’a pas lieu.
4. Registre anti-perte. Critère : étant donné un ensemble de signaux entrants (fixtures), quand chaque signal est traité, alors une ligne immuable est ajoutée au registre avec un horodatage (fourni par l’appelant, pas par l’horloge système), et cette ligne n’est jamais supprimée ni modifiée.
5. Qualification par règles déterministes (sans LLM). Critère : étant donné une transcription avec des mots-clés de type de travaux et de ville, quand M1 exécute le classifieur, alors le type de travaux et la ville sont extraits par règles déterministes, et une étiquette d’urgence déclarée est attribuée si présente.
6. Consentement opt-in pour l’enregistrement. Critère : étant donné un signal vocal entrant, quand le consentement n’a pas été obtenu (soit explicitement refusé, soit absent), alors l’enregistrement n’est pas conservé, et la ligne de registre correspondante porte un marqueur « absence de consentement », sans bloquer le traitement non-enregistré.
7. Filtre de provenance anti-injection (R-015). Critère : étant donné un courriel ou une transcription de voicemail contenant une tentative d’injection (prompt adversaire), quand le contenu passe le filtre de provenance, alors toute portion externe non fiable est marquée comme contaminée, et n’est jamais injectée dans un prompt LLM.
8. Digest quotidien déterministe. Critère : étant donné un registre anti-perte contenant N signaux, quand le digest est généré à une date de référence donnée, alors la sortie est strictement reproductible (byte-identique) pour les mêmes entrées, sans appel externe.

3. Roadmap explicite (HORS v1)

- Session infra T3 obligatoire pour : intégration SIP réelle, trunk, numéros ; modèles STT/TTS locaux (faster-whisper, Piper-Kokoro) avec mesure de latence p95 ; intégration de Pipecat Flows ou LiveKit pour la téléphonie temps réel ; barge-in VAD en environnement bruyant ; mise en production du missed‑call rescue (service de rappel automatique). Ces capacités sont GATED_T3 et ne font pas partie du mode ombre v1.
- Services transversaux (Approval Engine, bus de notifications) : inexistants dans le core actuel. En v1, M1 utilise des adaptateurs in-memory simulés, traçables et testables, qui seront remplacés par les vrais services dès leur disponibilité (suivant le précédent M7-S005/M7-S006). Aucun développement de ces services n’est inclus dans M1 v1.

4. Règles métier dures

M1-R-01 : Il est interdit de produire un prix qu’il soit exact, approximatif ou sous forme de fourchette.
M1-R-02 : Il est interdit de produire une date de chantier, de visite ou de rendez-vous.
M1-R-03 : Il est interdit de produire un engagement ou une promesse au nom de l’entreprise.
M1-R-04 : Il est interdit de produire un aveu de responsabilité ou de faute.
M1-R-05 : Les phases voix 0→5 ne peuvent être sautées ; tout traitement vocal suit le même graphe d’états immuable.
M1-R-06 : Les demandes de prix sont routées vers M3, les dates vers M4, la finance vers M5, le commercial vers M2.
M1-R-07 : Le consentement explicite de l’appelant est obligatoire pour conserver un enregistrement vocal.
M1-R-08 : Tout contenu externe (courriel, transcription, formulaire) est considéré comme non fiable et ne doit jamais être injecté tel quel dans un prompt LLM.
M1-R-09 : Aucune information ne peut être inventée ; seules les données explicitement fournies par l’utilisateur ou les systèmes de référence sont transmises.
M1-R-10 : Chaque signal entrant, quel que soit son canal, génère exactement une ligne immuable dans le registre anti-perte.

5. Découpage en STORIES proposé (7 stories)

M1-S001 – Registre anti-perte et contrats gelés : valeur = toute opportunité capturée sans perte, interface stable avec M2/M3. Dépendances : aucune. Tier Proof : T1 (doc/données fixtures).
M1-S002 – Phases voix 0→5 pilotées par machine à états : valeur = traçabilité totale des appels, aucune phase sautée. Dépendances : M1-S001 (le registre reçoit les transitions). Tier Proof : T2 (logique métier/sécurité).
M1-S003 – Garde-fou déterministe des interdits absolus : valeur = défense anti-hallucination sur les points engageants. Dépendances : aucune (peut être développé en parallèle). Tier Proof : T2.
M1-S004 – Qualification par règles déterministes : valeur = classification immédiate sans LLM, base des décisions de routage. Dépendances : M1-S001. Tier Proof : T1.
M1-S005 – Filtre de provenance et blocage R-015 : valeur = empêcher l’injection de prompt indirecte via courriels/voicemails. Dépendances : aucune. Tier Proof : T2.
M1-S006 – Consentement opt-in bloquant : valeur = conformité EFVP, arrêt du traitement vocal si absence de consentement. Dépendances : M1-S001 (registre) et M1-S002 (machine à états). Tier Proof : T1.
M1-S007 – Digest quotidien déterministe et adaptateurs in-memory : valeur = Nathan reçoit une synthèse fiable, M1 s’interface avec des simulacres d’Approval Engine et de bus. Dépendances : M1-S001 et M1-S004. Tier Proof : T1.

Les stories sont ordonnées par dépendance réelle : M1-S001 est le socle minimal livrable en premier.

6. Critères de succès du module v1

- 100 % des signaux entrants de la fixture produisent une ligne de registre immuable.
- 100 % des tentatives de violation des interdits absolus sont bloquées avant tout appel LLM.
- 100 % des transitions de phases voix respectent la machine à états sur 1 000 exécutions aléatoires.
- 100 % des contenus empoisonnés (fixture R-015) sont neutralisés.
- Le digest quotidien produit un résultat strictement reproductible.
- Le contrat sha256 avec M2 et M3 est respecté sur toutes les fixtures.
- Zéro appel réseau, zéro horloge interne, zéro donnée inventée dans les tests.

7. Ce que le PM refuse explicitement

- « M1 pourrait donner une fourchette de prix indicative » → REFUSÉ, la responsabilité du prix appartient exclusivement à M3.
- « M1 pourrait confirmer une date approximative de chantier » → REFUSÉ, les dates sont la responsabilité de M4.
- « M1 pourrait prendre un rendez-vous ferme » → REFUSÉ, cela nécessiterait un accès au calendrier réel (M4) et constitue un engagement.
- « M1 pourrait qualifier un lead en chaud/tiède/froid sur la base de l’intonation » → REFUSÉ en v1, car cela nécessite des modèles STT avancés et une validation infra.
- « M1 pourrait envoyer un devis automatique » → REFUSÉ, tout chiffrage est émis par M3.
- « M1 pourrait relancer automatiquement les prospects après 24 h » → REFUSÉ, cela relève de l’automatisation commerciale (M2) ou du bus de notifications hors périmètre.
