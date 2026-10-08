"""Service de l'usine à contenu de chantier : les registres durables et les gestes des outils (PLAN T4.17).

Les modules voisins (`chantier`, `registre`, `decision`, `paquet`, `retrait`, `controle_texte`) sont purs et
décident ; celui-ci lit et écrit `opsys.stockage.maillons` et établit ce que la plateforme seule peut établir :
QUI appelle (la personne d'un jeton d'appareil, confirmée en base à l'instant même), QUI a décidé (un humain),
QUEL WCT M7 a reçu du bus. Rien de tout cela ne vient d'un argument d'outil (AGENTS.md « le LLM orchestre, il
ne fournit jamais un fait »).

Registres (`m07-marketing`, append-only, durables) :
  - `wct_recus`                        les WCT `m4.travaux_termines` reçus (source unique des faits d'un chantier) ;
  - `contenus_chantier`                les propositions : un maillon par contenu et par révision ;
  - `decisions_contenu`                la décision humaine sur un contenu ;
  - `exports_paquet`                   la trace qu'un paquet manuel a été remis (avec sa clé `utm_content`) ;
  - `retraits_consentement_marketing`  le retrait du consentement d'un client, jamais effacé.

Aucun outil de ce service ne publie, n'envoie ni ne programme quoi que ce soit : la publication est manuelle. Un
paquet exporté annonce seulement au bus le fait `m7.contenu_exporte` (PLAN T4.17-e : la clé de mesure du contenu, son
chantier, son canal), pour que M8 compte les leads par contenu ; rien de personnel n'y voyage.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select

from opsys import approbations, evenements, fichiers, identite, stockage, taxonomie
from opsys import contexte as contexte_appel
from opsys.stockage import codec
from opsys.stockage.maillons import EcritureConcurrente
from opsys.stockage.schema import REGISTRES

from ..brand import registre as brand_registre
from . import calendrier, chantier, mesure, paquet, plateformes, registre, retrait, verdicts
from . import decision as regle_decision
from .controle_texte import LIBELLES_REGLES, controler_texte

DEPARTEMENT = "m07-marketing"
# Le seul rôle qu'`m7_decider_contenu` reconnaît à un approbateur de la file (plus strict que la politique du
# département, qui peut s'élargir) : la décision d'un contenu public est celle du propriétaire.
ROLES_QUI_DECIDENT = frozenset({regle_decision.ROLE_DECIDEUR})
REGISTRE_WCT_RECUS = (DEPARTEMENT, "wct_recus")
REGISTRE_CONTENU_PUBLIC = (DEPARTEMENT, "contenu_public")
REGISTRE_CONTENUS_CHANTIER = (DEPARTEMENT, "contenus_chantier")
REGISTRE_DECISIONS_CONTENU = (DEPARTEMENT, "decisions_contenu")
REGISTRE_EXPORTS_PAQUET = (DEPARTEMENT, "exports_paquet")
REGISTRE_RETRAITS = (DEPARTEMENT, "retraits_consentement_marketing")
REGISTRE_CALENDRIER = (DEPARTEMENT, "calendrier_contenus")
REGISTRE_DECISIONS_CALENDRIER = (DEPARTEMENT, "decisions_calendrier")
REGISTRE_EXPORTS_CALENDRIER = (DEPARTEMENT, "exports_calendrier")
REGISTRE_DOSSIERS_MEDIAS = (DEPARTEMENT, "dossiers_medias")

STATUT_WCT_INCONNU = "wct_inconnu"
STATUT_ANNONCE = "annonce"
STATUT_DEJA_ANNONCE = "deja_annonce"
STATUT_PROFIL_MARQUE_NON_CONFIGURE = "profil_marque_non_configure"
STATUT_OK = "ok"

ORIGINE_BUS = "bus:m4.travaux_termines"
ORIGINE_BUS_RETRAIT = "bus:m1.retrait_consentement"
ORIGINE_AGENT = "agent"

LIMITE_LISTE_DEFAUT = 5
LIMITE_LISTE_MAX = 8
# `Capacites` tronque au-delà de 6 000 caractères : le téléphone ne lirait pas la suite. La liste s'arrête
# avant (un contenu au moins par page), et dit ce qu'il reste (`suivant`, `reste`).
BUDGET_LISTE = 5400  # réserve pour l'enveloppe + preuve courante unique ; sortie complète < 6 000
RESUME_ATTENTE_MAX = 200
ACTION_ATTENTE = "lire (m7_lister_contenus_chantier) puis approuver ou rejeter (m7_decider_contenu)"
A_FAIRE_PAQUET_EXPORTE = "retirer à la main les publications déjà faites avec ces paquets exportés"


# -- lecture des registres ---------------------------------------------------------------------------------------
def _lire(registre_nom: tuple[str, str]) -> list[dict[str, Any]]:
    return list(stockage.maillons(*registre_nom))


def wct_recu(wct_id: str) -> dict[str, Any] | None:
    """Le WCT `m4.travaux_termines` déjà reçu pour `wct_id` (registre `wct_recus`, alimenté seulement par le
    consommateur d'événements, jamais par un argument d'outil), ou `None`."""
    for enregistrement in stockage.maillons(*REGISTRE_WCT_RECUS):
        if enregistrement.get("wct_id") == wct_id:
            return enregistrement
    return None


def _empreinte_json(valeur: Any) -> str:
    return hashlib.sha256(json.dumps(
        valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _hash_evenements(evenements: list[dict[str, Any]]) -> str:
    return _empreinte_json(evenements)


def _proprietaire_console_actif() -> str | None:
    cnx = stockage.connexion_courante()
    identite_appelante = contexte_appel.identite_appelante()
    if cnx is None or identite_appelante is None or identite_appelante.source != "console" \
            or identite_appelante.role != "nathan_owner":
        return None
    signee = approbations.signataire_valide(cnx, identite_appelante)
    if signee is None:
        return None
    personne = identite.personne_active(cnx, signee.personne)
    if personne is None or "nathan_owner" not in personne.roles:
        return None
    return personne.identifiant


def _lire_edition_borne(nom: tuple[str, str]) -> list[dict[str, Any]]:
    """Bornes propres à l'édition privée, avant décodage des journaux utilisés."""
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise ValueError("édition hors transaction")
    filtre = (REGISTRES.c.departement == nom[0]) & (REGISTRES.c.registre == nom[1])
    nombre, volume, maximum = cnx.execute(
        select(
            func.count(),
            func.sum(func.length(REGISTRES.c.maillon)),
            func.max(func.length(REGISTRES.c.maillon)),
        ).where(filtre)
    ).one()
    if nombre > 10000 or (volume or 0) > 8 * 1024 * 1024 or (maximum or 0) > 65536:
        raise ValueError("journal d'édition hors limites")
    lignes = []
    for texte in cnx.execute(select(REGISTRES.c.maillon).where(filtre).order_by(REGISTRES.c.rang)).scalars():
        ligne = codec.decoder(texte)
        if not isinstance(ligne, dict):
            raise ValueError("ligne d'édition invalide")
        _empreinte_json(ligne)  # JSON UTF-8 fini, pas NaN/Infinity ni étiquette codec non sérialisable.
        lignes.append(ligne)
    return lignes


def _source_edition_texte(contenu_id: str, *, courant: bool = True) -> tuple[Any, Any]:
    if _proprietaire_console_actif() is None:
        return None, _refus(verdicts.verdict("REJ-TEXTE-PROPRIETAIRE-REQUIS", "propriétaire console actif requis"))
    try:
        propositions = _lire_edition_borne(REGISTRE_CONTENUS_CHANTIER)
        candidats = [p for p in propositions if p.get("contenu_id") == contenu_id]
        if len(candidats) != 1:
            raise ValueError("contenu absent ou ambigu")
        proposition = candidats[0]
        if (proposition.get("type") != "contenu_chantier"
                or proposition.get("approval_status") != registre.STATUT_PROPOSE):
            raise ValueError("forme canonique de proposition invalide")
        if courant and not registre.est_derniere_revision(proposition, propositions):
            return None, _refus(verdicts.verdict("REJ-TEXTE-CAS-PERIME", "une autre version existe ; relire"))
        wcts = [w for w in _lire_edition_borne(REGISTRE_WCT_RECUS) if w.get("wct_id") == proposition["wct_id"]]
        if len(wcts) != 1:
            raise ValueError("WCT absent ou ambigu")
        charge = wcts[0]
        retraits = _lire_edition_borne(REGISTRE_RETRAITS)
        if retrait.retrait_applicable(proposition["wct_id"], proposition.get("lead_id"), retraits) is not None:
            return None, _refus(verdicts.verdict(verdicts.REJ_CONSENTEMENT_RETIRE, "consentement retiré"))
        snapshot_marque, nature, refus = _pret_a_composer(charge)
        if refus is not None:
            return None, refus
        if (
            proposition.get("plateforme") not in plateformes.CODES_PLATEFORMES
            or type(proposition.get("revision")) is not int
            or proposition["revision"] < 1
        ):
            raise ValueError("plateforme/révision invalide")
        if (
            not isinstance(proposition.get("texte"), str)
            or proposition.get("empreinte_texte")
            != hashlib.sha256(
                proposition["texte"].encode("utf-8"),
            ).hexdigest()
        ):
            raise ValueError("empreinte de texte invalide")
        retraits_cibles = [
            r
            for r in retraits
            if r.get("wct_id") == proposition["wct_id"]
            or (proposition.get("lead_id") is not None and r.get("lead_id") == proposition["lead_id"])
        ]
        snapshot = _empreinte_json(
            {
                "proposition": proposition,
                "wct": charge,
                "marque": snapshot_marque["preuve"],
                "retraits": retraits_cibles,
            }
        )
        if _proprietaire_console_actif() is None:
            return None, _refus(verdicts.verdict(
                "REJ-TEXTE-PROPRIETAIRE-REQUIS", "propriétaire révoqué pendant lecture",
            ))
        return {
            "proposition": proposition,
            "propositions": propositions,
            "wct": charge,
            "marque": snapshot_marque,
            "nature": nature,
            "snapshot_sha256": snapshot,
        }, None
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, UnicodeError, RecursionError):
        return None, _refus(
            verdicts.verdict("REJ-TEXTE-SOURCE-INVALIDE", "source d'édition incohérente ou hors limites")
        )


def lire_edition_texte_humain(contenu_id: str) -> dict[str, Any]:
    source, refus = _source_edition_texte(contenu_id)
    if refus is not None:
        return refus
    proposition = source["proposition"]
    return {
        "accepte": True,
        "resultat": {
            "contenu_id": contenu_id,
            "revision": proposition["revision"],
            "empreinte_texte": proposition["empreinte_texte"],
            "snapshot_sha256": source["snapshot_sha256"],
            "plateforme": proposition["plateforme"],
            "longueur_max": plateformes.plateforme(proposition["plateforme"]).longueur_max,
            "texte": proposition["texte"],
            "marque_source": source["marque"]["preuve"],
            "edition_humaine": proposition.get("edition_humaine"),
        },
    }


def verifier_rejeu_edition_texte(contenu_id: str) -> dict[str, Any] | None:
    # Un reçu historique ne lance pas une nouvelle version : pas le CAS dépassé par sa propre écriture.
    return _source_edition_texte(contenu_id, courant=False)[1]


def reviser_texte_humain(
    contenu_id: str,
    revision_attendue: int,
    empreinte_texte_attendue: str,
    snapshot_attendu: str,
    texte: str,
    horodatage: str,
) -> dict[str, Any]:
    cnx = stockage.connexion_courante()
    if cnx is None or cnx.engine.dialect.name != "sqlite":
        return _refus(verdicts.verdict("REJ-TEXTE-ECRITURE-NON-QUALIFIEE", "édition qualifiée sur SQLite seulement"))
    source, refus = _source_edition_texte(contenu_id)
    if refus is not None:
        return refus
    proposition = source["proposition"]
    if (
        type(revision_attendue) is not int
        or proposition["revision"] != revision_attendue
        or proposition["empreinte_texte"] != empreinte_texte_attendue
        or source["snapshot_sha256"] != snapshot_attendu
    ):
        return _refus(verdicts.verdict("REJ-TEXTE-CAS-PERIME", "texte ou source changés ; relire avant correction"))
    try:
        texte_valide = isinstance(texte, str) and bool(texte.strip()) and len(texte.encode("utf-8")) <= 8000
    except UnicodeError:
        texte_valide = False
    if not texte_valide:
        return _refus(verdicts.verdict("REJ-TEXTE-INVALIDE", "texte UTF-8 non vide et borné requis"))
    texte = texte.strip()
    if texte == proposition["texte"]:
        return {
            "accepte": True,
            "resultat": {"modifie": False, "contenu_id": contenu_id, "revision": proposition["revision"]},
        }
    code = proposition["plateforme"]
    preparation = chantier.preparer(
        source["wct"],
        source["marque"]["profil"],
        source["nature"],
        {code: texte},
        source["propositions"],
        (),
        "console:" + str(_proprietaire_console_actif()),
        marque_source=source["marque"]["preuve"],
        renouveler_marque=False,
        revision_humaine=contenu_id,
    )
    if len(preparation.nouvelles) != 1:
        item = next(i for i in preparation.items if i["plateforme"] == code)
        return _refus(chantier.verdict_texte_non_conforme([r["regle"] for r in item.get("regles", [])]))
    finale, refus = _source_edition_texte(contenu_id)
    if refus is not None:
        return refus
    if finale["snapshot_sha256"] != snapshot_attendu:
        return _refus(verdicts.verdict("REJ-TEXTE-CAS-PERIME", "source modifiée avant enregistrement"))
    auteur = _proprietaire_console_actif()
    if auteur is None:
        return _refus(verdicts.verdict("REJ-TEXTE-PROPRIETAIRE-REQUIS", "propriétaire révoqué"))
    nouvelle = {
        **preparation.nouvelles[0],
        "propose_le": horodatage,
        "edition_humaine": {
            "par": auteur,
            "source": "console",
            "horodatage": horodatage,
            "ancien_contenu_id": contenu_id,
            "snapshot_source_sha256": snapshot_attendu,
        },
    }
    stockage.maillons(*REGISTRE_CONTENUS_CHANTIER).append(nouvelle)
    return {
        "accepte": True,
        "resultat": {"modifie": True, "contenu_id": nouvelle["contenu_id"], "revision": nouvelle["revision"]},
    }


def _snapshot_media(contenu_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Résout le WCT M7 reçu et ses sources complètes; aucun fait de l'appelant n'est utilisé."""
    cnx = stockage.connexion_courante()
    if cnx is None:
        return None, verdicts.verdict("REJ-MEDIA-TRANSACTION-REQUise", "transaction de base requise")
    propositions = _lire(REGISTRE_CONTENUS_CHANTIER)
    if any(
        not isinstance(p, dict)
        or not isinstance(p.get("contenu_id"), str)
        or not isinstance(p.get("wct_id"), str)
        or not isinstance(p.get("plateforme"), str)
        or type(p.get("revision")) is not int
        or p["revision"] < 1
        or not isinstance(p.get("empreinte_texte"), str)
        for p in propositions
    ):
        return None, verdicts.verdict("REJ-MEDIA-CONTENU-INVALIDE", "registre de contenus malformé")
    proposition = registre.proposition_par_id(propositions, contenu_id)
    if (
        proposition is None or type(proposition.get("revision")) is not int or proposition["revision"] < 1
        or not isinstance(proposition.get("wct_id"), str)
        or not isinstance(proposition.get("contenu_id"), str)
        or not isinstance(proposition.get("empreinte_texte"), str)
        or not isinstance(proposition.get("texte"), str)
        or not registre.est_derniere_revision(proposition, propositions)
    ):
        return None, verdicts.verdict("REJ-MEDIA-CONTENU-PERIME", "contenu absent ou remplacé")
    try:
        empreinte_texte = hashlib.sha256(proposition["texte"].encode("utf-8")).hexdigest()
    except UnicodeError:
        return None, verdicts.verdict("REJ-MEDIA-CONTENU-INVALIDE", "texte courant non encodable en UTF-8")
    if empreinte_texte != proposition["empreinte_texte"]:
        return None, verdicts.verdict("REJ-MEDIA-CONTENU-MODIFIE", "empreinte du texte courant divergente")
    wcts = _lire(REGISTRE_WCT_RECUS)
    if any(not isinstance(w, dict) for w in wcts):
        return None, verdicts.verdict("REJ-MEDIA-WCT-INVALIDE", "registre WCT reçu malformé")
    charges = [w for w in wcts if w.get("wct_id") == proposition.get("wct_id")]
    if len(charges) != 1:
        return None, verdicts.verdict("REJ-MEDIA-WCT-INVALIDE", "WCT absent ou ambigu dans le registre reçu")
    charge = charges[0]
    if not isinstance(charge, dict) or not isinstance(charge.get("wct_id"), str) \
            or not isinstance(charge.get("hash_maillon"), str):
        return None, verdicts.verdict("REJ-MEDIA-WCT-INVALIDE", "identité ou preuve de transition WCT absente")
    preuves_consentement = (
        charge.get("consentement_marketing") is True
        and all(isinstance(charge.get(c), str) and charge[c].strip() for c in (
            "consentement_recueilli_par", "consentement_recueilli_le", "consentement_version_texte",
        ))
    )
    if not preuves_consentement:
        return None, verdicts.verdict("REJ-MEDIA-CONSENTEMENT-ABSENT", "consentement marketing prouvé absent")
    if retrait.retrait_applicable(charge["wct_id"], charge.get("lead_id"), _lire(REGISTRE_RETRAITS)) is not None:
        return None, verdicts.verdict("REJ-MEDIA-CONSENTEMENT-RETIRE", "retrait marketing courant")
    sources = charge.get("photos")
    if not isinstance(sources, list) or not sources or not all(isinstance(r, str) for r in sources):
        return None, verdicts.verdict("REJ-MEDIA-SOURCES-INCOMPLETES", "WCT sans liste complète de photos")
    if len(set(sources)) != len(sources):
        return None, verdicts.verdict("REJ-MEDIA-SOURCES-AMBIGUES", "références photo dupliquées")
    fichiers_verifies = []
    for reference in sources:
        lecture = fichiers.lire_blob_verifie(cnx, reference)
        if not lecture.accepte or lecture.octets is None or lecture.type_mime is None:
            return None, verdicts.verdict("REJ-MEDIA-SOURCE-INVALIDE", "une photo du WCT n'est plus vérifiable")
        fichiers_verifies.append({
            "source_ref": reference,
            "source_sha256": fichiers.empreinte_depuis_reference(reference),
            "source_mime": lecture.type_mime,
            "source_taille": len(lecture.octets),
        })
    snapshot_marque = brand_registre.lire_snapshot_marque()
    profil, motif = snapshot_marque.get("profil"), snapshot_marque.get("motif")
    if not isinstance(profil, dict):
        return None, verdicts.verdict("REJ-MEDIA-PROFIL-ABSENT", motif or "profil de marque absent")
    refus_marque = _refus_marque(proposition, snapshot_marque)
    if refus_marque is not None:
        return None, refus_marque["verdict"]
    try:
        snapshot = {
            "contenu_id": proposition["contenu_id"],
            "contenu_revision": proposition["revision"],
            "empreinte_texte": proposition["empreinte_texte"],
            "wct_id": charge["wct_id"],
            "wct": charge,
            "profil_marque_sha256": _empreinte_json(profil),
            "marque_source": snapshot_marque["preuve"],
            "sources": fichiers_verifies,
        }
        empreinte_snapshot = _empreinte_json(snapshot)
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        return None, verdicts.verdict("REJ-MEDIA-WCT-INVALIDE", "charge WCT non canonique")
    return {"snapshot": snapshot, "snapshot_sha256": empreinte_snapshot}, None


def lire_dossier_medias(contenu_id: str) -> dict[str, Any]:
    if _proprietaire_console_actif() is None:
        return _refus(verdicts.verdict(
            "REJ-MEDIA-PROPRIETAIRE-REQUIS", "lecture privée réservée au propriétaire console",
        ))
    snapshot, refus = _snapshot_media(contenu_id)
    if refus is not None:
        return _refus(refus)
    etat = registre.etat_dossier_medias(_lire(REGISTRE_DOSSIERS_MEDIAS), contenu_id)
    if not etat["valide"]:
        return _refus(verdicts.verdict("REJ-MEDIA-DOSSIER-INCOHERENT", "journal médias incohérent"))
    if etat["evenements"] and any(
        e.get("snapshot_sha256") != snapshot["snapshot_sha256"] for e in etat["evenements"]
    ):
        etat = {**etat, "statut": "SNAPSHOT_PERIME", "medias": [], "evenements": []}
    if _proprietaire_console_actif() is None:
        return _refus(verdicts.verdict("REJ-MEDIA-PROPRIETAIRE-REQUIS", "identité propriétaire expirée"))
    # Le WCT complet peut contenir identité, adresse, GPS et notes de chantier.
    # La console ne reçoit que les métadonnées nécessaires à la revue; les octets
    # et la charge WCT restent dans leurs ports privés respectifs.
    return {
        "accepte": True,
        "resultat": {
            **etat,
            "snapshot_sha256": snapshot["snapshot_sha256"],
            "wct_id": snapshot["snapshot"]["wct_id"],
            "sources": [
                {
                    "source_ref": source["source_ref"],
                    "source_sha256": source["source_sha256"],
                    "type_mime": source["source_mime"],
                    "taille": source["source_taille"],
                }
                for source in snapshot["snapshot"]["sources"]
            ],
        },
    }


def preparer_media_humain(
    contenu_id: str, source_ref: str, octets: bytes, attestation_humaine: str,
    revision_attendue: int, empreinte_attendue: str, snapshot_attendu: str, horodatage: str,
) -> dict[str, Any]:
    """Dépose une variante fournie par un humain, ancrée sur la source WCT courante."""
    cnx = stockage.connexion_courante()
    if cnx is None or cnx.engine.dialect.name != "sqlite":
        return _refus(verdicts.verdict(
            "REJ-MEDIA-ECRITURE-NON-QUALIFIEE", "mutation média non qualifiée sur ce moteur de base",
        ))
    auteur = _proprietaire_console_actif()
    if auteur is None:
        return _refus(verdicts.verdict("REJ-MEDIA-PROPRIETAIRE-REQUIS", "écriture réservée au propriétaire console"))
    snapshot, refus = _snapshot_media(contenu_id)
    if refus is not None:
        return _refus(refus)
    journal = stockage.maillons(*REGISTRE_DOSSIERS_MEDIAS)
    etat = registre.etat_dossier_medias(journal, contenu_id)
    if not etat["valide"]:
        return _refus(verdicts.verdict("REJ-MEDIA-DOSSIER-INCOHERENT", "journal médias incohérent"))
    if revision_attendue != etat["revision"] or empreinte_attendue != etat["empreinte_dossier"]:
        return _refus(verdicts.verdict("REJ-MEDIA-DOSSIER-PERIME", "le dossier a changé; relire avant de déposer"))
    if snapshot["snapshot_sha256"] != snapshot_attendu:
        return _refus(verdicts.verdict("REJ-MEDIA-SNAPSHOT-PERIME", "le WCT, le profil ou le consentement a changé"))
    if etat["remises"]:
        return _refus(verdicts.verdict("REJ-MEDIA-DOSSIER-FIGE", "une remise qualifiée fige le dossier médias"))
    reprise_requise = any(e.get("snapshot_sha256") != snapshot_attendu for e in etat["evenements"])
    source = next((s for s in snapshot["snapshot"]["sources"] if s["source_ref"] == source_ref), None)
    if source is None:
        return _refus(verdicts.verdict("REJ-MEDIA-SOURCE-ETRANGERE", "source absente du WCT courant"))
    if not isinstance(octets, bytes) or not 1 <= len(octets) <= fichiers.TAILLE_MAX_OCTETS:
        return _refus(verdicts.verdict("REJ-MEDIA-PREPARE-INVALIDE", "fichier préparé absent ou hors limite"))
    if not isinstance(attestation_humaine, str) or not 20 <= len(attestation_humaine.strip()) <= 500:
        return _refus(verdicts.verdict("REJ-MEDIA-ATTESTATION-REQUISE", "attestation humaine de préparation requise"))
    signature = octets[:8]
    type_mime = "image/png" if signature.startswith(b"\x89PNG\r\n\x1a\n") else (
        "image/jpeg" if signature.startswith(b"\xff\xd8\xff") else None
    )
    if type_mime is None:
        return _refus(verdicts.verdict("REJ-MEDIA-PREPARE-INVALIDE", "seuls JPEG/PNG avec signature connue sont admis"))
    empreinte = hashlib.sha256(octets).hexdigest()
    nombre_blocs = -(-len(octets) // fichiers.TAILLE_BLOC_OCTETS)
    for index in range(nombre_blocs):
        bloc = octets[index * fichiers.TAILLE_BLOC_OCTETS:(index + 1) * fichiers.TAILLE_BLOC_OCTETS]
        depot = fichiers.deposer_bloc(
            cnx, empreinte, len(octets), type_mime, index, nombre_blocs,
            base64.b64encode(bloc).decode("ascii"), recu_le=horodatage,
        )
        if not depot.accepte or not depot.complet and index == nombre_blocs - 1:
            return _refus(verdicts.verdict("REJ-MEDIA-PREPARE-DEPOT-REFUSE", "CAS a refusé le fichier préparé"))
    if reprise_requise:
        reprise = {
            "type_maillon": "media_reprise", "contenu_id": contenu_id, "revision": etat["revision"] + 1,
            "revision_cible": etat["revision"], "empreinte_cible": etat["empreinte_dossier"],
            "snapshot_sha256": snapshot_attendu, "prepare_par": auteur, "horodatage": horodatage,
        }
        if _proprietaire_console_actif() != auteur:
            return _refus(verdicts.verdict("REJ-MEDIA-PROPRIETAIRE-REQUIS", "identité propriétaire expirée"))
        try:
            journal.append(reprise, rang_attendu=len(journal))
        except EcritureConcurrente:
            return _refus(verdicts.verdict("REJ-MEDIA-CONFLIT-CONCURRENT", "le dossier a changé pendant la reprise"))
        etat = registre.etat_dossier_medias(journal, contenu_id)
        if not etat["valide"]:
            return _refus(verdicts.verdict("REJ-MEDIA-DOSSIER-INCOHERENT", "reprise du journal médias incohérente"))
    revision = etat["revision"] + 1
    maillon = {
        "type_maillon": "media_prepare", "contenu_id": contenu_id, "revision": revision,
        "source_ref": source_ref, "source_sha256": source["source_sha256"],
        "prepared_ref": fichiers.reference_pour(empreinte), "prepared_sha256": empreinte,
        "prepared_mime": type_mime, "prepared_taille": len(octets),
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "attestation_humaine": attestation_humaine.strip(), "prepare_par": auteur,
        "horodatage": horodatage,
    }
    if _proprietaire_console_actif() != auteur:
        return _refus(verdicts.verdict("REJ-MEDIA-PROPRIETAIRE-REQUIS", "identité propriétaire expirée avant écriture"))
    try:
        journal.append(maillon, rang_attendu=len(journal))
    except EcritureConcurrente:
        return _refus(verdicts.verdict("REJ-MEDIA-CONFLIT-CONCURRENT", "le dossier a changé pendant l'écriture"))
    return {"accepte": True, "resultat": {"revision": revision, "prepared_ref": maillon["prepared_ref"]}}


def decider_dossier_medias(
    contenu_id: str, decision: str, revision_attendue: int, empreinte_attendue: str,
    snapshot_attendu: str, attestation_humaine: str, horodatage: str,
) -> dict[str, Any]:
    cnx = stockage.connexion_courante()
    if cnx is None or cnx.engine.dialect.name != "sqlite":
        return _refus(verdicts.verdict(
            "REJ-MEDIA-ECRITURE-NON-QUALIFIEE", "mutation média non qualifiée sur ce moteur de base",
        ))
    acteur, refus_acteur = _proprietaire_qui_decide("m7_decider_dossier_medias")
    if acteur is None:
        return _refus(refus_acteur or verdicts.verdict(
            "REJ-MEDIA-PROPRIETAIRE-REQUIS", "décision réservée au propriétaire",
        ))
    if decision not in {"approuver", "rejeter"}:
        return _refus(verdicts.verdict("REJ-MEDIA-DECISION-INVALIDE", "décision attendue: approuver ou rejeter"))
    if not isinstance(attestation_humaine, str) or not 20 <= len(attestation_humaine.strip()) <= 500:
        return _refus(verdicts.verdict("REJ-MEDIA-ATTESTATION-REQUISE", "attestation de revue humaine requise"))
    snapshot, refus = _snapshot_media(contenu_id)
    if refus is not None:
        return _refus(refus)
    journal = stockage.maillons(*REGISTRE_DOSSIERS_MEDIAS)
    etat = registre.etat_dossier_medias(journal, contenu_id)
    if not etat["valide"] or etat["revision"] == 0:
        return _refus(verdicts.verdict("REJ-MEDIA-DOSSIER-VIDE", "aucun préparé humain à réviser"))
    if revision_attendue != etat["revision"] or empreinte_attendue != etat["empreinte_dossier"]:
        return _refus(verdicts.verdict("REJ-MEDIA-DOSSIER-PERIME", "le dossier a changé; relire avant décision"))
    if snapshot["snapshot_sha256"] != snapshot_attendu or any(
        e.get("snapshot_sha256") != snapshot_attendu for e in etat["evenements"]
    ):
        return _refus(verdicts.verdict("REJ-MEDIA-SNAPSHOT-PERIME", "le WCT, le profil ou le consentement a changé"))
    sources = {s["source_ref"]: s for s in snapshot["snapshot"]["sources"]}
    prepares = {m["source_ref"]: m for m in etat["medias"]}
    if decision == "approuver":
        if any(e.get("snapshot_sha256") != snapshot_attendu for e in etat["evenements"]):
            return _refus(verdicts.verdict("REJ-MEDIA-SNAPSHOT-PERIME", "préparations issues d'une ancienne capture"))
        if set(prepares) != set(sources):
            return _refus(verdicts.verdict(
                "REJ-MEDIA-PREPARATION-INCOMPLETE", "chaque source WCT exige un préparé humain",
            ))
        for source_ref, media in prepares.items():
            source = fichiers.lire_blob_verifie(cnx, source_ref)
            prepare = fichiers.lire_blob_verifie(cnx, media.get("prepared_ref"))
            if (
                not source.accepte or not prepare.accepte or prepare.octets is None
                or hashlib.sha256(prepare.octets).hexdigest() != media.get("prepared_sha256")
                or media.get("source_sha256") != sources[source_ref]["source_sha256"]
            ):
                return _refus(verdicts.verdict("REJ-MEDIA-BLOB-INVALIDE", "une source ou variante ne se vérifie plus"))
    revision = etat["revision"] + 1
    maillon = {
        "type_maillon": "media_revue", "contenu_id": contenu_id, "revision": revision,
        "revision_cible": etat["revision"], "empreinte_cible": etat["empreinte_dossier"],
        "snapshot_sha256": snapshot_attendu, "decision": decision,
        "par": acteur["par"], "role": acteur["role"], "source": acteur["source"],
        "attestation_humaine": attestation_humaine.strip(), "horodatage": horodatage,
    }
    acteur_courant, refus_courant = _proprietaire_qui_decide("m7_decider_dossier_medias")
    if acteur_courant is None or acteur_courant["par"] != acteur["par"]:
        return _refus(refus_courant or verdicts.verdict(
            "REJ-MEDIA-PROPRIETAIRE-REQUIS", "identité propriétaire expirée",
        ))
    try:
        journal.append(maillon, rang_attendu=len(journal))
    except EcritureConcurrente:
        return _refus(verdicts.verdict("REJ-MEDIA-CONFLIT-CONCURRENT", "le dossier a changé pendant la décision"))
    return {"accepte": True, "resultat": {"revision": revision, "decision": decision}}


def remettre_dossier_medias_manuel(creneau_id: str, horodatage: str) -> dict[str, Any]:
    """Scelle une remise manuelle seulement si texte, créneau, consentement et médias sont courants."""
    acteur, refus = _proprietaire_qui_decide("m7_remettre_dossier_medias_manuel")
    if acteur is None:
        return _refus(refus or verdicts.verdict(verdicts.REJ_HUMAIN_REQUIS, "remise réservée au propriétaire"))
    cnx = stockage.connexion_courante()
    if cnx is None or cnx.engine.dialect.name != "sqlite":
        return _refus(verdicts.verdict(
            "REJ-MEDIA-ECRITURE-NON-QUALIFIEE", "mutation média non qualifiée sur ce moteur de base",
        ))
    slot = next((c for c in _lire(REGISTRE_CALENDRIER) if c.get("creneau_id") == creneau_id), None)
    if slot is None:
        return _refus(verdicts.verdict("REJ-MEDIA-CRENEAU-INCONNU", "créneau absent"))
    vue_slot = next((c for c in lister_calendrier(slot.get("wct_id")).get("creneaux", [])
                     if c.get("creneau_id") == creneau_id), None)
    if vue_slot is None or vue_slot.get("statut") != "APPROVED":
        return _refus(verdicts.verdict("REJ-MEDIA-CRENEAU-NON-APPROUVE", "créneau courant approuvé requis"))
    snapshot, refus = _snapshot_media(slot["contenu_id"])
    if refus is not None:
        return _refus(refus)
    propositions = _lire(REGISTRE_CONTENUS_CHANTIER)
    proposition = registre.proposition_par_id(propositions, slot["contenu_id"])
    if proposition is None:
        return _refus(verdicts.verdict("REJ-MEDIA-CONTENU-PERIME", "contenu courant absent"))
    decisions = _lire(REGISTRE_DECISIONS_CONTENU)
    exports_contenu = stockage.maillons(*REGISTRE_EXPORTS_PAQUET)
    contenu = registre.vue(
        proposition, decisions, list(exports_contenu), _lire(REGISTRE_RETRAITS),
    )
    if contenu.get("approval_status") != registre.STATUT_APPROUVE:
        return _refus(verdicts.verdict("REJ-MEDIA-TEXTE-NON-APPROUVE", "approbation courante du texte requise"))
    approbation_texte = registre.decision_de(slot["contenu_id"], decisions)
    if approbation_texte is None or approbation_texte.get("empreinte_texte") != proposition.get("empreinte_texte"):
        return _refus(verdicts.verdict(
            verdicts.REJ_CONTENU_MODIFIE, "le texte courant ne correspond plus au texte approuvé",
        ))
    refus_texte = _refus_texte(proposition)
    if refus_texte is not None:
        return refus_texte
    if not calendrier.horodatage_valide(horodatage):
        return _refus(verdicts.verdict(verdicts.REJ_HORODATAGE_INVALIDE, "horodatage ISO 8601 avec fuseau requis"))
    journal = stockage.maillons(*REGISTRE_DOSSIERS_MEDIAS)
    etat = registre.etat_dossier_medias(journal, slot["contenu_id"])
    if not etat["valide"] or etat["statut"] not in {"APPROUVE", "REMIS"}:
        return _refus(verdicts.verdict("REJ-MEDIA-DOSSIER-NON-APPROUVE", "revue humaine du dossier courant requise"))
    if any(e.get("snapshot_sha256") != snapshot["snapshot_sha256"] for e in etat["evenements"]):
        return _refus(verdicts.verdict("REJ-MEDIA-SNAPSHOT-PERIME", "WCT, profil ou consentement a changé"))
    remise_existante = etat["remises"][-1] if etat["remises"] else None
    if remise_existante is not None and remise_existante.get("creneau_id") != creneau_id:
        return _refus(verdicts.verdict("REJ-MEDIA-DOSSIER-FIGE", "le dossier a déjà été remis et est figé"))
    medias = {m.get("source_ref"): m for m in etat["medias"]}
    if set(medias) != {s["source_ref"] for s in snapshot["snapshot"]["sources"]}:
        return _refus(verdicts.verdict("REJ-MEDIA-PREPARATION-INCOMPLETE", "préparé humain manquant"))
    fichiers_prepares = []
    for media in medias.values():
        lecture = fichiers.lire_blob_verifie(cnx, media.get("prepared_ref"))
        if (
            not lecture.accepte or lecture.octets is None
            or hashlib.sha256(lecture.octets).hexdigest() != media.get("prepared_sha256")
        ):
            return _refus(verdicts.verdict("REJ-MEDIA-BLOB-INVALIDE", "une variante préparée ne se vérifie plus"))
        fichiers_prepares.append(media["prepared_ref"])
    utm_content, refus_mesure = mesure.identifiant_de_mesure(proposition)
    if utm_content is None:
        return _refus(refus_mesure or verdicts.verdict(verdicts.REJ_CONTENU_SANS_IDENTIFIANT,
                                                       "clé de mesure absente"))
    export = registre.export_de(slot["contenu_id"], list(exports_contenu))
    if export is not None and (
        export.get("wct_id") != slot["wct_id"]
        or export.get("empreinte_texte") != proposition.get("empreinte_texte")
    ):
        return _refus(verdicts.verdict("REJ-MEDIA-EXPORT-PERIME", "export existant lié à une autre révision"))
    if remise_existante is not None:
        # Réémission après rafraîchissement du même geste : aucun nouvel événement ni identifiant.
        remise = remise_existante
        if (
            export is None or export.get("export_id") != remise.get("export_id")
            or remise.get("wct_id") != slot.get("wct_id")
            or remise.get("snapshot_sha256") != snapshot["snapshot_sha256"]
            or remise.get("empreinte_texte") != proposition.get("empreinte_texte")
            or remise.get("prepared_refs") != sorted(set(fichiers_prepares))
        ):
            return _refus(verdicts.verdict("REJ-MEDIA-EXPORT-PERIME", "export lié absent ou remplacé"))
        paquet_reponse = _composer_paquet_media(contenu, snapshot["snapshot"]["wct"], remise)
        return {"accepte": True, "resultat": {"remise": remise, "paquet": paquet_reponse}}
    if _proprietaire_qui_decide("m7_remettre_dossier_medias_manuel")[0] is None:
        return _refus(verdicts.verdict("REJ-MEDIA-PROPRIETAIRE-REQUIS", "identité propriétaire expirée avant remise"))
    if export is None:
        export, refus_export = paquet.construire_export(
            {**contenu, "utm_content": utm_content}, acteur["par"], _horodatage_faisant_foi(horodatage),
        )
        if refus_export is not None or export is None:
            return _refus(refus_export or verdicts.verdict("REJ-MEDIA-EXPORT-INVALIDE", "export refusé"))
        exports_contenu.append(export)
    media_export_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        json.dumps({"contenu_id": slot["contenu_id"], "dossier": etat["empreinte_dossier"]}, sort_keys=True),
    ))
    revision = etat["revision"] + 1
    remise = {
        "type_maillon": "media_remise", "contenu_id": slot["contenu_id"], "revision": revision,
        "revision_cible": etat["revision"], "empreinte_cible": etat["empreinte_dossier"],
        "snapshot_sha256": snapshot["snapshot_sha256"], "creneau_id": creneau_id, "wct_id": slot["wct_id"],
        "media_export_id": media_export_id, "export_id": export["export_id"],
        "prepared_refs": sorted(set(fichiers_prepares)),
        "empreinte_texte": proposition["empreinte_texte"], "remis_par": acteur["par"], "horodatage": horodatage,
    }
    try:
        journal.append(remise, rang_attendu=len(journal))
    except EcritureConcurrente:
        return _refus(verdicts.verdict("REJ-MEDIA-CONFLIT-CONCURRENT", "le dossier a changé pendant la remise"))
    _annoncer_contenu_exporte(proposition, utm_content, export["horodatage"])
    paquet_reponse = _composer_paquet_media(contenu, snapshot["snapshot"]["wct"], remise)
    return {"accepte": True, "resultat": {"remise": remise, "paquet": paquet_reponse}}


def _composer_paquet_media(
    contenu: dict[str, Any], charge: dict[str, Any], remise: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refus_texte = _refus_texte(registre.proposition_par_id(_lire(REGISTRE_CONTENUS_CHANTIER), contenu["contenu_id"]))
    if refus_texte is not None:
        return {"avertissement": "le paquet texte courant n'est plus vérifié"}
    proposition = registre.proposition_par_id(_lire(REGISTRE_CONTENUS_CHANTIER), contenu["contenu_id"])
    utm_content, refus = mesure.identifiant_de_mesure(proposition)
    if utm_content is None:
        return {"avertissement": (refus or {}).get("detail", "clé de mesure absente")}
    profil = brand_registre.lire_snapshot_marque().get("profil")
    composition = paquet.composer_paquet(
        {**contenu, "utm_content": utm_content}, charge, _lire(REGISTRE_CONTENU_PUBLIC), profil or {},
    )
    composition["marque_source"] = dict(proposition["marque_source"])
    if remise is None:
        return composition
    etat = registre.etat_dossier_medias(_lire(REGISTRE_DOSSIERS_MEDIAS), contenu["contenu_id"])
    return paquet.ajouter_medias_prepares(composition, etat, remise)


def lire_media_prive(contenu_id: str, reference: str, *, mode: str) -> tuple[bytes, str] | None:
    """Lit des octets pour la seule route console interne, jamais pour un outil/MCP."""
    if mode not in {"apercu", "remise"} or _proprietaire_console_actif() is None:
        return None
    snapshot, refus = _snapshot_media(contenu_id)
    if refus is not None:
        return None
    etat = registre.etat_dossier_medias(_lire(REGISTRE_DOSSIERS_MEDIAS), contenu_id)
    if not etat["valide"] or any(
        e.get("snapshot_sha256") != snapshot["snapshot_sha256"] for e in etat["evenements"]
    ):
        return None
    reference_autorisee = False
    if mode == "apercu":
        source_refs = {s["source_ref"] for s in snapshot["snapshot"]["sources"]}
        prepares = {m.get("prepared_ref") for m in etat["medias"]}
        reference_autorisee = reference in source_refs or reference in prepares
    elif mode == "remise" and etat["statut"] == "REMIS":
        for remise in etat["remises"]:
            if reference not in remise.get("prepared_refs", []):
                continue
            slot = next(
                (s for s in _lire(REGISTRE_CALENDRIER) if s.get("creneau_id") == remise.get("creneau_id")), None,
            )
            vue_slot = next((s for s in lister_calendrier(remise.get("wct_id")).get("creneaux", [])
                             if s.get("creneau_id") == remise.get("creneau_id")), None)
            exports = list(_lire(REGISTRE_EXPORTS_PAQUET))
            export = registre.export_de(contenu_id, exports)
            proposition = registre.proposition_par_id(_lire(REGISTRE_CONTENUS_CHANTIER), contenu_id)
            decisions = _lire(REGISTRE_DECISIONS_CONTENU)
            approbation = registre.decision_de(contenu_id, decisions)
            if (
                slot is not None and vue_slot is not None and vue_slot.get("statut") == "APPROVED"
                and export is not None and export.get("export_id") == remise.get("export_id")
                and proposition is not None
                and export.get("empreinte_texte") == proposition.get("empreinte_texte")
                and approbation is not None
                and approbation.get("empreinte_texte") == proposition.get("empreinte_texte")
                and _refus_texte(proposition) is None
                and registre.statut(proposition, decisions, _lire(REGISTRE_RETRAITS)) == registre.STATUT_APPROUVE
            ):
                reference_autorisee = True
                break
    if not reference_autorisee:
        return None
    cnx = stockage.connexion_courante()
    if cnx is None:
        return None
    lecture = fichiers.lire_blob_verifie(cnx, reference)
    if not lecture.accepte or lecture.octets is None or lecture.type_mime is None:
        return None
    if _proprietaire_console_actif() is None:
        return None
    return lecture.octets, lecture.type_mime


def _refus(verdict: dict[str, Any]) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdict}


# -- qui appelle, qui décide ----------------------------------------------------------------------------------------
def _appelant_confirme() -> contexte_appel.IdentiteAppelante | None:
    """La personne et le rôle du jeton d'appareil, SI la base les confirme à l'instant même (personne active
    portant encore ce rôle) ; `None` pour un appel d'agent, hors transaction, ou une identité périmée."""
    appelante = contexte_appel.identite_appelante()
    cnx = stockage.connexion_courante()
    if appelante is None or cnx is None:
        return None
    return approbations.signataire_valide(cnx, appelante)


def _refus_lecture_admin() -> dict[str, Any] | None:
    """Confirme l'admin avant une lecture ; la voie interne sans identité reste disponible."""
    if contexte_appel.identite_appelante() is None:
        return None
    appelante = _appelant_confirme()
    if appelante is None or appelante.role != "admin":
        return verdicts.verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            "lecture marketing réservée à une personne active portant le rôle admin confirmé en base",
        )
    return None


def _qui_appelle() -> tuple[str, str]:
    """`(personne, source)` : la personne du jeton confirmé, sinon « agent ». Sert la provenance, jamais un droit."""
    confirmee = _appelant_confirme()
    if confirmee is None:
        return ORIGINE_AGENT, ORIGINE_AGENT
    return confirmee.personne, regle_decision.SOURCE_APPAREIL


def _proprietaire_qui_decide(nom_outil: str) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Qui décide : `({par, role, source}, None)` si c'est le propriétaire, sinon `(None, verdict de refus)`.

    Deux voies, jamais une troisième, et jamais un texte de modèle ni un argument :
    1. un appel d'appareil dont l'identité (posée par le core d'après un jeton vérifié) est CONFIRMÉE en base,
       de rôle `admin`, et dont la PERSONNE porte `nathan_owner` (même plafond que l'app d'approbation du
       socle : un gestionnaire `admin` ne décide pas à la place du propriétaire) ;
    2. l'exécution d'une demande que le propriétaire vient d'approuver dans la file d'approbation : le SOCLE dit qui
       l'a approuvée (`approbations.approbateur_en_cours`, PLAN T4.15-d ; demande relue en base, personne active
       portant encore son rôle), et seul `nathan_owner` compte, même si la politique du département s'élargit. Les
       arguments ne sont pas comparés : `decider` rejoue les arguments EXACTS enregistrés et lui seul pose la
       demande en cours.
    Tout le reste est refusé : un appel d'agent qui n'a pas passé par l'approbation (un département en mode
    `supervise` ou `autonome` exécute un N3 sans file), un appel hors transaction où rien n'est vérifiable."""
    cnx = stockage.connexion_courante()
    appelante = contexte_appel.identite_appelante()
    if appelante is not None:
        confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
        if confirmee is None:
            return None, verdicts.verdict(
                verdicts.REJ_HUMAIN_IDENTITE_INVALIDE,
                f"personne {appelante.personne!r} inconnue, inactive, ou ne porte plus le rôle "
                f"{appelante.role!r} du jeton d'appareil (ou identité non vérifiable hors transaction)",
            )
        personne = identite.personne_active(cnx, confirmee.personne)
        if confirmee.role != "admin" or personne is None or regle_decision.ROLE_DECIDEUR not in personne.roles:
            return None, verdicts.verdict(
                verdicts.REJ_HUMAIN_ROLE_INSUFFISANT,
                "l'approbation d'un contenu public est réservée au propriétaire (appareil admin de la personne "
                f"portant {regle_decision.ROLE_DECIDEUR})",
            )
        return {
            "par": confirmee.personne,
            "role": regle_decision.ROLE_DECIDEUR,
            "source": regle_decision.SOURCE_APPAREIL,
        }, None
    # Lire l'approbateur réel sans filtrer en amont : un rôle N3 élargi par erreur à `admin` doit rester visible
    # ici afin que l'outil refuse explicitement le non-propriétaire (et ne masque pas le problème en « humain requis »).
    approbateur = approbations.approbateur_en_cours(cnx, nom_outil, DEPARTEMENT)
    if approbateur is not None:
        if approbateur.role not in ROLES_QUI_DECIDENT:
            return None, verdicts.verdict(
                verdicts.REJ_HUMAIN_ROLE_INSUFFISANT,
                "l'approbateur de la file ne porte pas le rôle propriétaire requis pour un contenu public",
            )
        return {
            "par": approbateur.personne,
            "role": approbateur.role,
            "source": regle_decision.SOURCE_APPROBATION,
        }, None
    return None, verdicts.verdict(
        verdicts.REJ_HUMAIN_REQUIS,
        "approuver ou rejeter un contenu est une décision humaine : un agent ne peut pas la prendre seul. Le "
        "propriétaire la prend depuis l'app admin (section « À voir »), ou approuve la demande dans la console "
        "OPSYS. Ne la présente pas comme faite.",
    )


def _horodatage_faisant_foi(horodatage: str) -> str:
    """Pendant un appel d'appareil idempotent, l'heure de RÉCEPTION du serveur fait foi, jamais l'horloge de
    l'appareil ni l'`horodatage` fourni (même patron que `m4_pointer`, T1.4-d, et M10)."""
    reception = contexte_appel.horodatage_reception()
    return reception.recu_le.isoformat() if reception is not None else horodatage


# -- la nature des travaux et le profil de marque -------------------------------------------------------------------
def nature_du_chantier(charge: dict[str, Any]) -> tuple[chantier.Nature | None, str | None]:
    """`(nature, None)` ou `(None, motif)`. Un lead v2 dit son `service` (code de la taxonomie de l'entreprise,
    jamais recopiée ici, résolue en libellé et en termes) ; un lead v1 dit son `type_travaux`. Jamais l'un déduit
    de l'autre, jamais les deux (donnée contradictoire), jamais une nature inventée pour continuer. Le motif ne
    porte que le code du verdict de la taxonomie : son détail nomme un chemin du serveur."""
    if "type_travaux" in charge and "service" in charge:
        return None, "type_travaux ET service dans le même WCT (lead v1 ou v2, jamais les deux) : aucun contenu"
    if "service" in charge:
        service, verdict = taxonomie.valider_service(charge["service"])
        if service is None:
            return None, (
                f"service {charge['service']!r} introuvable ({verdict['code']}) : déclarer les services de "
                "l'entreprise (profil d'entreprise de l'instance)"
            )
        return chantier.Nature(service.libelle, tuple(service.mots_cles)), None
    type_travaux = charge.get("type_travaux")
    if isinstance(type_travaux, str) and type_travaux.strip():
        mots = type_travaux.replace("_", " ").strip()
        return chantier.Nature(mots, (mots,)), None
    return None, "nature des travaux absente du WCT (ni service ni type_travaux) : aucun contenu sans elle"


def _valider_textes(textes: Any) -> dict[str, str]:
    if textes is None:
        return {}
    if not isinstance(textes, dict):
        raise ValueError("textes : un objet {plateforme: texte} est attendu")
    inconnues = sorted(set(textes) - set(plateformes.CODES_PLATEFORMES))
    if inconnues:
        attendues = ", ".join(plateformes.CODES_PLATEFORMES)
        raise ValueError(f"textes : plateforme inconnue {inconnues} (attendu : {attendues})")
    for code, texte in textes.items():
        if not isinstance(texte, str) or not texte.strip():
            raise ValueError(f"textes.{code} : un texte non vide est attendu")
    return dict(textes)


def _pret_a_composer(charge: dict[str, Any]) -> tuple[Any, chantier.Nature | None, dict[str, Any] | None]:
    """Les refus de départ, dans l'ordre de `chantier` puis la marque et la nature : `(snapshot, nature, None)`
    ou `(None, None, {statut, motif})`. Rien n'est écrit ici."""
    statut, motif = chantier.verifier_chantier(charge, _lire(REGISTRE_RETRAITS))
    if statut is not None:
        return None, None, {"statut": statut, "motif": motif}
    snapshot_marque = brand_registre.lire_snapshot_marque()
    profil, motif = snapshot_marque.get("profil"), snapshot_marque.get("motif")
    if profil is None:
        return None, None, {"statut": STATUT_PROFIL_MARQUE_NON_CONFIGURE, "motif": motif}
    nature, motif = nature_du_chantier(charge)
    if nature is None:
        return None, None, {"statut": chantier.STATUT_NATURE_INCONNUE, "motif": motif}
    return snapshot_marque, nature, None


# -- proposer -------------------------------------------------------------------------------------------------------
def proposer_pour_charge(charge: dict[str, Any], textes: dict[str, str] | None, origine: str) -> dict[str, Any]:
    """Compose et enregistre les contenus d'un chantier dont le WCT est déjà reçu. Utilisé par le consommateur
    du bus (`textes` absent : gabarits du code) et par l'outil (`textes` du modèle, contrôlés comme le reste).

    Rend `{statut, motif, contenus}` ; `contenus` dit, par plateforme, ce qui est proposé, déjà là, refusé (avec
    ses règles) ou à récrire. Un refus de départ n'écrit RIEN ; un texte refusé n'écrit rien non plus."""
    snapshot_marque, nature, refus = _pret_a_composer(charge)
    if refus is not None:
        return {**refus, "contenus": []}
    profil = snapshot_marque["profil"]
    registre_contenus = stockage.maillons(*REGISTRE_CONTENUS_CHANTIER)
    preparation = chantier.preparer(
        charge,
        profil,
        nature,
        textes,
        list(registre_contenus),
        _lire(REGISTRE_DECISIONS_CONTENU),
        origine,
        marque_source=snapshot_marque["preuve"],
        renouveler_marque=origine != ORIGINE_BUS,
    )
    registre_contenus.extend(preparation.nouvelles)
    return {"statut": preparation.statut, "motif": None, "contenus": list(preparation.items)}


def proposer_contenus_chantier(wct_id: str, textes: dict[str, str] | None = None) -> dict[str, Any]:
    """Outil `m7_proposer_contenus_chantier` : voir `proposer_pour_charge`. Le WCT vient du registre `wct_recus`,
    jamais d'un argument ; un `wct_id` inconnu refuse (`wct_inconnu`), il n'invente rien."""
    charge = wct_recu(wct_id)
    if charge is None:
        return {
            "statut": STATUT_WCT_INCONNU,
            "contenus": [],
            "motif": f"wct_id inconnu : {wct_id!r} — aucun m4.travaux_termines reçu pour ce wct_id",
        }
    textes_valides = _valider_textes(textes)
    personne, source = _qui_appelle()
    origine = f"{source}:{personne}" if source == regle_decision.SOURCE_APPAREIL else ORIGINE_AGENT
    return proposer_pour_charge(charge, textes_valides, origine)


def lire_matiere_chantier(wct_id: str) -> dict[str, Any]:
    """Outil `m7_lire_matiere_chantier` (T0) : ce dont le modèle a besoin pour rédiger, et ce qui le refusera.
    Les mêmes refus que `proposer_contenus_chantier` (inutile de rédiger pour un chantier refusé). La note du
    chantier n'est montrée que si elle passe le contrôle des textes publics."""
    charge = wct_recu(wct_id)
    if charge is None:
        return {
            "statut": STATUT_WCT_INCONNU,
            "motif": f"wct_id inconnu : {wct_id!r} — aucun m4.travaux_termines reçu pour ce wct_id",
        }
    snapshot_marque, nature, refus = _pret_a_composer(charge)
    if refus is not None:
        return refus
    profil = snapshot_marque["profil"]
    matiere, avertissements = chantier.matiere_du_chantier(charge, profil, nature)
    description, motif_description = chantier.description_utilisable(charge, profil)
    ton = profil.get("tone")
    return {
        "statut": STATUT_OK,
        "marque_source": snapshot_marque["preuve"],
        "matiere": {
            "marque": matiere.marque,
            "accroche": matiere.accroche or None,
            "ton": ton
            if isinstance(ton, str) and not ton.casefold().startswith(chantier.MARQUEUR_NON_CONFIGURE)
            else None,
            "nature": matiere.nature,
            "ville": matiere.ville,
            "note_du_chantier": description,
            "photos": len([p for p in (charge.get("photos") or []) if isinstance(p, str)]),
            "mots_clics": list(chantier.mots_clics(nature, matiere.ville, profil)),
            "garanties_validees": [g for g in (profil.get("garanties_validees") or []) if isinstance(g, str)],
        },
        "plateformes": [
            {"code": p.code, "libelle": p.libelle, "public": p.public, "longueur_max": p.longueur_max, "media": p.media}
            for p in plateformes.PLATEFORMES
        ],
        "regles": dict(LIBELLES_REGLES),
        "avertissements": [
            *snapshot_marque["avertissements"], *avertissements, *([motif_description] if motif_description else []),
        ],
    }


# -- lire la file --------------------------------------------------------------------------------------------------
def _ligne_contenu(vue: dict[str, Any], preuve_marque: Any = None) -> dict[str, Any]:
    preuve = vue["preuve_consentement"]
    return {
        "contenu_id": vue["contenu_id"],
        "wct_id": vue["wct_id"],
        "plateforme": vue["plateforme"],
        "revision": vue["revision"],
        "approval_status": vue["approval_status"],
        "exporte": vue["exporte"],
        "marque_source": vue.get("marque_source"),
        "fraicheur_marque": registre.fraicheur_marque(vue, preuve_marque),
        "texte": vue["texte"],
        "origine_texte": vue["origine_texte"],
        "mots_clics": vue["mots_clics"],
        "lien_utm": vue["lien_utm"],
        "avertissements": vue["avertissements"],
        "decision": vue["decision"],
        "consentement": {
            "recueilli_par": preuve["recueilli_par"],
            "recueilli_le": preuve["recueilli_le"],
            "version_texte": preuve["version_texte"],
        },
    }


def lister_contenus_chantier(
    wct_id: str | None = None,
    statut: str | None = None,
    limite: int = LIMITE_LISTE_DEFAUT,
    decalage: int = 0,
) -> dict[str, Any]:
    """Outil `m7_lister_contenus_chantier` (T0, `admin`) : les contenus du moment (la dernière révision de
    chaque plateforme de chaque chantier), les plus récents d'abord, avec leur statut, leur texte ENTIER (on ne
    décide pas ce qu'on n'a pas lu), leur décision et la preuve du consentement. Bornée : `Capacites` tronque
    à 6 000 caractères ; `suivant` est le `decalage` de la page suivante, `null` quand rien ne suit."""
    refus = _refus_lecture_admin()
    if refus is not None:
        return _refus(refus)
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= LIMITE_LISTE_MAX:
        raise ValueError(f"limite : un entier de 1 à {LIMITE_LISTE_MAX} est attendu")
    if isinstance(decalage, bool) or not isinstance(decalage, int) or decalage < 0:
        raise ValueError("decalage : un entier de 0 ou plus est attendu")
    if statut is not None and statut not in registre.STATUTS:
        raise ValueError(f"statut : {', '.join(registre.STATUTS)} (ou absent)")
    decisions, exports = _lire(REGISTRE_DECISIONS_CONTENU), _lire(REGISTRE_EXPORTS_PAQUET)
    retraits = _lire(REGISTRE_RETRAITS)
    courantes = registre.dernieres_revisions(_lire(REGISTRE_CONTENUS_CHANTIER), wct_id)
    vues = [registre.vue(p, decisions, exports, retraits) for p in reversed(courantes)]
    if statut is not None:
        vues = [v for v in vues if v["approval_status"] == statut]
    preuve_marque = brand_registre.lire_snapshot_marque().get("preuve")
    lignes: list[dict[str, Any]] = []
    taille = 0
    for vue in vues[decalage : decalage + limite]:
        ligne = _ligne_contenu(vue, preuve_marque)
        cout = len(json.dumps(ligne, ensure_ascii=False))
        if cout > BUDGET_LISTE:
            raise ValueError("contenu trop volumineux pour une lecture complète bornée ; aucune troncature de texte")
        if lignes and taille + cout > BUDGET_LISTE:
            break
        lignes.append(ligne)
        taille += cout
    apres = decalage + len(lignes)
    return {
        "total": len(vues),
        "marque_courante": preuve_marque,
        "contenus": lignes,
        "decalage": decalage,
        "suivant": apres if lignes and apres < len(vues) else None,
        "reste": max(0, len(vues) - apres),
    }


# -- décider ---------------------------------------------------------------------------------------------------------
def _refus_marque(proposition: Any, snapshot: dict[str, Any] | None = None) -> dict[str, Any] | None:
    snapshot = snapshot if snapshot is not None else brand_registre.lire_snapshot_marque()
    if snapshot.get("statut") != "configure":
        return _refus(verdicts.verdict(verdicts.REJ_PROFIL_MARQUE, "marque courante indisponible ou invalide"))
    fraicheur = registre.fraicheur_marque(proposition, snapshot["preuve"])
    if fraicheur == "courante":
        return None
    code = "REJ-MARQUE-PREUVE-ABSENTE" if fraicheur == "preuve_absente" else "REJ-MARQUE-PERIMEE"
    return _refus(verdicts.verdict(code, "Marque non qualifiée : proposer explicitement une nouvelle révision."))


def verifier_marque_commande(nom: str, arguments: Mapping[str, Any], *, rejeu: bool = False) -> dict[str, Any] | None:
    """Préflight métier console, sous transaction, AVANT son cache de reçu.

    Le port MCP générique rejoue son reçu historique sans ce hook ; ce n'est pas
    une nouvelle décision/remise. Il n'offre pas ce refus actualisé (lot SDK séparé).
    """
    if stockage.connexion_courante() is None:
        raise RuntimeError("revalidation de marque hors transaction")
    contenu_id = arguments.get("contenu_id")
    if "creneau_id" in arguments:
        slot = next((c for c in _lire(REGISTRE_CALENDRIER) if c["creneau_id"] == arguments["creneau_id"]), None)
        contenu_id = slot.get("contenu_id") if slot is not None else None
    if nom not in {"m7_decider_contenu", "m7_proposer_creneau_calendrier", "m7_decider_creneau_calendrier",
                   "m7_exporter_creneau_manuel", "m7_decider_dossier_medias", "m7_remettre_dossier_medias_manuel"}:
        return None
    proposition = registre.proposition_par_id(_lire(REGISTRE_CONTENUS_CHANTIER), contenu_id)
    if proposition is None:
        return None
    if rejeu and retrait.retrait_applicable(
        proposition["wct_id"], proposition.get("lead_id"), _lire(REGISTRE_RETRAITS),
    ) is not None:
        return _refus(verdicts.verdict(
            verdicts.REJ_CONSENTEMENT_RETIRE, "consentement retiré : reçu historique non remis",
        ))
    if rejeu and not registre.est_derniere_revision(proposition, _lire(REGISTRE_CONTENUS_CHANTIER)):
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_PERIME, "une révision plus récente existe"))
    # Un rejet motivé n'approuve rien et ne qualifie pas l'ancienne preuve.
    return None if arguments.get("decision") == "rejeter" else _refus_marque(proposition)


def _contexte_du_contenu(proposition: dict[str, Any], profil: dict[str, Any]) -> Any:
    charge = wct_recu(proposition["wct_id"]) or {"wct_id": proposition["wct_id"]}
    return chantier.contexte_controle(charge, profil, plateformes.plateforme(proposition["plateforme"]).longueur_max)


def _refus_texte(proposition: dict[str, Any]) -> dict[str, Any] | None:
    """Le texte enregistré passe-t-il encore le contrôle ? (défense en profondeur : à l'approbation comme à
    l'export, jamais seulement à la proposition.) `None` s'il passe ; sinon le refus, qui nomme les règles."""
    snapshot_marque = brand_registre.lire_snapshot_marque()
    profil, motif = snapshot_marque.get("profil"), snapshot_marque.get("motif")
    if profil is None:
        return _refus(verdicts.verdict(verdicts.REJ_PROFIL_MARQUE, str(motif)))
    violations = controler_texte(proposition["texte"], _contexte_du_contenu(proposition, profil))
    if not violations:
        return _refus_marque(proposition, snapshot_marque)
    return _refus(chantier.verdict_texte_non_conforme([v.regle for v in violations]))


def decider_contenu(contenu_id: str, decision: str, horodatage: str, motif: str = "") -> dict[str, Any]:
    """Outil `m7_decider_contenu` : le propriétaire approuve ou rejette un contenu proposé (N3, « À voir »).

    Ordre (chaque refus intervient avant toute écriture) : qui décide (un humain, le propriétaire) ; le contenu
    existe ; son consentement n'est pas retiré ; c'est la dernière révision ; il est encore `PROPOSE` ; pour une
    approbation, son texte passe encore le contrôle. La décision porte l'empreinte du texte décidé."""
    acteur, refus = _proprietaire_qui_decide("m7_decider_contenu")
    if acteur is None:
        return _refus(refus or verdicts.verdict(verdicts.REJ_HUMAIN_REQUIS, "acteur humain introuvable"))
    propositions = _lire(REGISTRE_CONTENUS_CHANTIER)
    proposition = registre.proposition_par_id(propositions, contenu_id)
    if proposition is None:
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_INCONNU, f"contenu inconnu : {contenu_id!r}"))
    decisions, retraits = _lire(REGISTRE_DECISIONS_CONTENU), _lire(REGISTRE_RETRAITS)
    statut = registre.statut(proposition, decisions, retraits)
    if statut == registre.STATUT_RETIRE:
        return _refus(
            verdicts.verdict(
                verdicts.REJ_CONSENTEMENT_RETIRE,
                "le client a retiré son consentement marketing : rien à décider",
            )
        )
    if not registre.est_derniere_revision(proposition, propositions):
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_PERIME, "une révision plus récente existe pour ce contenu"))
    if statut != registre.STATUT_PROPOSE:
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_DEJA_TRANCHE, f"contenu déjà tranché ({statut})"))
    if decision == regle_decision.DECISION_APPROUVER:
        refus_texte = _refus_texte(proposition)
        if refus_texte is not None:
            return refus_texte
    maillon, verdict = regle_decision.construire_decision(
        proposition,
        decision,
        acteur["par"],
        acteur["role"],
        acteur["source"],
        motif,
        _horodatage_faisant_foi(horodatage),
    )
    if verdict is not None:
        return _refus(verdict)
    if proposition.get("marque_source") is not None:
        maillon = {**maillon, "marque_source": dict(proposition["marque_source"])}
    stockage.maillons(*REGISTRE_DECISIONS_CONTENU).append(maillon)
    approuve = maillon["decision"] == registre.STATUT_APPROUVE
    return {
        "accepte": True,
        "resultat": {
            "contenu_id": contenu_id,
            "plateforme": proposition["plateforme"],
            "approval_status": maillon["decision"],
            "par": maillon["par"],
            "source": maillon["source"],
            "horodatage": maillon["horodatage"],
            "empreinte_texte": maillon["empreinte_texte"],
            "prochaine_etape": "m7_exporter_paquet_manuel : le paquet à publier toi-même"
            if approuve
            else "un nouveau texte (textes de m7_proposer_contenus_chantier) crée une révision",
        },
    }


# -- exporter -------------------------------------------------------------------------------------------------------
def exporter_paquet_manuel(contenu_id: str, horodatage: str) -> dict[str, Any]:
    """Outil `m7_exporter_paquet_manuel` : le paquet manuel d'un contenu APPROUVÉ. Ne publie rien, n'appelle
    aucune API : il remet au propriétaire le texte, les mots-clics, le lien, les médias (« à flouter à la
    main »), l'heure suggérée du profil, les instructions. Refuse un contenu non approuvé, un chantier dont le
    consentement est retiré, un texte modifié depuis l'approbation ou qui ne passe plus le contrôle. La trace de
    l'export s'écrit une seule fois ; un second appel rend le même paquet (`deja_exporte`)."""
    propositions = _lire(REGISTRE_CONTENUS_CHANTIER)
    proposition = registre.proposition_par_id(propositions, contenu_id)
    if proposition is None:
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_INCONNU, f"contenu inconnu : {contenu_id!r}"))
    decisions, exports = _lire(REGISTRE_DECISIONS_CONTENU), _lire(REGISTRE_EXPORTS_PAQUET)
    retraits = _lire(REGISTRE_RETRAITS)
    contenu = registre.vue(proposition, decisions, exports, retraits)
    if contenu["approval_status"] == registre.STATUT_RETIRE:
        return _refus(
            verdicts.verdict(
                verdicts.REJ_CONSENTEMENT_RETIRE,
                "le client a retiré son consentement marketing : aucun export",
            )
        )
    if contenu["approval_status"] != registre.STATUT_APPROUVE:
        return _refus(
            verdicts.verdict(
                verdicts.REJ_CONTENU_NON_APPROUVE,
                f"contenu {contenu['approval_status']} : le propriétaire l'approuve d'abord (m7_decider_contenu)",
            )
        )
    approbation = registre.decision_de(contenu_id, decisions)
    if approbation is None or approbation["empreinte_texte"] != proposition["empreinte_texte"]:
        return _refus(
            verdicts.verdict(
                verdicts.REJ_CONTENU_MODIFIE,
                "le texte n'est plus celui que le propriétaire a approuvé : aucun export",
            )
        )
    refus_texte = _refus_texte(proposition)
    if refus_texte is not None:
        return refus_texte
    utm_content, refus_mesure = mesure.identifiant_de_mesure(proposition)
    if utm_content is None:
        return _refus(refus_mesure or verdicts.verdict(verdicts.REJ_CONTENU_SANS_IDENTIFIANT, "clé de mesure absente"))
    contenu = {**contenu, "utm_content": utm_content}
    profil = brand_registre.lire_snapshot_marque().get("profil")
    charge = wct_recu(proposition["wct_id"]) or {}
    composition = paquet.composer_paquet(contenu, charge, _lire(REGISTRE_CONTENU_PUBLIC), profil or {})
    composition["marque_source"] = dict(proposition["marque_source"])
    export = registre.export_de(contenu_id, exports)
    deja_exporte = export is not None
    if export is None:
        personne, _source = _qui_appelle()
        maillon, verdict = paquet.construire_export(contenu, personne, _horodatage_faisant_foi(horodatage))
        if verdict is not None:
            return _refus(verdict)
        maillon = {**maillon, "marque_source": dict(proposition["marque_source"])}
        stockage.maillons(*REGISTRE_EXPORTS_PAQUET).append(maillon)
        export = maillon
    return {
        "accepte": True,
        "resultat": {
            **composition,
            "deja_exporte": deja_exporte,
            "mesure": _annoncer_contenu_exporte(proposition, utm_content, export["horodatage"]),
        },
    }


# -- calendrier éditorial durable ----------------------------------------------------------------------------
def proposer_creneau_calendrier(contenu_id: str, planifie_le: str, horodatage: str) -> dict[str, Any]:
    """Ajoute de façon idempotente un brouillon calendaire pour un contenu chantier déjà approuvé.

    `planifie_le` est une intention avec fuseau, pas une commande de publication. Le WCT et l'empreinte source
    sont résolus depuis les registres canoniques ; les arguments ne peuvent pas fournir de faits de chantier.
    """
    propositions = _lire(REGISTRE_CONTENUS_CHANTIER)
    proposition = registre.proposition_par_id(propositions, contenu_id)
    if proposition is None:
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_INCONNU, f"contenu inconnu : {contenu_id!r}"))
    vues = registre.vue(
        proposition, _lire(REGISTRE_DECISIONS_CONTENU), _lire(REGISTRE_EXPORTS_PAQUET), _lire(REGISTRE_RETRAITS)
    )
    if vues["approval_status"] == registre.STATUT_RETIRE:
        return _refus(verdicts.verdict(verdicts.REJ_CONSENTEMENT_RETIRE, "consentement retiré : créneau refusé"))
    if vues["approval_status"] != registre.STATUT_APPROUVE:
        return _refus(
            verdicts.verdict(
                verdicts.REJ_CONTENU_NON_APPROUVE, "le contenu doit être approuvé avant de créer un créneau"
            )
        )
    refus_marque = _refus_marque(proposition)
    if refus_marque is not None:
        return refus_marque
    if not calendrier.horodatage_valide(horodatage):
        return _refus(verdicts.verdict(verdicts.REJ_HORODATAGE_INVALIDE, "horodatage ISO 8601 avec fuseau requis"))
    charge = wct_recu(proposition["wct_id"])
    if charge is None:
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_INCONNU, "WCT source absent du registre M7"))
    if (
        not isinstance(charge.get("hash_maillon"), str)
        or not charge.get("hash_maillon")
        or not calendrier.horodatage_valide(charge.get("horodatage_completion"))
    ):
        return _refus(verdicts.verdict("REJ-SOURCE-WCT-INCOMPLETE", "preuve hash/heure du WCT indisponible"))
    maillon = calendrier.creer_creneau(proposition, charge, planifie_le, _horodatage_faisant_foi(horodatage))
    if maillon is None:
        return _refus(verdicts.verdict(verdicts.REJ_HORODATAGE_INVALIDE, "planifie_le doit être ISO 8601 avec fuseau"))
    cree_par, origine = _qui_appelle()
    maillon = {**maillon, "cree_par": cree_par, "origine": origine}
    journal = stockage.maillons(*REGISTRE_CALENDRIER)
    existant = next((c for c in journal if c["creneau_id"] == maillon["creneau_id"]), None)
    if existant is not None and existant["empreinte_creneau"] != maillon["empreinte_creneau"]:
        return _refus(verdicts.verdict("REJ-CRENEAU-CONFLIT", "identifiant de créneau lié à une autre version"))
    if existant is None:
        journal.append(maillon)
        existant = maillon
    vue_slot = next(
        c for c in lister_calendrier(existant["wct_id"])["creneaux"] if c["creneau_id"] == existant["creneau_id"]
    )
    return {"accepte": True, "resultat": {**vue_slot, "deja_present": existant is not maillon}}


def lister_calendrier(wct_id: str | None = None) -> dict[str, Any]:
    """État reconstruit des journaux durables, avec retrait et décision actuels."""
    propositions = _lire(REGISTRE_CONTENUS_CHANTIER)
    decisions_contenu, retraits = _lire(REGISTRE_DECISIONS_CONTENU), _lire(REGISTRE_RETRAITS)
    resultat = []
    preuve_marque = brand_registre.lire_snapshot_marque().get("preuve")
    for slot in _lire(REGISTRE_CALENDRIER):
        if wct_id is not None and slot["wct_id"] != wct_id:
            continue
        proposition = registre.proposition_par_id(propositions, slot["contenu_id"])
        if proposition is None:
            continue
        statut_contenu = registre.statut(proposition, decisions_contenu, retraits)
        resultat.append(
            calendrier.etat(
                slot, _lire(REGISTRE_DECISIONS_CALENDRIER), _lire(REGISTRE_EXPORTS_CALENDRIER), statut_contenu
            )
        )
        resultat[-1]["fraicheur_marque"] = registre.fraicheur_marque(proposition, preuve_marque)
        charge = wct_recu(slot["wct_id"])
        if (
            charge is None
            or slot.get("wct_empreinte") != charge.get("hash_maillon")
            or slot.get("wct_termine_le") != charge.get("horodatage_completion")
        ):
            resultat[-1]["statut"] = "CONFLIT_SOURCE"
    return {"creneaux": resultat, "publication": "aucune publication ni programmation automatisée"}


def decider_creneau_calendrier(creneau_id: str, decision: str, horodatage: str, motif: str = "") -> dict[str, Any]:
    """Décision du propriétaire sur le créneau exact. Elle ne vaut pas approbation du texte ni publication."""
    acteur, refus = _proprietaire_qui_decide("m7_decider_creneau_calendrier")
    if acteur is None:
        return _refus(refus or verdicts.verdict(verdicts.REJ_HUMAIN_REQUIS, "acteur humain introuvable"))
    slot = next((c for c in _lire(REGISTRE_CALENDRIER) if c["creneau_id"] == creneau_id), None)
    if slot is None:
        return _refus(verdicts.verdict("REJ-CRENEAU-INCONNU", f"créneau inconnu : {creneau_id!r}"))
    if decision not in ("approuver", "rejeter"):
        return _refus(verdicts.verdict(verdicts.REJ_DECISION_INVALIDE, "decision : approuver ou rejeter"))
    if not calendrier.empreinte_valide(slot):
        return _refus(verdicts.verdict("REJ-CRENEAU-CONFLIT", "le créneau a changé depuis sa création"))
    charge = wct_recu(slot["wct_id"])
    if charge is None or slot.get("wct_empreinte") != charge.get("hash_maillon"):
        return _refus(verdicts.verdict("REJ-CRENEAU-CONFLIT", "preuve WCT différente de la source du créneau"))
    vue_slot = next((c for c in lister_calendrier(slot["wct_id"])["creneaux"] if c["creneau_id"] == creneau_id), None)
    if vue_slot is None or vue_slot["statut"] == "RETIRE":
        return _refus(verdicts.verdict(verdicts.REJ_CONSENTEMENT_RETIRE, "consentement retiré"))
    refus_marque = verifier_marque_commande(
        "m7_decider_creneau_calendrier", {"creneau_id": creneau_id, "decision": decision},
    )
    if refus_marque is not None:
        return refus_marque
    decision_visee = "APPROVED" if decision == "approuver" else "REJECTED"
    if vue_slot["decision"] is not None:
        if vue_slot["decision"]["decision"] == decision_visee:
            return {"accepte": True, "resultat": {**vue_slot["decision"], "deja_tranche": True}}
        return _refus(verdicts.verdict("REJ-CRENEAU-CONFLIT", "une décision opposée est déjà inscrite"))
    if vue_slot["statut"] != "BROUILLON":
        return _refus(verdicts.verdict("REJ-CRENEAU-DEJA-TRANCHE", f"créneau déjà tranché ({vue_slot['statut']})"))
    if decision == "rejeter" and (not isinstance(motif, str) or len(motif.strip()) < 5):
        return _refus(verdicts.verdict(verdicts.REJ_MOTIF_REQUIS, "un rejet explique le motif (5 caractères minimum)"))
    if not calendrier.horodatage_valide(horodatage):
        return _refus(verdicts.verdict(verdicts.REJ_HORODATAGE_INVALIDE, "horodatage ISO 8601 avec fuseau requis"))
    prop = registre.proposition_par_id(_lire(REGISTRE_CONTENUS_CHANTIER), slot["contenu_id"])
    if prop is None or prop["empreinte_texte"] != slot["empreinte_texte"]:
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_MODIFIE, "source du créneau a changé"))
    maillon = {
        "type": "decision_creneau",
        "creneau_id": creneau_id,
        "decision": decision_visee,
        "par": acteur["par"],
        "role": acteur["role"],
        "source": acteur["source"],
        "motif": motif.strip(),
        "horodatage": _horodatage_faisant_foi(horodatage),
        "empreinte_creneau": slot["empreinte_creneau"],
    }
    stockage.maillons(*REGISTRE_DECISIONS_CALENDRIER).append(maillon)
    return {"accepte": True, "resultat": maillon}


def exporter_creneau_manuel(creneau_id: str, horodatage: str) -> dict[str, Any]:
    """Remise manuelle explicitement demandée par le propriétaire; n'appelle aucune plateforme."""
    acteur, refus = _proprietaire_qui_decide("m7_exporter_creneau_manuel")
    if acteur is None:
        return _refus(refus or verdicts.verdict(verdicts.REJ_HUMAIN_REQUIS, "export réservé au propriétaire"))
    slot = next((c for c in _lire(REGISTRE_CALENDRIER) if c["creneau_id"] == creneau_id), None)
    if slot is None:
        return _refus(verdicts.verdict("REJ-CRENEAU-INCONNU", f"créneau inconnu : {creneau_id!r}"))
    if not calendrier.empreinte_valide(slot):
        return _refus(verdicts.verdict("REJ-CRENEAU-CONFLIT", "le créneau a changé depuis sa création"))
    charge = wct_recu(slot["wct_id"])
    if charge is None or slot.get("wct_empreinte") != charge.get("hash_maillon"):
        return _refus(verdicts.verdict("REJ-CRENEAU-CONFLIT", "preuve WCT différente de la source du créneau"))
    vue_slot = next((c for c in lister_calendrier(slot["wct_id"])["creneaux"] if c["creneau_id"] == creneau_id), None)
    if vue_slot is None or vue_slot["statut"] == "RETIRE":
        return _refus(verdicts.verdict(verdicts.REJ_CONSENTEMENT_RETIRE, "consentement retiré : export refusé"))
    if vue_slot["statut"] != "APPROVED":
        return _refus(verdicts.verdict("REJ-CRENEAU-NON-APPROUVE", "approbation du créneau requise"))
    if not calendrier.horodatage_valide(horodatage):
        return _refus(verdicts.verdict(verdicts.REJ_HORODATAGE_INVALIDE, "horodatage ISO 8601 avec fuseau requis"))
    paquet_reponse = exporter_paquet_manuel(slot["contenu_id"], horodatage)
    if not paquet_reponse.get("accepte"):
        return paquet_reponse
    exports = stockage.maillons(*REGISTRE_EXPORTS_CALENDRIER)
    export = next((e for e in exports if e["creneau_id"] == creneau_id), None)
    deja_exporte = export is not None
    if export is None:
        export = {
            "type": "export_creneau_manuel",
            "creneau_id": creneau_id,
            "contenu_id": slot["contenu_id"],
            "wct_id": slot["wct_id"],
            "empreinte_texte": slot["empreinte_texte"],
            "exporte_par": acteur["par"],
            "source": "remise_manuelle_proprietaire",
            "source_wct": slot["source"],
            "horodatage": _horodatage_faisant_foi(horodatage),
        }
        exports.append(export)
    return {
        "accepte": True,
        "resultat": {
            "creneau_id": creneau_id,
            "export": export,
            "deja_exporte": deja_exporte,
            "paquet": paquet_reponse["resultat"],
            "publication": "non publiée; publication humaine dans la plateforme officielle",
        },
    }


def _annoncer_contenu_exporte(proposition: dict[str, Any], utm_content: str, exporte_le: str) -> dict[str, str]:
    """Annonce au bus `m7.contenu_exporte`, dans la transaction de l'export (PLAN T4.17-e). L'identifiant du fait est
    celui du contenu : un export rejoué republie le même, un no-op de l'outbox. Republier à chaque appel rattrape un
    paquet exporté avant l'existence du fait (le ré-exporter, c'est l'annoncer), sans jamais annoncer deux fois."""
    evenement_id = mesure.evenement_id(proposition["contenu_id"])
    deja_annonce = evenements.deja_publie(evenement_id)
    evenements.publier(
        mesure.TYPE_EVENEMENT,
        DEPARTEMENT,
        mesure.charge_contenu_exporte(proposition, utm_content, exporte_le),
        evenement_id=evenement_id,
    )
    return {"fait": mesure.TYPE_EVENEMENT, "statut": STATUT_DEJA_ANNONCE if deja_annonce else STATUT_ANNONCE}


# -- retirer le consentement ----------------------------------------------------------------------------------
def enregistrer_retrait_consentement_marketing(wct_id: str, canal: str, horodatage: str) -> dict[str, Any]:
    """Outil `m7_enregistrer_retrait_consentement_marketing` (Loi 25) : le client a retiré son consentement à
    l'usage de son chantier en contenu public. Écrit une fois, ne se lève pas ; bloque à l'instant toute tâche
    de contenu de ce chantier (et des chantiers du même lead), y compris un paquet déjà proposé ou approuvé.
    Idempotent. La réponse dit ce qui est bloqué et ce qui, exporté, doit être retiré à la main."""
    charge = wct_recu(wct_id) if isinstance(wct_id, str) else None
    lead_id = charge.get("lead_id") if charge is not None else None
    personne, source = _qui_appelle()
    maillon, verdict = retrait.construire_retrait(
        wct_id,
        lead_id,
        canal,
        personne,
        source,
        _horodatage_faisant_foi(horodatage),
    )
    if verdict is not None:
        return _refus(verdict)
    retraits = _lire(REGISTRE_RETRAITS)
    existant = next(
        (
            r
            for r in retraits
            if r["retrait_id"] == maillon["retrait_id"] and (not lead_id or r.get("lead_id") == lead_id)
        ),
        None,
    )
    if existant is None:
        retrait_precedent = next((r for r in retraits if r.get("retrait_id") == maillon["retrait_id"]), None)
        if retrait_precedent is not None and lead_id:
            maillon = {
                **maillon,
                "type_maillon": "liaison_lead",
                "source_wct": {"wct_id": wct_id, "hash_maillon": charge.get("hash_maillon"),
                               "horodatage_completion": charge.get("horodatage_completion")},
            }
        stockage.maillons(*REGISTRE_RETRAITS).append(maillon)
        existant = maillon
    elif lead_id and not any(
        r["retrait_id"] == maillon["retrait_id"] and r.get("lead_id") == lead_id for r in retraits
    ):
        # Le retrait initial demeure inchangé. Quand le WCT canonique arrive, ajouter un maillon de liaison
        # append-only permet d'étendre ce retrait aux autres chantiers du lead sans réécrire l'historique.
        liaison = {**existant, "lead_id": lead_id, "type_maillon": "liaison_lead"}
        stockage.maillons(*REGISTRE_RETRAITS).append(liaison)
        existant = liaison
    contenus_bloques, deja_exportes = _contenus_touches_par([existant])
    a_faire = []
    if deja_exportes:
        a_faire.append(A_FAIRE_PAQUET_EXPORTE)
    if charge is None:
        a_faire.append(
            "wct_id inconnu de M7 : le retrait est enregistré et bloquera ce chantier s'il arrive ; vérifier le wct_id"
        )
    return {
        "accepte": True,
        "resultat": {
            "retrait_id": existant["retrait_id"],
            "wct_id": existant["wct_id"],
            "lead_id": existant["lead_id"],
            "wct_connu": charge is not None,
            "deja_enregistre": existant is not maillon,
            "contenus_bloques": contenus_bloques,
            "contenus_deja_exportes": deja_exportes,
            "a_faire": a_faire,
        },
    }


def rattacher_retraits_au_wct(charge: dict[str, Any]) -> int:
    """Lie append-only les retraits antérieurs de ce WCT à son lead prouvé à la réception.

    L'événement M4 est le seul producteur du lien rétroactif. Le fait de retrait original n'est jamais réécrit;
    un maillon de liaison contient le lead, le hash du WCT et son horodatage source. Le rejeu du WCT est un no-op.
    """
    wct_id, lead_id = charge.get("wct_id"), charge.get("lead_id")
    hash_wct, termine_le = charge.get("hash_maillon"), charge.get("horodatage_completion")
    if not all(isinstance(valeur, str) and valeur.strip() for valeur in (wct_id, lead_id, hash_wct, termine_le)):
        return 0
    journal = stockage.maillons(*REGISTRE_RETRAITS)
    retraits = list(journal)
    deja_lies = {
        (r.get("retrait_id"), r.get("lead_id")) for r in retraits
        if r.get("wct_id") == wct_id and r.get("lead_id") == lead_id
    }
    nouveaux = []
    for retrait_initial in retraits:
        cle = (retrait_initial.get("retrait_id"), lead_id)
        if retrait_initial.get("wct_id") != wct_id or retrait_initial.get("lead_id") is not None or cle in deja_lies:
            continue
        nouveaux.append({
            **retrait_initial,
            "lead_id": lead_id,
            "type_maillon": "liaison_lead",
            "source_wct": {"wct_id": wct_id, "hash_maillon": hash_wct,
                           "horodatage_completion": termine_le},
        })
        deja_lies.add(cle)
    for maillon in nouveaux:
        journal.append(maillon)
    return len(nouveaux)


def _contenus_touches_par(retraits: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """`(contenus bloqués, dont déjà exportés)` : les contenus courants que ces retraits bloquent, par chantier ou
    par lead. Un paquet exporté a pu être publié à la main : M7 ne publie jamais, il le dit."""
    concernes = [
        p
        for p in registre.dernieres_revisions(_lire(REGISTRE_CONTENUS_CHANTIER))
        if any(retrait.retrait_applicable(p["wct_id"], p.get("lead_id"), [r]) is not None for r in retraits)
    ]
    exports = _lire(REGISTRE_EXPORTS_PAQUET)
    deja_exportes = [p["contenu_id"] for p in concernes if registre.export_de(p["contenu_id"], exports) is not None]
    return [p["contenu_id"] for p in concernes], deja_exportes


def enregistrer_retrait_de_leads(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m1.retrait_consentement` (PLAN T4.17-c) : le client a écrit STOP à M1, qui dit au bus quels leads
    il avait ouverts pour lui. M7 inscrit UN retrait par lead (`retraits_consentement_marketing`, sans `wct_id`) : tout
    chantier de ces leads est bloqué, celui déjà reçu comme celui qui arrivera, paquet exporté compris (même
    registre, mêmes blocages que `m7_enregistrer_retrait_consentement_marketing`).

    Idempotent (un retrait par lead, identifiant déterministe) : une relivraison n'écrit rien. Fail-closed : une charge
    que M7 ne sait pas lire lève, l'événement est rejoué puis mis en quarantaine, visible ; un retrait n'est jamais
    ignoré en silence. Le résumé ne porte que des identifiants et des comptes : jamais un contact."""
    canal, horodatage = charge.get("canal"), charge.get("horodatage")
    lead_ids = charge.get("lead_ids")
    if not isinstance(lead_ids, list) or not lead_ids:
        raise ValueError(f"{verdicts.REJ_RETRAIT_INVALIDE}: lead_ids : au moins un lead est attendu")
    # Tout est validé avant la première écriture : un lead illisible ne laisse pas les autres à moitié inscrits.
    maillons: dict[str, dict[str, Any]] = {}
    for lead_id in lead_ids:
        maillon, verdict = retrait.construire_retrait_de_lead(
            lead_id,
            canal,
            ORIGINE_BUS_RETRAIT,
            ORIGINE_BUS_RETRAIT,
            horodatage,
        )
        if verdict is not None:
            raise ValueError(f"{verdict['code']}: {verdict['detail']}")
        maillons.setdefault(maillon["retrait_id"], maillon)
    journal = stockage.maillons(*REGISTRE_RETRAITS)
    connus = {r["retrait_id"] for r in journal}
    ecrits = [m for retrait_id, m in maillons.items() if retrait_id not in connus]
    for maillon in ecrits:
        journal.append(maillon)
    deja_enregistres = len(maillons) - len(ecrits)
    contenus_bloques, deja_exportes = _contenus_touches_par(ecrits)
    return {
        "traite": True,
        "retraits_ecrits": len(ecrits),
        "deja_enregistres": deja_enregistres,
        "contenus_bloques": contenus_bloques,
        "contenus_deja_exportes": deja_exportes,
        "a_faire": [A_FAIRE_PAQUET_EXPORTE] if deja_exportes else [],
    }


# -- « À voir » ----------------------------------------------------------------------------------------------------
def _resume_attente(proposition: dict[str, Any]) -> str:
    plateforme = plateformes.plateforme(proposition["plateforme"])
    lieu = f" à {proposition['ville']}" if proposition.get("ville") else ""
    une_ligne = " ".join(proposition["texte"].split())
    debut = f"{plateforme.libelle} — {proposition['nature']}{lieu} : « "
    reste = RESUME_ATTENTE_MAX - len(debut) - 2
    extrait = une_ligne if len(une_ligne) <= reste else une_ligne[: max(reste - 1, 0)] + "…"
    return f"{debut}{extrait} »"


def attentes() -> list[dict[str, Any]]:
    """La section « À voir » du propriétaire (ADR-0009 §5) : un contenu de chantier `PROPOSE` attend sa décision
    (N3). Lecture seule : ne décide ni n'exporte rien. Les contenus dont le consentement est retiré n'y sont plus."""
    decisions, retraits = _lire(REGISTRE_DECISIONS_CONTENU), _lire(REGISTRE_RETRAITS)
    return [
        {
            "type": "contenu_a_approuver",
            "id": proposition["contenu_id"],
            "resume": _resume_attente(proposition),
            "niveau": "N3",
            "depuis": proposition["propose_le"],
            "action_proposee": ACTION_ATTENTE,
        }
        for proposition in registre.dernieres_revisions(_lire(REGISTRE_CONTENUS_CHANTIER))
        if registre.statut(proposition, decisions, retraits) == registre.STATUT_PROPOSE
    ]


# -- retrait et contenu public (T4.3) -----------------------------------------------------------------------
def retrait_bloquant(charge: dict[str, Any]) -> dict[str, Any] | None:
    """Le retrait du consentement marketing qui bloque ce chantier, ou `None` : consulté par tout outil de
    contenu public, dont `m7_preparer_contenu_public` (T4.3)."""
    bloquant = retrait.retrait_applicable(charge.get("wct_id"), charge.get("lead_id"), _lire(REGISTRE_RETRAITS))
    return None if bloquant is None else dict(bloquant)
