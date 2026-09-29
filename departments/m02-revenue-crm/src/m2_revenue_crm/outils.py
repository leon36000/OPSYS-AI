"""Capacités d'agent du département M2 Revenue CRM.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est
réécrite. `m2_ingerer_lead` compose la chaîne complète (validation structurelle et
frontières → écriture → dédoublonnage → statut → readiness) en un seul appel, ce
qui évite à l'agent plusieurs allers-retours et garantit l'ordre des contrôles —
en particulier qu'un doublon probable est toujours signalé à l'ingestion
(correctif d'audit), jamais fusionné : la fusion n'existe nulle part dans ce
paquet, l'arbitrage humain se limite à confirmer deux dossiers distincts.

État partagé : ce module tient le registre du département, partagé par tous les
outils (ingestion, statuts, doublons, interactions, readiness, digest). En
production, il est adossé au stockage durable de l'instance (ADR-0009) via
`opsys.stockage.maillons(...)`, relu à chaque appel et jamais touché au
chargement du module. `reinitialiser_registre()` (réservé aux tests) le bascule
sur un registre EN MÉMOIRE vide ; `utiliser_stockage_durable()` revient au
stockage durable. Ce module est l'unique endroit du département qui connaît
`opsys` au-delà du contrat `Outil` — `registre.py` reste pur (ni `opsys` ni
SQLAlchemy).

Identité authentifiée (PLAN T1.4-k2, `acces.py`, docs/architecture/ROLES.md) : pour un appel d'appareil,
`_acteur_appareil` lit la personne et le rôle du jeton (`contexte.identite_appelante()`, jamais les
arguments) et les fait confirmer en base à chaque appel. `auteur` d'une interaction vient de cette
personne ; un vendeur ne voit et n'agit que sur les leads dont il est le propriétaire (`owner` de la
transition `nouveau -> qualifie`), l'admin sur tous. Chaque refus précède toute écriture. Sans identité
d'appareil (agent, console, consommateur d'événement) : comportement d'avant, aucun contrôle de personne.

Liste des leads (PLAN T4.6, `liste_leads.py`, `segments.py`) : `m2_lister_leads` lit le registre UNE fois, ne
rend au vendeur que ses leads (`acces.leads_visibles`, même contrôle que le reste), et cite pour chaque
segment sa règle et la donnée qui le déclenche. Les seuils des segments viennent de `department.yaml`
(`configuration.segments`, vides : « seuil à configurer »), relus à chaque appel comme M6 et M8.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from opsys import approbations, contexte, evenements, identite, jetons, stockage
from opsys.outils import Autonomie, Outil

from . import (
    acces,
    clients,
    contrats,
    digest,
    doublons,
    encodage,
    ingestion,
    interactions,
    liste_leads,
    readiness,
    segments,
    statuts,
    suggestions,
    verdicts,
)
from .registre import Registre

_DEPARTEMENT = "m02-revenue-crm"
# WCT déjà appliqués au lead (clé métier : wct_id) : un même fait republié sous un autre
# evenement_id est un « déjà appliqué », jamais une quarantaine. Même patron que `wct_recus` de
# M5 et M6.
_NOM_REGISTRE_WCT_RECUS = "wct_recus"
# Faits m3.devis_sans_reponse déjà appliqués (clé métier : devis_id, M2.7) : même patron que
# _NOM_REGISTRE_WCT_RECUS ci-dessus — un même devis republié sous un autre evenement_id est un
# « déjà appliqué », jamais une quarantaine.
_NOM_REGISTRE_RELANCES_DEVIS_RECUES = "relances_devis_recues"
# Faits m3.devis_accepte déjà appliqués (clé métier : devis_id, PLAN T4.10-a) : même patron — un même devis
# republié sous un autre evenement_id est un « déjà appliqué », jamais une seconde conversion ni une quarantaine.
_NOM_REGISTRE_DEVIS_ACCEPTES_RECUS = "devis_acceptes_recus"
_NOM_REGISTRE = "principal"
# `department.yaml` : source des seuils de segmentation (`configuration.segments`), relue à chaque appel comme
# M6 et M8 relisent la leur (l'admin l'édite sans toucher au code ; un test la remplace).
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"
# `Capacites._tronquer` mesure `{"ok": true, "resultat": ...}` : l'enveloppe et le `{"accepte": true, ...}` de
# M2 tiennent dans cette réserve. Sous ce budget, une page de `m2_lister_leads` n'est jamais tronquée (même
# calcul que M8 et M9).
_RESERVE_ENVELOPPE = 100
BUDGET_SORTIE = jetons.LIMITE_SORTIE_DEFAUT - _RESERVE_ENVELOPPE

_registre_memoire = Registre()
_stockage_durable_actif = True


def reinitialiser_registre() -> None:
    """Réinitialise le registre partagé du département sur un registre EN MÉMOIRE vide
    (réservé aux tests). Annule aussi un éventuel branchement sur le stockage durable :
    après cet appel, `_obtenir_registre()` revient toujours à la mémoire."""
    global _registre_memoire, _stockage_durable_actif
    _registre_memoire = Registre()
    _stockage_durable_actif = False


def utiliser_stockage_durable() -> None:
    """Revient au registre de production, adossé au stockage durable de l'instance (ADR-0009) :
    `opsys.stockage.maillons("m02-revenue-crm", "principal")`, dans la base et la transaction de
    l'appel courant (`opsys.outils.executer_atomique` en ouvre une autour de chaque appel
    d'outil). C'est l'état au chargement du module ; les tests l'utilisent après
    `reinitialiser_registre()`."""
    global _stockage_durable_actif
    _stockage_durable_actif = True


def _obtenir_registre() -> Registre:
    if _stockage_durable_actif:
        # Jamais de cache ici, à dessein (même principe que `opsys.stockage.maillons`) : une
        # instance fraîche à chaque appel relit l'état réel depuis la base, pour ne jamais figer
        # une empreinte devenue périmée entre deux appels d'outil (concurrence, autre processus).
        return Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    return _registre_memoire


def _publier_si_durable(type_evenement: str, charge: dict[str, Any], evenement_id: str) -> None:
    """Publie un événement (ADR-0009 §3) SEULEMENT si le registre de production est adossé au
    stockage durable (voir `_obtenir_registre`). En mode mémoire (tests unitaires, après
    `reinitialiser_registre()`), il n'existe ni base migrée ni consommateur réel : le bus
    d'événements est par nature un mécanisme durable inter-processus, et `evenements.repartir` ne
    tournera de toute façon jamais contre un registre en mémoire — publier échouerait sur une
    table absente pour rien plutôt que d'être un simple no-op silencieux."""
    if _stockage_durable_actif:
        evenements.publier(type_evenement, _DEPARTEMENT, charge, evenement_id=evenement_id)


# Événement publié à chaque qualification d'un lead (PLAN T1.4-k2) : le propriétaire tel que M2 le tient,
# lisible par un autre département à la source du bus (`evenements.charge_publiee`) sans importer M2.
_TYPE_EVENEMENT_LEAD_ASSIGNE = "m2.lead_assigne"


def _acteur_appareil(
    roles_permis: frozenset[str],
) -> tuple[acces.Acteur | None, dict[str, Any] | None]:
    """Qui appelle : ``(None, None)`` hors appel d'appareil, ``(acteur, None)`` si l'identité du jeton est
    CONFIRMÉE en base et dans la portée de l'outil, ``(None, verdict)`` sinon (PLAN T1.4-k2).

    Même patron que ``m4_field_ops.outils._acteur_appareil`` et ``m5_financecore.outils._acteur_appareil``
    (copie voulue : aucun import entre départements, #109 ; un helper du socle les réunirait). Le
    ``contexte.identite_appelante()`` ne rend que ce que le core a transmis en `_meta` : la personne a pu
    être désactivée, ou perdre le rôle, depuis l'émission du jeton. On la revérifie donc à chaque appel
    avec la même fonction que la validation humaine au départ (``approbations.signataire_valide``, T1.4-h :
    personne active portant encore ce rôle). Hors transaction (aucune base jointe), rien n'est vérifiable :
    refus fermé, jamais une identité crue sur parole. Ne lit JAMAIS les arguments de l'outil, n'écrit rien."""
    appelante = contexte.identite_appelante()
    if appelante is None:
        return None, None
    cnx = stockage.connexion_courante()
    confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
    if confirmee is None:
        return None, verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=(
                f"personne {appelante.personne!r} inconnue, inactive, ou ne porte plus le rôle "
                f"{appelante.role!r} porté par le jeton d'appareil (ou identité non vérifiable "
                "hors transaction)"
            ),
        )
    return acces.acteur_de(confirmee.personne, confirmee.role, roles_permis)


def _refus(verdict: dict[str, Any]) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdict}


def _exiger_admin() -> None:
    """Défense en profondeur des outils réservés à l'admin (digest, doublons) : la portée par outil est déjà
    tenue par le core (``Outil.roles_appareil``), le socle ne l'applique pas hors de lui. Un appel d'appareil
    dont l'identité n'est pas confirmée en base, ou qui n'est pas `admin`, lève un refus métier AVANT toute
    lecture ou écriture (``ValueError`` : ces outils rendent une liste ou un texte, pas un verdict)."""
    _, verdict = _acteur_appareil(acces.ROLES_ADMIN)
    if verdict is not None:
        raise ValueError(f"{verdict['code']} : {verdict['detail']}")


def _proprietaire_confirme(owner: Any) -> tuple[str | None, dict[str, Any] | None]:
    """``(identifiant, None)`` si ``owner`` est l'identifiant d'une personne ACTIVE qui peut posséder un lead
    (``acces.ROLES_PROPRIETAIRES``), sinon ``(None, verdict)``. Sert la qualification faite depuis un
    appareil : un ``owner`` saisi de travers ne doit pas rendre le lead invisible à tous les vendeurs, sans
    recours (le propriétaire est consigné une seule fois, à la qualification). Hors transaction : refus
    fermé, rien n'est vérifiable."""
    cnx = stockage.connexion_courante()
    personne = identite.personne_active(cnx, owner.strip()) if cnx is not None and isinstance(owner, str) else None
    if personne is None or not personne.roles & acces.ROLES_PROPRIETAIRES:
        return None, verdicts.construire_verdict(
            "REJ-OWNER-INCONNU",
            detail=(
                "owner doit être l'identifiant d'une personne OPSYS active portant le rôle seller ou admin "
                "(c'est cet identifiant qui rend le lead visible à son vendeur)"
            ),
        )
    return personne.identifiant, None


def _ingerer_et_lier(
    contrat: dict[str, Any], horodatage: str, reg: Registre
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Ingestion + lien Client 360 (PLAN T2.2), chemin PARTAGÉ par `ingerer_lead` et par
    l'ouverture automatique d'une nouvelle opportunité pour un client existant
    (`_ouvrir_nouvelle_opportunite_pour_wct`) — pour que les deux endroits ne puissent jamais
    diverger sur ce que « ingérer un lead » signifie. Publie `m2.client_associe` (catalogue
    `src/opsys/evenements/catalogue/m2.client_associe.json`) dans la MÊME transaction que
    l'ingestion (ADR-0009 §3) : M5 (aujourd'hui `client_id = lead_id`, en attente de ceci —
    `departments/m05-financecore/src/m5_financecore/outils.py::_essayer_facture_brouillon`) et M7
    (attribution des sources, M2.10) peuvent s'y abonner. N'écrit AUCUN signalement de doublon :
    c'est la responsabilité de l'appelant (voir `ingerer_lead`), pas de ce socle commun.
    """
    accuse, verdict = ingestion.ingerer(contrat, reg, horodatage)
    if verdict is not None:
        return None, verdict

    lead_id = contrat["lead_id"]
    # lier_lead ne peut refuser qu'un horodatage invalide, déjà validé ci-dessus par
    # ingestion.ingerer : un refus ici serait une incohérence interne, jamais un refus métier
    # normal à ce stade (même patron que marquer_chantier_termine pour son interaction système).
    lien_client, verdict_client = clients.lier_lead(reg, lead_id, contrat, horodatage)
    if verdict_client is not None:
        raise RuntimeError(f"clients.lier_lead a refusé un lead déjà ingéré avec succès : {verdict_client}")

    _publier_si_durable(
        "m2.client_associe",
        {
            "lead_id": lead_id,
            "client_id": lien_client["client_id"],
            "horodatage_association": accuse["horodatage"],
        },
        f"m2-client-associe-{lead_id}",
    )
    accuse["client_id"] = lien_client["client_id"]
    return accuse, None


# ---------------------------------------------------------------------------
# Fonctions enveloppes — chacune appelle le code métier existant tel quel.
# ---------------------------------------------------------------------------


def ingerer_lead(contrat: dict[str, Any], horodatage: str) -> dict[str, Any]:
    """Ingestion de bout en bout : validation + frontières (ingestion.ingerer),
    dédoublonnage (chaque doublon détecté à l'ingestion est signalé, jamais
    fusionné — correctif d'audit PRD §2b), lien Client 360 (PLAN T2.2), statut
    courant, readiness pour M3."""
    reg = _obtenir_registre()
    accuse, verdict = _ingerer_et_lier(contrat, horodatage, reg)
    if verdict is not None:
        return {"etape": "ingestion", "accepte": False, "verdict": verdict}

    lead_id = contrat["lead_id"]
    doublons_signales = []
    for autre_lead_id in accuse["doublons_detectes"]:
        signalement, verdict_doublon = doublons.signaler(reg, lead_id, autre_lead_id, horodatage)
        if verdict_doublon is None:
            doublons_signales.append(signalement)

    return {
        "etape": "complet",
        "accepte": True,
        "lead_id": lead_id,
        "client_id": accuse["client_id"],
        "accuse_ingestion": accuse,
        "doublons_signales": doublons_signales,
        "statut": statuts.statut_courant(reg, lead_id),
        "pret_pour_m3": readiness.evaluer(reg, lead_id),
    }


def transitionner_statut(
    lead_id: str,
    statut_cible: str,
    horodatage: str,
    owner: str | None = None,
    prochaine_action: dict[str, Any] | None = None,
    reference_devis_m3: str | None = None,
    motif: str | None = None,
) -> dict[str, Any]:
    """Transition de statut (`statuts.transitionner`).

    Appel d'appareil (PLAN T1.4-k2) : identité confirmée en base, puis un vendeur ne transitionne que
    SES leads (`acces.controler_lead`) ; à la qualification faite depuis un appareil (admin, seul à voir un
    lead `nouveau`), `owner` doit être l'identifiant d'une personne active qui peut posséder un lead
    (`_proprietaire_confirme`). Chaque refus précède toute écriture. Sans identité d'appareil : `owner`
    reste du texte libre, comme avant.

    La qualification publie `m2.lead_assigne` (propriétaire du lead, dans la MÊME transaction) : c'est ce
    fait, lu à la source du bus, que M3 confronte pour ne rendre à un vendeur que les devis de ses leads."""
    acteur, verdict_acteur = _acteur_appareil(acces.ROLES_LEADS)
    if verdict_acteur is not None:
        return _refus(verdict_acteur)
    reg = _obtenir_registre()
    verdict_lead = acces.controler_lead(reg, lead_id, acteur)
    if verdict_lead is not None:
        return _refus(verdict_lead)
    if (
        acteur is not None
        and statut_cible == "qualifie"
        and statuts.statut_courant(reg, lead_id) == "nouveau"
        and isinstance(owner, str)
        and owner.strip()
    ):
        owner, verdict_owner = _proprietaire_confirme(owner)
        if verdict_owner is not None:
            return _refus(verdict_owner)
    accuse, verdict = statuts.transitionner(
        lead_id, statut_cible, reg, horodatage,
        owner=owner, prochaine_action=prochaine_action,
        reference_devis_m3=reference_devis_m3, motif=motif,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    if statut_cible == "qualifie" and accuse["statut_precedent"] == "nouveau":
        # `owner` est ici une chaîne non vide : sans quoi `statuts.transitionner` aurait refusé.
        _publier_si_durable(
            _TYPE_EVENEMENT_LEAD_ASSIGNE,
            {"lead_id": lead_id, "proprietaire": owner.strip(), "horodatage_assignation": accuse["horodatage"]},
            f"m2-lead-assigne-{lead_id}",
        )
    return {"accepte": True, "resultat": accuse}


def detecter_doublons(lead_id: str) -> list[str]:
    _exiger_admin()
    return doublons.detecter(_obtenir_registre(), lead_id)


def signaler_doublon(lead_id_a: str, lead_id_b: str, horodatage: str) -> dict[str, Any]:
    _, verdict_acteur = _acteur_appareil(acces.ROLES_ADMIN)
    if verdict_acteur is not None:
        return _refus(verdict_acteur)
    signalement, verdict = doublons.signaler(_obtenir_registre(), lead_id_a, lead_id_b, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": signalement}


def arbitrer_doublon(signalement_id: str, decision: str, horodatage: str) -> dict[str, Any]:
    _, verdict_acteur = _acteur_appareil(acces.ROLES_ADMIN)
    if verdict_acteur is not None:
        return _refus(verdict_acteur)
    accuse, verdict = doublons.arbitrer(_obtenir_registre(), signalement_id, decision, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": accuse}


def enregistrer_interaction(
    lead_id: str, auteur: str | None = None, resume: str = "", horodatage: str = ""
) -> dict[str, Any]:
    """Enregistre une interaction (`interactions.enregistrer`).

    Appel d'appareil (PLAN T1.4-k2) : identité confirmée en base ; `auteur` VIENT de la personne
    authentifiée (absent : elle ; différent : `REJ-IDENTITE-FOURNIE-DIFFERENTE`, jamais remplacé en
    silence, `admin` compris) ; un vendeur n'écrit que sur SES leads. Chaque refus précède toute écriture.
    Sans identité d'appareil : `auteur` est celui de l'appelant, obligatoire (`REJ-CHAMP-VIDE` sinon, qui
    remplace l'ancien refus de schéma `arguments_invalides`). `resume` et `horodatage` restent requis par le
    schéma de l'outil : leurs valeurs par défaut ne servent qu'à un appel Python direct, qui obtient alors le
    verdict du champ vide plutôt qu'une exception."""
    acteur, verdict_acteur = _acteur_appareil(acces.ROLES_LEADS)
    if verdict_acteur is not None:
        return _refus(verdict_acteur)
    auteur_consigne, verdict_auteur = acces.auteur_effectif(acteur, auteur)
    if verdict_auteur is not None:
        return _refus(verdict_auteur)
    reg = _obtenir_registre()
    verdict_lead = acces.controler_lead(reg, lead_id, acteur)
    if verdict_lead is not None:
        return _refus(verdict_lead)
    accuse, verdict = interactions.enregistrer(lead_id, auteur_consigne, resume, reg, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": accuse}


def trouver_client_de_lead(lead_id: str) -> dict[str, Any]:
    """PLAN T2.2 (Client 360) : le client_id auquel ce lead (opportunité) est rattaché. Appel d'appareil
    (PLAN T1.4-k2) : identité confirmée, et un vendeur ne l'obtient que pour SES leads."""
    acteur, verdict_acteur = _acteur_appareil(acces.ROLES_LEADS)
    if verdict_acteur is not None:
        return _refus(verdict_acteur)
    reg = _obtenir_registre()
    verdict_lead = acces.controler_lead(reg, lead_id, acteur)
    if verdict_lead is not None:
        return _refus(verdict_lead)
    client_id = clients.client_de_lead(reg, lead_id)
    if client_id is None:
        return {
            "accepte": False,
            "verdict": verdicts.construire_verdict(
                "REJ-TRANSITION-ILLEGALE", detail=f"lead {lead_id} introuvable ou non lié à un client"
            ),
        }
    return {"accepte": True, "resultat": {"lead_id": lead_id, "client_id": client_id}}


def obtenir_client_360(client_id: str) -> dict[str, Any]:
    """PLAN T2.2 (Client 360) : vue compacte des opportunités, statuts, prochaines actions
    connues et interactions récentes d'un client. Lecture pure, aucune écriture.

    Appel d'appareil (PLAN T1.4-k2) : identité confirmée ; un vendeur ne voit d'un client que SES
    opportunités (statut, prochaine action, interactions), et un client dont aucune ne lui appartient
    donne le même refus qu'un client inconnu. L'admin voit tout."""
    acteur, verdict_acteur = _acteur_appareil(acces.ROLES_LEADS)
    if verdict_acteur is not None:
        return _refus(verdict_acteur)
    reg = _obtenir_registre()
    permis = acces.leads_visibles(reg, clients.opportunites_du_client(reg, client_id), acteur)
    if permis is not None and not permis:
        return _refus(acces.refus_client_sans_lead_visible())
    vue, verdict = clients.obtenir_vue_360(reg, client_id, permis)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": vue}


def suggerer_prochaine_action(lead_id: str, horodatage: str) -> dict[str, Any]:
    """PLAN T2.2 (M2.6) : suggestion déterministe de prochaine meilleure action, par table de
    règles citée (suggestions.suggerer) — jamais appliquée automatiquement au registre. Appel d'appareil
    (PLAN T1.4-k2) : identité confirmée, et un vendeur ne la reçoit que pour SES leads."""
    acteur, verdict_acteur = _acteur_appareil(acces.ROLES_LEADS)
    if verdict_acteur is not None:
        return _refus(verdict_acteur)
    reg = _obtenir_registre()
    verdict_lead = acces.controler_lead(reg, lead_id, acteur)
    if verdict_lead is not None:
        return _refus(verdict_lead)
    suggestion, verdict = suggestions.suggerer(reg, lead_id, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": suggestion}


def _seuils_segments() -> dict[str, dict[str, Any]]:
    """Les seuils de segmentation de `department.yaml/configuration.segments`, relus à chaque appel (patron de
    M6 et de M8). Bloc absent ou vide : « seuil à configurer » ; illisible : « seuil invalide ». Jamais une valeur
    par défaut (`segments.lire_seuils`)."""
    donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8"))
    configuration = donnees.get("configuration") if isinstance(donnees, dict) else None
    if configuration is None or isinstance(configuration, dict):
        bloc = configuration.get("segments") if isinstance(configuration, dict) else None
    else:
        bloc = configuration
    return segments.lire_seuils(bloc)


def _devis_sans_reponse_recus() -> list[dict[str, Any]] | None:
    """Les faits `m3.devis_sans_reponse` déjà reçus (registre `relances_devis_recues`, celui que remplit
    `_recevoir_devis_sans_reponse`). `None` quand le registre de M2 est en mémoire (tests unitaires sans base) :
    la source n'existe pas, `quote_stale` est alors non calculable, jamais « aucun devis en retard »."""
    if not _stockage_durable_actif:
        return None
    return list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RELANCES_DEVIS_RECUES))


def lister_leads(
    horodatage: str,
    statut: str | None = None,
    segment: str | None = None,
    decalage: int = 0,
    limite: int = liste_leads.LIMITE_DEFAUT,
) -> dict[str, Any]:
    """PLAN T4.6 (M2.11) : les leads que l'appelant peut voir, par statut et par segment, une page à la fois.
    Lecture pure, aucune écriture.

    Appel d'appareil : identité confirmée en base, puis un vendeur ne voit que SES leads (`acces.leads_visibles`,
    le même contrôle que les autres outils de lecture), l'admin tous ; un employé est refusé
    (`REJ-IDENTITE-APPAREIL-INVALIDE`). Un lead d'un autre n'est ni listé ni compté. Sans identité d'appareil
    (agent, console) : tous les leads, comme avant T1.4-k2. Le registre est lu une seule fois. La règle des
    segments et l'ordre de la liste sont ceux de `segments.py` et de `liste_leads.py`."""
    acteur, verdict_acteur = _acteur_appareil(acces.ROLES_LEADS)
    if verdict_acteur is not None:
        return _refus(verdict_acteur)
    maillons = _obtenir_registre().lire()
    visibles = acces.leads_visibles(
        liste_leads.Vue(maillons), liste_leads.identifiants_des_leads(maillons), acteur)
    page, verdict = liste_leads.lister(
        maillons,
        visibles=visibles,
        relances_devis=_devis_sans_reponse_recus(),
        seuils=_seuils_segments(),
        horodatage=horodatage,
        statut=statut,
        segment=segment,
        decalage=decalage,
        limite=limite,
        budget_caracteres=BUDGET_SORTIE,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": page}


def marquer_chantier_termine(
    lead_id: str,
    horodatage: str,
    prochaine_action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Chorégraphie « travaux terminés » côté M2 (DEFINITION-PRODUIT §6, cascade, ligne M2 :
    « Marque le chantier terminé, écrit l'activité, définit la prochaine action »).

    Transitionne le lead de 'chantier' à 'facture' (statuts.transitionner porte déjà, pour ce
    chemin, la condition prochaine_action — REJ-ACTION-ABSENTE sinon, avant toute écriture),
    puis écrit une interaction système (auteur 'system:m4', jamais un humain ni un texte libre
    généré par un modèle) dont le résumé est composé par ce module depuis les seuls champs
    reçus (lead_id, prochaine_action).

    Exactement deux maillons en cas de succès (transition puis interaction), zéro en cas de
    rejet : la validation de statuts.transitionner précède toute écriture, et par construction
    rien dans ce chemin ne peut faire échouer l'interaction une fois la transition acceptée
    (même horodatage déjà validé, lead désormais non terminal — la correction des statuts
    ci-dessus le garantit —, auteur et résumé non vides par construction) : sinon RuntimeError,
    jamais un maillon orphelin. Le registre est obtenu une seule fois et réutilisé pour les deux
    écritures (même patron que ingerer_lead), et — appelé via opsys.outils.executer_atomique,
    comme tout outil — les deux écritures partagent la transaction de base ouverte par cet
    appel (ADR-0009) : tout est annulé ensemble si quoi que ce soit échoue."""
    reg = _obtenir_registre()
    transition, verdict = statuts.transitionner(
        lead_id, "facture", reg, horodatage, prochaine_action=prochaine_action,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}

    resume = (
        f"Chantier terminé (lead {lead_id}). Prochaine action : "
        f"{prochaine_action['description']} (échéance {prochaine_action['echeance']})."
    )
    interaction, verdict_interaction = interactions.enregistrer(
        lead_id, "system:m4", resume, reg, horodatage,
    )
    if verdict_interaction is not None:
        raise RuntimeError(
            "interaction système refusée après une transition chantier->facture réussie "
            f"(incohérence interne, pas un refus métier normal) : {verdict_interaction}"
        )
    return {"accepte": True, "resultat": {"transition": transition, "interaction": interaction}}


# ---------------------------------------------------------------------------
# Consommateur d'événements (ADR-0009 §3, PLAN T1.2-c) : m4.travaux_termines
# ---------------------------------------------------------------------------
# La complétion d'un chantier (WCT de M4) prouve que la cédule et le chantier ont eu lieu :
# DEFINITION-PRODUIT §6, cascade « travaux terminés », ligne M2 « Marque le chantier terminé,
# écrit l'activité, définit la prochaine action ». Un lead introuvable, ou dont le statut
# commercial est incompatible avec une complétion de chantier, est une incohérence de données
# entre M4 et M2 : les deux exceptions nommées ci-dessous en sont la preuve pour le répartiteur
# (ADR-0009 §3) — jamais un refus métier silencieux, jamais une écriture partielle.


class LeadIntrouvable(LookupError):
    """lead_id absent du registre M2 — incohérence de données entre M2 et le département qui a
    publié l'événement (DEFINITION-PRODUIT §7 M2 : « Aucun lead sans statut, propriétaire,
    prochaine action ou historique »). Partagée par tous les consommateurs d'événements de ce
    module qui exigent un lead déjà connu : m4.travaux_termines (M4), m3.devis_sans_reponse
    (M3, M2.7 — voir _recevoir_devis_sans_reponse plus bas) et m3.devis_accepte (M3, PLAN T4.10-a —
    voir _recevoir_devis_accepte). Jamais un refus métier normal : le
    répartiteur réessaie puis met en quarantaine (ADR-0009 §3), sans qu'aucune écriture n'ait eu
    lieu ; le fait lui-même reste dans evenements_sortants (jamais supprimé), donc disponible
    pour une arrivée tardive si un humain republie l'événement une fois le lead connu de M2."""


class StatutIncompatibleAvecCompletion(ValueError):
    """m4.travaux_termines : le lead existe mais son statut commercial est incompatible avec une
    complétion de chantier — antérieur à la conversion (nouveau, qualifie), clos sans avoir
    jamais été converti (perdu : statuts.STATUTS_TERMINAUX n'admet aucune transition sortante), ou
    déjà postérieur au chantier (facture, paiement, avis) SANS client associé retrouvable
    (incohérence de données : chaque lead ingéré depuis PLAN T2.2 est lié à un client — voir
    `OpportuniteAmbigue` et `_ouvrir_nouvelle_opportunite_pour_wct` pour le cas normal, avec
    client, d'une affaire répétée). Jamais un refus métier normal : le répartiteur réessaie puis
    met en quarantaine (ADR-0009 §3), sans écriture."""


class OpportuniteAmbigue(ValueError):
    """m4.travaux_termines : le lead d'origine a déjà terminé SON propre cycle (facture, paiement
    ou avis — PLAN T2.2, relevé T1.2-e) et le CLIENT associé (clients.py, Client 360) porte
    PLUSIEURS opportunités actuellement EN COURS (converti, cedule ou chantier) : impossible de
    déterminer, sans décision humaine, à laquelle rattacher ce WCT. Jamais un choix arbitraire
    (ex. la plus récente) : §7 M2 interdit toute transition sans décision humaine explicite. Le
    répartiteur réessaie puis met en quarantaine (ADR-0009 §3) — visible par un humain
    (`opsys evenements etat`), qui arbitre manuellement (une interaction ou une transition
    explicite sur la bonne opportunité) puis, au besoin, republie le WCT."""


# Table de règles déterministe : statut commercial courant du lead -> étapes de transition à
# parcourir avant `marquer_chantier_termine` (DEFINITION-PRODUIT §6 cascade « travaux terminés »,
# ligne M2 ; §7 M2 « Cycle de vie couvert » : ...converti → cédule → chantier → facture...).
# Chaque étape est un couple déjà autorisé SANS condition additionnelle par
# statuts.TRANSITIONS_AUTORISEES (seul chantier->facture, parcouru par marquer_chantier_termine
# juste après, exige prochaine_action). Un statut absent de cette table est, par définition,
# incompatible avec une complétion de chantier (StatutIncompatibleAvecCompletion ci-dessus) —
# SAUF les trois de _STATUTS_POST_CHANTIER ci-dessous, gérés séparément (PLAN T2.2).
_ETAPES_VERS_CHANTIER: dict[str, tuple[str, ...]] = {
    "converti": ("cedule", "chantier"),
    "cedule": ("chantier",),
    "chantier": (),
}

# PLAN T2.2, relevé T1.2-e : « un second chantier pour un lead déjà à facture part en quarantaine
# (le cycle de vie est par lead, pas par chantier) ». Un lead à l'un de ces trois statuts a DÉJÀ
# terminé son propre cycle jusqu'au chantier : un second WCT pour ce même lead_id n'est plus une
# incohérence de données, c'est le signe d'une affaire répétée pour le même CLIENT (M4 n'a pas
# d'autre identifiant à reporter que le lead_id d'origine — voir _recevoir_travaux_termines).
_STATUTS_POST_CHANTIER: tuple[str, ...] = ("facture", "paiement", "avis")


def _regle_prochaine_action(charge: dict[str, Any]) -> dict[str, Any]:
    """Table de règles déterministe pour la prochaine action après complétion (PLAN T1.2-c ;
    DEFINITION-PRODUIT §6 cascade « travaux terminés », ligne M2 « ...définit la prochaine
    action » ; §7 M2, règles dures : « jamais...laisser un lead sans prochaine action »).

    La description est un texte FIXE choisi ci-dessous (jamais généré par un modèle) ;
    l'échéance est l'horodatage RÉEL du WCT (horodatage_completion) — jamais une date inventée
    ni calculée depuis une horloge ambiante.

    - Règle 1 (client_satisfait est False) : segment M2.11 `complaint_risk` (§7 M2) — traiter
      le risque de plainte avant toute autre relance.
    - Règle 2 (client_satisfait est True) : relances M2.7 « avis, référence » et segment M2.11
      `referral_candidate` (§7 M2).
    - Règle 3 (client_satisfait absent de la charge, ou explicitement null — jamais déduit) :
      repli par défaut sur le segment M2.11 `invoice_pending`, cohérent avec le statut
      `facture` que la transition vient d'atteindre.

    PLAN T2.2 : `charge["lead_id"]` doit être l'opportunité RÉELLEMENT visée par la transition
    (`lead_cible` dans `_recevoir_travaux_termines`, jamais forcément le `lead_id` d'origine du
    WCT quand celui-ci a été rattaché à une autre opportunité du même client) — une seule table,
    jamais un second calcul divergent selon qui appelle.
    """
    lead_id = charge["lead_id"]
    echeance = charge["horodatage_completion"]
    client_satisfait = charge.get("client_satisfait")
    if client_satisfait is False:
        description = (
            f"Traiter le risque de plainte du lead {lead_id} avant toute relance "
            "(client insatisfait signalé au WCT — DEFINITION-PRODUIT §7 M2.11 complaint_risk)."
        )
    elif client_satisfait is True:
        description = (
            f"Lancer la relance avis et référence du lead {lead_id} "
            "(client satisfait signalé au WCT — DEFINITION-PRODUIT §7 M2.7, M2.11 referral_candidate)."
        )
    else:
        description = (
            f"Assurer le suivi de la facture du lead {lead_id} jusqu'au paiement "
            "(client_satisfait non recueilli au WCT — DEFINITION-PRODUIT §7 M2.11 invoice_pending)."
        )
    return {"description": description, "echeance": echeance}


def _ouvrir_nouvelle_opportunite_pour_wct(
    reg: Registre,
    wct_recus,
    lead_id_origine: str,
    client_id: str,
    wct_id: str,
    horodatage: str,
) -> dict[str, Any]:
    """Ouvre une NOUVELLE opportunité pour le même client, AU LIEU D'UNE QUARANTAINE (PLAN T2.2,
    relevé T1.2-e), quand un WCT arrive pour un lead déjà au bout de son propre cycle
    (`_STATUTS_POST_CHANTIER`) et qu'aucune autre opportunité de ce client n'est en cours.

    Contact, ville, type de travaux et canal sont copiés VERBATIM depuis le contrat déjà validé
    du lead d'origine (des faits déjà connus de ce client, jamais une nouvelle donnée inventée) ;
    ``conversation_id`` aussi, faute d'une nouvelle conversation M1 à référencer. La nouvelle
    opportunité reste au statut `nouveau` : AUCUNE transition n'est fabriquée sans owner ni
    décision humaine (§7 M2, « jamais...laisser un lead sans prochaine action » — mais aussi
    jamais de transition sans décision humaine explicite). Elle devient orpheline au sens du
    digest (`digest.py`, 48 h sans owner) comme n'importe quel autre lead sans propriétaire
    assigné ; une interaction système explique pourquoi elle existe.

    Ne signale PAS de doublon (`doublons.signaler`) contre le lead d'origine : ce n'est pas un
    doublon accidentel à arbitrer, c'est une affaire répétée intentionnellement reconnue par ce
    correctif (M2.14 « Références et affaires répétées ») — un signalement forcerait un arbitrage
    humain sans objet.
    """
    contrat_origine = None
    for m in reg.lire():
        if m.get("type_entree") == "lead_ingere" and m.get("lead_id") == lead_id_origine:
            contrat_origine = m.get("contrat")
    if contrat_origine is None:
        # Ne devrait jamais arriver : le lead d'origine existe forcément (statut déjà lu par
        # l'appelant) — défense en profondeur, même famille d'incohérence que LeadIntrouvable.
        raise LeadIntrouvable(
            f"m4.travaux_termines : contrat introuvable pour le lead d'origine {lead_id_origine!r}"
        )

    nouveau_lead_id = f"{lead_id_origine}~opp~{wct_id}"
    nouveau_contrat = dict(contrat_origine, lead_id=nouveau_lead_id)
    _accuse, verdict = _ingerer_et_lier(nouveau_contrat, horodatage, reg)
    if verdict is not None:
        # Ne devrait jamais arriver : nouveau_contrat n'est qu'une copie d'un contrat déjà validé
        # (seul lead_id change, garanti frais par la présence de wct_id dans son suffixe).
        raise RuntimeError(
            "m4.travaux_termines : réouverture d'opportunité refusée pour un contrat déjà validé "
            f"à l'origine ({lead_id_origine!r}) : {verdict}"
        )

    resume = (
        f"Nouvelle opportunité ouverte pour le client {client_id} (affaire répétée, M2.14) suite "
        f"au WCT {wct_id} du lead {lead_id_origine} — celui-ci a déjà terminé son propre cycle. "
        "Aucun représentant assigné : qualifier avant de pouvoir facturer ce chantier déjà exécuté."
    )
    _, verdict_interaction = interactions.enregistrer(nouveau_lead_id, "system:m4", resume, reg, horodatage)
    if verdict_interaction is not None:
        raise RuntimeError(
            "m4.travaux_termines : interaction système refusée sur la nouvelle opportunité "
            f"{nouveau_lead_id!r} juste après son ingestion : {verdict_interaction}"
        )

    wct_recus.append({
        "wct_id": wct_id,
        "lead_id": lead_id_origine,
        "lead_id_applique": None,
        "nouvelle_opportunite": nouveau_lead_id,
        "horodatage_completion": horodatage,
    })
    return {
        "traite": True,
        "lead_id": lead_id_origine,
        "wct_id": wct_id,
        "client_id": client_id,
        "nouvelle_opportunite": nouveau_lead_id,
        "statut_nouvelle_opportunite": "nouveau",
    }


def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme m4.travaux_termines (ADR-0009 §3, PLAN T1.2-c ; DEFINITION-PRODUIT §6 cascade
    « travaux terminés », ligne M2). Détermine l'opportunité RÉELLE à faire progresser :

    - le lead du WCT est à `converti`/`cedule`/`chantier` -> chemin nominal inchangé, il avance
      jusqu'à `chantier` (`_ETAPES_VERS_CHANTIER`) puis `marquer_chantier_termine` ;
    - le lead du WCT a DÉJÀ terminé son propre cycle (`_STATUTS_POST_CHANTIER` : facture, paiement,
      avis) -> PLAN T2.2 (relevé T1.2-e), plus une incohérence en soi : cherche, PARMI LES AUTRES
      OPPORTUNITÉS DU MÊME CLIENT (clients.py, Client 360), celle qui est actuellement en cours —
      exactement une : le WCT s'y rattache ; aucune : une NOUVELLE opportunité s'ouvre pour ce
      client au lieu d'une quarantaine (`_ouvrir_nouvelle_opportunite_pour_wct`) ; plusieurs :
      `OpportuniteAmbigue`, jamais un choix arbitraire ;
    - tout autre statut (nouveau, qualifie, perdu, ou post-chantier sans client associé — ne
      devrait jamais arriver depuis PLAN T2.2) -> incohérence de données réelle,
      `StatutIncompatibleAvecCompletion`, inchangé.

    Une erreur NOMMÉE (`LeadIntrouvable`, `StatutIncompatibleAvecCompletion`, `OpportuniteAmbigue`)
    n'écrit jamais rien de partiel — le répartiteur livre chaque paire (événement, consommateur)
    dans son propre point de sauvegarde (ADR-0009 §3) : un lever ici annule toute transition déjà
    amorcée par CET appel, et le répartiteur réessaie puis met en quarantaine après 5 échecs,
    visible par un humain.

    Idempotent à deux niveaux : le répartiteur n'appelle cette fonction qu'une fois par
    (evenement_id, consommateur) traité avec succès (`EVENEMENTS_RECUS` UNIQUE, ADR-0009 §3), et
    un même WCT republié sous un autre evenement_id est reconnu par son `wct_id`
    (`_NOM_REGISTRE_WCT_RECUS`) : rien ne s'écrit une seconde fois, aucune quarantaine.
    """
    lead_id = charge["lead_id"]
    wct_id = charge["wct_id"]
    horodatage = charge["horodatage_completion"]
    wct_recus = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)
    if any(recu.get("wct_id") == wct_id for recu in wct_recus):
        return {"traite": True, "lead_id": lead_id, "wct_id": wct_id, "deja_applique": True}
    reg = _obtenir_registre()

    statut = statuts.statut_courant(reg, lead_id)
    if statut is None:
        raise LeadIntrouvable(f"m4.travaux_termines : lead {lead_id!r} introuvable au registre M2")

    lead_cible = lead_id
    if statut in _STATUTS_POST_CHANTIER:
        client_id = clients.client_de_lead(reg, lead_id)
        if client_id is None:
            # Ne devrait jamais arriver pour un lead ingéré depuis ce correctif (chaque ingestion
            # lie un client, _ingerer_et_lier) : fail-closed, même famille que les statuts
            # antérieurs à la conversion ci-dessous — incohérence de données, pas un cas normal.
            raise StatutIncompatibleAvecCompletion(
                f"m4.travaux_termines : lead {lead_id!r} au statut {statut!r} sans client associé "
                "(Client 360, PLAN T2.2) — incohérence de données, impossible de chercher une "
                "opportunité de reprise pour ce client."
            )
        candidats = sorted(
            autre for autre in clients.opportunites_du_client(reg, client_id)
            if autre != lead_id and statuts.statut_courant(reg, autre) in _ETAPES_VERS_CHANTIER
        )
        if len(candidats) > 1:
            raise OpportuniteAmbigue(
                f"m4.travaux_termines : le client {client_id!r} porte {len(candidats)} "
                f"opportunités en cours ({candidats!r}) — impossible de déterminer laquelle "
                f"rattacher au WCT {wct_id!r} sans décision humaine."
            )
        if len(candidats) == 1:
            lead_cible = candidats[0]
        else:
            return _ouvrir_nouvelle_opportunite_pour_wct(reg, wct_recus, lead_id, client_id, wct_id, horodatage)

    statut_cible_depart = statuts.statut_courant(reg, lead_cible)
    etapes = _ETAPES_VERS_CHANTIER.get(statut_cible_depart)
    if etapes is None:
        raise StatutIncompatibleAvecCompletion(
            f"m4.travaux_termines : lead {lead_id!r} au statut {statut!r}, incompatible avec une "
            "complétion de chantier (attendu converti, cedule ou chantier)"
        )

    depuis = statut_cible_depart
    for statut_cible in etapes:
        _, verdict = statuts.transitionner(lead_cible, statut_cible, reg, horodatage)
        if verdict is not None:
            # Jamais attendu : _ETAPES_VERS_CHANTIER ne propose que des couples autorisés sans
            # condition additionnelle par statuts.py — défense en profondeur, même patron que
            # marquer_chantier_termine ci-dessus pour son écriture d'interaction.
            raise RuntimeError(
                f"m4.travaux_termines : transition {depuis}->{statut_cible} refusée de façon "
                f"inattendue pour le lead {lead_cible!r} : {verdict}"
            )
        depuis = statut_cible

    prochaine_action = _regle_prochaine_action({**charge, "lead_id": lead_cible})
    resultat = marquer_chantier_termine(lead_cible, horodatage, prochaine_action)
    if not resultat["accepte"]:
        raise RuntimeError(
            "m4.travaux_termines : marquer_chantier_termine refusé après une transition validée "
            f"pour le lead {lead_cible!r} : {resultat['verdict']}"
        )
    wct_recus.append({
        "wct_id": wct_id,
        "lead_id": lead_id,
        "lead_id_applique": lead_cible,
        "horodatage_completion": horodatage,
    })
    return {
        "traite": True,
        "lead_id": lead_id,
        "lead_id_applique": lead_cible,
        "wct_id": wct_id,
        "statut_final": resultat["resultat"]["transition"]["statut"],
        "prochaine_action": prochaine_action,
    }


# ---------------------------------------------------------------------------
# Consommateur d'événements (ADR-0009 §3, M2.7 Relances) : m3.devis_sans_reponse
# ---------------------------------------------------------------------------
# DEFINITION-PRODUIT §6, flux principal : « M3 estime et rédige la soumission → M2 suit la
# soumission (relances) ». §7 M2 : « M2.7 Relances : séquences, dormants, ancien client,
# saisonnier, avis, référence » ; règles dures « pas de spam, pas d'agressivité, opt-in respecté,
# fréquence limitée, validation humaine au départ ». M2 ne relance jamais elle-même : elle
# rattache le fait au lead (et au client, s'il existe) et en tire une relance PROPOSÉE
# (suggestions.suggerer_relance_devis_sans_reponse) — un humain décide, M1 enverra plus tard
# (frontière T3 du socle : aucun envoi au client par M2, jamais).


def _recevoir_devis_sans_reponse(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme m3.devis_sans_reponse (ADR-0009 §3, M2.7 — voir le commentaire ci-dessus).

    Rattache le fait au lead par UNE interaction système (auteur ``system:m3``) — jamais une
    transition de statut : la relance reste une PROPOSITION, jamais appliquée seule (§7 M2). Cette
    même interaction rattache aussi le fait au CLIENT (Client 360, ligne de temps) quand le lead en
    a un (``clients.client_de_lead``) : ``clients.vue_360``/``_interactions_du_lead`` parcourt déjà
    les interactions par ``lead_id``, aucun code supplémentaire n'est nécessaire ici. Un lead
    jamais lié à un client (antérieur à PLAN T2.2, ou ingéré hors de ``ingerer_lead``) reste traité
    normalement : ``client_id`` est simplement ``None`` dans le résultat. N'ÉCRASE JAMAIS
    l'historique : ``interactions.enregistrer`` n'ajoute qu'un maillon (registre append-only).

    Le délai, les deux horodatages et le statut viennent TELS QUELS de la charge (déjà produite et
    validée par M3, catalogue ``m3.devis_sans_reponse.json``) : rien n'est recalculé ni inventé ici
    — voir ``suggestions.suggerer_relance_devis_sans_reponse``, seule à décider du texte de la
    relance, à partir de ces mêmes champs.

    Idempotent à deux niveaux, même patron que ``_recevoir_travaux_termines``/``wct_recus`` :
    le répartiteur n'appelle cette fonction qu'une fois par (evenement_id, consommateur) traité
    avec succès (``EVENEMENTS_RECUS`` UNIQUE, ADR-0009 §3) ; et un même devis republié sous un
    autre ``evenement_id`` (rejeu du producteur — M3 utilise déjà un identifiant déterministe par
    ``devis_id``, mais ce consommateur reste défensif, comme M4/WCT) est reconnu par son
    ``devis_id`` (``_NOM_REGISTRE_RELANCES_DEVIS_RECUES``) : rien ne s'écrit une seconde fois,
    aucune quarantaine pour une redélivrance.

    Lead introuvable : ``LeadIntrouvable`` (même erreur nommée que ``m4.travaux_termines`` —
    incohérence de données, jamais un refus métier normal) ; le répartiteur réessaie puis met en
    quarantaine (ADR-0009 §3), visible par un humain (``opsys evenements etat``), sans qu'aucune
    écriture n'ait eu lieu.

    Lead perdu (``statuts.STATUTS_TERMINAUX``) : aucune relance n'est due ; le fait est gardé au
    registre des relances reçues avec ``ignore: "lead_clos"``, sans interaction ni quarantaine.
    """
    devis_id = charge["devis_id"]
    lead_id = charge["lead_id"]
    relances_recues = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RELANCES_DEVIS_RECUES)
    if any(recu.get("devis_id") == devis_id for recu in relances_recues):
        return {"traite": True, "lead_id": lead_id, "devis_id": devis_id, "deja_applique": True}

    reg = _obtenir_registre()
    statut_lead = statuts.statut_courant(reg, lead_id)
    if statut_lead is None:
        raise LeadIntrouvable(f"m3.devis_sans_reponse : lead {lead_id!r} introuvable au registre M2")

    client_id = clients.client_de_lead(reg, lead_id)
    fait_recu = {
        "devis_id": devis_id,
        "lead_id": lead_id,
        "statut_devis": charge["statut"],
        "horodatage_devis": charge["horodatage_devis"],
        "horodatage_reference": charge["horodatage_reference"],
        "delai_relance_jours": charge["delai_relance_jours"],
        "client_id": client_id,
    }
    if statut_lead in statuts.STATUTS_TERMINAUX:
        # Dossier clos (perdu) : aucune relance n'est due. Le fait est gardé comme trace, aucune
        # interaction n'est écrite (le dossier clos la refuserait) et rien ne part en quarantaine :
        # un devis resté ouvert chez M3 pour un lead perdu n'est pas une donnée incohérente.
        relances_recues.append({**fait_recu, "ignore": "lead_clos"})
        return {
            "traite": True,
            "lead_id": lead_id,
            "devis_id": devis_id,
            "client_id": client_id,
            "relance_proposee": None,
            "motif": f"lead {lead_id!r} au statut {statut_lead!r} : dossier clos, aucune relance",
        }

    suggestion = suggestions.suggerer_relance_devis_sans_reponse(charge)
    resume = f"Devis {devis_id} sans réponse : {suggestion['suggestion']} {suggestion['motif']}"
    _, verdict_interaction = interactions.enregistrer(
        lead_id, "system:m3", resume, reg, charge["horodatage_reference"]
    )
    if verdict_interaction is not None:
        # Ne devrait jamais arriver pour un lead trouvé, non clos (traité ci-dessus), avec un
        # horodatage et un résumé valides : défense en profondeur, jamais un cas silencieux, même
        # patron que marquer_chantier_termine.
        raise RuntimeError(
            "m3.devis_sans_reponse : interaction système refusée pour un lead trouvé "
            f"(lead {lead_id!r}, statut {statut_lead!r}) : {verdict_interaction}"
        )

    relances_recues.append(fait_recu)
    return {
        "traite": True,
        "lead_id": lead_id,
        "devis_id": devis_id,
        "client_id": client_id,
        "relance_proposee": suggestion,
    }


# ---------------------------------------------------------------------------
# Consommateur d'événements (ADR-0009 §3, PLAN T2.1-b) : m1.lead_qualifie
# ---------------------------------------------------------------------------
# Le lead qu'un canal du core a fait qualifier par M1 (`m1_recevoir_message_canal`) arrive ici par le bus, jamais par
# un appel direct de M1 (document des canaux, `docs/departements/`, §1). M2 fait ce qu'elle fait de tout lead :
# l'ingérer par la chaîne complète (`ingerer_lead` : contrat v2, frontières, unicité, doublons, Client 360,
# `m2.client_associe`).


class LeadRefuse(ValueError):
    """m1.lead_qualifie : M2 refuse le lead — contrat invalide (service retiré du profil depuis la qualification,
    par exemple), frontière de vérité violée, ou `lead_id` déjà ingéré avec un AUTRE contenu. Jamais une acceptation
    silencieuse : le répartiteur réessaie, puis met l'événement en quarantaine, visible par un humain
    (`opsys evenements etat`), sans qu'aucune écriture n'ait eu lieu."""


def _recevoir_lead_qualifie(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme m1.lead_qualifie (ADR-0009 §3, PLAN T2.1-b) : ingère le lead v2 avec l'heure de réception que M1 a
    reçue de la plateforme (`charge["horodatage"]`), jamais une horloge de M2.

    Idempotent à deux niveaux, même patron que ``_recevoir_travaux_termines`` : le répartiteur n'appelle cette
    fonction qu'une fois par (evenement_id, consommateur) traité avec succès (``EVENEMENTS_RECUS`` UNIQUE) ; et un
    lead déjà ingéré (même ``lead_id``, même contenu : même empreinte de contrat) est reconnu ici — rien ne s'écrit
    une seconde fois, ni lead, ni lien client, ni opportunité, ni événement ``m2.client_associe``, et aucune
    quarantaine pour une redélivrance. Un ``lead_id`` connu mais d'un AUTRE contenu est une incohérence :
    ``LeadRefuse``.

    Refus de l'ingestion (``accepte: false``) : ``LeadRefuse``, avec le code et le détail du verdict. M2 ne
    corrige rien et ne devine rien : le lead reste chez M1 (registre anti-perte), rien n'est perdu.
    """
    lead = charge["lead"]
    lead_id = lead["lead_id"]
    reg = _obtenir_registre()
    existant = next(
        (m for m in reg.lire() if m.get("type_entree") == ingestion.TYPE_ENTREE and m.get("lead_id") == lead_id), None
    )
    if existant is not None:
        if existant.get("empreinte_contrat") != encodage.empreinte(lead):
            raise LeadRefuse(
                f"m1.lead_qualifie : le lead {lead_id!r} est déjà ingéré avec un contenu différent : "
                "incohérence, aucune écriture (décision humaine requise)."
            )
        return {
            "accepte": True,
            "deja_applique": True,
            "lead_id": lead_id,
            "client_id": clients.client_de_lead(reg, lead_id),
        }
    resultat = ingerer_lead(lead, charge["horodatage"])
    if not resultat["accepte"]:
        verdict = resultat["verdict"]
        raise LeadRefuse(
            f"m1.lead_qualifie : M2 refuse le lead {lead_id!r} — {verdict['code']} : {verdict['detail']}"
        )
    return resultat


# ---------------------------------------------------------------------------
# Consommateur d'événements (ADR-0009 §3, PLAN T4.10-a) : m3.devis_accepte
# ---------------------------------------------------------------------------
# DEFINITION-PRODUIT §6, flux principal : « soumission acceptée → M4 planifie, route, exécute » ; §7 M2.8 :
# « Intelligence des soumissions [...] passage à M4 et M5 ». Jusqu'ici M2 ne savait pas qu'un devis avait été
# accepté : le lead restait `qualifie`. M2 le sait maintenant par le bus, sans que personne ne le lui écrive :
# `qualifie -> converti` (avec `reference_devis_m3`), la prochaine action « planifier le chantier » (règle
# citée, `suggestions.prochaine_action_planifier_chantier`) et une activité au Client 360. M2 ne promet ni date
# ni créneau : c'est M4 qui planifie (§7 M2, règles dures).


class AcceptationIncompatible(ValueError):
    """m3.devis_accepte : le lead existe mais l'acceptation ne peut pas s'y rattacher sans décision humaine :
    lead jamais qualifié (`nouveau` : aucun propriétaire ni prochaine action, aucune transition n'est fabriquée
    pour lui), ou déjà converti par UN AUTRE devis (le devis accepté ne remplace pas la référence déjà
    consignée). Jamais un refus métier normal : le répartiteur réessaie puis met en quarantaine (ADR-0009 §3),
    visible d'un humain (`opsys evenements etat`), sans qu'aucune écriture n'ait eu lieu."""


def _recevoir_devis_accepte(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme m3.devis_accepte (ADR-0009 §3, PLAN T4.10-a) : `qualifie -> converti`.

    - lead `qualifie` : transition `converti` avec `reference_devis_m3` = le devis, à l'heure de l'acceptation
      (`horodatage_acceptation`, jamais une horloge de M2), la prochaine action « planifier le chantier »
      (`suggestions.prochaine_action_planifier_chantier`, échéance = l'heure de l'acceptation : jamais une date
      inventée ni promise) portée par la transition (le Client 360 la lit), et une interaction système
      (auteur `system:m3`) qui rattache le fait au dossier ;
    - lead déjà `converti` (ou plus loin) PAR CE DEVIS : rien à faire, `deja_converti` (un humain ou un
      ancien flux l'avait converti avant l'acceptation) ;
    - lead `perdu` : aucune conversion n'est possible, le fait est gardé (`ignore: "lead_clos"`), sans
      interaction ni quarantaine (même patron que `m3.devis_sans_reponse`) ;
    - lead inconnu : `LeadIntrouvable` ; lead `nouveau`, ou déjà converti par un AUTRE devis :
      `AcceptationIncompatible`. Jamais une écriture partielle : le répartiteur livre chaque paire dans son
      propre point de sauvegarde, il réessaie puis met en quarantaine (ADR-0009 §3).

    Idempotent à deux niveaux, même patron que `_recevoir_devis_sans_reponse` : le répartiteur n'appelle cette
    fonction qu'une fois par (evenement_id, consommateur) traité avec succès ; et un même devis republié sous
    un autre `evenement_id` est reconnu par son `devis_id` (`_NOM_REGISTRE_DEVIS_ACCEPTES_RECUS`) : rien ne
    s'écrit une seconde fois. Aucun montant n'est lu ni gardé : M2 n'est pas la source de vérité financière
    (§7 M2).
    """
    devis_id = charge["devis_id"]
    lead_id = charge["lead_id"]
    horodatage = charge["horodatage_acceptation"]
    recus = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_ACCEPTES_RECUS)
    if any(recu.get("devis_id") == devis_id for recu in recus):
        return {"traite": True, "lead_id": lead_id, "devis_id": devis_id, "deja_applique": True}

    reg = _obtenir_registre()
    statut = statuts.statut_courant(reg, lead_id)
    if statut is None:
        raise LeadIntrouvable(f"m3.devis_accepte : lead {lead_id!r} introuvable au registre M2")
    client_id = clients.client_de_lead(reg, lead_id)
    fait_recu = {"devis_id": devis_id, "lead_id": lead_id, "horodatage_acceptation": horodatage, "client_id": client_id}

    if statut in statuts.STATUTS_TERMINAUX:
        recus.append({**fait_recu, "ignore": "lead_clos"})
        return {
            "traite": True, "lead_id": lead_id, "devis_id": devis_id, "client_id": client_id, "converti": False,
            "motif": f"lead {lead_id!r} au statut {statut!r} : dossier clos, aucune conversion",
        }
    if statut == "nouveau":
        raise AcceptationIncompatible(
            f"m3.devis_accepte : le devis {devis_id!r} est accepté mais le lead {lead_id!r} n'a jamais été "
            "qualifié (statut 'nouveau') : aucun propriétaire ni prochaine action, aucune transition n'est "
            "fabriquée. Décision humaine requise."
        )
    if statut != "qualifie":
        reference = statuts.reference_devis(reg, lead_id)
        if reference != devis_id:
            raise AcceptationIncompatible(
                f"m3.devis_accepte : le lead {lead_id!r} (statut {statut!r}) est déjà converti par le devis "
                f"{reference!r} ; le devis accepté {devis_id!r} ne peut pas lui être rattaché sans décision humaine."
            )
        recus.append({**fait_recu, "deja_converti": True})
        return {
            "traite": True, "lead_id": lead_id, "devis_id": devis_id, "client_id": client_id,
            "converti": False, "deja_converti": True, "statut": statut,
        }

    prochaine_action = suggestions.prochaine_action_planifier_chantier(devis_id, horodatage)
    _, verdict = statuts.transitionner(
        lead_id, "converti", reg, horodatage, reference_devis_m3=devis_id, prochaine_action=prochaine_action,
    )
    if verdict is not None:
        raise AcceptationIncompatible(
            f"m3.devis_accepte : la conversion du lead {lead_id!r} par le devis {devis_id!r} est refusée "
            f"({verdict['code']} : {verdict['detail']}), aucune écriture."
        )
    resume = (
        f"Soumission acceptée (devis {devis_id}) : le lead passe de qualifié à converti. "
        f"Prochaine action : {prochaine_action['description']} (échéance {prochaine_action['echeance']})."
    )
    _, verdict_interaction = interactions.enregistrer(lead_id, "system:m3", resume, reg, horodatage)
    if verdict_interaction is not None:
        # Jamais attendu : le lead vient d'être converti (non clos), l'horodatage est déjà validé, l'auteur
        # et le résumé ne sont pas vides. Défense en profondeur : lever annule aussi la transition.
        raise RuntimeError(
            "m3.devis_accepte : interaction système refusée juste après une conversion réussie "
            f"(incohérence interne, pas un refus métier normal) : {verdict_interaction}"
        )
    recus.append(fait_recu)
    return {
        "traite": True, "lead_id": lead_id, "devis_id": devis_id, "client_id": client_id, "converti": True,
        "statut": "converti", "prochaine_action": prochaine_action,
    }


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    """Types d'événements consommés par M2 (ADR-0009 §3) — voir `department.yaml/evenements`."""
    return {
        "m4.travaux_termines": _recevoir_travaux_termines,
        "m3.devis_sans_reponse": _recevoir_devis_sans_reponse,
        "m1.lead_qualifie": _recevoir_lead_qualifie,
        "m3.devis_accepte": _recevoir_devis_accepte,
    }


def evaluer_readiness(lead_id: str, horodatage: str) -> dict[str, Any]:
    """Émet le marqueur de readiness (aucune écriture au registre) : soit le lead
    satisfait déjà les quatre conditions et le marqueur est signé, soit un
    verdict détaille précisément ce qui manque. Appel d'appareil (PLAN T1.4-k2) : identité confirmée, et un
    vendeur ne l'évalue que pour SES leads."""
    acteur, verdict_acteur = _acteur_appareil(acces.ROLES_LEADS)
    if verdict_acteur is not None:
        return _refus(verdict_acteur)
    reg = _obtenir_registre()
    verdict_lead = acces.controler_lead(reg, lead_id, acteur)
    if verdict_lead is not None:
        return _refus(verdict_lead)
    marqueur, verdict = readiness.emettre_marqueur(reg, lead_id, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": marqueur}


def produire_digest(date_jour: str, horodatage: str) -> str:
    _exiger_admin()
    return digest.produire_digest(_obtenir_registre(), date_jour, horodatage)


# ---------------------------------------------------------------------------
# Schémas JSON partagés
# ---------------------------------------------------------------------------

_CONTACT = {
    "type": "object",
    "properties": {cle: {"type": "string"} for cle in contrats.CLES_CONTACT},
    "additionalProperties": False,
}
_UTM = {
    "type": "object",
    "description": "Optionnel (PLAN T2.2) : paramètres UTM tels que fournis, aucune énumération M7 revalidée ici.",
    "properties": {cle: {"type": "string"} for cle in contrats.CLES_UTM},
    "additionalProperties": False,
}
_CONTRAT = {
    "type": "object",
    "description": (
        "Lead transmis par le module amont, dans la version qu'il DÉCLARE. v1 (gelée, sans "
        "schema_version) : sept champs obligatoires dont type_travaux (énuméré fermé). v2 "
        "(schema_version = 2) : service (code déclaré par le profil d'entreprise de l'instance) "
        "remplace type_travaux. source/utm/campagne optionnels dans les deux versions (PLAN T2.2) — "
        "jamais de valeur par défaut si absents."
    ),
    "properties": {
        "schema_version": {"type": "integer", "enum": [contrats.VERSION_CONTRAT_V2], "description": "v2 seulement."},
        "lead_id": {"type": "string"},
        "conversation_id": {"type": "string"},
        "contact": _CONTACT,
        "type_travaux": {
            "type": "string", "enum": list(contrats.TYPES_TRAVAUX), "description": "v1 seulement.",
        },
        "service": {"type": "string", "description": "v2 seulement : code d'un service déclaré par l'entreprise."},
        "ville": {"type": "string"},
        "urgence_declaree": {"type": "boolean"},
        "canal": {"type": "string", "enum": list(contrats.CANAUX)},
        "source": {"type": "string", "description": "Optionnel : canal d'acquisition déclaré par M7."},
        "campagne": {"type": "string", "description": "Optionnel : campagne marketing déclarée par M7."},
        "utm": _UTM,
    },
    "required": [c for c in contrats.CHAMPS_CONTRAT_GELE if c != "type_travaux"],
    "additionalProperties": False,
}
_HORODATAGE = {"type": "string", "description": "ISO-8601 avec fuseau horaire, fourni par l'appelant"}
_PROCHAINE_ACTION = {
    "type": ["object", "null"],
    "description": "{description (non vide), echeance (ISO-8601 avec fuseau)} — jamais générée par ce module",
}
_PROCHAINE_ACTION_OBLIGATOIRE = {
    "type": "object",
    "description": (
        "{description (non vide), echeance (ISO-8601 avec fuseau)} — jamais générée par ce "
        "module, obligatoire pour cet outil (jamais de lead sans prochaine action)."
    ),
}


def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques du paquet sont des énumérés)."""
    return (
        Outil(
            nom="m2_ingerer_lead",
            description=(
                "Ingère un lead qualifié de bout en bout : validation structurelle et frontières de "
                "vérité, écriture au registre, détection ET signalement des doublons probables (jamais "
                "de fusion), statut courant, readiness pour M3."
            ),
            parametres={
                "type": "object",
                "properties": {"contrat": _CONTRAT, "horodatage": _HORODATAGE},
                "required": ["contrat", "horodatage"],
                "additionalProperties": False,
            },
            fonction=ingerer_lead,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m2_transitionner_statut",
            description=(
                "Transitionne le statut d'un lead (nouveau→qualifie, qualifie→converti, "
                "qualifie→perdu, nouveau→perdu). Chaque transition exige les données humaines "
                "correspondantes (owner+prochaine_action, ou reference_devis_m3, ou motif) ; jamais "
                "générées par cet outil. Pendant un appel d'appareil authentifié (PLAN T1.4-k2), un "
                "vendeur ne transitionne que SES leads (dont il est owner) ; à la qualification, owner "
                "est l'identifiant OPSYS d'une personne active (seller ou admin), qui rend le lead "
                "visible à son vendeur."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "statut_cible": {"type": "string", "enum": list(statuts.STATUTS)},
                    "horodatage": _HORODATAGE,
                    "owner": {
                        "type": ["string", "null"],
                        "description": (
                            "Propriétaire du lead, exigé à la qualification : l'identifiant OPSYS de la "
                            "personne (ex. vendeur.un), jamais son nom."
                        ),
                    },
                    "prochaine_action": _PROCHAINE_ACTION,
                    "reference_devis_m3": {"type": ["string", "null"]},
                    "motif": {"type": ["string", "null"]},
                },
                "required": ["lead_id", "statut_cible", "horodatage"],
                "additionalProperties": False,
            },
            fonction=transitionner_statut,
            autonomie=Autonomie.T1,
            # §9.4 (vendeur : pipeline personnel, perdu avec motif). Le vendeur agit seul en N3 (T1.4-h),
            # sur SES leads (T1.4-k2).
            roles_appareil=acces.ROLES_LEADS,
        ),
        Outil(
            nom="m2_detecter_doublons",
            description="Liste les lead_id déjà ingérés qui sont des doublons probables du lead donné (lecture pure).",
            parametres={
                "type": "object",
                "properties": {"lead_id": {"type": "string"}},
                "required": ["lead_id"],
                "additionalProperties": False,
            },
            fonction=detecter_doublons,
            # §9.5 M2 (admin : doublons).
            roles_appareil=acces.ROLES_ADMIN,
        ),
        Outil(
            nom="m2_signaler_doublon",
            description="Inscrit un signalement de doublon potentiel entre deux leads, en attente d'arbitrage humain.",
            parametres={
                "type": "object",
                "properties": {
                    "lead_id_a": {"type": "string"},
                    "lead_id_b": {"type": "string"},
                    "horodatage": _HORODATAGE,
                },
                "required": ["lead_id_a", "lead_id_b", "horodatage"],
                "additionalProperties": False,
            },
            fonction=signaler_doublon,
            autonomie=Autonomie.T1,
            # §9.5 M2 (admin : doublons).
            roles_appareil=acces.ROLES_ADMIN,
        ),
        Outil(
            nom="m2_arbitrer_doublon",
            description=(
                "Consigne l'arbitrage humain d'un signalement de doublon. Seule décision possible en "
                "v1 : 'distincts_confirmes' (les deux leads restent des dossiers séparés)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "signalement_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["distincts_confirmes"]},
                    "horodatage": _HORODATAGE,
                },
                "required": ["signalement_id", "decision", "horodatage"],
                "additionalProperties": False,
            },
            fonction=arbitrer_doublon,
            autonomie=Autonomie.T1,
            # §9.5 M2 (admin : doublons) ; arbitrage humain, jamais le vendeur.
            roles_appareil=acces.ROLES_ADMIN,
        ),
        Outil(
            nom="m2_enregistrer_interaction",
            description=(
                "Enregistre une interaction commerciale humaine réelle pour un lead actif (non clos). "
                "Pendant un appel d'appareil authentifié (PLAN T1.4-k2), auteur est la personne "
                "authentifiée : omis, il vaut cette personne ; différent, c'est un refus nommé, jamais "
                "un remplacement silencieux ; un vendeur n'écrit que sur SES leads. Sans appareil "
                "(agent), auteur est obligatoire."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "auteur": {
                        "type": ["string", "null"],
                        "description": (
                            "Obligatoire pour un agent ; pour un appareil, omis ou égal à la personne "
                            "authentifiée."
                        ),
                    },
                    "resume": {"type": "string"},
                    "horodatage": _HORODATAGE,
                },
                "required": ["lead_id", "resume", "horodatage"],
                "additionalProperties": False,
            },
            fonction=enregistrer_interaction,
            autonomie=Autonomie.T1,
            # §9.4 (vendeur : notes), sur SES leads ; `auteur` vient de la personne authentifiée (T1.4-k2).
            roles_appareil=acces.ROLES_LEADS,
        ),
        Outil(
            nom="m2_trouver_client_de_lead",
            description=(
                "PLAN T2.2 (Client 360) : retrouve le client_id auquel un lead (opportunité) est "
                "rattaché. Lecture pure."
            ),
            parametres={
                "type": "object",
                "properties": {"lead_id": {"type": "string"}},
                "required": ["lead_id"],
                "additionalProperties": False,
            },
            fonction=trouver_client_de_lead,
            # §9.4 (vendeur : Client 360).
            roles_appareil=acces.ROLES_LEADS,
        ),
        Outil(
            nom="m2_obtenir_client_360",
            description=(
                "PLAN T2.2 (M2.2) : vue 360 compacte d'un client — ses opportunités, statuts, "
                "prochaines actions connues et interactions récentes. Lecture pure, jamais d'écriture."
            ),
            parametres={
                "type": "object",
                "properties": {"client_id": {"type": "string"}},
                "required": ["client_id"],
                "additionalProperties": False,
            },
            fonction=obtenir_client_360,
            # §9.4 (vendeur : Client 360).
            roles_appareil=acces.ROLES_LEADS,
        ),
        Outil(
            nom="m2_lister_leads",
            description=(
                "PLAN T4.6 (M2.11) : liste les leads que l'appelant peut voir, filtrés par statut et par "
                "segment, une page à la fois (decalage, suivant). Un vendeur ne voit que SES leads, l'admin "
                "tous. Chaque lead porte ses segments, avec la règle citée et la donnée qui la déclenche ; "
                "un segment non calculable dit « non calculable, manque X » et un filtre sur lui est refusé "
                "(seuils à configurer dans department.yaml). Ordre : le plus ancien lead d'abord. Aucun "
                "montant. Lecture pure. Pour lire la suite, rappeler avec decalage = suivant."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "statut": {
                        "type": ["string", "null"],
                        "enum": [*statuts.STATUTS, None],
                        "description": "Facultatif : ne garder que les leads de ce statut.",
                    },
                    "segment": {
                        "type": ["string", "null"],
                        "enum": [*segments.SEGMENTS, None],
                        "description": "Facultatif : ne garder que les leads de ce segment (M2.11).",
                    },
                    "decalage": {
                        "type": "integer",
                        "minimum": 0,
                        "description": (
                            "Rang du premier lead rendu (0 par défaut) : la valeur `suivant` de la page précédente."
                        ),
                    },
                    "limite": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": liste_leads.LIMITE_MAX,
                        "description": (
                            f"Leads par page au plus (défaut {liste_leads.LIMITE_DEFAUT}) ; "
                            "la taille de la sortie les borne aussi."
                        ),
                    },
                    "horodatage": _HORODATAGE,
                },
                "required": ["horodatage"],
                "additionalProperties": False,
            },
            fonction=lister_leads,
            # §9.4 (vendeur : « ses leads », pipeline personnel) et §9.5 (admin : pipeline, leads chauds). Le
            # vendeur ne voit que les siens (`acces.leads_visibles`, T1.4-k2) ; l'employé n'a aucune portée.
            roles_appareil=acces.ROLES_LEADS,
        ),
        Outil(
            nom="m2_evaluer_readiness",
            description=(
                "Évalue si un lead qualifié est prêt pour M3 (owner, type de travaux valide, ville, "
                "interaction post-qualification). Émet un marqueur signé si oui, sinon un verdict "
                "détaillant précisément ce qui manque. Ne modifie jamais le registre."
            ),
            parametres={
                "type": "object",
                "properties": {"lead_id": {"type": "string"}, "horodatage": _HORODATAGE},
                "required": ["lead_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=evaluer_readiness,
            # §9.4 M3 (vendeur : « lead prêt pour l'estimation »).
            roles_appareil=acces.ROLES_LEADS,
        ),
        Outil(
            nom="m2_suggerer_prochaine_action",
            description=(
                "PLAN T2.2 (M2.6) : suggère la prochaine meilleure action pour un lead, par table de "
                "règles déterministe et citée — jamais un modèle, jamais appliquée automatiquement au "
                "registre. Lecture pure."
            ),
            parametres={
                "type": "object",
                "properties": {"lead_id": {"type": "string"}, "horodatage": _HORODATAGE},
                "required": ["lead_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=suggerer_prochaine_action,
            # §9.4 (vendeur : prochaine meilleure action).
            roles_appareil=acces.ROLES_LEADS,
        ),
        Outil(
            nom="m2_produire_digest",
            description="Produit le digest déterministe du pipeline commercial, reconstruit à la date_jour donnée.",
            parametres={
                "type": "object",
                "properties": {"date_jour": {"type": "string"}, "horodatage": _HORODATAGE},
                "required": ["date_jour", "horodatage"],
                "additionalProperties": False,
            },
            fonction=produire_digest,
            # §9.5 M2 (admin : pipeline, leads chauds) ; le vendeur n'a que le sien.
            roles_appareil=acces.ROLES_ADMIN,
        ),
        Outil(
            nom="m2_marquer_chantier_termine",
            description=(
                "Marque le chantier d'un lead converti comme terminé (statut chantier→facture) et "
                "écrit l'interaction système correspondante (auteur system:m4, résumé factuel "
                "construit depuis les champs reçus, jamais un texte libre). prochaine_action est "
                "obligatoire : jamais de lead sans prochaine action."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "horodatage": _HORODATAGE,
                    "prochaine_action": _PROCHAINE_ACTION_OBLIGATOIRE,
                },
                "required": ["lead_id", "horodatage", "prochaine_action"],
                "additionalProperties": False,
            },
            fonction=marquer_chantier_termine,
            autonomie=Autonomie.T1,
        ),
    )
