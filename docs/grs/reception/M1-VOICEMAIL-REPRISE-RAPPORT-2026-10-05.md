# M1 — reprise de transcription après panne STT

Le premier STT en panne importe déjà le voicemail sans texte et ouvre un rappel humain.
Une transcription consentie ultérieure du même appel était rejetée comme contradictoire.
La reprise ajoute maintenant un maillon `appel_voicemail_enrichi` et une note au transfert
initial. Le maillon d’import d’origine reste intact; aucun second rappel n’est créé.

La preuve est volontairement stricte : même source/appel/statut, téléphone et instant
reconstituant exactement l’empreinte du fallback sans texte/consentement, signal initial et
transfert correspondant. L’origine manuelle est fixée par le wrapper. Une origine hôte,
un historique ambigu, un consentement absent ou une transcription divergente ne permettent
pas cette transition. Un ancien import sans preuves suffisantes reste refusé.

Le transfert ouvert garde la priorité humaine, sans lead forcé vers M2/M10. Un transfert
clos reçoit une note tardive sans réouverture ni perte du motif humain. La transcription
reste dans le registre privé M1; aucun fichier audio ou texte client n’est ajouté à M10.
Le reçu STT peut retrouver l’enrichissement accepté et éviter un troisième appel local lors
d’un upload identique. Une panne avant l’écriture finale annule aussi les notes/consentements
intermédiaires dans la transaction SQLite; une reprise ultérieure réussit.

Fichiers modifiés :

- `departments/m01-front-office/src/m1_front_office/outils.py` et `registre.py`.
- `departments/m01-front-office/tests/test_voicemail_stt.py` et `test_import_appels_durable.py`.
- `tests/test_console_voicemail_upload.py`.

ROOT a reproduit le défaut avant la correction : r310, 16 réussis et un échec attendu.
La campagne finale **r314 passe 283/283 dans huit fichiers complets**, Ruff et manifestes
verts, sources inchangées pendant exécution, aucune hausse des compteurs OOM. Elle comprend
le routeur console, la vraie SQLite, un serveur STT HTTP local fictif, les refus d’origine
hôte et les contrats de transferts/registre/consentement. Les reçus rouges r311 (lint),
r312 (code de refus et champs de tests), r313 (champ de projection des nouveaux tests)
restent conservés. ROOT a repris le stage Luna après indisponibilité de ce modèle et a
corrigé les assertions d’après `transferts._extrait`, sans supprimer leurs contrôles.

Limites : aucune téléphonie de production, fournisseur STT réel, mesure de précision vocale,
appel client ou SMS sortant. La transition prouve l’identité métier de l’appel; le fallback
historique ne prouve pas l’identité des octets d’un enregistrement audio. L’upload et ses
consentements restent contrôlés par le routeur existant. M1 global n’est pas déclaré complet.

## Sources et reçus

[Capsule](../../research/REPRISE-2026-10-05/preuves/RECEPTION-VENDEUR-PROMPTS-r1.tar.xz)
— SHA-256 618b58912bca71acc16abc5ec1639c502141414e2b468dea35128a5ac36f5f75.
[Inventaire et limites](../../research/REPRISE-2026-10-05/preuves/RECEPTION-VENDEUR-PROMPTS-r1.json).
La capsule conserve les rapports avant ces liens; r317 scanne 31 chemins et ne trouve aucun secret.
