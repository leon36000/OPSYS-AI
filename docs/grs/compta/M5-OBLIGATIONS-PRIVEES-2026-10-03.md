# M5 — Calendrier privé des déclarations humaines paie/DAS

État au 3 octobre 2026 : intégré localement, **PARTIEL**. Cette tranche recueille et protège des
montants confirmés par une personne; elle ne calcule ni paie nette, retenue, cotisation, remise,
paiement ou déclaration officielle. Les métadonnées de source sont déclaratives.

## Parcours disponible

La console sert `GET` et `POST /finance/paie/obligations` sous son préfixe configuré (`/opsys`
par défaut). Le formulaire de préparation de paie existant contient un lien vers ce calendrier.
La personne doit conserver un rôle actif `finance` ou `nathan_owner`; `admin` seul ne suffit pas.
Le POST exige le jeton CSRF, une révision et un identifiant de mutation. Un champ supplémentaire,
un paramètre de requête ou un snapshot périmé est refusé. Chaque confirmation comporte catégorie,
montant CAD, période, date de paie, échéance, pièce, autorité et dates/version déclarées.

Le propriétaire de la transaction existante est conservé. Le registre append-only
`m05-financecore/obligations_paies_das_privees` contient des enveloppes AES-GCM avec chaîne
vérifiée et contrôle de rejeu lié à l'acteur, à la révision et au contenu. Les clés sont dans la
portée `m05/obligations-paies-das` du propriétaire de clés existant. La lecture vérifie toute la
chaîne; une clé manquante ou une altération bloque le calendrier. Les droits sont relus avant
l'ajout et après le déchiffrement. Le rendu échappe les valeurs et répond avec `Cache-Control:
no-store`. Le registre est limité à 4 096 entrées; le dépassement est refusé avant matérialisation.

Fichiers : [service privé](../../../src/opsys/console/obligations_privees.py),
[console](../../../src/opsys/console/paie_ui.py) et
[tests](../../../tests/test_console_paie_obligations.py).

## Vérification effectivement exécutée

Les deux fichiers entiers `tests/test_console_paie.py` et
`tests/test_console_paie_obligations.py` passent **26 cas**, soit 14 du parcours existant et
12 du calendrier, avec zéro échec, erreur ou skip. Ruff passe sur les trois fichiers modifiés.
La vérification utilise la vraie base canonique SQLite, la vraie application HTTP et AES-GCM;
les données métier sont synthétiques. Elle couvre rejet CSRF/champs/permissions, accès finance,
rejeux, conflits de révision, XSS, altération du ciphertext, perte de clé et révocation de rôle.
Les 576 sources mesurées restent identiques pendant l'exécution; aucun nouvel OOM ni processus
survivant n'est constaté.

Le conducteur conservé annonce initialement RED car son compteur attendu était 22 : il omettait
quatre expansions paramétrées du fichier existant. ROOT a vérifié indépendamment les fonctions
et les listes `parametrize` dans l'AST contre tous les identifiants JUnit : 14 + 12 = 26. Aucun
résultat brut n'a été réécrit et aucun test n'a été relancé pour masquer ce défaut du compteur.
Voir [vérification ROOT](../../research/REPRISE-2026-10-03/preuves/m5-obligations/VERIFICATION-ROOT.json),
[JUnit](../../research/REPRISE-2026-10-03/preuves/m5-obligations/pytest.xml.gz) et
[reçu brut](../../research/REPRISE-2026-10-03/preuves/m5-obligations/receipt.json.gz).

## Limites et suite nécessaire

Une seconde tranche ajoute un cycle explicite : remplacement d'une obligation active et
déclaration humaine de règlement. Chaque transition conserve l'historique chiffré et valide
toute la projection sémantique avant lecture, rejeu ou ajout. Un règlement conserve le montant
et la source; il ne déclenche aucun paiement et reste **non rapproché**. Les cibles absentes,
déjà remplacées ou réglées sont refusées. Des obligations actives de même catégorie et période
signalent une ambiguïté; elles ne sont pas additionnées automatiquement.

Les deux fichiers de tests entiers passent désormais **35 cas**, soit 14 existants et 21 privés,
avec zéro échec, erreur ou skip; Ruff passe sur les trois sources. La première exécution de ce
lot comportait 34 succès et un échec de fixture : sa doublure de chiffrement ne savait pas relire
l'historique. La fixture corrigée délègue à AES-GCM réel puis retire les droits après chiffrement;
elle vérifie effectivement le refus avant écriture. Les résultats initiaux sont conservés.
Voir [preuve du cycle](../../research/REPRISE-2026-10-03/preuves/m5-cycle/VERIFICATION-ROOT.json)
et [JUnit complet](../../research/REPRISE-2026-10-03/preuves/m5-cycle/pytest.xml.gz).

Une troisième tranche relie maintenant le registre au dossier CFO **HTML privé**, puis à une
page humaine de rapprochement et de cash privé. Voir le
[contrat et la sous-matrice du rapprochement](M5-RAPPROCHEMENT-CFO-PRIVE-2026-10-03.md).
Les outils MCP/LLM, l'API financière ordinaire et les prévisions principales ne consomment pas
ces déclarations privées. Le snapshot reste **INCONNU**, sans montant utilisable, tant que les
sources ne sont pas toutes rapprochées ou qu'une composante financière manque. Le statut global
de M5 reste **PARTIEL**; cette tranche ne qualifie ni paie nette ni DAS officielles.

L'export Python complet contient la base métier et ses clés de déchiffrement. Il reste aussi
sensible que cette base et doit être chiffré avant transfert. La suppression d'une clé dans
l'instance ne supprime pas ses copies dans les anciennes archives. La politique Git du Core
est un autre chemin; elle ne remplace pas cette protection de l'export Python.
