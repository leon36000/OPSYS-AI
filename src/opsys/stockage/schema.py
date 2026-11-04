"""Tables de la base de l'instance (SQLAlchemy Core, portable SQLite et PostgreSQL).

Toute évolution passe par une migration Alembic (`migrations/versions/`), jamais par `create_all`.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)

# Tables créées par SQLite pour l'index lexical FTS5 de la base de connaissances (migration 0041) : elles n'ont pas de
# `Table` dans `META` ; les inventaires de tables des tests les ajoutent à `META.tables`.
TABLES_VIRTUELLES_SQLITE = frozenset({
    "connaissances_fts", "connaissances_fts_config", "connaissances_fts_content", "connaissances_fts_data",
    "connaissances_fts_docsize", "connaissances_fts_idx",
})

# Longueur déclarée des identifiants d'événements (migration 0056 : 512 sur PostgreSQL, qui fait respecter la longueur ;
# SQLite ne la fait pas respecter). Un identifiant d'opportunité répétée dépasse 128 caractères (M2, T4.18).
LONGUEUR_ID_EVENEMENT = 512

META = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

# Outbox de déclarations cron : état de remise, pas un second registre des profils.
AGENTS_DECLENCHEURS_INTENTIONS = Table(
    "agents_declencheurs_intentions", META,
    Column("id", String(64), primary_key=True),
    Column("instance_id", String(36), nullable=False),
    Column("agent_id", String(64), nullable=False),
    Column("profile_revision", BigInteger, nullable=False),
    Column("profile_hash", String(64), nullable=False),
    Column("trigger_hash", String(64), nullable=False),
    Column("memory_policy_hash", String(64), nullable=False),
    Column("fuseau", String(64), nullable=False),
    Column("declaration_key", String(96), nullable=False, unique=True),
    Column("statut", String(24), nullable=False),
    Column("demande_par", String(64), nullable=False),
    Column("demande_role", String(32), nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("retrait_par", String(64)),
    CheckConstraint("profile_revision > 0", name="agents_cron_revision_positive"),
    CheckConstraint("statut IN ('a_declarer','a_retirer','retiree')", name="agents_cron_statut_valide"),
)
Index("ix_agents_cron_attente", AGENTS_DECLENCHEURS_INTENTIONS.c.statut,
      AGENTS_DECLENCHEURS_INTENTIONS.c.agent_id)

AGENTS_DECLENCHEURS_COMMANDES = Table(
    "agents_declencheurs_commandes", META,
    Column("acteur", String(64), primary_key=True),
    Column("mutation_id", String(128), primary_key=True),
    Column("empreinte", String(64), nullable=False),
    Column("reponse", Text, nullable=False),
    Column("cree_le", Text, nullable=False),
)

# Reçus de retrait privé : conservation de la source humaine et de l'ACK natif,
# aucun nouveau profil, aucune capacité brute ni suppression d'intention.
AGENTS_CRON_RETRAITS = Table(
    "agents_cron_retraits", META,
    Column("intention_id", String(64), ForeignKey("agents_declencheurs_intentions.id"), primary_key=True),
    Column("epoch", Integer, nullable=False),
    Column("receipt_id", String(64), nullable=False, unique=True),
    Column("source_hash", String(64), nullable=False),
    Column("retrait_par", String(64), nullable=False),
    Column("mutation_id", String(128), nullable=False),
    Column("commande_hash", String(64), nullable=False),
    Column("retire_le", Text, nullable=False),
    Column("native_job_id", String(128), nullable=False),
    Column("native_revision", String(50), nullable=False),
    Column("declaration_hash", String(64), nullable=False),
    Column("acquitte_le", Text, nullable=False),
    Column("reponse", Text, nullable=False),
    CheckConstraint("epoch > 0", name="agents_cron_retraits_epoch"),
    CheckConstraint("length(receipt_id) = 64 AND length(source_hash) = 64 AND "
                    "length(commande_hash) = 64 AND length(declaration_hash) = 64",
                    name="agents_cron_retraits_empreintes"),
    CheckConstraint("length(native_revision) = 50 AND substr(native_revision, 1, 7) = 'sha256:'",
                    name="agents_cron_retraits_revision_native"),
)

# Registres append-only des départements : un maillon par ligne, dans l'ordre de la chaîne.
# La clé (département, registre, rang) interdit deux maillons au même rang, même en écriture
# concurrente depuis deux processus.
REGISTRES = Table(
    "registres_maillons",
    META,
    Column("departement", String(64), primary_key=True),
    Column("registre", String(64), primary_key=True),
    Column("rang", Integer, primary_key=True),
    Column("maillon", Text, nullable=False),
    Column("cree_le", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Plan de contrôle (ADR-0009) : approbations humaines, jetons consommés, artefacts tronqués,
# journal d'audit, mode effectif des départements. Vivait dans `~/.opsys/etat.db` (sqlite3 brut) ;
# migré ici (`opsys.etat.importer_etat_si_necessaire`) pour que la décision humaine et l'exécution
# de l'outil approuvé partagent une seule transaction avec le métier (`outils.executer_atomique`).
#
# Dates en texte ISO, pas en `DateTime` : elles repartent telles quelles vers les API JSON et les
# gabarits HTML de la console (`console/pages.py::_date`, qui attend une chaîne), et `usage_tokens.jour`
# sert de borne à des comparaisons `BETWEEN` textuelles (ISO trie comme le calendrier) ; un type
# `DateTime` renverrait des objets natifs côté Python et romprait ces deux usages sans rien gagner
# en portabilité, la colonne texte se comportant déjà à l'identique sur SQLite et PostgreSQL.

APPROBATIONS = Table(
    "approbations",
    META,
    Column("id", String(32), primary_key=True),
    Column("cree_le", Text, nullable=False),
    Column("departement", String(64), nullable=False),
    Column("outil", String(128), nullable=False),
    Column("arguments", Text, nullable=False),
    Column("motif_demande", Text, nullable=False, server_default=text("''")),
    Column("statut", String(16), nullable=False),
    Column("decide_par", Text),
    Column("decide_le", Text),
    Column("motif_decision", Text),
    Column("resultat", Text),
    # Niveau N (ADR-0009 §4) figé à la création de la demande (`approbations.creer_demande`), pour
    # que la décision (rôle autorisé, ADR-0009 §5) et l'affichage humain restent ceux montrés au
    # moment de la demande même si le catalogue d'outils change ensuite. Nullable : les demandes
    # importées de l'ancien `etat.db` (pré-ADR-0009, migration 0002) n'en portent pas ; `decider`
    # retombe alors sur le niveau le plus restrictif (N5), fail-closed.
    Column("niveau", String(4)),
    # Rôle de la personne (`decide_par`, désormais un identifiant de `personnes`) utilisé pour cette
    # décision (ADR-0009 §5) : une personne peut porter plusieurs rôles, celui-ci est celui qui a
    # autorisé la décision. Renseigné par `approbations.decider`, jamais par un appelant.
    Column("decide_role", Text),
    # Attestation du professionnel (nom, profession, référence du document joint), JSON, obligatoire
    # pour approuver une demande N5 en plus de la signature du propriétaire (ADR-0009 §5) ; absente
    # sinon.
    Column("attestation", Text),
    # Ticket M2/M3 scellé au moment de la demande; jamais fourni à nouveau au clic humain.
    Column("ticket_cible_hash", String(64)),
    CheckConstraint("statut IN ('en_attente','en_cours','refusee','executee','echec')", name="statut_valide"),
    Index("ix_approbations_statut", "statut", "cree_le"),
)

# Liaison à cible vérifiée (C02) : ticket privé à usage unique, empreinte du secret seulement.
# Le ticket reste dans la même transaction SQLite que l'approbation/exécution métier; son cache de
# réponse rend un renvoi de transport idempotent. Le contenu métier reste dans les registres M2/M3/M10.
LIAISONS_TICKETS = Table(
    "liaisons_tickets",
    META,
    Column("ticket_hash", String(64), primary_key=True),
    Column("cree_le", Text, nullable=False),
    Column("expire_le", Text, nullable=False),
    Column("departement", String(64), nullable=False),
    Column("agent_id", String(64), nullable=False),
    Column("cle_session", Text, nullable=False),
    Column("affaire_id", String(197), nullable=False),
    Column("genre_affaire", String(16), nullable=False),
    Column("ligne_liaison_id", String(64), nullable=False),
    Column("outil", String(128), nullable=False),
    Column("empreinte_arguments", String(64), nullable=False),
    Column("statut", String(16), nullable=False, server_default=text("'disponible'")),
    Column("demande_id", String(32), unique=True),
    Column("reponse", Text),
    Column("consomme_le", Text),
    CheckConstraint("genre_affaire IN ('lead','opportunite')", name="genre_affaire_valide"),
    CheckConstraint("statut IN ('disponible','scelle','consomme')", name="statut_valide"),
    Index("ix_liaisons_tickets_expire", "expire_le", "statut"),
)

# Identité (ADR-0009 §5) : une personne, ses rôles. Remplace le mot de passe partagé de la console —
# toute décision (approbation, connexion) est désormais signée par une personne active. `actif` coupe
# l'accès sans supprimer l'historique (une décision passée garde son `decide_par`) ; réactivable.
PERSONNES = Table(
    "personnes",
    META,
    Column("identifiant", String(64), primary_key=True),
    Column("nom", Text, nullable=False),
    Column("actif", Boolean, nullable=False, server_default=text("true")),
    Column("mot_de_passe_hash", Text, nullable=False),  # hashlib.scrypt, jamais de clair (opsys.identite)
    Column("cree_le", Text, nullable=False),
)

# Rôles d'une personne (ADR-0009 §5) : enum fermé porté par une CHECK, jamais un texte libre. Une
# personne peut porter plusieurs rôles (ex. nathan_owner ET finance) ; la clé (identifiant, role)
# interdit le doublon.
ROLES_PERSONNES = Table(
    "roles",
    META,
    Column("identifiant", String(64), ForeignKey("personnes.identifiant"), primary_key=True),
    Column("role", String(32), primary_key=True),
    CheckConstraint(
        "role IN ('nathan_owner','admin','finance','manager','seller','employee','client','system_agent')",
        name="role_valide",
    ),
)

USAGE_TOKENS = Table(
    "usage_tokens",
    META,
    Column("jour", Text, primary_key=True),
    Column("departement", String(64), primary_key=True),
    Column("modele", String(128), primary_key=True),
    Column("appels", BigInteger, nullable=False, server_default=text("0")),
    Column("tokens_entree", BigInteger, nullable=False, server_default=text("0")),
    Column("tokens_sortie", BigInteger, nullable=False, server_default=text("0")),
    Column("tokens_cache_lus", BigInteger, nullable=False, server_default=text("0")),
)

ARTEFACTS = Table(
    "artefacts",
    META,
    Column("id", String(32), primary_key=True),
    Column("cree_le", Text, nullable=False),
    Column("source", String(128), nullable=False),
    Column("departement", String(64)),
    Column("origine", String(64)),
    Column("taille", Integer, nullable=False),
    Column("contenu", Text, nullable=False),
)

JOURNAL = Table(
    "journal",
    META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quand", Text, nullable=False),
    Column("par", Text, nullable=False),
    Column("action", String(128), nullable=False),
    Column("cible", Text, nullable=False),
    Column("details", Text, nullable=False, server_default=text("'{}'")),
)

# Clés de chiffrement destructibles (PLAN T4.2, POLITIQUE-geolocalisation.md §5) : effacement
# cryptographique (crypto-shredding) pour une donnée personnelle qu'un registre append-only ne
# peut ni modifier ni supprimer une fois écrite (REGISTRES ci-dessus, INSERT seul). Un maillon
# chiffré avec la clé (portee, identifiant) reste dans la chaîne pour toujours, intact ; DÉTRUIRE
# la ligne ici retire la clé de l'API sans toucher au registre ni à son empreinte. Le nettoyage
# des fichiers courants est suivi séparément dans EFFACEMENTS_CLES.
# `portee` namespace l'usage (ex. "m04-field-ops/gps") ;
# `identifiant` est la clé métier dans cette portée (ex. un technicien_id) — une seule clé par
# (portee, identifiant), jamais de rotation en v1 (voir `opsys.cles_chiffrement`).
CLES_CHIFFREMENT = Table(
    "cles_chiffrement",
    META,
    Column("portee", String(128), primary_key=True),
    Column("identifiant", String(128), primary_key=True),
    Column("cle", Text, nullable=False),
    Column("cree_le", Text, nullable=False),
)

# État distinct du DELETE logique ; aucune clé ni empreinte de clé dans cette file.
EFFACEMENTS_CLES = Table(
    "effacements_cles", META,
    Column("purge_id", String(32), primary_key=True),
    Column("portee", String(128), nullable=False),
    Column("identifiant", String(128), nullable=False),
    Column("demande_id", Text, nullable=True),
    Column("cree_le", Text, nullable=False),
    Column("cle_detruite", Boolean, nullable=False),
    Column("etat_fichiers", String(24), nullable=False),
    Column("motif", String(40), nullable=True),
    CheckConstraint("etat_fichiers IN ('en_attente','termine','non_qualifie')", name="etat_fichiers_valide"),
)

MODES_DEPARTEMENTS = Table(
    "modes_departements",
    META,
    Column("departement", String(64), primary_key=True),
    Column("mode", String(16), nullable=False),
    Column("modifie_par", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    CheckConstraint("mode IN ('ombre','supervise','autonome')", name="mode_valide"),
)

# Bus d'événements (ADR-0009 §3) : outbox durcie. `publier()` insère dans EVENEMENTS_SORTANTS dans
# la transaction métier courante (même point de sauvegarde que l'écriture qui le déclenche) ; le
# répartiteur (`opsys.evenements.repartir`) livre chaque événement à chacun de ses consommateurs
# abonnés et trace le résultat dans EVENEMENTS_RECUS. `evenement_id` est fourni (idempotence du
# producteur) ou un uuid4 hex généré par défaut ; sa clé primaire porte l'unicité exigée par
# l'ADR. `charge` est le JSON typé du codec (`stockage.codec`), comme les maillons de registre.
EVENEMENTS_SORTANTS = Table(
    "evenements_sortants",
    META,
    Column("evenement_id", String(LONGUEUR_ID_EVENEMENT), primary_key=True),
    Column("type_evenement", String(128), nullable=False),
    Column("producteur", String(64), nullable=False),
    Column("charge", Text, nullable=False),
    Column("cree_le", Text, nullable=False),
    Index("ix_evenements_sortants_type", "type_evenement", "cree_le"),
)

# Un reçu par (événement, consommateur) : UNIQUE(evenement_id, consommateur) est la clé primaire
# elle-même, donc une relivraison ne peut jamais créer un second reçu « traité » pour la même paire
# (idempotence effective). `statut` : 'echec' (réessai plus tard selon `prochaine_tentative`,
# backoff exponentiel), 'traite' (résumé du consommateur dans `resultat`, jamais rejoué), ou
# 'quarantaine' (5 échecs : plus aucune relivraison automatique, visible dans `opsys-metier evenements etat`).
EVENEMENTS_RECUS = Table(
    "evenements_recus",
    META,
    Column("evenement_id", String(LONGUEUR_ID_EVENEMENT), ForeignKey("evenements_sortants.evenement_id"),
           primary_key=True),
    Column("consommateur", String(64), primary_key=True),
    Column("statut", String(16), nullable=False),
    Column("tentatives", Integer, nullable=False, server_default=text("0")),
    Column("prochaine_tentative", Text),
    Column("resultat", Text),
    Column("derniere_erreur", Text),
    CheckConstraint("statut IN ('echec','traite','quarantaine')", name="statut_valide"),
    Index("ix_evenements_recus_statut", "statut", "prochaine_tentative"),
)

# Idempotence des mutations d'appareil (T1.4-b ; contrat R12 §4, `docs/architecture/IDEMPOTENCE.md`).
# `(appareil, cle_idempotence)` est la clé posée par `opsys.idempotence.reclamer`, dans la MÊME
# transaction que l'exécution de l'outil (`opsys.capacites.Capacites._appeler_idempotent`) : un
# renvoi de la même clé, du même outil et des mêmes arguments (`empreinte_arguments`) rejoue
# `reponse` (encodée par `stockage.codec`, comme les maillons de registre) sans ré-exécuter.
# `statut='en_cours'` n'est jamais visible hors de sa transaction : `finaliser` l'écrase avant le
# commit, ou la transaction entière (réclamation comprise) s'annule avec une panne interne — jamais
# enregistrée, pour qu'un renvoi réel réessaie. `horodatage_appareil` (heure de l'appareil, affichage
# seulement) et `recu_le` (heure du serveur, fait foi — ex. la paie, M4/T1.4-d) sont du texte ISO,
# comme les autres dates du plan de contrôle (voir la note sur APPROBATIONS ci-dessus).
MUTATIONS_APPLIQUEES = Table(
    "mutations_appliquees",
    META,
    Column("appareil", String(128), primary_key=True),
    Column("cle_idempotence", String(128), primary_key=True),
    Column("outil", String(128), nullable=False),
    Column("empreinte_arguments", String(64), nullable=False),
    Column("reponse", Text, nullable=False),
    Column("horodatage_appareil", Text, nullable=False),
    Column("recu_le", Text, nullable=False),
    Column("statut", String(24), nullable=False),
    CheckConstraint("statut IN ('en_cours','ok','refus_metier','en_attente_approbation')", name="statut_valide"),
)

# Appairage d'appareil (ADR-0009 §5 : table `appareils` appairés à une personne ; T1.4-c2, R12
# §1.3/§6/§9). `identifiant` est le même `deviceId` que le core transmet en `_meta` MCP
# `opsys/appareil` (T1.4-b/c1, colonne `appareil` de MUTATIONS_APPLIQUEES ci-dessus) : la même
# identité sert l'idempotence des mutations et la portée du rôle nommé du jeton. `role` est
# EXACTEMENT le type `Profil` fermé du client mobile (`mobile/src/roles/types.ts`), moins `client`
# (lien tokenisé, jamais un appareil apparié durablement, R12 §6) — pas `finance`/`manager`/
# `system_agent`, sans profil mobile, ni `nathan_owner` : un rôle de jeton hors de `Profil` ferait
# refuser tout routage côté app (`evaluerGarde`, fail-closed) ; l'appareil du propriétaire est donc
# appairé `admin`, sa portée additionnelle passant par la PERSONNE (`opsys/personne`), jamais par le
# rôle du jeton (voir `opsys.appareils.ROLES_APPAREIL`).
APPAREILS = Table(
    "appareils",
    META,
    Column("identifiant", String(128), primary_key=True),
    Column("personne", String(64), ForeignKey("personnes.identifiant"), nullable=False),
    Column("role", String(32), nullable=False),
    Column("appaire_le", Text, nullable=False),
    CheckConstraint("role IN ('admin','employee','seller')", name="role_appareil_valide"),
)

# Dépôt de fichiers adressé par contenu (T1.4-e2, ADR-0009 §2 « tout dans la même base » : les
# binaires de preuve — photos après-chantier, signature client — vivent dans la même base que le
# reste, les sauvegardes restent cohérentes ; pas de service de stockage séparé). Département-
# agnostique à dessein : `opsys.fichiers` ne connaît aucun catalogue de verdicts, pour que M5
# (reçus) et M7 (contenus) puissent réutiliser ces deux tables sans dépendre de M4
# (docs/architecture/FICHIERS.md). Contenu stocké en base64 texte (colonne ``Text``), comme le
# reste du plan de contrôle (ex. ``cles_chiffrement.cle`` en hex) : pas de type BLOB propre à un
# dialecte, portable SQLite/PostgreSQL sans code spécifique.
#
# ``fichiers`` porte la déclaration (immuable une fois posée : ``deposer_bloc`` refuse toute
# redéclaration incohérente de la même empreinte) et l'état d'assemblage ; ``fichiers_blocs`` porte
# chaque bloc reçu, un par ``(empreinte_sha256, index_bloc)`` — la liste des index déjà reçus permet
# à un appareil hors ligne d'abord de reprendre un envoi interrompu (``m4_etat_fichier``) sans
# retransmettre ce qui est déjà là.
FICHIERS = Table(
    "fichiers",
    META,
    Column("empreinte_sha256", String(64), primary_key=True),
    Column("taille_octets", Integer, nullable=False),
    Column("type_mime", String(32), nullable=False),
    Column("nombre_blocs", Integer, nullable=False),
    # Faux tant que tous les blocs annoncés ne sont pas reçus ET que le contenu assemblé n'a pas
    # passé les trois vérifications (taille, SHA-256, octets magiques du type annoncé) — jamais
    # mis à vrai avant coup (`opsys.fichiers.deposer_bloc`).
    Column("complet", Boolean, nullable=False, server_default=text("false")),
    Column("cree_le", Text, nullable=False),
    Column("complete_le", Text),
    CheckConstraint("type_mime IN ('image/jpeg','image/png')", name="type_mime_valide"),
    CheckConstraint("taille_octets BETWEEN 1 AND 10485760", name="taille_octets_valide"),
    CheckConstraint("nombre_blocs BETWEEN 1 AND 64", name="nombre_blocs_valide"),
)

FICHIERS_BLOCS = Table(
    "fichiers_blocs",
    META,
    Column("empreinte_sha256", String(64), ForeignKey("fichiers.empreinte_sha256"), primary_key=True),
    Column("index_bloc", Integer, primary_key=True),
    Column("contenu_base64", Text, nullable=False),
    Column("taille_octets", Integer, nullable=False),
    Column("recu_le", Text, nullable=False),
    CheckConstraint("index_bloc >= 0", name="index_bloc_valide"),
)

# Pilote d'import comptable CSV : source et résultats restent chiffrés dans le lot préparatoire.
FUSION_LOTS = Table(
    "fusion_lots",
    META,
    Column("lot_id", String(36), primary_key=True),
    Column("acteur", String(64), nullable=False),
    Column("mutation_id", String(128), nullable=False),
    Column("empreinte_requete", String(64), nullable=False),
    Column("cle_deduplication", String(64), nullable=False, unique=True),
    Column("compte_interne_id", String(64), nullable=False),
    Column("devise", String(3), nullable=False),
    Column("mapping_colonnes", Text, nullable=False),
    Column("source_sha256", String(64), nullable=False),
    Column("source_octets", Integer, nullable=False),
    Column("source_nonce", String(24), nullable=False),
    Column("source_cipher", Text, nullable=False),
    Column("source_cipher_octets", Integer, nullable=False),
    Column("resultat_nonce", String(24)),
    Column("resultat_cipher", Text),
    Column("resultat_cipher_octets", Integer, nullable=False),
    Column("cle_reference", String(64), nullable=False),
    Column("version_format", Integer, nullable=False),
    Column("snapshot_version", Integer, nullable=False),
    Column("snapshot_empreinte", String(64)),
    Column("statut", String(32), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("curseur", Integer, nullable=False),
    Column("total_lignes", Integer),
    Column("nombre_propositions", Integer, nullable=False),
    Column("verdict", Text),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    UniqueConstraint("acteur", "mutation_id", name="uq_fusion_lots_acteur_mutation"),
    CheckConstraint("devise = 'CAD'", name="devise_cad"),
    CheckConstraint("source_octets BETWEEN 1 AND 1048576", name="source_taille"),
    CheckConstraint("source_cipher_octets >= source_octets", name="source_cipher_taille"),
    CheckConstraint("resultat_cipher_octets >= 0", name="resultat_cipher_taille"),
    CheckConstraint("snapshot_version >= 0", name="snapshot_version"),
    CheckConstraint("revision > 0 AND curseur >= 0", name="revision_curseur"),
    CheckConstraint("nombre_propositions >= 0", name="nombre_propositions"),
    CheckConstraint(
        "statut IN ('RECU','EN_COURS','PROPOSITIONS','AUCUNE_PROPOSITION','REFUSE',"
        "'SNAPSHOT_OBSOLETE','ERREUR_REPRENABLE')",
        name="statut_valide",
    ),
)
Index("ix_fusion_lots_cree", FUSION_LOTS.c.cree_le)
Index("ix_fusion_lots_acteur", FUSION_LOTS.c.acteur)

FUSION_COMMANDES = Table(
    "fusion_commandes",
    META,
    Column("acteur", String(64), primary_key=True),
    Column("mutation_id", String(128), primary_key=True),
    Column("empreinte_requete", String(64), nullable=False),
    Column("lot_id", String(36), ForeignKey("fusion_lots.lot_id"), nullable=False),
    Column("cree_le", Text, nullable=False),
)

FUSION_LIGNES = Table(
    "fusion_lignes",
    META,
    Column("lot_id", String(36), ForeignKey("fusion_lots.lot_id", ondelete="CASCADE"), primary_key=True),
    Column("numero", Integer, primary_key=True),
    Column("nonce", String(24), nullable=False),
    Column("cipher", Text, nullable=False),
    Column("cipher_octets", Integer, nullable=False),
    Column("est_proposition", Boolean, nullable=False),
    CheckConstraint("numero >= 2", name="numero_csv"),
    CheckConstraint("cipher_octets > 0", name="cipher_taille"),
)

FUSION_QUOTA = Table(
    "fusion_quota",
    META,
    Column("id", Integer, primary_key=True),
    Column("lots", Integer, nullable=False),
    Column("octets_cipher", Integer, nullable=False),
    CheckConstraint("id = 1", name="singleton"),
    CheckConstraint("lots BETWEEN 0 AND 64", name="lots_borne"),
    CheckConstraint("octets_cipher BETWEEN 0 AND 67108864", name="octets_bornes"),
)

# Pilote PDF natif préparatoire : compartiment FINANCIAL distinct des lots CSV.
FUSION_PDF_LOTS = Table(
    "fusion_pdf_lots", META,
    Column("lot_id", String(36), primary_key=True),
    Column("acteur", String(64), nullable=False),
    Column("mutation_id", String(128), nullable=False),
    Column("empreinte_requete", String(64), nullable=False),
    Column("cle_deduplication", String(64), nullable=False, unique=True),
    Column("type_source", String(16), nullable=False),
    Column("classe", String(16), nullable=False),
    Column("extracteur", String(64), nullable=False),
    Column("configuration_sha256", String(64), nullable=False),
    Column("source_sha256", String(64), nullable=False),
    Column("source_octets", Integer, nullable=False),
    Column("source_nonce", String(24), nullable=False),
    Column("source_cipher", Text, nullable=False),
    Column("source_cipher_octets", Integer, nullable=False),
    Column("resultat_nonce", String(24)),
    Column("resultat_cipher", Text),
    Column("resultat_cipher_octets", Integer, nullable=False),
    Column("cle_reference", String(64), nullable=False),
    Column("version_format", Integer, nullable=False),
    Column("statut", String(32), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("total_pages", Integer, nullable=False),
    Column("code", String(64)),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    UniqueConstraint("acteur", "mutation_id", name="uq_fusion_pdf_lots_acteur_mutation"),
    CheckConstraint("type_source = 'pdf_natif' AND classe = 'FINANCIAL'", name="classification"),
    CheckConstraint("source_octets BETWEEN 1 AND 1048576", name="source_taille"),
    CheckConstraint("source_cipher_octets = source_octets + 16", name="source_cipher_taille"),
    CheckConstraint("resultat_cipher_octets BETWEEN 0 AND 524304", name="resultat_taille"),
    CheckConstraint("version_format = 1 AND revision > 0", name="versions"),
    CheckConstraint("total_pages BETWEEN 0 AND 20", name="pages_borne"),
    CheckConstraint(
        "statut IN ('RECU','EXTRAIT_PREPARATOIRE','REFUSE','ERREUR_REPRENABLE')", name="statut_valide",
    ),
    CheckConstraint(
        "(statut = 'EXTRAIT_PREPARATOIRE' AND resultat_nonce IS NOT NULL AND resultat_cipher IS NOT NULL "
        "AND resultat_cipher_octets > 16 AND total_pages > 0 AND code IS NULL) OR "
        "(statut <> 'EXTRAIT_PREPARATOIRE' AND resultat_nonce IS NULL AND resultat_cipher IS NULL "
        "AND resultat_cipher_octets = 0 AND total_pages = 0)", name="resultat_etat",
    ),
)
Index("ix_fusion_pdf_lots_cree", FUSION_PDF_LOTS.c.cree_le)

FUSION_PDF_COMMANDES = Table(
    "fusion_pdf_commandes", META,
    Column("acteur", String(64), primary_key=True),
    Column("mutation_id", String(128), primary_key=True),
    Column("empreinte_requete", String(64), nullable=False),
    Column("lot_id", String(36), ForeignKey("fusion_pdf_lots.lot_id"), nullable=False),
    Column("cree_le", Text, nullable=False),
)

FUSION_PDF_QUOTA = Table(
    "fusion_pdf_quota", META,
    Column("id", Integer, primary_key=True),
    Column("lots", Integer, nullable=False),
    Column("octets_cipher", Integer, nullable=False),
    CheckConstraint("id = 1", name="singleton"),
    CheckConstraint("lots BETWEEN 0 AND 16", name="lots_borne"),
    CheckConstraint("octets_cipher BETWEEN 0 AND 16777216", name="octets_bornes"),
)

# Brouillon AP revu par un humain : contenu chiffré lié à un lot PDF, jamais écrit dans le registre M5.
FUSION_AP_BROUILLONS = Table(
    "fusion_ap_brouillons", META,
    Column("lot_id", String(36), ForeignKey("fusion_pdf_lots.lot_id"), primary_key=True),
    Column("source_sha256", String(64), nullable=False),
    Column("configuration_sha256", String(64), nullable=False),
    Column("extracteur", String(64), nullable=False),
    Column("revision_pdf", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("statut", String(24), nullable=False),
    Column("auteur", String(64), nullable=False),
    Column("modifie_par", String(64), nullable=False),
    Column("cle_reference", String(64), nullable=False),
    Column("version_format", Integer, nullable=False),
    Column("proposition_nonce", String(24), nullable=False),
    Column("proposition_cipher", Text, nullable=False),
    Column("proposition_cipher_octets", Integer, nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    CheckConstraint("length(source_sha256) = 64 AND length(configuration_sha256) = 64", name="empreintes"),
    CheckConstraint("revision_pdf > 0 AND revision > 0 AND version_format = 1", name="versions"),
    CheckConstraint("statut = 'A_REVOIR'", name="statut_revue"),
    CheckConstraint("length(proposition_nonce) = 16", name="nonce_taille"),
    CheckConstraint("proposition_cipher_octets BETWEEN 17 AND 8208", name="proposition_taille"),
)

# Source OCR immuable d'un brouillon AP. L'absence de ligne signifie PDF_NATIF.
FUSION_AP_OCR_SOURCES = Table(
    "fusion_ap_ocr_sources", META,
    Column("lot_id", String(36), ForeignKey("fusion_ap_brouillons.lot_id"), primary_key=True),
    Column("source_type", String(24), nullable=False),
    Column("ocr_run_id", String(36), ForeignKey("fusion_pdf_ocr_runs.ocr_run_id"), nullable=False),
    Column("revision_run", Integer, nullable=False),
    Column("ocr_configuration_sha256", String(64), nullable=False),
    Column("ocr_profil_id", String(32), nullable=False),
    CheckConstraint("source_type = 'OCR_CANDIDAT'", name="source_type_ocr_candidat"),
    CheckConstraint("revision_run > 0", name="revision_run_positive"),
    CheckConstraint("length(ocr_configuration_sha256) = 64", name="configuration_sha256_taille"),
    CheckConstraint("length(ocr_profil_id) BETWEEN 1 AND 32", name="profil_id_taille"),
)

FUSION_AP_COMMANDES = Table(
    "fusion_ap_commandes", META,
    Column("lot_id", String(36), ForeignKey("fusion_ap_brouillons.lot_id"), primary_key=True),
    Column("acteur", String(64), primary_key=True),
    Column("mutation_id", String(128), primary_key=True),
    Column("empreinte_requete", String(64), nullable=False),
    Column("revision_resultat", Integer, nullable=False),
    Column("cree_le", Text, nullable=False),
    CheckConstraint("length(empreinte_requete) = 64", name="empreinte_taille"),
    CheckConstraint("revision_resultat > 0", name="revision_positive"),
)

# Liaison de provenance uniquement : la facture et ses corrections restent dans le registre M5.
FUSION_AP_SAISIES = Table(
    "fusion_ap_saisies", META,
    Column("lot_id", String(36), ForeignKey("fusion_ap_brouillons.lot_id"), primary_key=True),
    Column("acteur", String(64), nullable=False),
    Column("mutation_id", String(128), nullable=False),
    Column("commande_sha256", String(64), nullable=False),
    Column("preuve_json", Text, nullable=False),
    Column("approbation_id", String(12), ForeignKey("approbations.id"), nullable=False, unique=True),
    Column("facture_id", String(64), nullable=False),
    Column("maillon_id", String(64), nullable=False),
    Column("rang_maillon", Integer, nullable=False),
    Column("cree_le", Text, nullable=False),
    UniqueConstraint("acteur", "mutation_id", name="uq_fusion_ap_saisies_acteur_mutation"),
    CheckConstraint("length(commande_sha256) = 64 AND length(maillon_id) = 64", name="empreintes"),
    CheckConstraint("rang_maillon >= 0", name="rang"),
    CheckConstraint("length(preuve_json) BETWEEN 2 AND 4096", name="preuve_bornee"),
)

# Profils d'agents configurables : projection courante + historique immuable des révisions.
AGENTS_CONFIGURABLES = Table(
    "agents_configurables",
    META,
    Column("id", String(64), primary_key=True),
    Column("departement", String(64), nullable=False),
    Column("responsabilite", Text, nullable=False),
    Column("palier_modele", String(16), nullable=False),
    Column("outils", Text, nullable=False),
    Column("budget_jour", BigInteger, nullable=False),
    Column("budget_mois", BigInteger, nullable=False),
    Column("limite_tours", Integer, nullable=False),
    Column("limite_reessais", Integer, nullable=False),
    Column("limite_concurrence", Integer, nullable=False),
    Column("declencheurs", Text, nullable=False),
    Column("actif", Boolean, nullable=False),
    Column("supprime", Boolean, nullable=False, server_default=text("false")),
    Column("revision", BigInteger, nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(64), nullable=False),
    Column("mutation_id", String(128), nullable=False),
    Column("mutation_hash", String(64), nullable=False),
    CheckConstraint("palier_modele IN ('local','rapide','standard','fort')", name="palier_valide"),
    CheckConstraint("budget_jour > 0 AND budget_mois > 0", name="budgets_positifs"),
    CheckConstraint("limite_tours > 0 AND limite_reessais >= 0 AND limite_concurrence > 0", name="limites_valides"),
    CheckConstraint("revision > 0", name="revision_positive"),
)

AGENTS_CONFIGURABLES_HISTORIQUE = Table(
    "agents_configurables_historique",
    META,
    Column("agent_id", String(64), primary_key=True),
    Column("revision", BigInteger, primary_key=True),
    Column("instantane", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(64), nullable=False),
    Column("mutation_id", String(128), nullable=False),
)

# Autorisation humaine distincte du profil; limitée aux deux lectures CFO préparatoires.
AGENTS_GRANTS_CFO = Table(
    "agents_grants_cfo",
    META,
    Column("agent_id", String(64), primary_key=True),
    Column("instance_id", String(128), nullable=False),
    Column("profile_revision", BigInteger, nullable=False),
    Column("version", Integer, nullable=False),
    Column("active", Boolean, nullable=False),
    Column("tools", Text, nullable=False),
    Column("reports_per_day", Integer, nullable=False),
    Column("expires_at", Text, nullable=False),
    Column("report_date_start", String(10), nullable=False),
    Column("report_date_end", String(10), nullable=False),
    Column("granted_by", String(64), nullable=False),
    Column("granted_role", String(32), nullable=False),
    Column("created_at", Text, nullable=False),
    Column("modified_at", Text, nullable=False),
    Column("modified_by", String(64), nullable=False),
    Column("modified_role", String(32), nullable=False),
    CheckConstraint("profile_revision > 0 AND version > 0", name="agents_grants_cfo_revision_positive"),
    CheckConstraint("report_date_start <= report_date_end", name="agents_grants_cfo_report_dates_ordered"),
    CheckConstraint("reports_per_day BETWEEN 1 AND 20", name="agents_grants_cfo_quota_valid"),
)

AGENTS_GRANTS_CFO_HISTORIQUE = Table(
    "agents_grants_cfo_historique",
    META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("agent_id", String(64), nullable=False),
    Column("version", Integer, nullable=False),
    Column("event", String(16), nullable=False),
    Column("snapshot", Text, nullable=False),
    Column("actor", String(64), nullable=False),
    Column("actor_role", String(32), nullable=False),
    Column("created_at", Text, nullable=False),
    CheckConstraint("event IN ('grant','revocation')", name="agents_grants_cfo_event_valid"),
)

AGENTS_TICKETS_CFO = Table(
    "agents_tickets_cfo",
    META,
    Column("ticket_hash", String(64), primary_key=True),
    Column("agent_id", String(64), nullable=False),
    Column("grant_version", Integer, nullable=False),
    Column("profile_revision", BigInteger, nullable=False),
    Column("instance_id", String(128), nullable=False),
    Column("tool", String(128), nullable=False),
    Column("arguments_hash", String(64), nullable=False),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    Column("status", String(16), nullable=False, server_default=text("'available'")),
    Column("consumed_at", Text),
    CheckConstraint(
        "tool IN ('m5_preparer_dossier_decision_cfo','m5_preparer_decision_capital')",
        name="agents_tickets_cfo_tool_valid",
    ),
    CheckConstraint("status IN ('available','consumed')", name="agents_tickets_cfo_status_valid"),
)

Index("ix_agents_tickets_cfo_agent_created", AGENTS_TICKETS_CFO.c.agent_id, AGENTS_TICKETS_CFO.c.created_at)

OPSYS_INSTANCE = Table(
    "opsys_instance",
    META,
    Column("id", Integer, primary_key=True),
    Column("instance_id", String(36), nullable=False, unique=True),
    CheckConstraint("id = 1", name="opsys_instance_singleton"),
)

# Historique append-only : aucune politique initiale n'est créée par la migration.
SERVICE_POLITIQUES = Table(
    'service_politiques', META,
    Column('instance_id', String(36), ForeignKey('opsys_instance.instance_id'), primary_key=True),
    Column('consommateur', String(128), primary_key=True),
    Column('operation', String(64), primary_key=True),
    Column('revision', Integer, primary_key=True),
    Column('active', Boolean, nullable=False),
    Column('expire_le', BigInteger, nullable=False),
    CheckConstraint('revision > 0 AND expire_le > 0', name='service_politique_revision'),
    CheckConstraint('active IN (false, true)', name='service_politique_active'),
)
SERVICE_AUDIT = Table(
    'service_audit', META,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('instance_id', String(36), nullable=False),
    Column('consommateur', String(128), nullable=False),
    Column('operation', String(64), nullable=False),
    Column('revision', Integer, nullable=False),
    Column('evenement_id', String(LONGUEUR_ID_EVENEMENT)),
    Column('action', String(24), nullable=False),
    CheckConstraint("action IN ('usage','revocation')", name='service_audit_action'),
)

# Private native-publication attempt ledger, never a second configuration selector.
CONFIGURATION_PUBLICATIONS = Table(
    "configuration_publications", META,
    Column("id", String(64), primary_key=True),
    Column("instance_id", String(36), ForeignKey("opsys_instance.instance_id"), nullable=False),
    Column("cible_hash", String(64), nullable=False),
    Column("operation", String(16), nullable=False),
    Column("base_hash", String(64), nullable=False),
    Column("candidat_hash", String(64), nullable=False),
    Column("source_hash", String(64), nullable=False),
    Column("fichiers_hash", String(64), nullable=False),
    Column("sql_hash", String(64), nullable=False),
    Column("liaison_hash", String(64), nullable=False),
    Column("capacite_hash", String(64), nullable=False),
    Column("version", Integer, nullable=False),
    Column("bail_jusqua", BigInteger, nullable=False),
    Column("etat", String(24), nullable=False),
    Column("observation_hash", String(64)),
    CheckConstraint("operation = 'publish'", name="publication_operation"),
    CheckConstraint("version > 0 AND version <= 2147483647 AND bail_jusqua > 0", name="publication_version_bail"),
    CheckConstraint("etat IN ('preparee','dispatch_reserve','incertaine','candidat_observe','annulee')",
                    name="publication_etat"),
    CheckConstraint("length(id) = 64 AND length(instance_id) = 36 AND length(cible_hash) = 64 AND "
                    "length(base_hash) = 64 AND length(candidat_hash) = 64 AND length(source_hash) = 64 AND "
                    "length(fichiers_hash) = 64 AND length(sql_hash) = 64 AND length(liaison_hash) = 64 AND "
                    "length(capacite_hash) = 64 AND (observation_hash IS NULL OR length(observation_hash) = 64)",
                    name="publication_empreintes"),
)
Index("uq_configuration_publication_active", CONFIGURATION_PUBLICATIONS.c.instance_id,
      CONFIGURATION_PUBLICATIONS.c.cible_hash, unique=True,
      sqlite_where=text("etat IN ('preparee','dispatch_reserve','incertaine')"),
      postgresql_where=text("etat IN ('preparee','dispatch_reserve','incertaine')"))

AGENTS_CONFIGURABLES_COMMANDES = Table(
    "agents_configurables_commandes",
    META,
    Column("mutation_id", String(128), primary_key=True),
    Column("agent_id", String(64), nullable=False),
    Column("empreinte", String(64), nullable=False),
    Column("reponse", Text, nullable=False),
)

AGENTS_POLITIQUE_ENTREPRISE = Table(
    "agents_politique_entreprise",
    META,
    Column("id", Integer, primary_key=True),
    Column("budget_jour", BigInteger, nullable=False),
    Column("budget_mois", BigInteger, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(64), nullable=False),
    CheckConstraint("id = 1", name="singleton"),
    CheckConstraint("budget_jour > 0 AND budget_mois >= budget_jour", name="budgets_valides"),
    CheckConstraint("revision > 0", name="revision_positive"),
)

AGENTS_RESERVATIONS = Table(
    "agents_reservations",
    META,
    Column("id", String(32), primary_key=True),
    Column("agent_id", String(64), nullable=False),
    Column("departement", String(64), nullable=False),
    Column("execution_id", String(128), nullable=False),
    Column("cle_idempotence", String(128), nullable=False),
    Column("tokens_plafond", BigInteger, nullable=False),
    Column("tokens_reels", BigInteger),
    Column("jour", Text, nullable=False),
    Column("mois", String(7), nullable=False),
    Column("tours", Integer, nullable=False),
    Column("reessais", Integer, nullable=False),
    Column("attempt_id", String(160)),
    Column("cycle_id", String(160)),
    Column("candidate_index", Integer),
    Column("stream_ordinal", Integer),
    Column("is_fallback_retry", Boolean),
    Column("statut", String(16), nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    UniqueConstraint("agent_id", "cle_idempotence", name="uq_agents_reservations_agent_cle"),
    UniqueConstraint("cycle_id", name="uq_agents_reservations_cycle"),
    CheckConstraint("stream_ordinal IS NULL OR stream_ordinal >= 0", name="stream_ordinal_valide"),
    CheckConstraint("tokens_plafond > 0 AND (tokens_reels IS NULL OR tokens_reels >= 0)", name="tokens_valides"),
    CheckConstraint("tours > 0 AND reessais >= 0", name="tours_valides"),
    CheckConstraint("statut IN ('reservee','conciliee','liberee')", name="statut_valide"),
)

AGENTS_RESERVATIONS_HISTORIQUE = Table(
    "agents_reservations_historique",
    META,
    Column("id", String(32), primary_key=True),
    Column("reservation_id", String(32), nullable=False),
    Column("evenement", String(16), nullable=False),
    Column("tokens_reels", BigInteger),
    Column("raison", Text, nullable=False),
    Column("cree_le", Text, nullable=False),
    CheckConstraint("evenement IN ('reservee','conciliee','liberee')", name="evenement_valide"),
)

CONNECTEURS_STT = Table(
    "connecteurs_stt", META,
    Column("id", String(32), primary_key=True),
    Column("actif", Boolean, nullable=False),
    Column("references", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(64), nullable=False),
    Column("mutation_id", String(128), nullable=False),
    Column("mutation_hash", String(64), nullable=False),
    CheckConstraint("id = 'stt-m1'", name="id_valide"),
    CheckConstraint("revision > 0", name="revision_positive"),
)

CONNECTEURS_STT_HISTORIQUE = Table(
    "connecteurs_stt_historique", META,
    Column("revision", Integer, primary_key=True),
    Column("instantane", Text, nullable=False),
)

CONNECTEURS_STT_COMMANDES = Table(
    "connecteurs_stt_commandes", META,
    Column("mutation_id", String(128), primary_key=True),
    Column("acteur", String(64), nullable=False),
    Column("empreinte", String(64), nullable=False),
    Column("reponse", Text, nullable=False),
)

CONNECTEURS_STT_DIAGNOSTICS = Table(
    "connecteurs_stt_diagnostics", META,
    Column("mutation_id", String(128), primary_key=True),
    Column("revision", Integer, nullable=False),
    Column("acteur", String(64), nullable=False),
    Column("jeton", String(64), nullable=False),
    Column("statut", String(32), nullable=False),
    Column("resultat", Text),
    Column("expire_le", Text, nullable=False),
    Column("cree_le", Text, nullable=False),
)

# Autorité de remise privée, dépendante de l'intention humaine ; aucun ordonnanceur parallèle.
AGENTS_DECLENCHEURS_REMISES = Table(
    "agents_declencheurs_remises", META,
    Column("intention_id", String(64), ForeignKey("agents_declencheurs_intentions.id"), primary_key=True),
    Column("epoch", Integer, nullable=False),
    Column("capability_hash", String(64), nullable=False),
    Column("declaration_hash", String(64), nullable=False),
    Column("native_expected_revision", Integer),
    Column("native_expected_fingerprint", String(50)),
    Column("native_job_id", String(128)),
    Column("native_config_revision", Integer),
    Column("native_config_fingerprint", String(50)),
    Column("etat", String(16), nullable=False),
    Column("lease_epoch", Integer, nullable=False),
    Column("lease_until", Text, nullable=False),
    Column("lease_seconds", Integer, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    CheckConstraint("epoch > 0 AND lease_epoch > 0", name="agents_cron_remises_epochs"),
    CheckConstraint("length(capability_hash) = 64 AND length(declaration_hash) = 64",
                    name="agents_cron_remises_empreintes"),
    CheckConstraint("attempts BETWEEN 1 AND 3", name="agents_cron_remises_tentatives"),
    CheckConstraint("lease_seconds BETWEEN 1 AND 120", name="agents_cron_remises_lease"),
    CheckConstraint("etat IN ('preparation','remise','revoquee')", name="agents_cron_remises_etat"),
    CheckConstraint("native_expected_revision IS NULL OR native_expected_revision > 0",
                    name="agents_cron_remises_revision_attendue"),
    CheckConstraint("native_expected_revision IS NULL OR native_expected_fingerprint IS NULL",
                    name="agents_cron_remises_revision_attendue_type"),
    CheckConstraint("native_expected_fingerprint IS NULL OR (length(native_expected_fingerprint) = 50 AND "
                    "substr(native_expected_fingerprint, 1, 7) = 'sha256:' AND "
                    "substr(native_expected_fingerprint, 50, 1) IN "
                    "('A','E','I','M','Q','U','Y','c','g','k','o','s','w','0','4','8'))",
                    name="agents_cron_remises_revision_attendue_sha256"),
    CheckConstraint("native_config_revision IS NULL OR native_config_revision > 0",
                    name="agents_cron_remises_revision_native"),
    CheckConstraint("native_config_revision IS NULL OR native_config_fingerprint IS NULL",
                    name="agents_cron_remises_revision_native_type"),
    CheckConstraint("native_config_fingerprint IS NULL OR (length(native_config_fingerprint) = 50 AND "
                    "substr(native_config_fingerprint, 1, 7) = 'sha256:' AND "
                    "substr(native_config_fingerprint, 50, 1) IN "
                    "('A','E','I','M','Q','U','Y','c','g','k','o','s','w','0','4','8'))",
                    name="agents_cron_remises_revision_native_sha256"),
    CheckConstraint("etat != 'remise' OR (native_job_id IS NOT NULL AND "
                    "((native_config_revision IS NOT NULL AND native_config_fingerprint IS NULL) OR "
                    "(native_config_revision IS NULL AND native_config_fingerprint IS NOT NULL)))",
                    name="agents_cron_remises_ack"),
)

# Candidats OCR liés aux lots PDF natifs : stockage et quota indépendants de PDF/AP/CSV.
FUSION_PDF_OCR_RUNS = Table(
    "fusion_pdf_ocr_runs", META,
    Column("ocr_run_id", String(36), primary_key=True),
    Column("pdf_lot_id", String(36), ForeignKey("fusion_pdf_lots.lot_id"), nullable=False),
    Column("acteur", String(64), nullable=False),
    Column("source_sha256", String(64), nullable=False),
    Column("revision_pdf_source", Integer, nullable=False),
    Column("configuration_sha256", String(64), nullable=False),
    Column("profil_id", String(32), nullable=False),
    Column("cle_reference", String(64), nullable=False),
    Column("version_format", Integer, nullable=False),
    Column("revision_run", Integer, nullable=False),
    Column("statut", String(24), nullable=False),
    Column("reserve_octets", Integer, nullable=False),
    Column("resultat_nonce", String(24)),
    Column("resultat_cipher", Text),
    Column("resultat_cipher_octets", Integer, nullable=False),
    Column("code", String(64)),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    UniqueConstraint(
        "pdf_lot_id", "source_sha256", "revision_pdf_source", "configuration_sha256",
        name="uq_fusion_pdf_ocr_runs_source_profil",
    ),
    CheckConstraint("length(ocr_run_id) = 36 AND length(pdf_lot_id) = 36", name="run_ids_taille"),
    CheckConstraint("length(acteur) BETWEEN 1 AND 64", name="acteur_taille"),
    CheckConstraint("length(source_sha256) = 64 AND length(configuration_sha256) = 64", name="empreintes"),
    CheckConstraint("revision_pdf_source BETWEEN 1 AND 2147483647", name="revision_pdf_source_borne"),
    CheckConstraint("length(profil_id) BETWEEN 1 AND 32", name="profil_taille"),
    CheckConstraint("length(cle_reference) BETWEEN 1 AND 64", name="cle_reference_taille"),
    CheckConstraint("version_format = 1", name="version_format"),
    CheckConstraint("revision_run BETWEEN 1 AND 2147483647", name="revision_run_borne"),
    CheckConstraint(
        "statut IN ('RESERVE','A_REVOIR','REFUSE','ERREUR_REPRENABLE','PERIME')", name="statut_valide",
    ),
    CheckConstraint("reserve_octets BETWEEN 0 AND 262160", name="reserve_octets_borne"),
    CheckConstraint("resultat_cipher_octets BETWEEN 0 AND 262160", name="resultat_taille"),
    CheckConstraint("code IS NULL OR length(code) BETWEEN 1 AND 64", name="code_taille"),
    CheckConstraint(
        "(statut = 'RESERVE' AND reserve_octets = 262160 AND resultat_nonce IS NULL "
        "AND resultat_cipher IS NULL AND resultat_cipher_octets = 0 AND code IS NULL) OR "
        "(statut = 'A_REVOIR' AND reserve_octets = 0 AND resultat_nonce IS NOT NULL "
        "AND length(resultat_nonce) = 16 AND resultat_cipher IS NOT NULL "
        "AND resultat_cipher_octets BETWEEN 17 AND 262160 "
        "AND length(resultat_cipher) BETWEEN 24 AND 349548 "
        "AND length(resultat_cipher) = 4 * ((resultat_cipher_octets + 2) / 3) AND code IS NULL) OR "
        "(statut IN ('REFUSE','ERREUR_REPRENABLE','PERIME') AND reserve_octets = 0 "
        "AND resultat_nonce IS NULL AND resultat_cipher IS NULL AND resultat_cipher_octets = 0 "
        "AND code IS NOT NULL AND length(code) BETWEEN 1 AND 64)",
        name="etat_payload_reservation",
    ),
)
Index("ix_fusion_pdf_ocr_runs_cree", FUSION_PDF_OCR_RUNS.c.cree_le)

FUSION_PDF_OCR_COMMANDES = Table(
    "fusion_pdf_ocr_commandes", META,
    Column("acteur", String(64), primary_key=True),
    Column("mutation_id", String(128), primary_key=True),
    Column("empreinte_requete", String(64), nullable=False),
    Column("ocr_run_id", String(36), ForeignKey("fusion_pdf_ocr_runs.ocr_run_id"), nullable=False),
    Column("cree_le", Text, nullable=False),
    CheckConstraint("length(acteur) BETWEEN 1 AND 64", name="acteur_taille"),
    CheckConstraint("length(mutation_id) BETWEEN 1 AND 128", name="mutation_taille"),
    CheckConstraint("length(empreinte_requete) = 64", name="empreinte_taille"),
    CheckConstraint("length(ocr_run_id) = 36", name="run_id_taille"),
)
Index("ix_fusion_pdf_ocr_commandes_run", FUSION_PDF_OCR_COMMANDES.c.ocr_run_id)

FUSION_PDF_OCR_QUOTA = Table(
    "fusion_pdf_ocr_quota", META,
    Column("id", Integer, primary_key=True),
    Column("lots", Integer, nullable=False),
    Column("octets_cipher", Integer, nullable=False),
    CheckConstraint("id = 1", name="singleton"),
    CheckConstraint("lots BETWEEN 0 AND 16", name="lots_borne"),
    CheckConstraint("octets_cipher BETWEEN 0 AND 4194304", name="octets_bornes"),
)

# Originaux reçus par projet : chiffrement externe, aucune référence CAS globale.
PIECES_PROJET = Table(
    "pieces_projet", META,
    Column("piece_id", String(32), primary_key=True),
    Column("lead_id", String(200), nullable=False),
    Column("client_id", String(200), nullable=False),
    Column("auteur", String(200), nullable=False),
    Column("mutation_id", String(32), nullable=False),
    Column("empreinte", String(64), nullable=False),
    Column("source_sha256", String(64), nullable=False),
    Column("type_mime", String(32), nullable=False),
    Column("taille_octets", Integer, nullable=False),
    Column("recu_le", String(40), nullable=False),
    Column("version_format", Integer, nullable=False),
    Column("nonce", String(24), nullable=False),
    Column("chiffre", Text, nullable=False),
    Column("titre_nonce", String(24), nullable=False),
    Column("titre_chiffre", Text, nullable=False),
    UniqueConstraint("auteur", "mutation_id", name="uq_pieces_projet_saisie"),
    CheckConstraint("version_format = 1", name="pieces_format"),
    CheckConstraint("taille_octets > 0 AND taille_octets <= 1048576", name="pieces_taille"),
    CheckConstraint("type_mime IN ('image/jpeg','image/png','application/pdf')", name="pieces_type"),
)
Index("ix_pieces_projet_lead", PIECES_PROJET.c.lead_id, PIECES_PROJET.c.recu_le, PIECES_PROJET.c.piece_id)

# Classement administratif compagnon : l’original et son AAD restent immuables.
PIECES_CLASSEMENTS = Table(
    "pieces_classements", META,
    Column("piece_id", String(32), ForeignKey("pieces_projet.piece_id"), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("lead_id", String(200), nullable=False),
    Column("categorie", String(24), nullable=False),
    Column("avant", String(24), nullable=False),
    Column("motif", String(24), nullable=False),
    Column("auteur", String(200), nullable=False),
    Column("mutation_id", String(32), nullable=False),
    Column("empreinte", String(64), nullable=False),
    Column("source_sha256", String(64), nullable=False),
    Column("horodatage", String(40), nullable=False),
    Column("precedent", String(64), nullable=False),
    Column("chaine", String(64), nullable=False),
    UniqueConstraint("auteur", "mutation_id", name="uq_pieces_classements_saisie"),
    CheckConstraint("revision >= 1 AND revision <= 32", name="classements_revision"),
)

# Originaux courriel privés non rattachés : aucun fait M1 ou projet implicite.
RECEPTIONS_COURRIEL = Table(
    "receptions_courriel", META,
    Column("identite_id", String(64), primary_key=True),
    Column("recu_id", String(32), nullable=False, unique=True),
    Column("source_sha256", String(64), nullable=False),
    Column("taille_octets", Integer, nullable=False),
    Column("version_format", Integer, nullable=False),
    Column("enregistre_le", String(24), nullable=False),
    Column("cle_reference", String(32), nullable=False),
    Column("nonce", LargeBinary, nullable=False),
    Column("chiffre", LargeBinary, nullable=False),
    CheckConstraint("version_format = 1", name="courriel_version"),
    CheckConstraint("taille_octets > 0 AND taille_octets <= 1048576", name="courriel_taille"),
    CheckConstraint("length(nonce) = 12 AND length(chiffre) > 16 AND length(chiffre) <= 1064980",
                    name="courriel_chiffre"),
)

# Private candidate; not a grant, proof or current freshness assertion.
SERVICE_ATTESTATIONS_M4 = Table(
    'service_attestations_m4', META,
    Column('audit_id', Integer, ForeignKey('service_audit.id'), primary_key=True),
    Column('instance_id', String(36), nullable=False),
    Column('evenement_id', String(LONGUEUR_ID_EVENEMENT), nullable=False),
    Column('revision', Integer, nullable=False),
    Column('trace_rang', Integer, nullable=False),
    Column('trace_sha256', String(64), nullable=False),
    Column('source_m4', String(64), nullable=False),
    Column('projection_sha256', String(64), nullable=False),
    Column('version_m4', String(64), nullable=False),
    UniqueConstraint('instance_id', 'trace_rang', name='service_attestation_trace_unique'),
    CheckConstraint('trace_rang >= 0 AND revision > 0', name='service_attestation_bounds'),
)


# Recalcul privé : registres append-only ; pas de politique ni de droit initial.
SERVICE_RECALCUL_INTENTIONS = Table(
    "service_recalcul_intentions",
    META,
    Column("intention_id", String(64), primary_key=True),
    Column("instance_id", String(36), nullable=False),
    Column("acteur", String(256), nullable=False),
    Column("wct_id", String(64), nullable=False),
    Column("devis_id", String(256), nullable=False),
    CheckConstraint(
        "length(intention_id)=64 AND length(wct_id)=64",
        name="recalcul_intention_identifiants",
    ),
)
SERVICE_RECALCUL_ATTESTATIONS = Table(
    "service_recalcul_attestations_v2",
    META,
    Column(
        "intention_id",
        String(64),
        ForeignKey("service_recalcul_intentions.intention_id"),
        primary_key=True,
    ),
    Column(
        "audit_recalcul_id",
        Integer,
        ForeignKey("service_audit.id"),
        nullable=False,
        unique=True,
    ),
    Column(
        "audit_service_id",
        Integer,
        ForeignKey("service_audit.id"),
        nullable=False,
        unique=True,
    ),
    Column("revision_recalcul", Integer, nullable=False),
    Column("revision_service", Integer, nullable=False),
    Column("trace_rang", Integer, nullable=False),
    Column("trace_empreinte", String(64), nullable=False),
    Column("source_m4", String(64), nullable=False),
    Column("projection_m4", String(64), nullable=False),
    Column("wct_hash", String(64), nullable=False),
    Column("version_m4", String(64), nullable=False),
    CheckConstraint(
        "revision_recalcul>0 AND revision_service>0 AND trace_rang>=0",
        name="recalcul_attestation_bornes",
    ),
    CheckConstraint(
        "length(trace_empreinte)=64 AND length(source_m4)=64 AND length(projection_m4)=64 AND length(wct_hash)=64",
        name="recalcul_attestation_hashes",
    ),
)
SERVICE_RECALCUL_RESULTATS = Table(
    "service_recalcul_resultats",
    META,
    Column(
        "intention_id",
        String(64),
        ForeignKey("service_recalcul_intentions.intention_id"),
        primary_key=True,
    ),
    Column("statut", String(32), nullable=False),
    Column("version", String(256)),
    CheckConstraint(
        "statut IN ('publiee','deja_tracee','en_attente_devis_accepte','en_attente_travaux_termines')",
        name="recalcul_resultat_statut",
    ),
)


# File métier privée avant clôture WCT. Aucun droit initial créé.
WCT_ATTENTES = Table(
    "wct_attentes",
    META,
    Column(
        "evenement_id",
        String(LONGUEUR_ID_EVENEMENT),
        ForeignKey("evenements_sortants.evenement_id"),
        primary_key=True,
    ),
    Column("consommateur", String(64), nullable=False),
    Column("instance_id", String(36), nullable=False),
    Column("devis_id", String(128), nullable=False),
    Column("lead_id", String(128), nullable=False),
    Column("recu_sha256", String(64), nullable=False),
    Column("etat", String(16), nullable=False),
    Column("cree_epoch", BigInteger, nullable=False),
    Column("expire_epoch", BigInteger, nullable=False),
    Column("source_m3", String(64)),
    Column("source_m5", String(64)),
    Column("revision_politique", Integer, nullable=False),
    CheckConstraint(
        "etat IN ('attente','prete','terminee','expiree','refusee')",
        name="wct_attente_etat",
    ),
    CheckConstraint(
        "expire_epoch > cree_epoch AND revision_politique > 0",
        name="wct_attente_bornes",
    ),
    Index("ix_wct_attentes_etat_expire", "etat", "expire_epoch"),
    Index("ix_wct_attentes_devis", "etat", "devis_id"),
)
WCT_ATTENTES_AUDIT = Table(
    "wct_attentes_audit",
    META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "evenement_id",
        String(LONGUEUR_ID_EVENEMENT),
        ForeignKey("wct_attentes.evenement_id"),
        nullable=False,
    ),
    Column("action", String(16), nullable=False),
    Column("epoch", BigInteger, nullable=False),
    Column("revision_politique", Integer, nullable=False),
    Column("source_m3", String(64)),
    Column("source_m5", String(64)),
    CheckConstraint(
        "action IN ('attente','prete','terminee','expiree','refusee')",
        name="wct_attente_audit_action",
    ),
)


# Opérateur Core des politiques de service (D1, migration 0036) : chaque octroi, renouvellement ou révocation fait
# par un admin de la console, append-only, lié à la révision de politique qu'il a créée. Aucun octroi initial.
SERVICE_POLITIQUES_JOURNAL = Table(
    "service_politiques_journal",
    META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("instance_id", String(36), nullable=False),
    Column("consommateur", String(128), nullable=False),
    Column("operation", String(64), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("action", String(16), nullable=False),
    Column("acteur", String(256), nullable=False),
    Column("motif", String(500), nullable=False),
    Column("epoch", BigInteger, nullable=False),
    Column("expire_le", BigInteger, nullable=False),
    ForeignKeyConstraint(
        ["instance_id", "consommateur", "operation", "revision"],
        [
            "service_politiques.instance_id",
            "service_politiques.consommateur",
            "service_politiques.operation",
            "service_politiques.revision",
        ],
        name="service_pol_journal_revision_fk",
    ),
    UniqueConstraint("instance_id", "consommateur", "operation", "revision", name="service_pol_journal_revision"),
    CheckConstraint(
        "action IN ('octroi','renouvellement','revocation')",
        name="service_pol_journal_action",
    ),
    CheckConstraint("revision > 0 AND epoch > 0 AND expire_le > 0", name="service_pol_journal_bornes"),
)

# Journal du réconciliateur du coût certifié (E8, mode actif seulement) : une ligne par exécution de l'acteur
# système qui a publié, ou par refus distinct (même intention et même code journalisés une seule fois).
COUT_CERTIFIE_RECONCILIATIONS = Table(
    "cout_certifie_reconciliations",
    META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("instance_id", String(36), nullable=False),
    Column("acteur", String(256), nullable=False),
    Column("wct_id", String(64), nullable=False),
    Column("devis_id", String(256), nullable=False),
    Column("intention_id", String(64), nullable=False),
    Column("statut", String(16), nullable=False),
    Column("code", String(64)),
    Column("epoch", BigInteger, nullable=False),
    CheckConstraint(
        "statut IN ('publiee','deja_executee','rien_a_faire','refus')",
        name="cout_certifie_reconciliation_statut",
    ),
    CheckConstraint(
        "length(wct_id)=64 AND length(intention_id)=64 AND epoch > 0",
        name="cout_certifie_reconciliation_bornes",
    ),
    Index("ix_cout_certifie_reconciliations_intention", "intention_id", "statut"),
)

# -- Plateforme : registre de fournisseurs et coffre de secrets (migration 0037) ---------------------
# Profil de licence du client (singleton) confronté au bloc licence de chaque fournisseur.
FOURNISSEURS_PROFIL = Table(
    "fournisseurs_profil", META,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("usage_commercial", Boolean, nullable=False),
    Column("revenu_annuel_usd", BigInteger, nullable=True),
    Column("territoires", Text, nullable=False),
    Column("heberge_pour_tiers", Boolean, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(64), nullable=False),
    CheckConstraint("id = 1", name="singleton"),
    CheckConstraint("revenu_annuel_usd IS NULL OR revenu_annuel_usd >= 0", name="revenu_positif"),
    CheckConstraint("revision > 0", name="revision_positive"),
)
# Définition figée (JSON canonique, sans aucune valeur de secret) d'un fournisseur configuré.
FOURNISSEURS_CONFIGURATIONS = Table(
    "fournisseurs_configurations", META,
    Column("identifiant", String(80), primary_key=True),
    Column("capacite", String(24), nullable=False),
    Column("definition", Text, nullable=False),
    Column("actif", Boolean, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("dernier_test", Text, nullable=True),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(64), nullable=False),
    CheckConstraint(
        "capacite IN ('llm','embeddings','reranker','ocr','stt','tts','avatar','image','video','recherche_web',"
        "'courriel','vision')",
        name="capacite_valide",
    ),
    CheckConstraint("revision > 0", name="revision_positive"),
)
# Sélection par capacité : portée '*' = défaut global, sinon code de département (m07-marketing…).
FOURNISSEURS_SELECTIONS = Table(
    "fournisseurs_selections", META,
    Column("capacite", String(24), primary_key=True),
    Column("portee", String(64), primary_key=True),
    Column("identifiant", String(80), ForeignKey("fournisseurs_configurations.identifiant"), nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(64), nullable=False),
)
# Coffre : métadonnées seulement ; la valeur n'existe que chiffrée dans coffre_versions.
COFFRE_SECRETS = Table(
    "coffre_secrets", META,
    Column("nom", String(80), primary_key=True),
    Column("service", String(32), nullable=False),
    Column("etat", String(16), nullable=False),
    Column("version_active", Integer, nullable=True),
    Column("cree_le", Text, nullable=False),
    Column("cree_par", String(64), nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(64), nullable=False),
    Column("revoque_le", Text, nullable=True),
    Column("revoque_par", String(64), nullable=True),
    CheckConstraint("etat IN ('actif','revoque')", name="etat_valide"),
    CheckConstraint(
        "(etat = 'actif' AND version_active IS NOT NULL AND revoque_le IS NULL) OR "
        "(etat = 'revoque' AND version_active IS NULL AND revoque_le IS NOT NULL)",
        name="etat_coherent",
    ),
)
# Chiffrement d'enveloppe AES-256-GCM : clé de donnée par version, enveloppée par la clé maîtresse
# (hors base). Une version remplacée ou révoquée perd immédiatement ses octets chiffrés.
COFFRE_VERSIONS = Table(
    "coffre_versions", META,
    Column("nom", String(80), ForeignKey("coffre_secrets.nom"), primary_key=True),
    Column("version", Integer, primary_key=True, autoincrement=False),
    Column("etat", String(16), nullable=False),
    Column("algorithme", String(40), nullable=False),
    Column("empreinte_cle_maitresse", String(32), nullable=True),
    Column("nonce_cle", LargeBinary, nullable=True),
    Column("cle_enveloppee", LargeBinary, nullable=True),
    Column("nonce_valeur", LargeBinary, nullable=True),
    Column("valeur_chiffree", LargeBinary, nullable=True),
    Column("cree_le", Text, nullable=False),
    Column("purge_le", Text, nullable=True),
    CheckConstraint("etat IN ('active','remplacee','revoquee')", name="etat_valide"),
    CheckConstraint("version > 0", name="version_positive"),
    CheckConstraint(
        "(etat = 'active' AND valeur_chiffree IS NOT NULL AND cle_enveloppee IS NOT NULL AND nonce_cle IS NOT NULL "
        "AND nonce_valeur IS NOT NULL AND empreinte_cle_maitresse IS NOT NULL AND purge_le IS NULL) OR "
        "(etat <> 'active' AND valeur_chiffree IS NULL AND cle_enveloppee IS NULL AND nonce_cle IS NULL "
        "AND nonce_valeur IS NULL AND purge_le IS NOT NULL)",
        name="octets_selon_etat",
    ),
)
# Jetons opaques remis aux agents : seule l'empreinte SHA-256 est conservée, liée à un porteur et un usage.
COFFRE_JETONS = Table(
    "coffre_jetons", META,
    Column("empreinte", String(64), primary_key=True),
    Column("nom", String(80), ForeignKey("coffre_secrets.nom"), nullable=False),
    Column("porteur", String(80), nullable=False),
    Column("usage", String(120), nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("cree_par", String(64), nullable=False),
    Column("expire_epoch", BigInteger, nullable=False),
    Column("revoque", Boolean, nullable=False),
    Index("ix_coffre_jetons_nom", "nom"),
)
# Journal d'accès append-only (déclencheurs de la migration 0036) : jamais de valeur ni de jeton.
COFFRE_ACCES = Table(
    "coffre_acces", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quand", Text, nullable=False),
    Column("nom", String(80), nullable=False),
    Column("action", String(32), nullable=False),
    Column("acteur", String(80), nullable=False),
    Column("usage", String(120), nullable=True),
    Column("resultat", String(8), nullable=False),
    Column("code", String(48), nullable=True),
    CheckConstraint("resultat IN ('ok','refus')", name="resultat_valide"),
    Index("ix_coffre_acces_nom", "nom", "id"),
)

# -- Ingestion d'onboarding : lots, documents, tâches durables, journal, brouillons (migration 0038) ---------------
# Phase SQLite de la table de tâches (FEUILLE-DE-ROUTE r1, « Orchestration d'ingestion ») ; l'interface
# `opsys.ingestion_onboarding.taches.PortTaches` est celle qu'un adaptateur DBOS sur PostgreSQL reprendra.
# Les contenus (originaux, résultats d'étape, champs des brouillons) ne sont stockés que CHIFFRÉS (AES-GCM, clé
# externe `OPSYS_INGESTION_CLE` du pilote Fusion) ; les colonnes en clair ne portent que des métadonnées.
INGESTION_LOTS = Table(
    "ingestion_lots", META,
    Column("lot_id", String(32), primary_key=True),
    Column("acteur", String(200), nullable=False),
    Column("mutation_id", String(64), nullable=False),
    Column("nom_source", String(128), nullable=False),
    Column("source_sha256", String(64), nullable=False),
    Column("type_source", String(8), nullable=False),
    Column("statut", String(16), nullable=False),
    Column("nb_documents", Integer, nullable=False),
    Column("octets", BigInteger, nullable=False),
    Column("cle_reference", String(64), nullable=False),
    Column("version_format", Integer, nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    UniqueConstraint("acteur", "mutation_id", name="uq_ingestion_lots_mutation"),
    CheckConstraint("statut IN ('EN_COURS','TERMINE')", name="statut_valide"),
    CheckConstraint("nb_documents >= 0 AND octets >= 0 AND version_format = 1", name="bornes"),
)
INGESTION_DOCUMENTS = Table(
    "ingestion_documents", META,
    Column("document_id", String(32), primary_key=True),
    Column("lot_id", String(32), ForeignKey("ingestion_lots.lot_id"), nullable=False),
    Column("rang", Integer, nullable=False),
    Column("nom", String(255), nullable=False),
    Column("taille", BigInteger, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("type_detecte", String(8), nullable=True),
    Column("classe", String(24), nullable=True),
    Column("statut", String(16), nullable=False),
    Column("code", String(64), nullable=True),
    Column("doublon_de", String(32), nullable=True),
    Column("nonce", Text, nullable=True),
    Column("chiffre", Text, nullable=True),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    UniqueConstraint("lot_id", "rang", name="uq_ingestion_documents_rang"),
    CheckConstraint(
        "statut IN ('EN_ATTENTE','EN_COURS','TERMINE','A_VERIFIER','NON_TRAITE','REFUSE','DOUBLON')",
        name="statut_valide",
    ),
    CheckConstraint(
        "(chiffre IS NULL AND nonce IS NULL) OR (chiffre IS NOT NULL AND nonce IS NOT NULL)", name="chiffre_complet"
    ),
    CheckConstraint("statut <> 'DOUBLON' OR (doublon_de IS NOT NULL AND chiffre IS NULL)", name="doublon_sans_copie"),
    # Dédoublonnage exact : un seul ORIGINAL conservé par empreinte, toutes les copies pointent vers lui.
    Index("uq_ingestion_documents_original", "sha256", unique=True,
          sqlite_where=text("chiffre IS NOT NULL"), postgresql_where=text("chiffre IS NOT NULL")),
    Index("ix_ingestion_documents_lot", "lot_id", "rang"),
)
INGESTION_TACHES = Table(
    "ingestion_taches", META,
    Column("tache_id", String(32), primary_key=True),
    Column("document_id", String(32), ForeignKey("ingestion_documents.document_id"), nullable=False),
    Column("lot_id", String(32), ForeignKey("ingestion_lots.lot_id"), nullable=False),
    Column("etape", String(16), nullable=False),
    Column("rang_etape", Integer, nullable=False),
    Column("statut", String(20), nullable=False),
    Column("tentatives", Integer, nullable=False),
    Column("porteur", String(64), nullable=True),
    Column("bail_expire", BigInteger, nullable=True),
    Column("disponible_des", BigInteger, nullable=False),
    Column("code", String(64), nullable=True),
    Column("nonce", Text, nullable=True),
    Column("chiffre", Text, nullable=True),
    Column("empreinte_resultat", String(64), nullable=True),
    Column("revision", Integer, nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    # La clé d'idempotence d'une tâche : (document, étape). Une reprise ne crée jamais une seconde tâche.
    UniqueConstraint("document_id", "etape", name="uq_ingestion_taches_etape"),
    CheckConstraint(
        "statut IN ('EN_ATTENTE','BAIL','TERMINEE','SAUTEE','ECHEC_REPRENABLE','FILE_MORTE')", name="statut_valide"
    ),
    CheckConstraint("(statut = 'BAIL') = (porteur IS NOT NULL AND bail_expire IS NOT NULL)", name="bail_coherent"),
    CheckConstraint("tentatives >= 0 AND revision >= 1 AND rang_etape BETWEEN 1 AND 7", name="bornes"),
    Index("ix_ingestion_taches_lot", "lot_id", "statut"),
)
# Journal du pipeline, append-only (déclencheurs de la migration 0038) : identifiants, étapes, codes, compteurs ;
# jamais un contenu, un montant ni un nom de client.
INGESTION_JOURNAL = Table(
    "ingestion_journal", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quand", Text, nullable=False),
    Column("lot_id", String(32), nullable=False),
    Column("document_id", String(32), nullable=True),
    Column("tache_id", String(32), nullable=True),
    Column("acteur", String(200), nullable=False),
    Column("evenement", String(48), nullable=False),
    Column("code", String(64), nullable=True),
    Column("details", Text, nullable=False),
    Index("ix_ingestion_journal_lot", "lot_id", "id"),
)
INGESTION_BROUILLONS = Table(
    "ingestion_brouillons", META,
    Column("brouillon_id", String(32), primary_key=True),
    Column("lot_id", String(32), ForeignKey("ingestion_lots.lot_id"), nullable=False),
    Column("document_id", String(32), ForeignKey("ingestion_documents.document_id"), nullable=False),
    Column("genre", String(32), nullable=False),
    Column("cle_metier", String(64), nullable=False),
    Column("statut", String(16), nullable=False),
    Column("raisons", Text, nullable=False),
    Column("cles", Text, nullable=False),
    Column("nonce", Text, nullable=False),
    Column("chiffre", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("decision", Text, nullable=True),
    Column("reference_definitive", String(64), nullable=True),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    UniqueConstraint("genre", "cle_metier", name="uq_ingestion_brouillons_cle"),
    CheckConstraint("genre IN ('ap_facture_fournisseur','crm_client','courriel_contact')", name="genre_valide"),
    CheckConstraint("statut IN ('PRET','A_VERIFIER','VALIDE','ECARTE')", name="statut_valide"),
    CheckConstraint("(statut IN ('VALIDE','ECARTE')) = (decision IS NOT NULL)", name="decision_humaine"),
    CheckConstraint("statut <> 'VALIDE' OR reference_definitive IS NOT NULL", name="reference_si_valide"),
    CheckConstraint("revision >= 1", name="revision_positive"),
    Index("ix_ingestion_brouillons_lot", "lot_id", "genre", "statut"),
)

# -- Voix et visages des avatars : registre par client, consentements, qualifications, canaux (migration 0039) ---
# Un avatar garde ses identifiants LOGIQUES (`voix.lea.defaut`, `visage.lea.defaut` : manifeste ou profil) ;
# ces tables disent ce que le client a réellement derrière : quel fournisseur (registre de fournisseurs, 0037), quel
# manifeste figé (empreinte), quel consentement du locuteur, quelle qualification EXÉCUTÉE. Aucune donnée vocale n'est
# stockée ici : seulement des références (contrat, empreinte SHA-256 du document) et des métadonnées.
AVATARS_ENTREES = Table(
    "avatars_entrees", META,
    Column("identifiant", String(64), primary_key=True),
    Column("genre", String(8), nullable=False),
    # NULL tant que l'entrée est « prevu » : aucun runtime n'est lié. La clé étrangère impose un fournisseur CONFIGURÉ.
    Column("fournisseur_id", String(80), ForeignKey("fournisseurs_configurations.identifiant"), nullable=True),
    Column("langue", String(8), nullable=False),
    Column("accent", String(40), nullable=True),
    Column("origine", String(16), nullable=False),
    Column("actif_usage_commercial", String(16), nullable=True),
    Column("empreinte_vocale_tiers", Boolean, nullable=False),
    Column("declaration_biometrie", Text, nullable=True),
    Column("manifeste", Text, nullable=False),
    Column("empreinte_manifeste", String(64), nullable=False),
    Column("etat", String(12), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(64), nullable=False),
    CheckConstraint("genre IN ('voix','visage')", name="genre_valide"),
    CheckConstraint("etat IN ('prevu','configure','qualifie')", name="etat_valide"),
    CheckConstraint("(etat = 'prevu') = (fournisseur_id IS NULL)", name="etat_runtime_coherent"),
    CheckConstraint("origine IN ('generique','clonee','ressemblance')", name="origine_valide"),
    CheckConstraint("(genre = 'voix' AND origine <> 'ressemblance') OR (genre = 'visage' AND origine <> 'clonee')",
                    name="origine_du_genre"),
    CheckConstraint("length(empreinte_manifeste) = 64 AND revision > 0", name="bornes"),
)
# Consentement ÉCRIT d'un locuteur (voix) ou d'une personne dont la ressemblance sert de visage. Révocable une fois,
# jamais modifiable ni supprimable (déclencheurs de la migration 0039). Le document signé reste hors de la base :
# on garde sa référence et son empreinte.
AVATARS_CONSENTEMENTS = Table(
    "avatars_consentements", META,
    Column("consentement_id", String(32), primary_key=True),
    Column("identifiant", String(64), ForeignKey("avatars_entrees.identifiant"), nullable=False),
    Column("locuteur_ref", String(64), nullable=False),
    Column("portee", Text, nullable=False),
    Column("forme", String(8), nullable=False),
    Column("document_ref", String(200), nullable=False),
    Column("document_sha256", String(64), nullable=False),
    Column("signe_le", String(10), nullable=False),
    Column("expire_le", String(10), nullable=True),
    Column("enregistre_le", Text, nullable=False),
    Column("enregistre_par", String(64), nullable=False),
    Column("revoque_le", Text, nullable=True),
    Column("revoque_par", String(64), nullable=True),
    Column("revoque_motif", String(200), nullable=True),
    CheckConstraint("forme = 'ecrit'", name="forme_ecrite"),
    CheckConstraint("length(document_sha256) = 64", name="empreinte_document"),
    CheckConstraint("(revoque_le IS NULL) = (revoque_par IS NULL)", name="revocation_coherente"),
    CheckConstraint("expire_le IS NULL OR expire_le > signe_le", name="expiration_apres_signature"),
    Index("ix_avatars_consentements_entree", "identifiant", "revoque_le"),
)
# Journal des tests de connexion/qualification EXÉCUTÉS, append-only. Lié à l'empreinte du runtime testé : une
# modification du fournisseur (modèle, point d'accès, licence) rend la qualification périmée. `nature` = « reel » pour
# une sonde réelle du serveur ; « double » pour un double de test (jamais qualifiant).
AVATARS_QUALIFICATIONS = Table(
    "avatars_qualifications", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quand", Text, nullable=False),
    Column("acteur", String(64), nullable=False),
    Column("fournisseur_id", String(80), ForeignKey("fournisseurs_configurations.identifiant"), nullable=False),
    Column("empreinte_runtime", String(64), nullable=False),
    Column("nature", String(8), nullable=False),
    Column("statut", String(20), nullable=False),
    Column("detail", String(200), nullable=False),
    Column("latence_ms", Integer, nullable=True),
    CheckConstraint("nature IN ('reel','double')", name="nature_valide"),
    CheckConstraint(
        "statut IN ('succes','echec','delai','non_verifiable','refuse_politique')", name="statut_valide"),
    CheckConstraint("length(empreinte_runtime) = 64", name="empreinte_runtime_valide"),
    Index("ix_avatars_qualifications_runtime", "fournisseur_id", "empreinte_runtime", "id"),
)
# Canal déclaré « disponible » pour un département : décision d'un administrateur, avec les preuves qui l'ont permise.
# L'état EFFECTIF est recalculé à chaque lecture (consentement révoqué => « suspendu ») ; cette ligne n'est jamais
# une preuve suffisante à elle seule.
AVATARS_CANAUX = Table(
    "avatars_canaux", META,
    Column("departement", String(64), primary_key=True),
    Column("canal", String(16), primary_key=True),
    Column("etat", String(10), nullable=False),
    Column("preuves", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(64), nullable=False),
    CheckConstraint("canal IN ('voix','audiovisuel')", name="canal_valide"),
    CheckConstraint("etat IN ('disponible','retire')", name="etat_valide"),
    CheckConstraint("revision > 0", name="revision_positive"),
)
# -- Connecteurs courriel : comptes, états OAuth, idempotence, brouillons sortants, journal (migration 0040) ---------
# Aucun secret ici : les jetons OAuth et mots de passe d'application ne vivent que dans le coffre (`coffre_*`), la base
# ne garde le NOM du secret. Aucun contenu de courriel en clair : les brouillons sortants sont scellés (AES-GCM, clé
# externe d'ingestion) ; les messages lus ne laissent qu'une clé d'idempotence et une empreinte.
COURRIEL_COMPTES = Table(
    "courriel_comptes", META,
    Column("compte_id", String(64), primary_key=True),
    Column("fournisseur", String(8), nullable=False),
    Column("adresse", String(254), nullable=False),
    Column("etat", String(24), nullable=False),
    Column("usage", String(16), nullable=False),
    Column("secret_nom", String(80), nullable=True),
    Column("generation", Integer, nullable=False),
    Column("portees", Text, nullable=False),
    Column("configuration", Text, nullable=False),
    Column("finalite", Text, nullable=False),
    Column("retention_jours", Integer, nullable=False),
    Column("consentement_le", Text, nullable=True),
    Column("consentement_par", String(200), nullable=True),
    Column("dossiers_suivis", Text, nullable=False),
    Column("curseurs", Text, nullable=False),
    Column("derniere_synchro_le", Text, nullable=True),
    Column("derniere_synchro_statut", String(16), nullable=True),
    Column("derniere_erreur_code", String(64), nullable=True),
    Column("derniere_erreur_le", Text, nullable=True),
    Column("messages_total", Integer, nullable=False),
    Column("connecte_par", String(200), nullable=True),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    CheckConstraint("fournisseur IN ('gmail','graph','imap','mbox')", name="fournisseur_valide"),
    CheckConstraint(
        "etat IN ('non_connecte','autorisation_en_cours','connecte','reconnexion_requise','revoque','erreur')",
        name="etat_valide",
    ),
    CheckConstraint("usage IN ('lecture','lecture_envoi')", name="usage_valide"),
    CheckConstraint("etat <> 'connecte' OR (consentement_le IS NOT NULL AND "
                    "(secret_nom IS NOT NULL OR fournisseur = 'mbox'))", name="connecte_complet"),
    CheckConstraint("generation >= 0 AND messages_total >= 0 AND revision >= 1 AND retention_jours BETWEEN 1 AND 3650",
                    name="bornes"),
)
COURRIEL_ETATS_OAUTH = Table(
    "courriel_etats_oauth", META,
    Column("nonce", String(64), primary_key=True),
    Column("compte_id", String(64), nullable=False),
    Column("fournisseur", String(8), nullable=False),
    Column("usage", String(16), nullable=False),
    Column("expire_epoch", BigInteger, nullable=False),
    Column("utilise_epoch", BigInteger, nullable=True),
    Column("cree_epoch", BigInteger, nullable=False),
    Index("ix_courriel_etats_oauth_compte", "compte_id"),
)
COURRIEL_MESSAGES = Table(
    "courriel_messages", META,
    Column("compte_id", String(64), ForeignKey("courriel_comptes.compte_id"), primary_key=True),
    Column("cle_message", String(64), primary_key=True),
    Column("empreinte", String(64), primary_key=True),
    Column("statut", String(12), nullable=False),
    Column("lot_id", String(32), nullable=True),
    Column("nb_pieces", Integer, nullable=False),
    Column("nb_pieces_transmises", Integer, nullable=False),
    Column("vu_le", Text, nullable=False),
    CheckConstraint("statut IN ('INGERE','SANS_PIECE','REFUSE')", name="statut_valide"),
    CheckConstraint("nb_pieces >= 0 AND nb_pieces_transmises >= 0 AND nb_pieces_transmises <= nb_pieces",
                    name="bornes"),
)
# Références de fournisseur déjà traitées (tout résultat : ingéré, doublon, refusé) : une page interrompue par le
# quota de débit n'oblige pas à relire ni à re-télécharger ses messages déjà faits. Le contrôle d'autorité reste
# `courriel_messages`.
COURRIEL_REFS = Table(
    "courriel_refs", META,
    Column("compte_id", String(64), ForeignKey("courriel_comptes.compte_id"), primary_key=True),
    Column("ref_cle", String(64), primary_key=True),
    Column("vu_le", Text, nullable=False),
)
COURRIEL_BROUILLONS = Table(
    "courriel_brouillons", META,
    Column("brouillon_id", String(32), primary_key=True),
    Column("compte_id", String(64), ForeignKey("courriel_comptes.compte_id"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("statut", String(16), nullable=False),
    Column("empreinte", String(64), nullable=False),
    Column("cle_reference", String(64), nullable=False),
    Column("nonce", Text, nullable=False),
    Column("chiffre", Text, nullable=False),
    Column("demande_id", String(32), nullable=True),
    Column("approuve_par", String(200), nullable=True),
    Column("cree_par", String(200), nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("termine_le", Text, nullable=True),
    Column("code", String(64), nullable=True),
    UniqueConstraint("demande_id", name="uq_courriel_brouillons_demande"),
    CheckConstraint(
        "statut IN ('BROUILLON','DEMANDE','APPROUVE','ENVOI_RESERVE','ENVOYE','ECHEC','INCERTAIN','REFUSE')",
        name="statut_valide",
    ),
    CheckConstraint("revision >= 1", name="revision_positive"),
    CheckConstraint("statut = 'BROUILLON' OR demande_id IS NOT NULL", name="demande_si_avance"),
    CheckConstraint("statut NOT IN ('APPROUVE','ENVOI_RESERVE','ENVOYE') OR approuve_par IS NOT NULL",
                    name="approbateur_si_approuve"),
    Index("ix_courriel_brouillons_compte", "compte_id", "statut"),
)
# Journal append-only (déclencheurs de la migration 0040) : identifiants, codes, compteurs ; jamais un contenu de
# courriel, une adresse de correspondant, un jeton ni un secret.
COURRIEL_JOURNAL = Table(
    "courriel_journal", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quand", Text, nullable=False),
    Column("compte_id", String(64), nullable=False),
    Column("evenement", String(48), nullable=False),
    Column("code", String(64), nullable=True),
    Column("acteur", String(200), nullable=False),
    Column("details", Text, nullable=False),
    Index("ix_courriel_journal_compte", "compte_id", "id"),
)

# -- Bases de connaissances par département (migration 0041, docs/architecture/CONNAISSANCES.md) ----------------------
# Une base par département ; des SOURCES (suite de versions) ; des VERSIONS immuables (texte, empreinte, provenance
# complète) dont l'état n'est jamais un champ modifiable : c'est le dernier événement de `connaissances_etats`
# (append-only). Des FRAGMENTS immuables avec leur emplacement (page, section, décalages) ; un index lexical FTS5
# (SQLite seulement, créé par la migration) ; des ESPACES vectoriels (un par fournisseur d'embeddings ET empreinte de sa
# configuration) et des VECTEURS rattachés à un espace. Tout est append-only (déclencheurs de la migration 0041) sauf la
# ligne de `connaissances_bases`, qui ne porte que l'espace vectoriel actif.
CONNAISSANCES_BASES = Table(
    "connaissances_bases", META,
    Column("departement", String(64), primary_key=True),
    Column("cree_le", Text, nullable=False),
    Column("cree_par", String(200), nullable=False),
    Column("espace_actif", String(64), ForeignKey("connaissances_espaces.espace_id"), nullable=True),
    Column("modifie_le", Text, nullable=False),
)
CONNAISSANCES_ESPACES = Table(
    "connaissances_espaces", META,
    Column("espace_id", String(64), primary_key=True),
    Column("fournisseur_id", String(80), nullable=False),
    Column("modele", String(200), nullable=False),
    Column("dimension", Integer, nullable=False),
    Column("config_sha256", String(64), nullable=False),
    Column("profil", Text, nullable=False),
    Column("cree_le", Text, nullable=False),
    CheckConstraint("dimension BETWEEN 2 AND 8192", name="dimension_valide"),
)
CONNAISSANCES_SOURCES = Table(
    "connaissances_sources", META,
    Column("source_id", String(32), primary_key=True),
    Column("departement", String(64), ForeignKey("connaissances_bases.departement"), nullable=False),
    Column("cle", String(96), nullable=False),
    Column("titre", String(300), nullable=False),
    Column("domaine", String(16), nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("cree_par", String(200), nullable=False),
    UniqueConstraint("departement", "cle", name="uq_connaissances_sources_cle"),
    CheckConstraint("domaine IN ('comptabilite','fiscalite','juridique','investissement','technique','general')",
                    name="domaine_valide"),
)
CONNAISSANCES_VERSIONS = Table(
    "connaissances_versions", META,
    Column("version_id", String(32), primary_key=True),
    Column("source_id", String(32), ForeignKey("connaissances_sources.source_id"), nullable=False),
    Column("numero", Integer, nullable=False),
    Column("type_source", String(8), nullable=False),
    Column("editeur", String(200), nullable=False),
    Column("type_autorite", String(10), nullable=False),
    Column("reference", String(500), nullable=False),
    Column("date_publication", String(10), nullable=True),
    Column("date_consultation", String(10), nullable=False),
    Column("licence_reutilisation", String(24), nullable=False),
    Column("expire_le", String(10), nullable=True),
    Column("revision_due_le", String(10), nullable=True),
    Column("sha256", String(64), nullable=False),
    Column("sha256_octets", String(64), nullable=False),
    Column("empreinte_meta", String(64), nullable=False),
    Column("texte", Text, nullable=False),
    Column("nb_pages", Integer, nullable=False),
    Column("nb_fragments", Integer, nullable=False),
    Column("suspect", Boolean, nullable=False),
    Column("signaux", Text, nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("cree_par", String(200), nullable=False),
    UniqueConstraint("source_id", "numero", name="uq_connaissances_versions_numero"),
    CheckConstraint("numero >= 1 AND nb_pages >= 1 AND nb_fragments >= 0", name="bornes"),
    CheckConstraint("type_source IN ('texte','markdown','html','pdf')", name="type_valide"),
    CheckConstraint("type_autorite IN ('officielle','reconnue','interne','tierce','fictive')", name="autorite_valide"),
    CheckConstraint(
        "licence_reutilisation IN ('domaine_public','licence_ouverte','permission_ecrite','interne',"
        "'droit_auteur_reserve','inconnue')", name="licence_valide"),
    Index("ix_connaissances_versions_source", "source_id", "numero"),
)
CONNAISSANCES_ETATS = Table(
    "connaissances_etats", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("version_id", String(32), ForeignKey("connaissances_versions.version_id"), nullable=False),
    Column("etat", String(10), nullable=False),
    Column("par", String(200), nullable=False),
    Column("mode", String(8), nullable=False),
    Column("role", String(32), nullable=True),
    Column("raison", Text, nullable=True),
    Column("controles", Text, nullable=True),
    Column("quand", Text, nullable=False),
    CheckConstraint("etat IN ('brouillon','revu','publie','retire')", name="etat_valide"),
    CheckConstraint("mode IN ('humain','agent','systeme')", name="mode_valide"),
    CheckConstraint("etat <> 'retire' OR (raison IS NOT NULL AND length(raison) >= 10)", name="retrait_motive"),
    CheckConstraint("mode <> 'humain' OR role IS NOT NULL", name="humain_avec_role"),
    Index("ix_connaissances_etats_version", "version_id", "id"),
)
CONNAISSANCES_FRAGMENTS = Table(
    "connaissances_fragments", META,
    Column("chunk_id", String(32), primary_key=True),
    Column("version_id", String(32), ForeignKey("connaissances_versions.version_id"), nullable=False),
    Column("rang", Integer, nullable=False),
    Column("texte", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("page", Integer, nullable=False),
    Column("section", Text, nullable=True),
    Column("debut", Integer, nullable=False),
    Column("fin", Integer, nullable=False),
    UniqueConstraint("version_id", "rang", name="uq_connaissances_fragments_rang"),
    CheckConstraint("rang >= 0 AND page >= 1 AND debut >= 0 AND fin > debut", name="bornes"),
    Index("ix_connaissances_fragments_version", "version_id", "rang"),
)
CONNAISSANCES_VECTEURS = Table(
    "connaissances_vecteurs", META,
    Column("chunk_id", String(32), ForeignKey("connaissances_fragments.chunk_id"), primary_key=True),
    Column("espace_id", String(64), ForeignKey("connaissances_espaces.espace_id"), primary_key=True),
    Column("dimension", Integer, nullable=False),
    Column("vecteur", LargeBinary, nullable=False),
    CheckConstraint("dimension BETWEEN 2 AND 8192 AND length(vecteur) = dimension * 4", name="taille_coherente"),
)
CONNAISSANCES_INDEXATIONS = Table(
    "connaissances_indexations", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quand", Text, nullable=False),
    Column("departement", String(64), nullable=False),
    Column("version_id", String(32), nullable=True),
    Column("genre", String(10), nullable=False),
    Column("espace_id", String(64), nullable=True),
    Column("nb_fragments", Integer, nullable=False),
    Column("par", String(200), nullable=False),
    CheckConstraint("genre IN ('lexical','vectoriel','bascule')", name="genre_valide"),
    CheckConstraint("nb_fragments >= 0", name="bornes"),
    Index("ix_connaissances_indexations_base", "departement", "id"),
)

# -- Planificateur des connecteurs : exécuteurs durables, baux, journal (migration 0044)
# ---------------------------------
# Un exécuteur (synchronisation courriel, envoi approuvé, publication WordPress ou sociale) ne tourne que si un
# admin l'a
# ACTIVÉ depuis la console (mode `ombre` ou `actif`, expiration, motif) ; l'absence de ligne vaut `inactif`. Le bail
# garantit un seul exécuteur à la fois par ressource (compte courriel, site, compte social), avec un jeton de
# fencing croissant. Le journal est append-only (déclencheurs) : identifiants, codes, compteurs ; jamais un contenu de
# courriel, un jeton ni un secret.
PLANIFICATEUR_EXECUTEURS = Table(
    "planificateur_executeurs", META,
    Column("executeur", String(40), primary_key=True),
    Column("mode", String(8), nullable=False),
    Column("intervalle_s", Integer, nullable=False),
    Column("expire_le", BigInteger, nullable=True),
    Column("prochain_passage", BigInteger, nullable=False),
    Column("dernier_passage", BigInteger, nullable=True),
    Column("dernier_statut", String(24), nullable=True),
    Column("dernier_code", String(64), nullable=True),
    Column("revision", Integer, nullable=False),
    Column("modifie_par", String(200), nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("motif", Text, nullable=False),
    CheckConstraint("mode IN ('inactif','ombre','actif')", name="mode_valide"),
    CheckConstraint("intervalle_s BETWEEN 15 AND 86400 AND revision >= 1", name="bornes"),
    CheckConstraint("mode = 'inactif' OR expire_le IS NOT NULL", name="expiration_si_actif"),
)
PLANIFICATEUR_BAUX = Table(
    "planificateur_baux", META,
    Column("ressource", String(160), primary_key=True),
    Column("porteur", String(80), nullable=False),
    Column("jeton", BigInteger, nullable=False),
    Column("acquis_epoch", BigInteger, nullable=False),
    Column("expire_epoch", BigInteger, nullable=False),
    CheckConstraint("jeton >= 1 AND expire_epoch >= acquis_epoch", name="bornes"),
)
PLANIFICATEUR_JOURNAL = Table(
    "planificateur_journal", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quand", Text, nullable=False),
    Column("executeur", String(40), nullable=False),
    Column("ressource", String(160), nullable=True),
    Column("evenement", String(32), nullable=False),
    Column("mode", String(8), nullable=True),
    Column("statut", String(24), nullable=True),
    Column("code", String(64), nullable=True),
    Column("acteur", String(200), nullable=False),
    Column("details", Text, nullable=False),
    Index("ix_planificateur_journal_executeur", "executeur", "id"),
)

# -- Planification autonome : approbations de première activation d'un exécuteur IRRÉVERSIBLE, échéances de rétention
# (migration 0055, docs/architecture/PLANIFICATION.md) ----------------------------------------------------------------
# `planificateur_approbations` (append-only) : la décision d'un admin humain, depuis la console, d'activer un exécuteur
# dont l'effet est irréversible (purge de rétention) APRÈS avoir vu l'aperçu à blanc de ce qui sera purgé. Elle porte
# l'empreinte de CET aperçu, la révision de l'exécuteur qu'elle autorise et une expiration (90 jours). Sans ligne
# valide,
# l'exécuteur n'exécute pas, quel que soit son mode.
PLANIFICATEUR_APPROBATIONS = Table(
    "planificateur_approbations", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("executeur", String(40), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("apercu_empreinte", String(64), nullable=False),
    Column("nb_elements", Integer, nullable=False),
    Column("approuve_par", String(200), nullable=False),
    Column("approuve_le", Text, nullable=False),
    Column("expire_le", BigInteger, nullable=False),
    CheckConstraint("revision >= 1 AND nb_elements >= 0", name="bornes"),
    Index("ix_planificateur_approbations_executeur", "executeur", "id"),
)
# `retention_echeances` : l'index des clés détruisibles à échéance (enregistrement vocal, adresse d'un courriel reçu
# par M1). `ref` est un pseudonyme (jamais une adresse ni un contenu) ; la ligne est le seul état mutable (en_attente
# -> purgee) ; la clé elle-même vit dans `cles_chiffrement` et sa destruction passe par `effacements_cles`.
RETENTION_ECHEANCES = Table(
    "retention_echeances", META,
    Column("domaine", String(32), primary_key=True),
    Column("ref", String(160), primary_key=True),
    Column("portee", String(128), nullable=False),
    Column("identifiant", String(128), nullable=False),
    Column("echeance_epoch", BigInteger, nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("statut", String(12), nullable=False),
    Column("purge_le", Text, nullable=True),
    CheckConstraint("statut IN ('en_attente','purgee')", name="statut_valide"),
    CheckConstraint("(statut = 'purgee') = (purge_le IS NOT NULL)", name="purge_coherente"),
    Index("ix_retention_echeances_statut", "statut", "echeance_epoch"),
)

# -- M8 : entrepôt analytique DÉRIVÉ et pont BI en lecture (migration 0046) ---------------------------------------
# L'entrepôt (M8.2) n'est JAMAIS une source de vérité : chaque table est reconstructible depuis les registres des
# départements (`faits_chantier`, `faits_entonnoir`, `faits_contenus`, `faits_cash_libre`), qui restent la vérité. Il
# est
# versionné (`version_schema`, `version_catalogue`, empreinte des registres sources) et chaque mesure porte sa
# fraîcheur et sa
# provenance. `m8_ent_constructions` est le journal des constructions (une ligne par état distinct des registres) ;
# les tables
# `m8_ent_*` autres que `m8_ent_mesures_hist` ne portent que la construction COURANTE (remplacée en bloc, dans une
# transaction).
# Aucune colonne ne porte une personne (ni technicien, ni client, ni contact) : seulement des identifiants d'affaire,
# des
# instants, des comptes et des montants arrêtés par les départements propriétaires.
M8_ENT_CONSTRUCTIONS = Table(
    "m8_ent_constructions", META,
    Column("rang", Integer, primary_key=True, autoincrement=True),
    Column("construction_id", String(64), nullable=False, unique=True),
    Column("version_schema", Integer, nullable=False),
    Column("version_catalogue", String(64), nullable=False),
    Column("empreinte_registres", String(64), nullable=False),
    Column("construit_le", Text, nullable=False),
    Column("nb_mesures", Integer, nullable=False),
    Column("comptes", Text, nullable=False),
    CheckConstraint("version_schema >= 1 AND nb_mesures >= 0", name="bornes"),
)
M8_ENT_MESURES_COURANTES = Table(
    "m8_ent_mesures_courantes", META,
    Column("metric_id", String(80), primary_key=True),
    Column("construction_id", String(64), ForeignKey("m8_ent_constructions.construction_id"), nullable=False),
    Column("nom", Text, nullable=False),
    Column("domaine", String(24), nullable=False),
    Column("sens", String(20), nullable=False),
    Column("sensibilite", String(16), nullable=False),
    Column("proprietaire", String(64), nullable=False),
    Column("unite", String(32), nullable=False),
    Column("statut", String(16), nullable=False),
    Column("valeur", Text, nullable=True),
    Column("detail", Text, nullable=True),
    Column("source", Text, nullable=False),
    Column("version_definition", String(64), nullable=False),
    Column("dernier_fait_le", Text, nullable=True),
    Column("fraicheur_attendue_s", Integer, nullable=True),
    Column("fraicheur_terminale", Boolean, nullable=False),
    CheckConstraint("statut IN ('calculee','non_calculable')", name="statut_valide"),
    CheckConstraint("(statut = 'calculee') = (valeur IS NOT NULL)", name="valeur_si_calculee"),
)
M8_ENT_MESURES_HIST = Table(
    "m8_ent_mesures_hist", META,
    Column("construction_id", String(64), ForeignKey("m8_ent_constructions.construction_id"), primary_key=True),
    Column("metric_id", String(80), primary_key=True),
    Column("construit_le", Text, nullable=False),
    # Clé UTC normalisée à la nanoseconde (``AAAA-MM-JJTHH:MM:SS.NNNNNNNNNZ``) : longueur fixe, donc l'ordre
    # lexicographique est l'ordre chronologique. Le texte d'origine reste dans ``construit_le`` ; cette colonne est
    # dérivée et remplacée par la migration 0087 pour les historiques déjà stockés. Nulle seulement pour une ligne
    # écrite hors du producteur : le lecteur refuse alors de sélectionner (fail-closed).
    Column("construit_le_utc", Text, nullable=True),
    Column("statut", String(16), nullable=False),
    Column("valeur", Text, nullable=True),
    Column("version_definition", String(64), nullable=False),
    Column("dernier_fait_le", Text, nullable=True),
    Index("ix_m8_ent_mesures_hist_metrique", "metric_id", "construit_le"),
    Index("ix_m8_ent_mesures_hist_metrique_utc", "metric_id", "construit_le_utc", "construction_id"),
)
M8_ENT_DIM_CHANTIER = Table(
    "m8_ent_dim_chantier", META,
    Column("wct_id", String(256), primary_key=True),
    Column("construction_id", String(64), ForeignKey("m8_ent_constructions.construction_id"), nullable=False),
    Column("devis_id", String(256), nullable=True),
    Column("termine_le", Text, nullable=False),
    Column("duree_reelle_minutes", Integer, nullable=True),
    Column("duree_estimee_minutes", Integer, nullable=True),
    Column("statut_wct", String(64), nullable=True),
    Column("variance_statut", String(32), nullable=True),
    Column("signal_materiaux", Boolean, nullable=True),
    Column("verdict_marge", String(32), nullable=True),
    Column("marge_reelle_cad", Text, nullable=True),
)
M8_ENT_DIM_LEAD = Table(
    "m8_ent_dim_lead", META,
    Column("lead_id", String(256), primary_key=True),
    Column("construction_id", String(64), ForeignKey("m8_ent_constructions.construction_id"), nullable=False),
    Column("recu_le", Text, nullable=True),
    Column("qualifie_le", Text, nullable=True),
    Column("utm_content", String(256), nullable=True),
)
M8_ENT_FAIT_DEVIS = Table(
    "m8_ent_fait_devis", META,
    Column("devis_id", String(256), primary_key=True),
    Column("construction_id", String(64), ForeignKey("m8_ent_constructions.construction_id"), nullable=False),
    Column("lead_id", String(256), nullable=True),
    Column("envoye_le", Text, nullable=True),
    Column("accepte_le", Text, nullable=True),
    Column("prix_total_cad", Text, nullable=True),
    Column("sans_reponse_statut", String(16), nullable=True),
    Column("sans_reponse_constate_le", Text, nullable=True),
)
M8_ENT_MART_CONTENUS = Table(
    "m8_ent_mart_contenus", META,
    Column("contenu_id", String(256), primary_key=True),
    Column("construction_id", String(64), ForeignKey("m8_ent_constructions.construction_id"), nullable=False),
    Column("utm_content", String(256), nullable=False),
    Column("canal", String(32), nullable=True),
    Column("wct_id", String(256), nullable=True),
    Column("exporte_le", Text, nullable=True),
    Column("suivi", String(16), nullable=False),
    Column("leads", Integer, nullable=True),
    Column("devis_envoyes", Integer, nullable=True),
    Column("devis_acceptes", Integer, nullable=True),
)
M8_ENTREPOT_TABLES = (
    M8_ENT_CONSTRUCTIONS, M8_ENT_MESURES_COURANTES, M8_ENT_MESURES_HIST, M8_ENT_DIM_CHANTIER, M8_ENT_DIM_LEAD,
    M8_ENT_FAIT_DEVIS, M8_ENT_MART_CONTENUS,
)

# Pont vers les outils BI externes (M8.14) : EN LECTURE SEULE. Un jeton BI est un secret du coffre
# (`pont-bi.<jeton_id>`)
# à portée de lecture dédiée ; cette table n'en garde que les métadonnées (jamais la valeur, jamais son empreinte). Le
# journal
# d'accès est append-only (déclencheurs) : qui (jeton), quoi (jeu), combien (lignes), quand, refus et leur code ;
# jamais le
# contenu exporté ni le jeton présenté.
PONT_BI_JETONS = Table(
    "pont_bi_jetons", META,
    Column("jeton_id", String(32), primary_key=True),
    Column("libelle", String(120), nullable=False),
    Column("secret_nom", String(80), nullable=False, unique=True),
    Column("jeux", Text, nullable=False),
    Column("financier", Boolean, nullable=False),
    Column("quota_requetes_heure", Integer, nullable=False),
    Column("quota_lignes_jour", Integer, nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("cree_par", String(200), nullable=False),
    Column("expire_epoch", BigInteger, nullable=False),
    Column("revoque", Boolean, nullable=False),
    Column("revoque_le", Text, nullable=True),
    Column("revoque_par", String(200), nullable=True),
    CheckConstraint("quota_requetes_heure >= 1 AND quota_lignes_jour >= 1", name="quotas_positifs"),
)
PONT_BI_ACCES = Table(
    "pont_bi_acces", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quand", Text, nullable=False),
    Column("epoch", BigInteger, nullable=False),
    Column("jeton_id", String(32), nullable=True),
    Column("jeu", String(64), nullable=True),
    Column("format", String(16), nullable=True),
    Column("phase", String(8), nullable=False),
    Column("statut", String(16), nullable=False),
    Column("code", String(64), nullable=True),
    Column("lignes", Integer, nullable=True),
    CheckConstraint("phase IN ('debut','fin')", name="phase_valide"),
    CheckConstraint("statut IN ('accepte','refuse','termine','echec')", name="statut_valide"),
    Index("ix_pont_bi_acces_jeton", "jeton_id", "epoch"),
)
PONT_BI_TABLES = (PONT_BI_JETONS, PONT_BI_ACCES)

# -- Graphe de connaissances d'entités de M10 (migration 0052, docs/architecture/M10-SOI-GRAPHE.md) --------------------
# Trois tables APPEND-ONLY (déclencheurs de la migration) : des NŒUDS typés (schéma fermé : client, propriété,
# intervention, matériau, fournisseur, équipe, document, décision), des ARÊTES typées dont la validité dans le monde est
# bornée (`valide_de`, et `valide_a` posé par l'événement de fermeture) et dont la provenance est obligatoire, et les
# ÉVÉNEMENTS D'ÉTAT des arêtes (brouillon → confirmée → fermée, ou rejetée) : l'état d'une arête n'est jamais un champ
# modifiable, c'est son dernier événement. Aucune donnée personnelle : un client ou une propriété n'est connu que par
# son pseudonyme stable.
GRAPHE_NOEUDS = Table(
    "graphe_noeuds", META,
    Column("noeud_id", String(32), primary_key=True),
    Column("type", String(16), nullable=False),
    Column("cle", String(128), nullable=False),
    Column("libelle", String(120), nullable=False),
    Column("source_ref", String(200), nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("cree_par", String(200), nullable=False),
    UniqueConstraint("type", "cle", name="uq_graphe_noeuds_cle"),
    CheckConstraint("type IN ('client','propriete','intervention','materiau','fournisseur','equipe','document',"
                    "'decision')", name="type_valide"),
)
GRAPHE_ARETES = Table(
    "graphe_aretes", META,
    Column("arete_id", String(32), primary_key=True),
    Column("type", String(16), nullable=False),
    Column("de_noeud", String(32), ForeignKey("graphe_noeuds.noeud_id"), nullable=False),
    Column("vers_noeud", String(32), ForeignKey("graphe_noeuds.noeud_id"), nullable=False),
    Column("valide_de", String(10), nullable=False),
    Column("sensible", Boolean, nullable=False),
    Column("origine", String(16), nullable=False),
    Column("source_type", String(40), nullable=False),
    Column("source_ref", String(200), nullable=False),
    Column("confiance", String(8), nullable=False),
    Column("cree_le", Text, nullable=False),
    Column("cree_par", String(200), nullable=False),
    UniqueConstraint("type", "de_noeud", "vers_noeud", "valide_de", name="uq_graphe_aretes_identite"),
    CheckConstraint("de_noeud <> vers_noeud", name="pas_de_boucle"),
    CheckConstraint("origine IN ('bus','agent','humain','systeme')", name="origine_valide"),
    Index("ix_graphe_aretes_de", "de_noeud"),
    Index("ix_graphe_aretes_vers", "vers_noeud"),
)
GRAPHE_ARETES_ETATS = Table(
    "graphe_aretes_etats", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("arete_id", String(32), ForeignKey("graphe_aretes.arete_id"), nullable=False),
    Column("etat", String(12), nullable=False),
    Column("quand", Text, nullable=False),
    Column("par", String(200), nullable=False),
    Column("mode", String(8), nullable=False),
    Column("role", String(32), nullable=True),
    Column("raison", Text, nullable=True),
    Column("valide_a", String(10), nullable=True),
    CheckConstraint("etat IN ('brouillon','confirmee','fermee','rejetee')", name="etat_valide"),
    CheckConstraint("mode IN ('agent','humain','systeme')", name="mode_valide"),
    Index("ix_graphe_aretes_etats_arete", "arete_id", "id"),
)
GRAPHE_TABLES = (GRAPHE_NOEUDS, GRAPHE_ARETES, GRAPHE_ARETES_ETATS)

# -- Rôles de modèles et passerelle LiteLLM (migration 0086) ------------------------------------------------------
# Un RÔLE (llm_rapide, llm_fort, llm_raisonnement, embeddings, reranker, ocr, vl, stt, tts, image) désigne un
# fournisseur
# du registre (0037), le nom du modèle à appeler (alias de passerelle), des replis ordonnés, des plafonds et des coûts
# déclarés. Aucune valeur de secret : seulement des NOMS du coffre. Sans ligne, le rôle est inerte (fail-closed).
MODELES_ROLES = Table(
    "modeles_roles", META,
    Column("role", String(24), primary_key=True),
    Column("fournisseur_id", String(80), ForeignKey("fournisseurs_configurations.identifiant"), nullable=False),
    Column("modele_appel", String(200), nullable=False),
    Column("replis", Text, nullable=False),
    Column("amont", Text, nullable=True),
    Column("plafond_jetons_jour", BigInteger, nullable=True),
    Column("budget_usd_mois", String(24), nullable=True),
    Column("cout_entree_par_million", String(24), nullable=True),
    Column("cout_sortie_par_million", String(24), nullable=True),
    Column("cout_source", String(200), nullable=True),
    Column("mesures", Text, nullable=True),
    Column("revision", Integer, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(200), nullable=False),
    CheckConstraint(
        "role IN ('llm_rapide','llm_fort','llm_raisonnement','embeddings','reranker','ocr','vl','stt','tts','image')",
        name="role_valide",
    ),
    CheckConstraint("revision > 0", name="revision_positive"),
    CheckConstraint("plafond_jetons_jour IS NULL OR plafond_jetons_jour > 0", name="plafond_positif"),
)
# Réglages singuliers (clés `passerelle`, `raisonnement`, `catalogue` = dernière découverte) : JSON sans secret,
# révision optimiste.
MODELES_REGLAGES = Table(
    "modeles_reglages", META,
    Column("cle", String(24), primary_key=True),
    Column("valeur", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("modifie_le", Text, nullable=False),
    Column("modifie_par", String(200), nullable=False),
    CheckConstraint("cle IN ('passerelle','raisonnement','catalogue')", name="cle_valide"),
    CheckConstraint("revision > 0", name="revision_positive"),
)
# Historique append-only (déclencheurs de la migration 0086) : chaque changement avec l'état d'avant et d'après,
# l'acteur et le niveau d'approbation confirmé. C'est de lui que vient le retour arrière. Jamais de secret.
MODELES_HISTORIQUE = Table(
    "modeles_historique", META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("quand", Text, nullable=False),
    Column("cible", String(32), nullable=False),
    Column("action", String(40), nullable=False),
    Column("acteur", String(200), nullable=False),
    Column("niveau", String(4), nullable=False),
    Column("avant", Text, nullable=True),
    Column("apres", Text, nullable=True),
    Index("ix_modeles_historique_cible", "cible", "id"),
)
# Consommation par rôle et par jour (compteurs absolus incrémentés par l'appel routé) : alimente plafonds et budgets.
MODELES_USAGE = Table(
    "modeles_usage", META,
    Column("role", String(24), primary_key=True),
    Column("jour", String(10), primary_key=True),
    Column("appels", BigInteger, nullable=False),
    Column("jetons_entree", BigInteger, nullable=False),
    Column("jetons_sortie", BigInteger, nullable=False),
    Column("cout_micro_usd", BigInteger, nullable=False),
    Column("appels_repli", BigInteger, nullable=False),
    CheckConstraint("appels >= 0 AND jetons_entree >= 0 AND jetons_sortie >= 0 AND cout_micro_usd >= 0 "
                    "AND appels_repli >= 0",
                    name="positifs"),
)
MODELES_TABLES = (MODELES_ROLES, MODELES_REGLAGES, MODELES_HISTORIQUE, MODELES_USAGE)
