"""Vérifier la météo des créneaux d'un plan de cédule proposé, et proposer le report (M4.10, M4.21, PLAN T4.13).

Module pur (stdlib et modules de M4 ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau ; un test le
vérifie par analyse du code) : les règles, la prévision et le lieu lui sont INJECTÉS (un profil lu, un fournisseur du
port ``FournisseurMeteo``, une lecture de position confirmée). Il ne fait QUE lire : rien n'est écrit au registre, rien
n'est assigné, aucun statut ne change (outil T0). Le report et la nouvelle cédule sont des PROPOSITIONS ; les appliquer
est un geste de l'admin (N3), jamais fait ici.

Ce qu'on juge : les visites d'un plan proposé (``cedule_tournees``, maillon ``cedule_proposee``). Une visite est un
CRÉNEAU : une intervention, un jour NUMÉROTÉ de la cédule et des minutes de début et de fin. Le plan ne connaît pas le
calendrier (M4 n'en tient pas encore) : l'appelant fournit ``calendrier`` (``{jour: AAAA-MM-JJ}``), et un jour sans date
donne « inconnu ».

Pour chaque créneau, dans l'ordre : le service de l'intervention (un lead v1 n'en a pas : inconnu) ; la date du jour ;
les règles du service (absentes : « seuil à configurer », inconnu) ; si les règles n'exigent aucune prévision (tout sans
objet) : ok ; la position CONFIRMÉE du chantier, généralisée au dixième de degré ; la prévision du fournisseur pour ce
lieu et cette date (panne : inconnu, jamais ok) ; le verdict de ``meteo.evaluer_creneau``. Une prévision n'est demandée
qu'une fois par lieu et par date.

Un créneau bloquant donne un REPORT PROPOSÉ (motif ``meteo``) et une NOUVELLE PROPOSITION DE CÉDULE pour les jours
restants : les arguments de ``m4_proposer_cedule`` (fenêtres sans le jour fermé pour le service touché) et un APERÇU du
plan que ``proposer`` en tirerait, calculé sur une COPIE du registre (rien n'est rangé). Les mêmes arguments passés à
``m4_proposer_cedule`` donnent le même ``plan_id`` que l'aperçu tant que le registre et les profils n'ont pas changé.
Sans jamais appliquer : ``m4_appliquer_cedule`` reste N3.

Un plan peut être PÉRIMÉ pour une intervention : un autre plan, appliqué depuis la proposition de celui-ci, l'a déjà
placée (``cedule_appliquee`` d'un autre ``plan_id``). Son créneau est alors jugé, mais marqué ``plan_perime`` : il ne
compte ni dans le statut d'ensemble, ni dans les reports, ni dans les jours que la cédule relancée ferme, car le report
d'un créneau que plus rien ne tient viserait une intervention qui est ailleurs.

Ne rend ni coordonnée, ni contact, ni prix, et ne promet aucune date au client (frontière T3).
"""

from __future__ import annotations

from functools import partial

from . import cedule_tournees, etats, meteo, registre, verdicts

STATUT_RELANCE_APERCU = "apercu"
STATUT_RELANCE_A_REJOUER = "surcharge_a_rejouer"
STATUT_RELANCE_RIEN = "rien_a_relancer"

# Statuts d'intervention pour lesquels `m4_signaler_report` (planifiee -> reportee, en_route -> reportee) existe.
STATUTS_REPORTABLES = ("planifiee", "en_route")

NIVEAU_DETAIL_MAX = 3

__all__ = [
    "NIVEAU_DETAIL_MAX",
    "STATUT_RELANCE_APERCU",
    "STATUT_RELANCE_A_REJOUER",
    "STATUT_RELANCE_RIEN",
    "STATUTS_REPORTABLES",
    "normaliser_calendrier",
    "normaliser_jours",
    "presenter",
    "verifier",
    "vue_compacte",
]


def _verdict(code, detail):
    return verdicts.construire_verdict(code, detail=detail)


def normaliser_calendrier(calendrier):
    """``({jour: date}, None)`` ou ``(None, verdict)`` : la table jour de la cédule -> date civile locale.

    Les clés sont des jours entiers (ou leur texte, un objet JSON n'a que des clés textuelles), les valeurs des dates
    ``AAAA-MM-JJ`` qui existent. Rien n'est deviné : ni date par défaut, ni jour suivant le précédent."""
    if not isinstance(calendrier, dict) or not calendrier:
        return None, _verdict(
            "REJ-CHAMP-MANQUANT",
            "calendrier : {jour: date AAAA-MM-JJ} attendu, au moins un jour (M4 ne tient pas de calendrier : le jour "
            "numéroté de la cédule se relie à une date civile ici, jamais par défaut)",
        )
    propre = {}
    for cle, date in calendrier.items():
        texte = str(cle)
        if isinstance(cle, bool) or not texte.isascii() or not texte.isdigit():
            return None, _verdict("REJ-CONTRAT-INVALIDE", f"calendrier : jour entier attendu (reçu {cle!r})")
        if not meteo.est_date(date):
            return None, _verdict(
                "REJ-CONTRAT-INVALIDE",
                f"calendrier[{texte}] : date civile AAAA-MM-JJ attendue (reçu {date!r})",
            )
        propre[int(texte)] = date
    return propre, None


def normaliser_jours(jours):
    """``(None, None)`` (tous les jours du plan), ``(ensemble de jours, None)`` ou ``(None, verdict)``.

    Un plan de plusieurs semaines ne tient pas dans une réponse d'appareil : ``jours`` restreint la vérification aux
    jours demandés (des entiers, au moins un). Rien n'est deviné : un jour mal formé est refusé."""
    if jours is None:
        return None, None
    if (
        not isinstance(jours, list)
        or not jours
        or any(isinstance(jour, bool) or not isinstance(jour, int) or jour < 0 for jour in jours)
    ):
        return None, _verdict(
            "REJ-CONTRAT-INVALIDE",
            "jours : une liste non vide de jours entiers (0, 1, ...) du plan est attendue, ou aucun argument pour tous "
            "les jours",
        )
    return set(jours), None


def _cause(code, detail):
    return {"code": code, "detail": detail}


def _plans_perimes(registre_cible, plan_id):
    """``{intervention_id: plan_id qui la tient}`` pour les interventions que le plan ``plan_id`` ne tient plus.

    Le dernier plan appliqué qui place une intervention est celui qui la tient ; s'il n'est pas ``plan_id`` et qu'il a
    été appliqué APRÈS la proposition de ``plan_id``, ce plan est périmé pour elle. Un autre plan appliqué AVANT cette
    proposition n'a rien changé : ``plan_id`` propose alors un nouveau placement."""
    rang_proposition = None
    dernier = {}
    for rang, maillon in enumerate(registre_cible.lire()):
        if maillon["type_entree"] == cedule_tournees.TYPE_PROPOSEE and maillon["plan_id"] == plan_id:
            rang_proposition = rang
        elif maillon["type_entree"] == cedule_tournees.TYPE_APPLIQUEE:
            for assignation in maillon["assignations"]:
                dernier[assignation["intervention_id"]] = (rang, maillon["plan_id"])
    return {
        identifiant: tenant
        for identifiant, (rang, tenant) in dernier.items()
        if tenant != plan_id and rang_proposition is not None and rang > rang_proposition
    }


def _regles_du_service(profil, service):
    """Les règles du service, ou ``None`` (aucun profil, aucun service, service non déclaré)."""
    if not isinstance(profil, dict) or service is None:
        return None
    return profil.get("services", {}).get(service)


class _Previsions:
    """Une prévision par (lieu, date) : la même demande n'est faite qu'une fois par vérification."""

    def __init__(self, fournisseur):
        self._fournisseur = fournisseur
        self._reponses = {}

    def de(self, lieu, date):
        cle = (lieu["latitude_microdegres"], lieu["longitude_microdegres"], date)
        if cle not in self._reponses:
            previsions, verdict = self._fournisseur.previsions(dict(lieu), date, date)
            if verdict is None:
                probleme = meteo.valider_previsions(previsions)
                if probleme is not None:
                    previsions, verdict = None, _verdict(meteo.CODE_REPONSE_INVALIDE, probleme)
            self._reponses[cle] = (previsions, verdict)
        return self._reponses[cle]


def _creneau(base, date, regles, verdict_profil, previsions, verdict_fournisseur, position_du_lead):
    """Le créneau jugé : ``base`` (qui, quand, quel service) et le résultat de la météo."""
    debut, fin = base["debut_min"], base["fin_min"]

    def inconnu(cause):
        return {**base, "date": date, **meteo.resultat_inconnu(regles, date, debut, fin, cause)}

    if base["service"] is None:
        return inconnu(
            _cause(
                "REJ-CHAMP-MANQUANT",
                "intervention issue d'un lead v1 (type_travaux) : les règles météo sont par service, aucune ne "
                "s'applique à un type de travaux",
            )
        )
    if date is None:
        return inconnu(
            _cause(
                "REJ-CHAMP-MANQUANT",
                f"le jour {base['jour']} de la cédule n'a pas de date dans le calendrier : la fournir, jamais la "
                "deviner",
            )
        )
    if verdict_profil is not None:
        return inconnu(_cause(verdict_profil["code"], verdict_profil["detail"]))
    if regles is None:
        return inconnu(
            _cause(
                "REJ-CHAMP-MANQUANT",
                f"seuil à configurer : aucune règle météo pour le service {base['service']!r} "
                "(`opsys-metier meteo declarer`)",
            )
        )
    if not meteo.regles_exigent_une_prevision(regles):
        # Tous les risques sont déclarés sans objet : aucune prévision ne peut changer le verdict.
        return {**base, "date": date, **meteo.evaluer_creneau(regles, None, date, debut, fin)}
    if previsions is None:
        return inconnu(verdict_fournisseur)
    position, verdict = position_du_lead()
    if verdict is not None:
        return inconnu(_cause(verdict["code"], verdict["detail"]))
    lieu = meteo.lieu_generalise(position["latitude_microdegres"], position["longitude_microdegres"])
    prevision, verdict = previsions.de(lieu, date)
    if verdict is not None:
        return inconnu(_cause(verdict["code"], verdict["detail"]))
    return {**base, "date": date, **meteo.evaluer_creneau(regles, prevision, date, debut, fin)}


def _report_propose(creneau):
    """Le report proposé d'un créneau bloquant : un motif, un jour, et le geste qui l'appliquerait (jamais fait ici)."""
    statut = creneau["statut_intervention"]
    geste = None
    if statut in STATUTS_REPORTABLES:
        geste = {
            "outil": "m4_signaler_report",
            "niveau": "N3",
            "arguments": {"intervention_id": creneau["intervention_id"], "motif": meteo.MOTIF_REPORT},
            "a_completer": "horodatage",
        }
        explication = (
            f"l'intervention est {statut} : m4_signaler_report (motif meteo) la fait passer à reportee ; un client "
            "déjà informé du créneau se prévient par M1, jamais d'ici"
        )
    else:
        explication = (
            f"l'intervention est {statut} : aucun changement d'état à faire, le jour fermé est retiré de sa fenêtre "
            "dans la nouvelle proposition de cédule"
        )
    return {
        "intervention_id": creneau["intervention_id"],
        "motif": meteo.MOTIF_REPORT,
        "jour": creneau["jour"],
        "date": creneau["date"],
        "statut_intervention": statut,
        "geste": geste,
        "explication": explication,
        "regles_franchies": [
            regle["detail"] for regle in creneau["regles"] if regle["statut"] == meteo.STATUT_BLOQUANT
        ],
    }


def _apercu(resultat):
    """L'aperçu d'un plan proposé : ses visites et ce qu'il laisse de côté, jamais une coordonnée."""
    return {
        "plan_id": resultat["plan_id"],
        "deja_proposee": resultat["deja_proposee"],
        "mode_bride": resultat["mode_bride"],
        "avertissement": resultat["avertissement"],
        "plan": resultat["plan"],
        "non_cedulees": resultat["non_cedulees"],
        "totaux": resultat["totaux"],
    }


def _relance(registre_cible, plan, bloques, service_de, lire_position, lire_equipes, lire_meteo, fournisseur_matrice):
    """La nouvelle proposition de cédule pour les jours restants : arguments et aperçu, jamais rangée ni appliquée."""
    preparation = meteo.preparer_relance(plan["entree"]["chantiers"], bloques, service_de)
    base = {"jours_retires": preparation["jours_retires"], "exclues": preparation["exclues"]}
    if not preparation["chantiers"]:
        return {
            **base,
            "statut": STATUT_RELANCE_RIEN,
            "arguments": None,
            "apercu": None,
            "explication": "aucun chantier du plan ne peut être replacé automatiquement : voir « exclues »",
        }
    arguments = {
        "intervention_ids": preparation["intervention_ids"],
        "chantiers": preparation["chantiers"],
        "moteur": plan["moteur"],
    }
    surcharges = sorted(
        cle
        for cle, source in plan["provenance"].items()
        if cle != "chantiers" and source == cedule_tournees.SOURCE_SURCHARGE
    )
    if surcharges:
        return {
            **base,
            "statut": STATUT_RELANCE_A_REJOUER,
            "arguments": arguments,
            "apercu": None,
            "explication": (
                "le plan a été proposé avec des valeurs en surcharge (" + ", ".join(surcharges) + ") : relancer "
                "m4_proposer_cedule avec ces arguments ET les mêmes surcharges ; aucun aperçu n'est calculé"
            ),
        }
    # Une COPIE du registre : `proposer` y range son maillon, le vrai registre n'est jamais touché.
    copie = registre.Registre(registre_cible.lire())
    resultat, verdict = cedule_tournees.proposer(
        copie,
        {"intervention_ids": arguments["intervention_ids"], "chantiers": arguments["chantiers"]},
        lire_position,
        plan["horodatage"],
        propose_par=None,
        fournisseur=fournisseur_matrice,
        moteur=plan["moteur"],
        lire_equipes=lire_equipes,
        lire_meteo=lire_meteo,
    )
    if verdict is not None:
        return {
            **base,
            "statut": STATUT_RELANCE_A_REJOUER,
            "arguments": arguments,
            "apercu": None,
            "verdict": verdict,
            "explication": "la nouvelle proposition n'a pas pu être calculée : voir « verdict »",
        }
    return {
        **base,
        "statut": STATUT_RELANCE_APERCU,
        "arguments": arguments,
        "apercu": _apercu(resultat),
        "explication": (
            "aperçu du plan pour les jours restants ; m4_proposer_cedule avec ces arguments (et un horodatage) le "
            "range sous le même plan_id, puis m4_appliquer_cedule (N3) l'applique : rien n'est appliqué ici"
        ),
    }


def _attributions(creneaux):
    """Les mentions de licence à afficher, une par source, dans l'ordre d'apparition."""
    vues = {}
    for creneau in creneaux:
        citation = (creneau.get("prevision") or {}).get("citation")
        if citation and citation.get("attribution"):
            vues.setdefault(citation["source"], citation["attribution"])
    return [{"source": source, "attribution": texte} for source, texte in vues.items()]


def verifier(
    registre_cible,
    plan_id,
    calendrier,
    lire_position,
    profil,
    verdict_profil,
    fournisseur,
    verdict_fournisseur,
    lire_equipes=None,
    lire_meteo=None,
    fournisseur_matrice=None,
    jours=None,
):
    """``(résultat, None)`` ou ``(None, verdict)`` : la météo de chaque créneau d'un plan proposé, et le report proposé.

    ``plan_id`` : un plan de ``m4_proposer_cedule`` (appliqué ou non) ; ``calendrier`` : ``{jour: date}`` ;
    ``lire_position(registre, chantier_id)`` : ``(position, None)`` ou ``(None, verdict)`` (la position CONFIRMÉE, la
    même lecture que la cédule) ; ``profil, verdict_profil`` : le profil météo lu (``opsys.meteo.charger_meteo``) ;
    ``fournisseur`` : un objet du port ``FournisseurMeteo`` ou ``None`` ; ``verdict_fournisseur`` : pourquoi il n'y en a
    pas (``None`` : aucun n'est ouvert). ``lire_equipes``, ``lire_meteo``, ``fournisseur_matrice`` : ceux de la cédule,
    pour l'aperçu de la nouvelle proposition. ``jours`` : ``None`` (tous les jours du plan) ou une liste de jours :
    seuls les créneaux de ces jours sont jugés (et peuvent fermer un jour dans la cédule relancée, qui garde tous les
    chantiers du plan).

    Refus (rien n'est écrit, la fonction n'écrit jamais) : calendrier absent ou mal formé, plan inconnu
    (``REJ-CEDULE-PLAN-INTROUVABLE``). Tout le reste est un RÉSULTAT, y compris une panne de fournisseur (créneau
    « inconnu », avec sa cause) : le statut d'ensemble est le pire des créneaux, « inconnu » s'il n'y en a aucun."""
    dates, verdict = normaliser_calendrier(calendrier)
    if verdict is not None:
        return None, verdict
    jours_juges, verdict = normaliser_jours(jours)
    if verdict is not None:
        return None, verdict
    instantane = cedule_tournees.instantane_du_registre(registre_cible)
    plan = cedule_tournees.plan_propose(instantane, plan_id)
    if plan is None:
        return None, _verdict("REJ-CEDULE-PLAN-INTROUVABLE", f"aucun plan proposé sous l'identifiant {plan_id!r}")
    inscriptions = cedule_tournees.inscriptions_du_registre(instantane)
    perimes = _plans_perimes(instantane, plan_id)
    if fournisseur is None:
        verdict_fournisseur = verdict_fournisseur or _verdict(
            meteo.CODE_FOURNISSEUR_FERME,
            "aucun fournisseur météo n'est ouvert : saisir la prévision (previsions_saisies) ou déclarer un "
            "fournisseur dans le profil météo (`opsys-metier meteo declarer`, clé fournisseur)",
        )
        previsions = None
    else:
        previsions = _Previsions(fournisseur)
    service_de = {}
    creneaux = []
    for route in plan["sortie"]["plan"]:
        if jours_juges is not None and route["jour"] not in jours_juges:
            continue
        for visite in route["visites"]:
            identifiant = visite["chantier"]
            inscription = inscriptions[identifiant]
            cle_travaux, nature = etats.travaux_de(inscription)
            service = nature if cle_travaux == etats.CLE_SERVICE else None
            service_de[identifiant] = service
            base = {
                "intervention_id": identifiant,
                "equipe": route["equipe"],
                "jour": route["jour"],
                "debut_min": visite["debut_min"],
                "fin_min": visite["fin_min"],
                "service": service,
                "statut_intervention": etats.statut_courant(instantane, identifiant),
                "plan_perime": identifiant in perimes,
            }
            creneaux.append(
                _creneau(
                    base,
                    dates.get(route["jour"]),
                    _regles_du_service(profil, service),
                    verdict_profil,
                    previsions,
                    verdict_fournisseur,
                    partial(lire_position, instantane, inscription["lead_id"]),
                )
            )
    if jours_juges is not None and not creneaux:
        jours_du_plan = sorted({route["jour"] for route in plan["sortie"]["plan"]})
        return None, _verdict(
            "REJ-CONTRAT-INVALIDE",
            f"jours : aucun créneau du plan {plan_id!r} ne tombe les jours demandés (jours du plan : {jours_du_plan})",
        )
    creneaux.sort(key=lambda c: (c["jour"], c["equipe"], c["debut_min"], c["intervention_id"]))
    vivants = [c for c in creneaux if not c["plan_perime"]]
    bloques = [
        {"intervention_id": c["intervention_id"], "jour": c["jour"]}
        for c in vivants
        if c["statut"] == meteo.STATUT_BLOQUANT
    ]
    resultat = {
        "plan_id": plan_id,
        "statut": meteo.pire(c["statut"] for c in vivants),
        "creneaux": creneaux,
        "a_valider": [
            {
                "intervention_id": c["intervention_id"],
                "jour": c["jour"],
                "date": c["date"],
                "regles": [r["detail"] for r in c["regles"] if r["statut"] == meteo.STATUT_VALIDATION],
            }
            for c in vivants
            if c["statut"] == meteo.STATUT_VALIDATION
        ],
        "reports_proposes": [_report_propose(c) for c in vivants if c["statut"] == meteo.STATUT_BLOQUANT],
        "cedule_relancee": None,
        "attributions": _attributions(creneaux),
    }
    if any(c["plan_perime"] for c in creneaux):
        resultat["perimes"] = [
            {"intervention_id": c["intervention_id"], "tenu_par": perimes[c["intervention_id"]]}
            for c in creneaux
            if c["plan_perime"]
        ]
        resultat["avertissement"] = (
            "ce plan est périmé pour les interventions listées (perimes) : un autre plan appliqué les a déjà "
            "placées ; leurs créneaux sont jugés mais ne comptent ni dans le statut, ni dans les reports, ni dans la "
            "cédule relancée ; "
            "vérifier le plan qui les tient (tenu_par)"
        )
    if bloques:
        resultat["cedule_relancee"] = _relance(
            registre_cible,
            plan,
            bloques,
            service_de,
            lire_position,
            lire_equipes,
            lire_meteo,
            fournisseur_matrice,
        )
    return resultat, None


# ---------------------------------------------------------------------------
# Présentation : la réponse d'un appareil est bornée (6 000 caractères), un résultat tronqué cacherait des créneaux
# ---------------------------------------------------------------------------
_CLES_CRENEAU = (
    "intervention_id",
    "equipe",
    "jour",
    "date",
    "debut_min",
    "fin_min",
    "service",
    "statut_intervention",
    "statut",
    "plan_perime",
)
_DETAIL_REDUIT = (
    None,
    "les créneaux ok ne portent plus le détail de leurs règles (la prévision reste citée) ; le détail d'un jour se lit "
    "avec l'argument jours",
    "les créneaux ok sont résumés par jour (ok_resume), les autres ne détaillent que les règles qui les rendent à "
    "regarder, et un report proposé ne répète plus son explication ; le détail d'un jour se lit avec l'argument jours",
    "les créneaux ok sont résumés par jour (ok_resume), les autres ne détaillent que les règles qui les rendent à "
    "regarder, un report proposé ne répète plus son explication et l'aperçu du plan relancé est réduit à ses totaux : "
    "m4_proposer_cedule avec les arguments de la relance donne le plan complet ; le détail d'un jour se lit avec "
    "l'argument jours",
)
_CLES_REPORT_ALLEGE = ("explication", "regles_franchies")


def _regle_compacte(regle):
    return {"risque": regle["risque"], "statut": regle["statut"], "detail": regle["detail"]}


def _prevision_compacte(prevision):
    """La citation de la prévision (source, heure d'émission, auteur d'une saisie), sans les points horaires ni la
    mention de licence (une fois, dans ``attributions``) : les valeurs jugées sont dans le détail de chaque règle."""
    if prevision is None:
        return None
    return {cle: valeur for cle, valeur in prevision["citation"].items() if cle != "attribution" and valeur is not None}


def _creneau_compact(creneau, niveau):
    """Un créneau sous la forme du ``niveau`` : dès 1, un créneau ok n'a plus de règles ; dès 2, un créneau à regarder
    ne garde que les règles qui ne sont pas ok (celles qui le rendent à regarder)."""
    sortie = {cle: creneau[cle] for cle in _CLES_CRENEAU}
    ok = creneau["statut"] == meteo.STATUT_OK
    if not (niveau >= 1 and ok):
        regles = creneau["regles"]
        if niveau >= 2:
            regles = [regle for regle in regles if regle["statut"] != meteo.STATUT_OK]
        sortie["regles"] = [_regle_compacte(regle) for regle in regles]
    if creneau.get("cause"):
        sortie["cause"] = creneau["cause"]
    if creneau["sans_objet"]:
        sortie["sans_objet"] = creneau["sans_objet"]
    if creneau["a_configurer"]:
        sortie["a_configurer"] = creneau["a_configurer"]
    sortie["prevision"] = _prevision_compacte(creneau["prevision"])
    return sortie


def vue_compacte(resultat, niveau):
    """Le résultat de ``verifier`` sous une forme plus courte, ``niveau`` de 0 à ``NIVEAU_DETAIL_MAX`` : jamais moins
    d'information sur ce qui demande un geste, jamais un créneau non ok caché.

    0 : les règles réduites à risque, statut et détail (qui cite la valeur, l'heure et le seuil), la prévision réduite à
    sa citation ; 1 : les créneaux ok sans le détail de leurs règles ; 2 : les créneaux ok résumés par jour
    (``ok_resume``), les autres réduits aux règles qui ne sont pas ok, les reports proposés sans leur explication ;
    3 : de plus, l'aperçu de la cédule relancée réduit à ses totaux. Dès le niveau 1, ``detail_reduit`` le dit."""
    creneaux = resultat["creneaux"]
    vue = {cle: valeur for cle, valeur in resultat.items() if cle != "creneaux"}
    if niveau >= 2:
        vue["creneaux"] = [_creneau_compact(c, niveau) for c in creneaux if c["statut"] != meteo.STATUT_OK]
        par_jour = {}
        for creneau in creneaux:
            if creneau["statut"] == meteo.STATUT_OK:
                cle = (creneau["jour"], creneau["date"])
                par_jour[cle] = par_jour.get(cle, 0) + 1
        vue["ok_resume"] = [
            {"jour": jour, "date": date, "nombre": nombre}
            for (jour, date), nombre in sorted(par_jour.items(), key=lambda e: e[0][0])
        ]
        vue["reports_proposes"] = [
            {cle: valeur for cle, valeur in report.items() if cle not in _CLES_REPORT_ALLEGE}
            for report in resultat["reports_proposes"]
        ]
    else:
        vue["creneaux"] = [_creneau_compact(c, niveau) for c in creneaux]
    relance = resultat["cedule_relancee"]
    if niveau >= 3 and relance is not None and relance.get("apercu") is not None:
        apercu = {cle: valeur for cle, valeur in relance["apercu"].items() if cle != "plan"}
        vue["cedule_relancee"] = {**relance, "apercu": apercu}
    if _DETAIL_REDUIT[niveau] is not None:
        vue["detail_reduit"] = _DETAIL_REDUIT[niveau]
    return vue


def presenter(resultat, tient):
    """``(vue, None)`` ou ``(None, verdict)`` : la vue la plus détaillée du résultat dont ``tient(vue)`` est vrai.

    ``tient`` : un prédicat sur la vue (l'appelant mesure la place que la réponse prend). Si même la vue la plus courte
    ne tient pas, le verdict le dit et nomme l'argument ``jours`` : une réponse tronquée cacherait des créneaux."""
    for niveau in range(NIVEAU_DETAIL_MAX + 1):
        vue = vue_compacte(resultat, niveau)
        if tient(vue):
            return vue, None
    return None, _verdict(
        "REJ-CONTRAT-INVALIDE",
        "le plan est trop grand pour une réponse d'appareil, même résumé : vérifier quelques jours à la fois avec "
        "l'argument jours (par exemple jours=[0])",
    )
