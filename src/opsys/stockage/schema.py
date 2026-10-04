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
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)

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
    Column("profile_revision", Integer, nullable=False),
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
# la ligne ici (vrai DELETE, contrairement à REGISTRES) rend ce maillon irrécupérable sans jamais
# toucher au registre ni à son empreinte. `portee` namespace l'usage (ex. "m04-field-ops/gps") ;
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
    Column("evenement_id", String(128), primary_key=True),
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
    Column("evenement_id", String(128), ForeignKey("evenements_sortants.evenement_id"), primary_key=True),
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
    Column("revision", Integer, nullable=False),
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
    Column("revision", Integer, primary_key=True),
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
    Column("profile_revision", Integer, nullable=False),
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
    Column("profile_revision", Integer, nullable=False),
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
