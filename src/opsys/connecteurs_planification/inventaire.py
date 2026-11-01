"""Inventaire exécutable des « tours » : le travail périodique qu'un système autonome doit faire sans qu'un humain lance
chaque tour, et l'état de son branchement au planificateur durable (docs/architecture/PLANIFICATION.md §2).

Chaque entrée dit : où est le code (module, fonction), si le rejouer est sûr, si le niveau est N0 à N2 ou N3 et plus,
de quel transport il dépend et si ce transport existe, puis la DÉCISION justifiée :

- `deja_branche` : un exécuteur du planificateur (ou, hors planificateur, la boucle d'entretien de l'image) le déclenche
  ;
- `brancher_maintenant` : sûr à automatiser (lecture, calcul, brouillon, indexation, reconstruction, purge,
  vérification) ;
  l'exécuteur nommé le déclenche, `inactif` tant qu'un admin ne l'a pas activé ;
- `brancher_quand_transport` : le travail est branché ou branchable, mais son transport réel n'existe pas (ou son
  approbation de dépense n'existe pas) : l'état « en attente de transport » le dit ;
- `ne_jamais_automatiser` : N3 et plus sans approbation humaine consommée possible ici, ou identité qu'un acteur système
  ne doit pas porter : le geste reste humain ;
- `a_construire` : ni transport ni niveau n'empêchent, mais la pièce manquante n'est pas livrée (dit lequel).

`scripts/planification/inventaire_tours.py` imprime ce tableau et `--verifier` contrôle, sans importer le code des
départements, que chaque fonction citée existe encore dans son module (un renommage casse le test, pas la prod en
silence).
"""

from __future__ import annotations

import dataclasses

DECISIONS = ("deja_branche", "brancher_maintenant", "brancher_quand_transport", "ne_jamais_automatiser", "a_construire")
TRANSPORTS = ("aucun", "local", "port_sans_transport_reel")


@dataclasses.dataclass(frozen=True)
class Tour:
    identifiant: str
    libelle: str
    module: str  # chemin relatif à la racine du dépôt
    fonction: str  # nom de la fonction ou méthode (cherchée dans le module, imbriquée comprise)
    niveau: str  # N0 à N5, tel que déclaré
    idempotent: str  # comment le rejeu est sûr (ou pourquoi il ne l'est pas)
    transport: str  # `aucun` | `local` | `port_sans_transport_reel`
    decision: str
    justification: str
    executeur: str | None = None  # nom dans `etat.DEFINITIONS` (ou "entrypoint.sh" pour la boucle d'entretien)

    @property
    def n3_ou_plus(self) -> bool:
        return self.niveau[:2] in {"N3", "N4", "N5"}


_OPS = "departments/"
TOURS: tuple[Tour, ...] = (
    # -- déjà branchés (câblage des connecteurs)
    # ------------------------------------------------------------------------
    Tour("courriel.synchro", "Synchronisation courriel", "src/opsys/courriel_connecteurs/ingestion.py",
         "synchroniser_compte", "N2", "curseur persisté après la page, idempotence par Message-ID et empreinte",
         "port_sans_transport_reel", "deja_branche",
         "Lecture seule chez le fournisseur ; le transport urllib existe mais n'a jamais touché un vrai service.",
         "courriel.synchro"),
    Tour("courriel.envoi", "Envoi des courriels approuvés", "src/opsys/courriel_connecteurs/envoi.py", "envoyer",
         "N3 : approbation consommée", "jeton lié à l'empreinte, consommé par comparaison-échange avant le réseau",
         "port_sans_transport_reel", "deja_branche",
         "N3 : ne part qu'avec l'approbation humaine consommée ; jamais sans.", "courriel.envoi"),
    Tour("m7.wordpress.brouillons", "WordPress : brouillons",
    _OPS + "m07-marketing/src/m7_marketing/wordpress/executeur.py",
         "transmettre_brouillon", "N2", "trois échecs écartent le brouillon jusqu'à révision",
         "port_sans_transport_reel",
         "deja_branche", "Brouillon seulement (statut draft/pending) : réversible.", "m7.wordpress.brouillons"),
    Tour("m7.wordpress.publication", "WordPress : publication approuvée",
         _OPS + "m07-marketing/src/m7_marketing/wordpress/executeur.py", "publier", "N3 : approbation consommée",
         "une approbation sert une fois ; réponse perdue réconciliée en relisant le site", "port_sans_transport_reel",
         "deja_branche", "Publication publique : approbation humaine consommée obligatoire.",
         "m7.wordpress.publication"),
    Tour("m7.social.publication", "Réseaux sociaux : publication approuvée",
         _OPS + "m07-marketing/src/m7_marketing/sas_social/executeur.py", "executer", "N3/N4 : approbation consommée",
         "publication d'issue incertaine retrouvée avant tout nouvel envoi", "port_sans_transport_reel", "deja_branche",
         "Publication publique : approbation humaine consommée obligatoire.", "m7.social.publication"),
    Tour("memoire.purger_expires", "Mémoire : purge des fragments expirés (Loi 25, art. 23)",
         "src/opsys/memoire/store.py", "purger_expires", "N2", "supprime ce dont `expire_le` est passé : rejouable",
         "local", "deja_branche",
         "Déjà périodique par la boucle d'entretien de l'image (PostgreSQL seulement) ; hors planificateur durable "
         "parce que la mémoire vectorielle est une base distincte.", "entrypoint.sh"),
    # -- à brancher maintenant (exécuteurs de cette tranche) -----------------------------------------------------------
    Tour("m8.construire_entrepot", "M8 : reconstruction de l'entrepôt",
         _OPS + "m08-analytics/src/m8_analytics/analytique_outils.py", "construire_entrepot", "N2",
         "empreinte des registres + version : `inchange` si rien n'a bougé ; id de construction déterministe", "aucun",
         "brancher_maintenant", "Écriture dérivée, reconstructible depuis les registres : réversible.", "m8.entrepot"),
    Tour("m8.publier_faits_consolides", "M8 : faits consolidés pour M10",
         _OPS + "m08-analytics/src/m8_analytics/analytique_outils.py", "publier_faits_consolides", "N2",
         "evenement_id déterministe : un rejeu ne republie pas", "aucun", "brancher_maintenant",
         "Publication interne au bus : N0 à N2.", "m8.entrepot"),
    Tour("m8.enregistrer_sante", "M8 : santé de l'entreprise",
         _OPS + "m08-analytics/src/m8_analytics/analytique_outils.py", "enregistrer_sante", "N2",
         "`meme_jugement` : un rejeu n'ajoute rien", "aucun", "brancher_maintenant",
         "Calcul déterministe consigné : N2.", "m8.entrepot"),
    Tour("m5.cycle_comptable", "M5 : cycle d'opérations (brouillons, relances préparées, préclôture)",
         _OPS + "m05-financecore/src/m5_financecore/outils_operations.py", "executer_cycle_comptable", "N2",
         "idempotent par pièce, par (facture, palier) et par jour de mesure ; rejouer ne crée rien de plus", "aucun",
         "brancher_maintenant",
         "S'arrête aux BROUILLONS : aucun paiement, envoi de relance ni clôture (N3/N4 humains). "
         "À valider auprès d'un comptable (CPA) / professionnel qualifié.", "m5.cycle"),
    Tour("m10.construire_soi", "M10 : modèle de soi (propositions)",
         _OPS + "m10-memoire/src/m10_memoire/soi_graphe.py", "construire_soi", "N2",
         "une proposition identique ajoute seulement une source", "aucun", "brancher_maintenant",
         "Propose, ne confirme jamais : la confirmation est un geste humain (N3).", "m10.mnemo"),
    Tour("m10.synchroniser_graphe", "M10 : synchronisation du graphe d'entités",
         _OPS + "m10-memoire/src/m10_memoire/soi_graphe.py", "synchroniser_graphe", "N2",
         "arêtes déjà connues comptées, jamais doublées ; pagination par `suivant`", "aucun", "brancher_maintenant",
         "Les arêtes sensibles restent en attente d'une personne.", "m10.mnemo"),
    Tour("m10.extraire_lecons", "M10 : leçons candidates", _OPS + "m10-memoire/src/m10_memoire/soi_graphe.py",
         "extraire_lecons", "N2", "leçons déjà connues ou en cours comptées", "aucun", "brancher_maintenant",
         "Leçons PROPOSÉES seulement ; la décision est humaine.", "m10.mnemo"),
    Tour("m10.surveiller_lecons", "M10 : surveillance des leçons promues",
         _OPS + "m10-memoire/src/m10_memoire/soi_graphe.py", "surveiller_lecons", "N0", "lecture seule", "aucun",
         "brancher_maintenant", "Lecture et mesure : ne retire rien, une régression est décidée par une personne.",
         "m10.mnemo"),
    Tour("m10.reindexer_connaissances", "M10 : réindexation des connaissances",
         "src/opsys/connaissances/index.py", "reindexer", "N2",
         "saute les fragments déjà vectorisés ; bascule atomique, l'espace actif ne change pas si un embedding échoue",
         "port_sans_transport_reel", "brancher_maintenant",
         "Calcul d'index réversible ; sans adaptateur d'embeddings (aucun en production) l'exécuteur dit "
         "« en attente de "
         "transport » au lieu d'échouer.", "m10.connaissances.reindexation"),
    Tour("m7.tour_ingestion", "M7 : signaux marketing (Search Console, analytique, publicité)",
         _OPS + "m07-marketing/src/m7_marketing/signaux/ingestion.py", "tour_ingestion", "N2",
         "curseur ne bouge que dans la transaction d'écriture ; faits idempotents ; quota persisté",
         "port_sans_transport_reel", "brancher_maintenant",
         "Lecture seule chez le tiers ; transport réel absent : « en attente de transport ». Un compte fictif n'écrit "
         "jamais de dépense.", "m7.signaux"),
    Tour("m7.tour_veille", "M7 : veille concurrentielle", _OPS + "m07-marketing/src/m7_marketing/veille/collecte.py",
         "tour_veille", "N2",
         "observation_id = (concurrent, url, contenu, jour UTC) : un rejeu du jour ne duplique pas",
         "port_sans_transport_reel", "brancher_maintenant",
         "Pages publiques déclarées (robots.txt, délai par hôte) ; transport réel absent : « en attente de "
         "transport ».",
         "m7.veille"),
    Tour("m7.studio.executer_fond", "M7 : génération de fonds (modèles locaux)",
         _OPS + "m07-marketing/src/m7_marketing/studio/executeur.py", "executer", "N2 (local)",
         "job_id déterministe ; provenance dédupliquée par sha de la sortie ; 3 échecs closent la demande",
         "port_sans_transport_reel", "brancher_maintenant",
         "Modèle LOCAL seulement (gratuit, interne). Aucun adaptateur de génération n'est livré : « en attente de "
         "transport ».", "m7.studio.fonds"),
    Tour("sauvegarde.verifier", "Vérification des sauvegardes chiffrées", "src/opsys/sauvegarde_chiffree.py",
    "verifier",
         "N0", "lecture seule", "local", "brancher_maintenant",
         "Authentifie l'archive entière sans rien écrire. Exige que le serveur détienne la clé de sauvegarde : choix "
         "d'exploitation explicite (variables d'environnement), sinon « en attente de transport ».",
         "sauvegarde.verification"),
    Tour("peremptions.connaissances", "Péremption des sources de connaissances (dont fiscales)",
         "src/opsys/connaissances/lecture.py", "etat_bases", "N0", "lecture seule", "aucun", "brancher_maintenant",
         "Constat des sources périmées ou à réviser et des échéances de rétention en retard ; ne corrige rien.",
         "peremptions.balayage"),
    Tour("retention.courriel", "Rétention Loi 25 : courriel d'ingestion", "src/opsys/retention/courriel.py", "purger",
         "N3 humain à la 1re activation", "un lot purgé perd son lien : plus jamais planifié", "aucun",
         "brancher_maintenant",
         "Irréversible : aperçu à blanc et validation humaine avant la première purge, puis automatique.",
         "retention.courriel"),
    Tour("retention.cles", "Rétention Loi 25 : clés détruites à échéance (voix, adresses M1)",
         "src/opsys/retention/echeances.py", "detruire", "N3 humain à la 1re activation",
         "purge_id déterministe : un rejeu ne détruit pas une clé recréée", "aucun", "brancher_maintenant",
         "Crypto-effacement ; liste fermée de portées (la rétention GPS de M4 n'en fait pas partie).",
         "retention.cles"),
    Tour("retention.traces", "Rétention : traces d'observabilité", "src/opsys/observabilite/traces.py",
         "appliquer_retention", "N3 humain à la 1re activation", "segments déjà retirés absents : rejouable", "local",
         "brancher_maintenant", "Télémétrie masquée, jamais le segment du jour ; consignée dans purges.jsonl.",
         "retention.traces"),
    Tour("retention.reprendre_effacements", "Reprise des effacements de clés autorisés",
    "src/opsys/cles_chiffrement.py",
         "reprendre_effacements", "N2", "ne rappelle jamais `detruire`", "local", "brancher_maintenant",
         "Termine le nettoyage de fichiers d'un effacement DÉJÀ autorisé : une reprise, pas une décision.",
         "retention.effacements"),
    # -- à brancher quand le transport (ou l'approbation de dépense) existera ------------------------------------------
    Tour("m10.ingerer_source", "M10 : ingestion de sources de connaissances", "src/opsys/connaissances/ingestion.py",
         "ingerer", "N2", "même sha256 et même méta : `rejeu`, rien d'écrit", "port_sans_transport_reel",
         "brancher_quand_transport",
         "Aucun collecteur de sources n'existe : le contenu est un argument. Il n'y a rien à planifier tant qu'une "
         "source déclarée (fichier, URL) et son transport ne sont pas livrés.", None),
    Tour("m7.studio.fond_payant", "M7 : génération de fond par un modèle API (payant)",
         _OPS + "m07-marketing/src/m7_marketing/studio/executeur.py", "executer", "N3/N4 (dépense)",
         "même idempotence que le local, mais une réponse perdue après l'appel repaie", "port_sans_transport_reel",
         "brancher_quand_transport",
         "Payant et l'invite sort du Québec (EFVP) : il faut une approbation de dépense consommée et un plafond "
         "de coût "
         "par mois, qui n'existent pas encore pour la génération. Jamais exécuté ici sans elles.", None),
    Tour("sauvegarde.creer", "Création d'une sauvegarde chiffrée", "src/opsys/sauvegarde_chiffree.py", "sauvegarder",
         "N2", "crée un nouveau fichier à chaque appel", "local", "brancher_quand_transport",
         "La clé de sauvegarde doit rester hors de l'instance (politique) ; la copie hors site est une décision "
         "humaine. "
         "À brancher quand la garde de clé de l'hôte sera décidée.", None),
    # -- ne jamais automatiser ---------------------------------------------------------------------------------------
    Tour("m7.executer_panel", "M7 : panel de moteurs d'IA (GEO)", _OPS + "m07-marketing/src/m7_marketing/geo/panel.py",
         "executer_panel", "N4 (dépense)", "non : rien n'est persisté, relancer repose et repaie",
         "port_sans_transport_reel",
         "ne_jamais_automatiser",
         "Dépense par appel, plafond mensuel, transfert hors Québec : un geste humain approuvé, jamais un tour.", None),
    Tour("m9.rafraichir_lectures", "M9 : rafraîchissement des lectures de la direction",
         _OPS + "m09-strategic-intelligence/src/m9_strategic_intelligence/outils_athena.py", "rafraichir", "N2",
         "non : chaque appel ajoute des captures", "aucun", "ne_jamais_automatiser",
         "Décision de M9 : les lectures exigent l'identité d'un admin humain authentifié ; l'acteur système ne porte "
         "aucune identité de personne.", None),
    Tour("m4.purger_retention_gps", "M4 : purge de la rétention GPS",
         _OPS + "m04-field-ops/src/m4_field_ops/outils.py", "purger_retention_gps", "N5",
         "purge_id lié à la demande", "aucun", "ne_jamais_automatiser",
         "N5 : propriétaire ET attestation d'un professionnel, par personne ; hors de portée de tout acteur système.",
         None),
    # -- à construire ------------------------------------------------------------------------------------------------
    Tour("m10.consolider_affaire", "M10 : consolidation nocturne d'une affaire",
         _OPS + "m10-memoire/src/m10_memoire/consolidation.py", "consolider_affaire", "N2",
         "idempotent par (affaire, jour, ensemble de sources)", "aucun", "a_construire",
         "Dépend d'un énumérateur des affaires touchées la veille, qui n'existe pas : aujourd'hui un tour d'agent le "
         "fait (planification `consolidation-nocturne` du manifeste, livrée en pause).", None),
)

# Péremptions évaluées À LA LECTURE (rien n'écrit, donc rien à balayer ; le constat planifié est
# `peremptions.balayage`).
EVALUATIONS_A_LA_LECTURE: tuple[tuple[str, str, str], ...] = (
    ("Sources fiscales de M5", _OPS + "m05-financecore/src/m5_financecore/conseiller_fiscal.py",
     "statut_sources_sujets"),
    ("Licences des fournisseurs", "src/opsys/fournisseurs/registre.py", "resoudre"),
    ("Consentement de suivi M4", _OPS + "m04-field-ops/src/m4_field_ops/suivi_client.py", "etat_du_consentement"),
    ("Jetons d'approbation de courriel", "src/opsys/courriel_connecteurs/envoi.py", "verifier_demande"),
    ("Mesures périmées de M8", _OPS + "m08-analytics/src/m8_analytics/fraicheur_mesures.py", "evaluer"),
)


def par_identifiant() -> dict[str, Tour]:
    return {t.identifiant: t for t in TOURS}
