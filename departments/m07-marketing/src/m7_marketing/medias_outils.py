"""Les outils de M7 pour les MÉDIAS PAYANTS : plan de campagne en brouillon, règles d'arrêt préparées, rapport
honnête, anomalies de dépense.

Chaque fonction est une enveloppe mince : elle établit QUI appelle (la plateforme, jamais un argument), lit le
registre durable
de M7 et appelle la fonction pure de `medias_payants/`. Registres : `plans_medias` (plans, chaîne de hachage) et, en
lecture, les
faits publicitaires du registre des signaux (`signaux_marketing`, lus chez la plateforme par les connecteurs de
lecture).

Niveaux (ADR-0009) :
  - rédiger, réviser, soumettre ou retirer un plan : N2 (rien ne sort d'OPSYS) ;
  - évaluer les règles d'arrêt, produire le rapport de performance : T0, MAIS avec la garde de
  `m7_lire_depenses_marketing` (la
    dépense est de l'argent) ;
  - signaler les anomalies de dépense au bus (M9, M8) : N2 (un fait interne, aucune action) ;
  - APPROUVER LE LANCEMENT d'un plan (`m7_demander_lancement_campagne`) : N4, ENGAGEMENT DE DÉPENSE, le propriétaire
  seulement. Un
    agent ne peut que le déposer dans la file ; approuvé, le lancement est CONSIGNÉ
    (`LANCEMENT_APPROUVE_NON_EXECUTE`), jamais
    exécuté : aucun outil ne crée, ne modifie, ne met en pause ni ne finance une campagne chez une plateforme.
Aucun rôle d'appareil.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from opsys import evenements, stockage
from opsys.observabilite.pii import MasqueurPII
from opsys.outils import Autonomie, Niveau, Outil

from .medias_payants import anomalies as anomalies_mod
from .medias_payants import plan as plan_mod
from .medias_payants import rapport as rapport_mod
from .medias_payants import regles as regles_mod
from .publication_outils import POLITIQUE, _decideur, _horodatage
from .signaux import minimisation, modele, registre
from .studio import actifs as actifs_studio
from .usine import service as usine_service

NOM_LANCEMENT = "m7_demander_lancement_campagne"
SOURCE_PAR_CANAL = {"google_ads": modele.GOOGLE_ADS, "meta": modele.META_ADS}
TYPE_ANOMALIE = "m7.anomalie_depense_detectee"
PRODUCTEUR = "m07-marketing"
LIMITE_JOURS = 366


def _journal(reg: tuple[str, str]):
    return stockage.maillons(*reg)


def _maintenant() -> datetime:
    return datetime.now(UTC)


def _masqueur() -> MasqueurPII:
    return minimisation.masqueur_local()


def _resolveur(actif_id: str) -> dict[str, Any]:
    return actifs_studio.media_pour_sas(_journal(actifs_studio.REGISTRE), actif_id)


def _controle_marques():
    try:
        from .veille import conformite, observations
        from .veille import registre as registre_veille
    except ImportError:  # pragma: no cover — le module de veille fait partie du département
        return None
    concurrents = list(registre_veille.plier(stockage.maillons(*registre_veille.REGISTRE)).values())
    vues = observations.charger(stockage.maillons(*observations.REGISTRE_OBSERVATIONS))
    return lambda texte: [
        r["detail"]
        for r in conformite.controler_texte_propose(texte, concurrents, vues)["refus"]
        if r["code"] == "REJ-VEILLE-MARQUE-CONCURRENT"
    ]


def _controles(instant: datetime) -> dict[str, Any]:
    return {
        "politique": POLITIQUE,
        "maintenant": instant,
        "resolveur": _resolveur,
        "masqueur": _masqueur(),
        "controle_marques": _controle_marques(),
    }


def _garde_argent(nom: str) -> None:
    from . import outils as _outils

    _outils._autoriser_lecture_performance(nom)


# -- plans
# --------------------------------------------------------------------------------------------------------------------
def preparer_plan_media(
    plan: dict[str, Any], cle_idempotence: str, horodatage: str, plan_id: str | None = None
) -> dict[str, Any]:
    """N2 : crée (ou révise, avec `plan_id`) un plan de campagne en BROUILLON. Ne lance rien, ne dépense rien."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    return plan_mod.composer(
        _journal(plan_mod.REGISTRE),
        plan,
        cle_idempotence,
        usine_service._qui_appelle()[0],
        instant[0],
        plan_id=plan_id,
        **_controles(instant[1]),
    )


def soumettre_plan_media(plan_id: str, horodatage: str) -> dict[str, Any]:
    """N2 : brouillon -> prêt pour approbation, si tous les contrôles passent à l'instant même (visuels toujours
    approuvés,
    début dans le futur, plafonds)."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    return plan_mod.soumettre(
        _journal(plan_mod.REGISTRE), plan_id, usine_service._qui_appelle()[0], instant[0], **_controles(instant[1])
    )


def demander_lancement_campagne(plan_id: str, empreinte: str, horodatage: str) -> dict[str, Any]:
    """N4 : approuve le LANCEMENT d'un plan (engagement de dépense) par son empreinte exacte. Consigne la décision
    ; n'exécute
    ni ne dépense rien."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    acteur, refus = _decideur(NOM_LANCEMENT)
    if acteur is None:
        return refus
    resultat = plan_mod.approuver_lancement(
        _journal(plan_mod.REGISTRE), plan_id, empreinte, acteur, instant[0], **_controles(instant[1])
    )
    if resultat.get("accepte"):
        resultat = {
            **resultat,
            "statut": plan_mod.APPROUVE,
            "executee_par_opsys": False,
            "suite": "Aucune dépense n'a été engagée par OPSYS : la direction lance la campagne dans la plateforme "
            "avec le dossier de lancement (m7_lire_plans_media avec avec_dossier).",
        }
    return resultat


def retirer_plan_media(plan_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """N2 : retire un plan (jamais effacé). Ne rappelle pas une campagne déjà lancée par la direction."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    return plan_mod.retirer(_journal(plan_mod.REGISTRE), plan_id, usine_service._qui_appelle()[0], motif, instant[0])


def lire_plans_media(
    plan_id: str | None = None, etat: str | None = None, limite: int = 20, avec_dossier: bool = False
) -> dict[str, Any]:
    """T0 : les plans, ou un plan en détail ; pour un plan APPROUVÉ, le dossier de lancement manuel."""
    resultat = plan_mod.lire(_journal(plan_mod.REGISTRE), plan_id, etat, limite)
    if not (avec_dossier and plan_id and resultat.get("accepte")):
        return resultat
    tous, _ = plan_mod.charger(_journal(plan_mod.REGISTRE))
    courant = tous[plan_id]
    if courant.etat != plan_mod.APPROUVE:
        return {
            **resultat,
            "dossier": None,
            "dossier_refus": "le dossier de lancement n'existe que pour un plan dont le lancement est approuvé (N4)",
        }
    medias = {}
    for creatif in courant.plan["creatifs"]:
        lu = _resolveur(creatif["actif_id"])
        if lu.get("accepte") and lu["empreinte_actif"] == creatif["empreinte_actif"]:
            medias[creatif["actif_id"]] = lu["media"]
    return {**resultat, "dossier": plan_mod.dossier_de_lancement(courant, medias)}


# -- lecture des faits publicitaires
# ------------------------------------------------------------------------------------------
def _cents(texte: str) -> int:
    return int((Decimal(texte) * 100).to_integral_value(ROUND_HALF_UP))


def _decimal_ou_none(mesures: dict[str, str], cle: str) -> Decimal | None:
    return Decimal(mesures[cle]) if cle in mesures else None


def _entier_ou_none(mesures: dict[str, str], cle: str) -> int | None:
    if cle not in mesures:
        return None
    valeur = Decimal(mesures[cle])
    return int(valeur) if valeur == valeur.to_integral_value() else None


def lire_serie(canal: str, debut: date, fin: date, *, nature: str, campagne_ref: str | None = None) -> dict[str, Any]:
    """Les jours de dépense lus pour un canal : `nature` `campagne_jour` (toutes les campagnes, ou une seule avec
    `campagne_ref`) ou `compte_jour` (le total du compte). Seuls les faits en CAD servent (jamais de conversion de
    devise) ;
    les autres sont comptés dans `ignores_devise`."""
    source = SOURCE_PAR_CANAL[canal]
    lu = registre.lire(_journal(registre.REGISTRE), source=source, nature=nature, debut=debut, fin=fin, limite=1000)
    # `registre.lire` borne à 1000 faits par page : on reprend tant qu'il en reste (jamais tronqué en silence)
    faits = list(lu["faits"])
    while lu["reste"]:
        lu = registre.lire(
            _journal(registre.REGISTRE),
            source=source,
            nature=nature,
            debut=debut,
            fin=fin,
            limite=1000,
            decalage=len(faits),
        )
        faits += lu["faits"]
    par_campagne: dict[str, dict[date, dict[str, Any]]] = {}
    ignores = 0
    fictifs = False
    for f in faits:
        if campagne_ref is not None and f["portee"]["ref"] != campagne_ref:
            continue
        if "cout_cad" not in f["mesures"] or f["devise"] != "CAD" or f["periode_debut"] != f["periode_fin"]:
            ignores += 1
            continue
        fictifs = fictifs or f["fictif"]
        par_campagne.setdefault(f["portee"]["ref"], {})[date.fromisoformat(f["periode_debut"])] = f
    return {"par_campagne": par_campagne, "ignores_devise": ignores, "fictifs_presents": fictifs}


def _jours_regles(jours: dict[date, dict[str, Any]]) -> list[regles_mod.Jour]:
    return [
        regles_mod.Jour(j, _cents(f["mesures"]["cout_cad"]), _decimal_ou_none(f["mesures"], "conversions"))
        for j, f in sorted(jours.items())
    ]


def _jours_perf(jours: dict[date, dict[str, Any]]) -> list[rapport_mod.JourPerf]:
    return [
        rapport_mod.JourPerf(
            j,
            _cents(f["mesures"]["cout_cad"]),
            _entier_ou_none(f["mesures"], "impressions"),
            _entier_ou_none(f["mesures"], "clics"),
            _decimal_ou_none(f["mesures"], "conversions"),
        )
        for j, f in sorted(jours.items())
    ]


def _periode(debut: str, fin: str) -> tuple[date, date] | dict[str, Any]:
    try:
        d, f = date.fromisoformat(debut), date.fromisoformat(fin)
    except (TypeError, ValueError):
        return {
            "accepte": False,
            "refus": [{"code": "REJ-MEDIA-PERIODE", "chemin": "$", "detail": "debut et fin : dates AAAA-MM-JJ"}],
        }
    if d > f or (f - d).days > LIMITE_JOURS:
        return {
            "accepte": False,
            "refus": [
                {"code": "REJ-MEDIA-PERIODE", "chemin": "$", "detail": "période inversée ou de plus de 367 jours"}
            ],
        }
    return d, f


def _plan_normalise(plan_id: str | None, canal: str | None) -> tuple[Any, str] | dict[str, Any]:
    if plan_id is None:
        if canal not in SOURCE_PAR_CANAL:
            return {
                "accepte": False,
                "refus": [
                    {
                        "code": "REJ-MEDIA-CANAL",
                        "chemin": "$.canal",
                        "detail": f"canal attendu parmi {list(SOURCE_PAR_CANAL)} sans plan",
                    }
                ],
            }
        return None, canal
    tous, refus = plan_mod.charger(_journal(plan_mod.REGISTRE))
    if refus is not None:
        return refus
    courant = tous.get(plan_id)
    if courant is None:
        return {
            "accepte": False,
            "refus": [
                {"code": "REJ-PLAN-MEDIA-INCONNU", "chemin": "$.plan_id", "detail": f"plan inconnu : {plan_id!r}"}
            ],
        }
    if canal is not None and canal != courant.plan["canal"]:
        return {
            "accepte": False,
            "refus": [
                {"code": "REJ-MEDIA-CANAL", "chemin": "$.canal", "detail": "le canal indiqué n'est pas celui du plan"}
            ],
        }
    return courant, courant.plan["canal"]


def evaluer_regles_media(
    debut: str, fin: str, campagne_ref: str | None = None, plan_id: str | None = None, canal: str | None = None
) -> dict[str, Any]:
    """T0 (garde financière) : évalue les règles d'arrêt PRÉPARÉES du plan (ou, sans plan, le saut de dépense et
    les trous) sur les
    jours lus. Rend des constats et des anomalies ; propose au plus une pause ; n'exécute rien."""
    _garde_argent("m7_evaluer_regles_media")
    periode = _periode(debut, fin)
    if isinstance(periode, dict):
        return periode
    cible = _plan_normalise(plan_id, canal)
    if isinstance(cible, dict):
        return cible
    courant, canal_ = cible
    nature = "campagne_jour" if campagne_ref else "compte_jour"
    lu = lire_serie(canal_, periode[0], periode[1], nature=nature, campagne_ref=campagne_ref)
    if not lu["par_campagne"]:
        return {
            "accepte": True,
            "canal": canal_,
            "campagne_ref": campagne_ref,
            "constats": [],
            "anomalies": [],
            "non_evaluables": [
                {
                    "regle": "toutes",
                    "regle_id": "toutes",
                    "raison": "aucun jour de dépense lu pour ce "
                    "canal et cette période : ni zéro ni normal — lire la source d'abord "
                    "(m7_lire_sources_signaux)",
                }
            ],
            "executee": False,
            "ignores_devise": lu["ignores_devise"],
        }
    # un compte peut porter plusieurs séries (plusieurs comptes publicitaires du même canal) : on ne les mélange pas
    if len(lu["par_campagne"]) > 1:
        return {
            "accepte": False,
            "refus": [
                {
                    "code": "REJ-MEDIA-AMBIGU",
                    "chemin": "$",
                    "detail": f"plusieurs séries ({sorted(lu['par_campagne'])}) : indiquer campagne_ref",
                }
            ],
        }
    ((_, jours),) = lu["par_campagne"].items()
    detection = anomalies_mod.detecter(
        canal=canal_,
        campagne_ref=campagne_ref,
        serie=_jours_regles(jours),
        debut=periode[0],
        fin=periode[1],
        plan=courant.plan if courant else None,
        fictif=lu["fictifs_presents"],
    )
    _garde_argent("m7_evaluer_regles_media")
    # l'instant d'observation le plus récent des faits lus : il date la détection SANS horloge (même données, même
    # instant)
    observe_le = max((f["observe_le"] for f in jours.values()), key=modele.instant_rfc3339)
    return {
        "accepte": True,
        "canal": canal_,
        "campagne_ref": campagne_ref,
        "plan_id": plan_id,
        **detection,
        "observe_le": observe_le,
        "executee": False,
        "ignores_devise": lu["ignores_devise"],
        "fictifs_presents": lu["fictifs_presents"],
        "lecture": "Les constats sont des PROPOSITIONS de pause décidées par la direction ; OPSYS n'exécute rien et "
        "n'a aucun accès en écriture aux plateformes.",
    }


def signaler_anomalies_depense(
    debut: str, fin: str, campagne_ref: str | None = None, plan_id: str | None = None, canal: str | None = None
) -> dict[str, Any]:
    """N2 (garde financière) : mêmes constats, et chaque anomalie est annoncée au bus
    (`m7.anomalie_depense_detectee`, M9 et M8),
    idempotente. N'agit sur aucune plateforme."""
    resultat = evaluer_regles_media(debut, fin, campagne_ref, plan_id, canal)
    if not resultat.get("accepte"):
        return resultat
    publiees = 0
    for a in resultat["anomalies"]:
        charge = {
            "anomalie_id": a["anomalie_id"],
            "canal": a["canal"],
            "campagne_ref": a["campagne_ref"],
            "regle": a["regle"],
            "severite": a["severite"],
            "valeur": a["valeur"],
            "seuil": a["seuil"],
            "unite": a["unite"],
            "jour_debut": a["jour_debut"],
            "jour_fin": a["jour_fin"],
            "detectee_le": resultat["observe_le"],
            "fictif": a["fictif"],
        }
        # même détection sur les mêmes faits : même événement (no-op du bus) ; une valeur révisée par la plateforme : un
        # autre événement, jamais un conflit d'enveloppe
        empreinte = hashlib.sha256(json.dumps(charge, sort_keys=True).encode()).hexdigest()[:12]
        evenements.publier(
            TYPE_ANOMALIE, PRODUCTEUR, charge, evenement_id=f"m7-anomalie-{a['anomalie_id']}-{empreinte}"
        )
        publiees += 1
    return {**resultat, "evenements_publies": publiees}


def rapport_performance_media(
    canal: str, debut: str, fin: str, campagne_refs: list[str] | None = None
) -> dict[str, Any]:
    """T0 (garde financière) : rapport de performance honnête (couverture, intervalles, suffisance, aucune cause)."""
    _garde_argent("m7_rapport_performance_media")
    periode = _periode(debut, fin)
    if isinstance(periode, dict):
        return periode
    if canal not in SOURCE_PAR_CANAL:
        return {
            "accepte": False,
            "refus": [
                {
                    "code": "REJ-MEDIA-CANAL",
                    "chemin": "$.canal",
                    "detail": f"canal attendu parmi {list(SOURCE_PAR_CANAL)}",
                }
            ],
        }
    lu = lire_serie(canal, periode[0], periode[1], nature="campagne_jour")
    campagnes = {
        ref: _jours_perf(jours)
        for ref, jours in lu["par_campagne"].items()
        if campagne_refs is None or ref in campagne_refs
    }
    if not campagnes:
        return {
            "accepte": True,
            "canal": canal,
            "campagnes": [],
            "causalite": "non_etablie",
            "ignores_devise": lu["ignores_devise"],
            "lecture": "Aucun jour de campagne lu pour ce canal et cette période : ce n'est pas une absence de "
            "dépense (lire la source d'abord).",
        }
    rapport = rapport_mod.construire(
        canal=canal, campagnes=campagnes, debut=periode[0], fin=periode[1], fictifs_presents=lu["fictifs_presents"]
    )
    _garde_argent("m7_rapport_performance_media")
    return {"accepte": True, **rapport, "ignores_devise": lu["ignores_devise"]}


_HORODATAGE = {"type": "string", "description": "ISO 8601 avec fuseau (l'heure du serveur fait foi)."}
_EMPREINTE = {
    "type": "string",
    "description": "Empreinte SHA-256 exacte du plan à approuver, rendue par la préparation.",
}
_CLE = {"type": "string", "description": "Clé d'idempotence de 16 à 64 caractères [A-Za-z0-9_-] : une clé, un plan."}
_PLAN = {
    "type": "object",
    "description": (
        "{nom, canal (google_ads|meta), objectif (leads|appels|trafic_local), budget {montant_total_cents, "
        "plafond_quotidien_cents, duree_jours, date_debut}, ciblage {zones, rayon_km, langues (fr-CA obligatoire), "
        "mots_cles, mots_cles_negatifs} — géographique et par mots-clés seulement, jamais d'âge, de sexe ni d'autre "
        "critère "
        "protégé —, creatifs [{actif_id d'un visuel du studio APPROUVÉ, textes [{langue, titre, description}] avec "
        "fr-CA}], "
        "regles (facultatif : cpa_max, depense_sans_conversion, saut_depense ; les plafonds sont déduits du budget), "
        "utm_campagne, divulgation_texte_ia, comptes_sas (Meta : facebook|instagram)}. Montants en cents entiers CAD."
    ),
}


def _objet(proprietes: dict[str, Any], requis: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False}


_PERIODE = {"debut": {"type": "string"}, "fin": {"type": "string"}}


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m7_preparer_plan_media",
            description=(
                "Crée (ou révise, avec plan_id) un PLAN DE CAMPAGNE PAYANTE en BROUILLON : budget en cents "
                "(plafonds durs du "
                "sas), ciblage géographique et par mots-clés (aucun critère protégé), créatifs = visuels du studio "
                "déjà "
                "APPROUVÉS par une personne, textes français obligatoires contrôlés, règles d'arrêt préparées (les "
                "deux "
                "plafonds sont déduits du budget). Idempotent par clé. Ne lance rien, ne dépense rien, ne contacte "
                "aucune "
                "plateforme."
            ),
            parametres=_objet(
                {"plan": _PLAN, "cle_idempotence": _CLE, "horodatage": _HORODATAGE, "plan_id": {"type": "string"}},
                ["plan", "cle_idempotence", "horodatage"],
            ),
            fonction=preparer_plan_media,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_soumettre_plan_media",
            description=(
                "Met un brouillon de plan en attente de la décision de la direction, SI tous les contrôles passent "
                "à l'instant "
                "même (visuels toujours approuvés et inchangés, début dans le futur, plafonds, texte, marques). "
                "Rien n'est "
                "lancé."
            ),
            parametres=_objet({"plan_id": {"type": "string"}, "horodatage": _HORODATAGE}, ["plan_id", "horodatage"]),
            fonction=soumettre_plan_media,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom=NOM_LANCEMENT,
            description=(
                "DÉCISION DE LA DIRECTION (N4, ENGAGEMENT DE DÉPENSE) : approuve le LANCEMENT d'un plan de campagne "
                "payante, "
                "budget compris, par son empreinte exacte. Un agent ne peut que la déposer dans la file ; "
                "approuvée, la "
                "décision est CONSIGNÉE (LANCEMENT_APPROUVE_NON_EXECUTE) : OPSYS ne dépense rien et ne crée aucune "
                "campagne ; "
                "la direction lance la campagne dans la plateforme avec le dossier de lancement."
            ),
            parametres=_objet(
                {"plan_id": {"type": "string"}, "empreinte": _EMPREINTE, "horodatage": _HORODATAGE},
                ["plan_id", "empreinte", "horodatage"],
            ),
            fonction=demander_lancement_campagne,
            autonomie=Autonomie.T1,
            niveau=Niveau.N4,
        ),
        Outil(
            nom="m7_retirer_plan_media",
            description="Retire un plan de campagne (jamais effacé). Ne rappelle pas une campagne déjà lancée par "
                        "la direction.",
            parametres=_objet(
                {
                    "plan_id": {"type": "string"},
                    "motif": {"type": "string", "maxLength": 300},
                    "horodatage": _HORODATAGE,
                },
                ["plan_id", "motif", "horodatage"],
            ),
            fonction=retirer_plan_media,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_lire_plans_media",
            description=(
                "Lit les plans de campagne payante (états : BROUILLON, PRET_POUR_APPROBATION, "
                "LANCEMENT_APPROUVE_NON_EXECUTE, "
                "RETIRE) ou un plan en détail ; avec avec_dossier, le dossier de lancement MANUEL d'un plan "
                "approuvé (étapes, "
                "plafonds à saisir, publications d'annonce préparées pour le sas social). Lecture seule."
            ),
            parametres=_objet(
                {
                    "plan_id": {"type": "string"},
                    "etat": {
                        "type": "string",
                        "enum": [plan_mod.BROUILLON, plan_mod.PRET, plan_mod.APPROUVE, plan_mod.RETIRE],
                    },
                    "limite": {"type": "integer", "minimum": 1, "maximum": 50},
                    "avec_dossier": {"type": "boolean"},
                },
                [],
            ),
            fonction=lire_plans_media,
        ),
        Outil(
            nom="m7_evaluer_regles_media",
            description=(
                "Évalue les règles d'arrêt PRÉPARÉES d'un plan (plafond quotidien, plafond total, coût par "
                "conversion maximal, "
                "dépense sans conversion, saut de dépense) et les anomalies de dépense (DEP-01 à DEP-07) sur les "
                "jours lus chez "
                "la plateforme. Un jour manquant est un TROU, jamais un zéro ; une règle sans de quoi être jugée est "
                "« non évaluable » avec sa raison. Propose au plus une PAUSE ; n'exécute rien. Réservé à l'admin "
                "confirmé ou au "
                "propriétaire (argent)."
            ),
            parametres=_objet(
                {
                    **_PERIODE,
                    "campagne_ref": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "canal": {"type": "string", "enum": list(SOURCE_PAR_CANAL)},
                },
                ["debut", "fin"],
            ),
            fonction=evaluer_regles_media,
        ),
        Outil(
            nom="m7_signaler_anomalies_depense",
            description=(
                "Comme m7_evaluer_regles_media, et annonce chaque anomalie de dépense au bus "
                "(m7.anomalie_depense_detectee : "
                "M9 et M8), de façon idempotente. N'agit sur aucune plateforme."
            ),
            parametres=_objet(
                {
                    **_PERIODE,
                    "campagne_ref": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "canal": {"type": "string", "enum": list(SOURCE_PAR_CANAL)},
                },
                ["debut", "fin"],
            ),
            fonction=signaler_anomalies_depense,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_rapport_performance_media",
            description=(
                "Rapport de performance publicitaire HONNÊTE sur les jours lus chez la plateforme : couverture et "
                "jours "
                "manquants, totaux, taux de clic et de conversion avec intervalle de Wilson et effectif, coût par "
                "conversion "
                "avec intervalle, suffisance de l'échantillon (sous 100 clics ou 5 conversions : ne pas conclure), "
                "campagnes "
                "indistinguables regroupées SANS classement, aucune causalité affirmée. Réservé à l'admin confirmé "
                "ou au "
                "propriétaire (argent)."
            ),
            parametres=_objet(
                {
                    "canal": {"type": "string", "enum": list(SOURCE_PAR_CANAL)},
                    **_PERIODE,
                    "campagne_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
                },
                ["canal", "debut", "fin"],
            ),
            fonction=rapport_performance_media,
        ),
    )


__all__ = [
    "NOM_LANCEMENT",
    "demander_lancement_campagne",
    "evaluer_regles_media",
    "lire_plans_media",
    "lire_serie",
    "outils",
    "preparer_plan_media",
    "rapport_performance_media",
    "retirer_plan_media",
    "signaler_anomalies_depense",
    "soumettre_plan_media",
]
