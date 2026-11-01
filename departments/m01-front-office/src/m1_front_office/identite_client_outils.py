"""Outils de vérification d'identité d'un correspondant (M1.10) : l'adaptateur entre `identite_client` (pur) et la
plateforme.

Ce que fait chaque outil, et ce qu'il ne fait pas :

- `m1_ouvrir_verification_identite` (N2) : ouvre une vérification pour le correspondant d'un courriel reçu et
prépare, dans le sas d'envoi habituel, un BROUILLON de courriel qui porte un code à usage unique. Rien n'est envoyé
(la demande N3 passe par `m1_demander_envoi_courriel`). Le code n'est jamais rendu à l'agent : seule son empreinte
salée est gardée.
- `m1_consigner_moyen_verification` (N2) : le correspondant a répondu par courriel ; le CODE vérifie le retour (même
  correspondant, authentification non échouée, une seule réponse comptée par signal, trois essais). L'agent ne
  fournit jamais le code : la preuve est le courriel reçu.
- `m1_attester_moyen_verification` et `m1_decider_verification_identite` (N3, personne authentifiée seulement) : les
moyens que seule une personne peut attester, et la décision (valider pour les actions sensibles, ou refuser).
- `m1_lire_verification_identite` (N0) : l'état, le niveau d'accès et ce que M1 est autorisé à dire. Sinon : « Je vais
  vérifier avec l'équipe. »

Aucune lecture de M2/M3/M4/M5 n'est faite ici : ce module décide SI M1 peut répondre sur un dossier, jamais ce qu'il
dit.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from opsys import stockage
from opsys.courriel_connecteurs import envoi
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.outils import Autonomie, Niveau, Outil

from . import horodatage as controle_horodatage
from . import identite_client as ic
from . import outils as _o
from . import reception, tri_courriel
from .registre import TYPE_RECU_COURRIEL, TYPE_REPONSE_COURRIEL

DEPARTEMENT = "m01-front-office"
REGISTRE = "verifications_identite"
ACTEUR = "m01-front-office"
PREFIXE_SIGNAL_VERIFICATION = "verification:"


def _reg() -> Any:
    return stockage.maillons(DEPARTEMENT, REGISTRE)


def _cnx() -> Any:
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise ValueError(
            "REJ-M1-IDENT-BASE: la vérification vit dans la base de l'instance (appel dans une transaction)"
        )
    return cnx


def _refus(code: str, detail: str) -> Any:
    """Un refus typé : `ValueError("CODE: détail")`, que le répartiteur d'outils rend en refus métier (même idiome que
    `courriel_outils`). Ne rend jamais : l'agent lit le code et corrige."""
    raise ValueError(f"{code}: {detail}")


def _instant(horodatage: str) -> str:
    quand = _o._horodatage_faisant_foi(horodatage)
    controle_horodatage.valider_horodatage(quand)
    return quand


def cle_correspondant(adresse: str) -> str:
    """Pseudonyme stable du correspondant (même idiome que l'identifiant de conversation : jamais l'adresse)."""
    correspondant, _ = reception.correspondant_du_canal("courriel", adresse)
    return reception.identifiant_de_conversation("courriel", correspondant)


def _reception(signal_id: str) -> dict[str, Any] | None:
    return next(
        (
            x
            for x in _o._obtenir_registre().lire()
            if x.get("type_entree") == TYPE_RECU_COURRIEL and x.get("signal_id") == signal_id
        ),
        None,
    )


def _texte_du_signal(signal_id: str, objet: str) -> str:
    signal = next(
        (
            x
            for x in _o._obtenir_registre().lire()
            if x.get("type_entree") == "signal" and x.get("signal_id") == signal_id
        ),
        None,
    )
    contenu = (signal or {}).get("contenu_filtre", "")
    return contenu[len(objet.strip()) + 1 :] if objet.strip() and contenu.startswith(objet.strip() + "\n") else contenu


def _ouverture(verification_id: str) -> dict[str, Any] | None:
    return next(
        (m for m in _reg() if m["type_entree"] == ic.TYPE_OUVERTE and m["verification_id"] == verification_id), None
    )


def _projection(verification_id: str, maintenant: str) -> ic.Projection:
    return ic.projeter(list(_reg()), verification_id, maintenant)


def _traduire(exc: ic.RefusIdentite) -> dict[str, Any]:
    code, _, detail = str(exc).partition(": ")
    return _refus(code, detail)


# ------------------------------------------------------------------------------------------------ ouverture
def ouvrir_verification_identite(
    signal_id: str, finalite: str, horodatage: str, retention_jours: int = ic.RETENTION_JOURS
) -> dict[str, Any]:
    recue = _reception(signal_id)
    if recue is None:
        return _refus("REJ-M1-IDENT-SIGNAL-INCONNU", "aucun courriel reçu sous ce signal_id")
    maintenant = _instant(horodatage)
    cle = cle_correspondant(recue["expediteur"])
    for m in _reg():
        if m["type_entree"] == ic.TYPE_OUVERTE and m["cle"] == cle and m["finalite"] == finalite:
            p = _projection(m["verification_id"], maintenant)
            if p.etat in ("a_verifier", "verifie", "refuse"):
                return {
                    "accepte": True,
                    "resultat": {**p.vers_json(), "deja_ouverte": True, "brouillon_id": m.get("brouillon_id")},
                }
    verification_id = "vi-" + hashlib.sha256(f"{cle}|{finalite}|{signal_id}".encode()).hexdigest()[:16]
    sel = secrets.token_hex(8)
    code = f"{secrets.randbelow(10**ic.LONGUEUR_CODE):0{ic.LONGUEUR_CODE}d}"
    corps = (
        f"Bonjour,\n\nPour confirmer votre identité, répondez à ce courriel en y inscrivant le code suivant : {code}\n"
        f"Ce code est valable {ic.VALIDITE_CODE_MIN} minutes et ne sert qu'une fois. Si vous n'êtes pas à "
        "l'origine de cette demande, ignorez ce message.\n\nL'équipe"
    )
    try:
        brouillon = envoi.creer_brouillon(
            _cnx(),
            ACTEUR,
            recue["compte_id"],
            en_reponse_a=recue.get("reference_reponse"),
            a=[recue["expediteur"]],
            objet="Confirmation de votre identité",
            corps=corps,
        )
        ligne = ic.ligne_ouverture(
            verification_id=verification_id,
            cle=cle,
            canal="courriel",
            finalite=finalite,
            signal_id=signal_id,
            maintenant=maintenant,
            sel=sel,
            empreinte=ic.empreinte_code(sel, code),
            brouillon_id=brouillon.brouillon_id,
            retention_jours=retention_jours,
        )
    except ic.RefusIdentite as exc:
        return _traduire(exc)
    except ErreurCourriel as exc:
        return _refus(exc.code, exc.detail)
    _reg().append(ligne)
    _o._obtenir_registre().ajouter(
        {
            "type_entree": TYPE_REPONSE_COURRIEL,
            "horodatage": maintenant,
            "signal_id": PREFIXE_SIGNAL_VERIFICATION + verification_id,
            "etape": "preparee",
            "brouillon_id": brouillon.brouillon_id,
            "revision": brouillon.revision,
            "empreinte": brouillon.empreinte,
            "compte_id": recue["compte_id"],
        }
    )
    p = _projection(verification_id, maintenant)
    return {
        "accepte": True,
        "resultat": {
            **p.vers_json(),
            "deja_ouverte": False,
            "brouillon_id": brouillon.brouillon_id,
            "consigne": "Rien n'est envoyé. Demande l'envoi avec m1_demander_envoi_courriel (approbation "
            "humaine). Le code n'est pas lisible ici : tu ne peux pas le fournir toi-même.",
        },
    }


# ------------------------------------------------------------------------------------------- moyens et décision
def consigner_moyen_verification(verification_id: str, signal_id_reponse: str, horodatage: str) -> dict[str, Any]:
    ouverture = _ouverture(verification_id)
    if ouverture is None:
        return _refus("REJ-M1-IDENT-INCONNUE", "vérification inconnue")
    maintenant = _instant(horodatage)
    p = _projection(verification_id, maintenant)
    if p.etat not in ("a_verifier", "verifie"):
        return _refus("REJ-M1-IDENT-ETAT", f"vérification « {p.etat} » : aucun essai n'est accepté")
    deja = next(
        (
            m
            for m in _reg()
            if m["type_entree"] == ic.TYPE_ESSAI
            and m["verification_id"] == verification_id
            and m["signal_id"] == signal_id_reponse
        ),
        None,
    )
    if deja is not None:
        return {"accepte": True, "resultat": {**p.vers_json(), "rejeu": True, "reussi": deja["reussi"]}}
    reponse = _reception(signal_id_reponse)
    if reponse is None:
        return _refus("REJ-M1-IDENT-SIGNAL-INCONNU", "aucun courriel reçu sous ce signal_id")
    if cle_correspondant(reponse["expediteur"]) != ouverture["cle"]:
        return _refus(
            "REJ-M1-IDENT-CORRESPONDANT-DIFFERENT",
            "la réponse ne vient pas du correspondant de la vérification : aucun moyen n'est consigné",
        )
    auth = reponse.get("authentification") or {}
    if "fail" in (auth.get("spf"), auth.get("dmarc")) or reponse.get("neutralise"):
        return _refus(
            "REJ-M1-IDENT-AUTHENTIFICATION",
            "l'authentification de l'expéditeur a échoué ou le texte porte une consigne neutralisée",
        )
    if ic._t(reponse["horodatage"]) < ic._t(ouverture["horodatage"]):
        return _refus("REJ-M1-IDENT-REPONSE-ANTERIEURE", "la réponse précède l'ouverture de la vérification")
    texte = tri_courriel._sans_fil_cite(_texte_du_signal(signal_id_reponse, reponse.get("objet") or ""))
    code = ic.extraire_code(texte)
    if code is None:
        return _refus(
            "REJ-M1-IDENT-CODE-ABSENT",
            "aucun code (ou plusieurs candidats) dans le texte NOUVEAU de la réponse ; aucun essai compté",
        )
    reussi = ic.code_valide(ouverture["sel"], ouverture["empreinte_code"], code)
    if not reussi and p.essais_restants <= 0:
        return _refus("REJ-M1-IDENT-ESSAIS-EPUISES", "trois essais ont échoué : la vérification est verrouillée")
    _reg().append(
        {
            "type_entree": ic.TYPE_ESSAI,
            "horodatage": maintenant,
            "verification_id": verification_id,
            "signal_id": signal_id_reponse,
            "reussi": reussi,
            "moyen": ic.MOYEN_CODE,
        }
    )
    p = _projection(verification_id, maintenant)
    if not reussi:
        # Refus RENDU (et non levé) : l'essai raté est écrit et doit survivre à l'appel, sinon trois essais ne
        # verrouilleraient jamais rien. Même forme qu'un verdict.
        return {
            "accepte": False,
            "verdict": {
                "code": "REJ-M1-IDENT-CODE-INVALIDE",
                "statut": "",
                "detail": f"code incorrect ; {p.essais_restants} essai(s) restant(s)",
            },
        }
    return {"accepte": True, "resultat": {**p.vers_json(), "reussi": True, "rejeu": False}}


def attester_moyen_verification(
    verification_id: str, moyen: str, horodatage: str, type_piece: str | None = None, note: str | None = None
) -> dict[str, Any]:
    acteur, refus = _o._acteur_humain("m1_attester_moyen_verification")
    if acteur is None:
        return refus or _refus("REJ-HUMAIN-REQUIS", "décision humaine requise")
    if moyen not in ic.MOYENS_HUMAINS:
        return _refus("REJ-M1-IDENT-MOYEN", f"moyen parmi {', '.join(ic.MOYENS_HUMAINS)}")
    if (moyen == "piece_identite_vue") != (type_piece is not None) or (
        type_piece is not None and type_piece not in ic.TYPES_PIECE
    ):
        return _refus(
            "REJ-M1-IDENT-PIECE",
            "pièce vue : le TYPE seulement (permis_conduire, passeport, "
            "carte_assurance_maladie, autre), jamais un numéro ; le type est interdit pour les autres moyens",
        )
    try:
        note_propre = ic.exiger_sans_donnee_identifiante(note)
    except ic.RefusIdentite as exc:
        return _traduire(exc)
    if _ouverture(verification_id) is None:
        return _refus("REJ-M1-IDENT-INCONNUE", "vérification inconnue")
    maintenant = _instant(horodatage)
    p = _projection(verification_id, maintenant)
    if p.etat not in ("a_verifier", "verifie"):
        return _refus("REJ-M1-IDENT-ETAT", f"vérification « {p.etat} » : aucun moyen n'est accepté")
    _reg().append(
        {
            "type_entree": ic.TYPE_ATTESTATION,
            "horodatage": maintenant,
            "verification_id": verification_id,
            "moyen": moyen,
            "type_piece": type_piece,
            "note": note_propre,
            "par": acteur["par"],
            "role": acteur["role"],
            "voie": acteur["voie"],
        }
    )
    return {"accepte": True, "resultat": _projection(verification_id, maintenant).vers_json()}


def decider_verification_identite(verification_id: str, decision: str, motif: str, horodatage: str) -> dict[str, Any]:
    acteur, refus = _o._acteur_humain("m1_decider_verification_identite")
    if acteur is None:
        return refus or _refus("REJ-HUMAIN-REQUIS", "décision humaine requise")
    if decision not in ("valider", "refuser"):
        return _refus("REJ-M1-IDENT-DECISION", "décision parmi valider, refuser")
    try:
        motif_propre = ic.exiger_sans_donnee_identifiante(motif)
    except ic.RefusIdentite as exc:
        return _traduire(exc)
    if not motif_propre or len(motif_propre) < 10:
        return _refus("REJ-M1-IDENT-MOTIF", "motif de 10 caractères au moins")
    if _ouverture(verification_id) is None:
        return _refus("REJ-M1-IDENT-INCONNUE", "vérification inconnue")
    maintenant = _instant(horodatage)
    p = _projection(verification_id, maintenant)
    if decision == "valider" and (p.etat != "verifie" or p.nb_moyens < 1):
        return _refus(
            "REJ-M1-IDENT-AUCUN-MOYEN",
            "aucun moyen valide : une personne ne valide pas une identité qu'aucune preuve n'appuie",
        )
    _reg().append(
        {
            "type_entree": ic.TYPE_DECISION,
            "horodatage": maintenant,
            "verification_id": verification_id,
            "decision": decision,
            "motif": motif_propre,
            "par": acteur["par"],
            "role": acteur["role"],
            "voie": acteur["voie"],
        }
    )
    return {"accepte": True, "resultat": _projection(verification_id, maintenant).vers_json()}


def lire_verification_identite(
    horodatage: str, verification_id: str | None = None, signal_id: str | None = None
) -> dict[str, Any]:
    if (verification_id is None) == (signal_id is None):
        return _refus("REJ-M1-IDENT-ARGUMENTS", "exactement un de verification_id ou signal_id")
    maintenant = _instant(horodatage)
    if signal_id is not None:
        recue = _reception(signal_id)
        if recue is None:
            return _refus("REJ-M1-IDENT-SIGNAL-INCONNU", "aucun courriel reçu sous ce signal_id")
        cle = cle_correspondant(recue["expediteur"])
        candidates = [m["verification_id"] for m in _reg() if m["type_entree"] == ic.TYPE_OUVERTE and m["cle"] == cle]
        if not candidates:
            return {
                "accepte": True,
                "resultat": {**ic.projeter([], "-", maintenant).vers_json(), "verification_id": None},
            }
        verification_id = candidates[-1]
    elif _ouverture(verification_id) is None:
        return _refus("REJ-M1-IDENT-INCONNUE", "vérification inconnue")
    return {"accepte": True, "resultat": _projection(verification_id, maintenant).vers_json()}


_HORO = {"type": "string", "description": "ISO-8601 avec fuseau ; l'heure du serveur fait foi pour un appareil."}
_VID = {"type": "string", "pattern": "^vi-[0-9a-f]{16}$"}
_SIG = {"type": "string", "minLength": 20, "maxLength": 120}


def outils_identite() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m1_ouvrir_verification_identite",
            description=(
                "Ouvre la vérification d'identité du correspondant d'un courriel reçu et prépare un BROUILLON "
                "de courriel portant un code à usage unique (rien n'est envoyé ; l'envoi passe par "
                "m1_demander_envoi_courriel). Le code n'est jamais rendu. Idempotent par correspondant et finalité."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "signal_id": _SIG,
                    "finalite": {"type": "string", "enum": list(ic.FINALITES)},
                    "horodatage": _HORO,
                    "retention_jours": {"type": "integer", "minimum": 1, "maximum": ic.RETENTION_MAX_JOURS},
                },
                "required": ["signal_id", "finalite", "horodatage"],
                "additionalProperties": False,
            },
            fonction=ouvrir_verification_identite,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_consigner_moyen_verification",
            description=(
                "Le correspondant a répondu par courriel : le code vérifie le retour (même correspondant, "
                "authentification non échouée, trois essais, une réponse comptée une fois). L'agent ne fournit "
                "jamais le code. Ne donne aucun accès sensible : une personne valide."
            ),
            parametres={
                "type": "object",
                "properties": {"verification_id": _VID, "signal_id_reponse": _SIG, "horodatage": _HORO},
                "required": ["verification_id", "signal_id_reponse", "horodatage"],
                "additionalProperties": False,
            },
            fonction=consigner_moyen_verification,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_attester_moyen_verification",
            description=(
                "Une PERSONNE authentifiée atteste un moyen que seule une personne peut vérifier (rappel au "
                "numéro du dossier, référence citée, connaissance du dossier, pièce vue : type seulement, jamais "
                "un numéro). Décision humaine, refusée à un agent seul."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "verification_id": _VID,
                    "moyen": {"type": "string", "enum": list(ic.MOYENS_HUMAINS)},
                    "type_piece": {"type": ["string", "null"], "enum": [*ic.TYPES_PIECE, None]},
                    "note": {"type": ["string", "null"], "maxLength": 200},
                    "horodatage": _HORO,
                },
                "required": ["verification_id", "moyen", "horodatage"],
                "additionalProperties": False,
            },
            fonction=attester_moyen_verification,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m1_decider_verification_identite",
            description=(
                "Une PERSONNE valide l'identité pour les actions sensibles (facturation, changement de "
                "rendez-vous, données personnelles) ou la refuse. Valider exige au moins un moyen valide. "
                "Décision humaine, jamais d'un agent seul."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "verification_id": _VID,
                    "decision": {"type": "string", "enum": ["valider", "refuser"]},
                    "motif": {"type": "string", "minLength": 10, "maxLength": 200},
                    "horodatage": _HORO,
                },
                "required": ["verification_id", "decision", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=decider_verification_identite,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m1_lire_verification_identite",
            description=(
                "État de la vérification d'identité d'un correspondant, niveau d'accès (aucun, probable, "
                "général, sensible) et ce que M1 peut dire. Sans niveau suffisant : « Je vais vérifier avec "
                "l'équipe. » Lecture."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "horodatage": _HORO,
                    "verification_id": {**_VID, "type": ["string", "null"]},
                    "signal_id": {**_SIG, "type": ["string", "null"]},
                },
                "required": ["horodatage"],
                "additionalProperties": False,
            },
            fonction=lire_verification_identite,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
    )
