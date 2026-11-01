"""Outils de rendez-vous de M1 (M1.9) : proposer des fenêtres depuis la capacité de M4, retenir, confirmer depuis la
cédule, préparer les messages et les rappels. Adaptateur de `rendez_vous` (pur).

Gouvernance (celle de la cédule de M4, inchangée) :
- M1 LIT la capacité des équipes et la semaine datée de la cédule par le port privé `lecteur_capacite_m4` (deux
lectures T0 existantes, aucun droit ajouté) ; il n'écrit jamais dans M4. Port absent ou lecture refusée :
fail-closed, rien n'est proposé ni confirmé.
- Une fenêtre RETENUE est un engagement interne qui expire (48 h) : elle n'est jamais présentée au client comme ferme.
- CONFIRMER est une décision de PERSONNE (admin, depuis l'appareil : la cédule de M4 exige un admin authentifié) qui
nomme une intervention que M4 a déjà DATÉE et confirmée ; l'heure vient de M4. Sans ce créneau : aucune confirmation.
- Les messages (confirmation, rappels) sont des BROUILLONS à gabarit fixe, jamais envoyés par ces outils ; leur envoi
passe par le sas (N3 courriel, N4 SMS). Les rappels portent leur échéance mais aucun déclencheur automatique n'est
livré : `rappels_dus` les liste pour qu'un humain ou un agent demande l'envoi.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable, Mapping
from typing import Any

from opsys import stockage
from opsys.courriel_connecteurs import envoi
from opsys.courriel_connecteurs.erreurs import ErreurCourriel
from opsys.outils import Autonomie, Niveau, Outil

from . import gabarits as gb
from . import horodatage as controle_horodatage
from . import outils as _o
from . import rendez_vous as rdv
from .registre import TYPE_RECU_COURRIEL, TYPE_REPONSE_COURRIEL

DEPARTEMENT = "m01-front-office"
REGISTRE = "rendez_vous"
ACTEUR = "m01-front-office"
Lecteur = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
_HORO = {"type": "string", "description": "ISO-8601 avec fuseau ; l'heure du serveur fait foi pour un appareil."}
_RDV = {"type": "string", "pattern": "^rdv-[0-9a-f]{16}$"}


def _reg() -> Any:
    return stockage.maillons(DEPARTEMENT, REGISTRE)


def _refus(code: str, detail: str) -> Any:
    """Un refus typé : `ValueError("CODE: détail")`, que le répartiteur d'outils rend en refus métier (même idiome que
    `courriel_outils`). Ne rend jamais : l'agent lit le code et corrige."""
    raise ValueError(f"{code}: {detail}")


def _traduire(exc: Exception) -> dict[str, Any]:
    code, _, detail = str(exc).partition(": ")
    return _refus(code, detail)


def _instant(horodatage: str) -> str:
    quand = _o._horodatage_faisant_foi(horodatage)
    controle_horodatage.valider_horodatage(quand)
    return quand


def _lire_m4(lecteur: Lecteur | None, outil: str, arguments: Mapping[str, Any]) -> tuple[Any, str | None]:
    """`(charge, None)` ou `(None, code)` : jamais une exception, jamais une valeur par défaut."""
    if lecteur is None:
        return None, "lecteur_capacite_m4_indisponible"
    try:
        reponse = lecteur(outil, arguments)
    except Exception as exc:  # noqa: BLE001 — une lecture qui plante est un refus nommé, pas une panne de l'outil
        return None, f"lecture_m4_erreur:{type(exc).__name__}"
    if not isinstance(reponse, Mapping) or not reponse.get("ok"):
        return None, str((reponse or {}).get("erreur") or "lecture_m4_refusee")[:80]
    interne = reponse.get("resultat")
    if not isinstance(interne, Mapping) or not interne.get("accepte"):
        verdict = (interne or {}).get("verdict") or {}
        return None, str(verdict.get("code") or "lecture_m4_refusee")[:80]
    return interne.get("resultat"), None


def _signal(signal_id: str) -> dict[str, Any] | None:
    return next(
        (
            x
            for x in _o._obtenir_registre().lire()
            if x.get("type_entree") == "signal" and x.get("signal_id") == signal_id
        ),
        None,
    )


def _etats(maintenant: str) -> dict[str, dict[str, Any]]:
    return rdv.etats(list(_reg()), maintenant)


# ---------------------------------------------------------------------------------------------------- proposer
def proposer_fenetres(
    lecteur: Lecteur | None,
    cle: str,
    signal_id: str,
    motif: str,
    duree_minutes: int,
    semaines: list[str],
    horodatage: str,
) -> dict[str, Any]:
    if motif not in rdv.MOTIFS:
        return _refus("REJ-M1-RDV-MOTIF", f"motif parmi {', '.join(rdv.MOTIFS)}")
    if type(duree_minutes) is not int or not rdv.DUREE_MIN <= duree_minutes <= rdv.DUREE_MAX:
        return _refus(
            "REJ-M1-RDV-DUREE",
            f"durée entière de {rdv.DUREE_MIN} à {rdv.DUREE_MAX} minutes, déclarée (jamais supposée)",
        )
    if not isinstance(cle, str) or not 6 <= len(cle) <= 120:
        return _refus("REJ-M1-RDV-CLE", "clé d'idempotence de 6 à 120 caractères")
    maintenant = _instant(horodatage)
    if _signal(signal_id) is None:
        return _refus("REJ-M1-RDV-SIGNAL-INCONNU", "aucun message reçu sous ce signal_id")
    rdv_id = rdv.identifiant_rdv(cle)
    existant = _etats(maintenant).get(rdv_id)
    if existant is not None:
        return {"accepte": True, "resultat": {**_vue(existant), "deja_propose": True}}
    try:
        lundis = rdv.valider_semaines(semaines, maintenant)
    except rdv.RefusRdv as exc:
        return _traduire(exc)
    charges: dict[str, Mapping[str, Any]] = {}
    echecs: dict[str, str] = {}
    for s in lundis:
        charge, code = _lire_m4(
            lecteur,
            "m4_lire_capacite_equipe",
            {"debut_semaine": s, "horodatage_reference": maintenant, "portee": "semaine_type"},
        )
        if code is not None:
            echecs[s] = code
        else:
            charges[s] = charge
    if not charges:
        return _refus("REJ-M1-RDV-LECTURE-M4", f"la capacité de M4 n'a pu être lue : {sorted(set(echecs.values()))}")
    try:
        opts = rdv.options(charges, duree_minutes, list(_reg()), maintenant)
    except rdv.RefusRdv as exc:
        return _traduire(exc)
    opts += [
        {
            "semaine": s,
            "statut": "lecture_impossible",
            "manque": [c],
            "minutes_libres": None,
            "minutes_retenues_m1": None,
            "equipes_possibles": [],
        }
        for s, c in sorted(echecs.items())
    ]
    _reg().append(
        {
            "type_entree": rdv.TYPE_PROPOSE,
            "horodatage": maintenant,
            "rdv_id": rdv_id,
            "cle": cle,
            "signal_id": signal_id,
            "motif": motif,
            "duree_minutes": duree_minutes,
            "options": opts,
        }
    )
    return {
        "accepte": True,
        "resultat": {
            **_vue(_etats(maintenant)[rdv_id]),
            "deja_propose": False,
            "consigne": "Aucune date n'est promise au client : retiens une fenêtre, puis une "
            "personne fait dater la cédule de M4.",
        },
    }


def _vue(r: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rdv_id": r["rdv_id"],
        "etat": r["etat"],
        "motif": r["motif"],
        "duree_minutes": r["duree_minutes"],
        "semaine_retenue": r["semaine"],
        "retenue_expire_le": r["retenue_expire_le"],
        "options": r["options"],
        "confirme": None
        if r["confirme"] is None
        else {k: r["confirme"].get(k) for k in ("intervention_id", "debut", "fin", "equipe_id", "par")},
        "messages": [
            {k: m.get(k) for k in ("type", "gabarit_id", "echeance", "brouillon_id", "statut")} for m in r["messages"]
        ],
    }


# ----------------------------------------------------------------------------------------------------- retenir
def retenir_fenetre(
    lecteur: Lecteur | None, rdv_id: str, semaine: str, horodatage: str, heures: int = rdv.RETENUE_HEURES
) -> dict[str, Any]:
    maintenant = _instant(horodatage)
    if type(heures) is not int or not 1 <= heures <= rdv.RETENUE_MAX_HEURES:
        return _refus("REJ-M1-RDV-RETENUE", f"retenue de 1 à {rdv.RETENUE_MAX_HEURES} heures")
    r = _etats(maintenant).get(rdv_id)
    if r is None:
        return _refus("REJ-M1-RDV-INCONNU", "rendez-vous inconnu")
    if r["etat"] in ("confirmee", "annulee", "passee"):
        return _refus("REJ-M1-RDV-ETAT", f"rendez-vous « {r['etat']} » : aucune retenue")
    if not any(o["semaine"] == semaine and o.get("statut") == "disponible" for o in r["options"]):
        return _refus("REJ-M1-RDV-FENETRE-NON-PROPOSEE", "cette semaine n'a pas été proposée comme disponible")
    # La capacité est relue à l'instant de la retenue : une proposition périmée ne retient rien.
    charge, code = _lire_m4(
        lecteur,
        "m4_lire_capacite_equipe",
        {"debut_semaine": semaine, "horodatage_reference": maintenant, "portee": "semaine_type"},
    )
    if code is not None:
        return _refus("REJ-M1-RDV-LECTURE-M4", f"la capacité de M4 n'a pu être relue : {code}")
    try:
        (option,) = rdv.options({semaine: charge}, r["duree_minutes"], list(_reg()), maintenant, sauf=rdv_id)
    except rdv.RefusRdv as exc:
        return _traduire(exc)
    if option["statut"] != "disponible":
        return _refus(
            "REJ-M1-RDV-CONFLIT",
            f"la semaine n'est plus disponible ({option['statut']}) : conflit avec la "
            "capacité de M4 ou une autre retenue de M1",
        )
    expire = rdv._t(maintenant) + dt.timedelta(hours=heures)
    _reg().append(
        {
            "type_entree": rdv.TYPE_RETENU,
            "horodatage": maintenant,
            "rdv_id": rdv_id,
            "semaine": semaine,
            "expire_le": expire.isoformat(),
            "minutes_nettes_avant": option["minutes_nettes"],
        }
    )
    return {
        "accepte": True,
        "resultat": {
            **_vue(_etats(maintenant)[rdv_id]),
            "consigne": "Retenue interne seulement : ne la présente pas comme un "
            "rendez-vous. Une personne doit faire dater la cédule de M4.",
        },
    }


# --------------------------------------------------------------------------------------------------- confirmer
def confirmer_rendez_vous(
    lecteur: Lecteur | None, rdv_id: str, intervention_id: str, horodatage: str
) -> dict[str, Any]:
    acteur, refus = _o._acteur_humain("m1_confirmer_rendez_vous")
    if acteur is None:
        return refus or _refus("REJ-HUMAIN-REQUIS", "décision humaine requise")
    maintenant = _instant(horodatage)
    etats = _etats(maintenant)
    r = etats.get(rdv_id)
    if r is None:
        return _refus("REJ-M1-RDV-INCONNU", "rendez-vous inconnu")
    if r["etat"] != "retenue":
        return _refus(
            "REJ-M1-RDV-ETAT", f"rendez-vous « {r['etat']} » : seule une fenêtre retenue (non expirée) se confirme"
        )
    if any(x["etat"] == "confirmee" and x["confirme"]["intervention_id"] == intervention_id for x in etats.values()):
        return _refus("REJ-M1-RDV-DEJA-CONFIRME", "cette intervention porte déjà un rendez-vous confirmé")
    cedule, code = _lire_m4(lecteur, "m4_lire_cedule_semaine", {"debut_semaine": r["semaine"]})
    if code is not None:
        return _refus(
            "REJ-M1-RDV-LECTURE-M4",
            f"la cédule de M4 n'a pu être lue ({code}) : rien n'est confirmé ; la "
            "confirmation se fait depuis l'app admin",
        )
    try:
        creneau = rdv.creneau_depuis_cedule(cedule, intervention_id, r["semaine"], r["duree_minutes"])
    except rdv.RefusRdv as exc:
        return _traduire(exc)
    _reg().append(
        {
            "type_entree": rdv.TYPE_CONFIRME,
            "horodatage": maintenant,
            "rdv_id": rdv_id,
            **creneau,
            "par": acteur["par"],
            "role": acteur["role"],
            "voie": acteur["voie"],
        }
    )
    return {"accepte": True, "resultat": _vue(_etats(maintenant)[rdv_id])}


# --------------------------------------------------------------------------------------------------- messages
def preparer_messages_rdv(
    rdv_id: str, canal: str, nom_entreprise: str, horodatage: str, decalages_minutes: list[int] | None = None
) -> dict[str, Any]:
    maintenant = _instant(horodatage)
    if not isinstance(nom_entreprise, str) or not 2 <= len(nom_entreprise.strip()) <= 80:
        return _refus("REJ-M1-RDV-ENTREPRISE", "nom de l'entreprise de 2 à 80 caractères")
    if decalages_minutes is not None and (not isinstance(decalages_minutes, list) or len(decalages_minutes) > 5):
        return _refus("REJ-M1-RDV-DECALAGE", "au plus 5 décalages de rappel")
    r = _etats(maintenant).get(rdv_id)
    if r is None:
        return _refus("REJ-M1-RDV-INCONNU", "rendez-vous inconnu")
    if r["etat"] != "confirmee":
        return _refus(
            "REJ-M1-RDV-NON-CONFIRME",
            f"rendez-vous « {r['etat']} » : aucun message de confirmation ni de "
            "rappel tant que M4 n'a pas daté la cédule et qu'une personne n'a pas confirmé",
        )
    if canal not in ("courriel", "sms"):
        return _refus("REJ-M1-RDV-CANAL", "canal parmi courriel, sms")
    c = r["confirme"]
    variables = {
        "entreprise": nom_entreprise,
        "date_texte": rdv.texte_date(c["debut"]),
        "debut": rdv.texte_heure(c["debut"]),
        "fin": rdv.texte_heure(c["fin"]),
    }
    try:
        echeances = rdv.echeances_rappel(c["debut"], maintenant, tuple(decalages_minutes or rdv.ECHEANCES_RAPPEL_MIN))
    except rdv.RefusRdv as exc:
        return _traduire(exc)
    signal = _signal(r["signal_id"])
    prepares: list[dict[str, Any]] = []
    refuses: list[dict[str, Any]] = []
    if canal == "courriel":
        recue = next(
            (
                x
                for x in _o._obtenir_registre().lire()
                if x.get("type_entree") == TYPE_RECU_COURRIEL and x.get("signal_id") == r["signal_id"]
            ),
            None,
        )
        if recue is None:
            return _refus("REJ-M1-RDV-CANAL", "ce rendez-vous ne vient pas d'un courriel reçu : utilise le canal sms")
        plan = [("confirmation", "courriel_rdv_confirmation", None)] + [
            ("rappel", "courriel_rdv_rappel", e) for e in echeances
        ]
        for type_, gabarit_id, echeance in plan:
            cle = f"{type_}:{echeance}"
            if any(m.get("cle") == cle for m in r["messages"]):
                continue
            try:
                objet, corps = gb.rendre(gabarit_id, variables, _phrases_actives(gabarit_id, f"{rdv_id}|{cle}"))
                brouillon = envoi.creer_brouillon(
                    stockage.connexion_courante(),
                    ACTEUR,
                    recue["compte_id"],
                    en_reponse_a=recue.get("reference_reponse"),
                    a=[recue["expediteur"]],
                    objet=objet,
                    corps=corps,
                )
            except (gb.RefusGabarit, ErreurCourriel) as exc:
                refuses.append({"type": type_, "code": getattr(exc, "code", None) or str(exc).partition(":")[0]})
                continue
            sid = f"rdv:{rdv_id}:{hashlib.sha256(cle.encode()).hexdigest()[:8]}"
            _o._obtenir_registre().ajouter(
                {
                    "type_entree": TYPE_REPONSE_COURRIEL,
                    "horodatage": maintenant,
                    "signal_id": sid,
                    "etape": "preparee",
                    "brouillon_id": brouillon.brouillon_id,
                    "revision": brouillon.revision,
                    "empreinte": brouillon.empreinte,
                    "compte_id": recue["compte_id"],
                }
            )
            ligne = {
                "type_entree": rdv.TYPE_MESSAGE,
                "horodatage": maintenant,
                "rdv_id": rdv_id,
                "cle": cle,
                "type": type_,
                "gabarit_id": gabarit_id,
                "canal": "courriel",
                "echeance": echeance,
                "brouillon_id": brouillon.brouillon_id,
                "statut": "BROUILLON",
            }
            _reg().append(ligne)
            prepares.append({k: ligne[k] for k in ("type", "gabarit_id", "echeance", "brouillon_id")})
    else:
        from . import assistant_sms_outils

        conversation_id = (signal or {}).get("conversation_id")
        if not conversation_id or (signal or {}).get("source") != "sms":
            return _refus("REJ-M1-RDV-CANAL", "ce rendez-vous ne vient pas d'un SMS reçu : utilise le canal courriel")
        for echeance in echeances:
            cle = f"rappel_sms:{echeance}"
            if any(m.get("cle") == cle for m in r["messages"]):
                continue
            try:
                rep = assistant_sms_outils.preparer_message_sms(
                    conversation_id, "sms_rappel_rdv", variables, maintenant
                )
            except ValueError as exc:
                refuses.append({"type": "rappel", "code": str(exc).partition(":")[0]})
                continue
            ligne = {
                "type_entree": rdv.TYPE_MESSAGE,
                "horodatage": maintenant,
                "rdv_id": rdv_id,
                "cle": cle,
                "type": "rappel",
                "gabarit_id": "sms_rappel_rdv",
                "canal": "sms",
                "echeance": echeance,
                "brouillon_id": rep["resultat"]["brouillon_id"],
                "statut": "BROUILLON",
            }
            _reg().append(ligne)
            prepares.append({k: ligne[k] for k in ("type", "gabarit_id", "echeance", "brouillon_id")})
    return {
        "accepte": True,
        "resultat": {
            "rdv_id": rdv_id,
            "prepares": prepares,
            "refuses": refuses,
            "consigne": "Brouillons rangés, rien n'est envoyé. Demande l'envoi (courriel : "
            "m1_demander_envoi_courriel ; SMS : m1_sms_demander_envoi). Aucun déclencheur automatique n'envoie un "
            "rappel à son échéance.",
        },
    }


def _phrases_actives(gabarit_id: str, cle: str) -> tuple[str, ...]:
    from . import apprentissage, tri_courriel_outils

    return apprentissage.phrases_gabarit(tri_courriel_outils.etat_apprentissage(), gabarit_id, cle)


# --------------------------------------------------------------------------------------------- annuler, lire
def annuler_rendez_vous(rdv_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    maintenant = _instant(horodatage)
    r = _etats(maintenant).get(rdv_id)
    if r is None:
        return _refus("REJ-M1-RDV-INCONNU", "rendez-vous inconnu")
    if r["etat"] in ("confirmee", "passee"):
        return _refus(
            "REJ-M1-RDV-CONFIRME",
            "un rendez-vous confirmé suit la cédule de M4 : M1 ne l'annule pas ; le "
            "report ou l'annulation passe par M4",
        )
    if r["etat"] == "annulee":
        return {"accepte": True, "resultat": {**_vue(r), "deja_annule": True}}
    if not isinstance(motif, str) or not 5 <= len(motif.strip()) <= 200:
        return _refus("REJ-M1-RDV-MOTIF", "motif de 5 à 200 caractères")
    _reg().append({"type_entree": rdv.TYPE_ANNULE, "horodatage": maintenant, "rdv_id": rdv_id, "motif": motif.strip()})
    return {"accepte": True, "resultat": _vue(_etats(maintenant)[rdv_id])}


def lire_rendez_vous(horodatage: str, rdv_id: str | None = None) -> dict[str, Any]:
    maintenant = _instant(horodatage)
    etats = _etats(maintenant)
    if rdv_id is not None:
        if rdv_id not in etats:
            return _refus("REJ-M1-RDV-INCONNU", "rendez-vous inconnu")
        choisis = [etats[rdv_id]]
    else:
        choisis = list(etats.values())[-25:]
    dus = []
    for r in choisis:
        if r["etat"] != "confirmee":
            continue
        for m in r["messages"]:
            if m.get("type") == "rappel" and m.get("echeance") and rdv._t(m["echeance"]) <= rdv._t(maintenant):
                dus.append(
                    {
                        "rdv_id": r["rdv_id"],
                        "brouillon_id": m["brouillon_id"],
                        "echeance": m["echeance"],
                        "canal": m["canal"],
                    }
                )
    return {
        "accepte": True,
        "resultat": {"rendez_vous": [_vue(r) for r in choisis], "rappels_dus": dus, "total": len(etats)},
    }


def outils_rdv(lecteur_capacite_m4: Lecteur | None = None) -> tuple[Outil, ...]:
    def proposer(cle, signal_id, motif, duree_minutes, semaines, horodatage):
        return proposer_fenetres(lecteur_capacite_m4, cle, signal_id, motif, duree_minutes, semaines, horodatage)

    def retenir(rdv_id, semaine, horodatage, heures=rdv.RETENUE_HEURES):
        return retenir_fenetre(lecteur_capacite_m4, rdv_id, semaine, horodatage, heures)

    def confirmer(rdv_id, intervention_id, horodatage):
        return confirmer_rendez_vous(lecteur_capacite_m4, rdv_id, intervention_id, horodatage)

    return (
        Outil(
            nom="m1_proposer_fenetres_rdv",
            description=(
                "Propose des SEMAINES où la capacité des équipes de M4 (minutes déclarées moins le planifié, moins "
                "ce que M1 a déjà retenu) peut accueillir la durée demandée. Granularité : la semaine ; aucune "
                "date ni heure n'est promise. Une capacité non calculable reste « non calculable, manque X ». "
                "Idempotent par clé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "cle": {
                        "type": "string",
                        "minLength": 6,
                        "maxLength": 120,
                        "description": "Clé d'idempotence de la demande (ex. le signal_id et le motif).",
                    },
                    "signal_id": {"type": "string", "minLength": 6, "maxLength": 200},
                    "motif": {"type": "string", "enum": list(rdv.MOTIFS)},
                    "duree_minutes": {"type": "integer", "minimum": rdv.DUREE_MIN, "maximum": rdv.DUREE_MAX},
                    "semaines": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": rdv.SEMAINES_MAX,
                        "items": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                        "description": "Lundis ISO des semaines candidates.",
                    },
                    "horodatage": _HORO,
                },
                "required": ["cle", "signal_id", "motif", "duree_minutes", "semaines", "horodatage"],
                "additionalProperties": False,
            },
            fonction=proposer,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_retenir_fenetre_rdv",
            description=(
                "RETIENT une semaine proposée (engagement interne de 48 h par défaut, la capacité de M4 est relue "
                "et les autres retenues de M1 comptent : conflit refusé). Jamais présentée au client comme un "
                "rendez-vous ferme."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "rdv_id": _RDV,
                    "semaine": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
                    "horodatage": _HORO,
                    "heures": {"type": "integer", "minimum": 1, "maximum": rdv.RETENUE_MAX_HEURES},
                },
                "required": ["rdv_id", "semaine", "horodatage"],
                "additionalProperties": False,
            },
            fonction=retenir,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_confirmer_rendez_vous",
            description=(
                "Une PERSONNE (admin, depuis l'app) confirme un rendez-vous : M4 doit déjà avoir DATÉ et confirmé "
                "la cédule pour l'intervention nommée ; l'heure est lue de M4, jamais fournie. Sans créneau daté "
                "valide : refus, rien n'est confirmé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "rdv_id": _RDV,
                    "intervention_id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "horodatage": _HORO,
                },
                "required": ["rdv_id", "intervention_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=confirmer,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m1_preparer_messages_rdv",
            description=(
                "Prépare, pour un rendez-vous CONFIRMÉ par M4, les BROUILLONS de confirmation (courriel) et de rappels "
                "(courriel ou SMS) à partir de gabarits fixes, avec leurs échéances calculées par le code. Rien "
                "n'est envoyé : l'envoi passe par le sas. Un rappel SMS exige l'opt-in exprès du correspondant."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "rdv_id": _RDV,
                    "canal": {"type": "string", "enum": ["courriel", "sms"]},
                    "nom_entreprise": {"type": "string", "minLength": 2, "maxLength": 80},
                    "horodatage": _HORO,
                    "decalages_minutes": {
                        "type": ["array", "null"],
                        "maxItems": 5,
                        "items": {"type": "integer", "minimum": 5, "maximum": 20160},
                    },
                },
                "required": ["rdv_id", "canal", "nom_entreprise", "horodatage"],
                "additionalProperties": False,
            },
            fonction=preparer_messages_rdv,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_annuler_rendez_vous",
            description=(
                "Annule une proposition ou une retenue de M1 (jamais un rendez-vous confirmé : il suit la cédule "
                "de M4). Libère les minutes retenues."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "rdv_id": _RDV,
                    "motif": {"type": "string", "minLength": 5, "maxLength": 200},
                    "horodatage": _HORO,
                },
                "required": ["rdv_id", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=annuler_rendez_vous,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_lire_rendez_vous",
            description=(
                "État des rendez-vous de M1 : options, retenue, créneau confirmé par M4, brouillons de messages et "
                "rappels dont l'échéance est passée. Lecture."
            ),
            parametres={
                "type": "object",
                "properties": {"horodatage": _HORO, "rdv_id": {**_RDV, "type": ["string", "null"]}},
                "required": ["horodatage"],
                "additionalProperties": False,
            },
            fonction=lire_rendez_vous,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
    )
