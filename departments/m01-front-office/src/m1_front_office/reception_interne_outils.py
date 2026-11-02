"""Outils de la réception qui regarde sa propre file (M1.11) : lire l'état, consigner les avis « À voir », calculer les
KPI.

Adaptateur de `reception_interne` (pur). Trois outils, tous INTERNES (aucun message n'est écrit au client, aucun canal
n'est
touché) et agent seulement (aucun droit d'appareil) :

- `m1_lire_attentes_reception` (N0) : l'état de la réception à un instant, des comptes et des références pseudonymes,
et ce
  qu'une consignation écrirait. C'est aussi la lecture de l'ombre d'un exécuteur planifié ;
- `m1_consigner_a_voir_reception` (N2) : écrit au registre `reception_interne` les avis qui n'y sont pas déjà (digest du
  jour, urgence toujours ouverte, rappel échu, conversation sans suivi). Chaque avis a une clé déterministe : rejouer
  n'écrit rien ;
- `m1_calculer_kpis` (N2) : les KPI du manifeste que le registre permet de calculer, consignés une fois par (jour,
  contenu).

Ce que le registre porte est déjà pseudonyme (identifiants de transfert et de conversation = empreintes) ; l'attente «
À voir »
(`attentes_reception`) n'a que des comptes et des références (Loi 25).
"""

from __future__ import annotations

from typing import Any

from opsys import service_acteur_systeme as systeme
from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage import lecture_m1
from opsys.stockage.concurrence import verrou_consultatif

from . import outils as _o
from . import reception_interne as rec
from .registre import Registre

DEPARTEMENT = "m01-front-office"
LISTE_MAX = 10  # références rendues par liste (le reste est compté, jamais tronqué en silence)
DELAI_MIN_S, DELAI_MAX_S = 15, 86400  # les bornes de l'intervalle du planificateur


def _avis_reg() -> Registre:
    return Registre(maillons=stockage.maillons(DEPARTEMENT, rec.REGISTRE))


def _lignes(borner: bool = True) -> list[dict[str, Any]]:
    """Les lignes du registre anti-perte, bornées quand il est durable (même garde que les autres lectures de M1). Les
    attentes « À voir » ne bornent pas : comme celles des transferts, elles ne doivent jamais faire taire toute la file
    de M1 (un département dont `attentes()` échoue est sauté en entier)."""
    cnx = stockage.connexion_courante()
    if borner and _o._stockage_durable_actif and cnx is not None:
        lecture_m1.borner(cnx)
    return _o._obtenir_registre().lire()


def _lignes_rdv() -> list[dict[str, Any]]:
    return list(stockage.maillons(DEPARTEMENT, "rendez_vous"))


def _verifier(maintenant: Any, jour: Any, delai: Any) -> dict[str, Any] | None:
    try:
        rec.instant(maintenant)
    except ValueError as exc:
        return _o._verdict_refus("REJ-HORODATAGE-INVALIDE", str(exc).partition(": ")[2])
    if jour is not None and not _o._date_calendaire_valide(jour):
        return _o._verdict_refus("REJ-DIGEST-DATE-INVALIDE", "jour doit être une date calendaire AAAA-MM-JJ")
    if delai is not None and (type(delai) is not int or not DELAI_MIN_S <= delai <= DELAI_MAX_S):
        return _o._verdict_refus(
            "REJ-RECEPTION-DELAI-INVALIDE", f"delai_controle_s : entier de {DELAI_MIN_S} à {DELAI_MAX_S} secondes"
        )
    return None


def _refus_hors_planificateur() -> dict[str, Any] | None:
    """L'écriture des avis et des KPI n'appartient qu'au planificateur durable : l'instant vient de SON horloge, jamais
    d'un argument d'agent. Un agent, une personne ou un appareil qui l'appellerait pourrait forger un instant et occuper
    la clé d'un avis (par exemple un digest futur) : refusé avant toute lecture du registre."""
    if systeme.planificateur_en_cours():
        return None
    return _o._verdict_refus(
        "REJ-RECEPTION-PLANIFICATEUR-REQUIS",
        "écriture réservée au planificateur durable (acteur système, tour en cours)",
    )


def _borner(liste: list[Any]) -> dict[str, Any]:
    return {"elements": liste[:LISTE_MAX], "omis": max(0, len(liste) - LISTE_MAX)}


def lire_attentes_reception(
    maintenant: str, jour: str | None = None, delai_controle_s: int | None = None
) -> dict[str, Any]:
    refus = _o._refus_lecture_admin() or _verifier(maintenant, jour, delai_controle_s)
    if refus is not None:
        return refus
    lignes, lignes_rdv = _lignes(), _lignes_rdv()
    avis = _avis_reg().lire()
    etat = rec.etat_reception(lignes, lignes_rdv, maintenant)
    a_consigner: dict[str, int | None] = {}
    lots: dict[str, str | None] = {}
    for groupe in rec.GROUPES:
        exige = (groupe == "digest" and jour is None) or (groupe == "urgences" and delai_controle_s is None)
        if exige:
            a_consigner[groupe] = lots[groupe] = None
            continue
        nouveaux = rec.avis_a_consigner(groupe, etat, avis, lignes=lignes, jour=jour, delai_controle_s=delai_controle_s)
        a_consigner[groupe] = len(nouveaux)
        # Empreinte de CE qui serait consigné (les clés, jamais les références) : l'ombre ne se répète pas pour le même
        # lot.
        lots[groupe] = rec._empreinte("|".join(sorted(a["cle"] for a in nouveaux)))[:12] if nouveaux else None  # noqa: SLF001
    digests = [a for a in avis if a.get("genre") == rec.GENRE_DIGEST]
    kpis = [a for a in avis if a.get("type_entree") == rec.TYPE_KPIS]
    return {
        "accepte": True,
        "resultat": {
            "maintenant": maintenant,
            "compteurs": rec.compteurs(etat),
            "a_rappeler": {k: v for k, v in etat["a_rappeler"].items() if k != "echus"}
            | {"echus": _borner(etat["a_rappeler"]["echus"])},
            "urgences_ouvertes": _borner(etat["urgences_ouvertes"]),
            "sans_suivi": _borner(etat["sans_suivi"]),
            "rendez_vous": etat["rendez_vous"],
            "historiques_illisibles": etat["historiques_illisibles"],
            # None = ce groupe exige un argument absent (le jour pour le digest, le délai pour les urgences) : jamais
            # un zéro.
            "a_consigner": a_consigner,
            "lots": lots,
            "dernier_digest": None
            if not digests
            else {k: digests[-1].get(k) for k in ("jour", "horodatage", "compteurs", "jours_couverts", "grille")},
            "derniers_kpis": None
            if not kpis
            else {k: kpis[-1].get(k) for k in ("jour", "horodatage", "fenetre", "kpis")},
        },
    }


def consigner_a_voir_reception(
    groupe: str, maintenant: str, jour: str | None = None, delai_controle_s: int | None = None
) -> dict[str, Any]:
    if groupe not in rec.GROUPES:
        return _o._verdict_refus("REJ-RECEPTION-GROUPE-INCONNU", f"groupe parmi {sorted(rec.GROUPES)}")
    refus = _o._refus_lecture_admin() or _verifier(maintenant, jour, delai_controle_s)
    if refus is not None:
        return refus
    refus = _refus_hors_planificateur()
    if refus is not None:
        return refus
    cnx = stockage.connexion_courante()
    if cnx is None or not cnx.in_transaction():
        return _o._verdict_refus("REJ-RECEPTION-STOCKAGE", "une transaction de l'instance est requise")
    verrou_consultatif(cnx, "m1-reception-interne")  # PostgreSQL : lire puis écrire sans doublon
    lignes, lignes_rdv = _lignes(), _lignes_rdv()
    registre = _avis_reg()
    try:
        nouveaux = rec.avis_a_consigner(
            groupe,
            rec.etat_reception(lignes, lignes_rdv, maintenant),
            registre.lire(),
            lignes=lignes,
            jour=jour,
            delai_controle_s=delai_controle_s,
        )
    except ValueError as exc:
        code, _, detail = str(exc).partition(": ")
        return _o._verdict_refus(code, detail)
    for avis in nouveaux:
        registre.ajouter(rec.ligne_avis(avis, maintenant))
    return {
        "accepte": True,
        "resultat": {"groupe": groupe, "ecrits": len(nouveaux), "genres": sorted({a["genre"] for a in nouveaux})},
    }


def calculer_kpis(
    jour: str, maintenant: str, jours: int = rec.FENETRE_KPI_DEFAUT, ecrire: bool = True
) -> dict[str, Any]:
    refus = _o._refus_lecture_admin() or _verifier(maintenant, jour, None)
    if refus is not None:
        return refus
    if type(jours) is not int or not 1 <= jours <= rec.FENETRE_KPI_MAX or type(ecrire) is not bool:
        return _o._verdict_refus("REJ-RECEPTION-FENETRE-INVALIDE", f"jours : entier de 1 à {rec.FENETRE_KPI_MAX}")
    calcul = rec.kpis(_lignes(), jour, jours)
    ecrit = False
    if ecrire:
        refus = _refus_hors_planificateur()
        if refus is not None:
            return refus
        cnx = stockage.connexion_courante()
        if cnx is None or not cnx.in_transaction():
            return _o._verdict_refus("REJ-RECEPTION-STOCKAGE", "une transaction de l'instance est requise")
        verrou_consultatif(cnx, "m1-reception-interne")
        registre = _avis_reg()
        cle = f"kpis|{jour}|{rec._empreinte(repr(sorted(calcul['kpis'].items(), key=str)))[:16]}"  # noqa: SLF001
        if not any(x.get("cle") == cle for x in registre.lire()):
            registre.ajouter(
                {"type_entree": rec.TYPE_KPIS, "horodatage": maintenant, "cle": cle, "jour": jour, **calcul}
            )
            ecrit = True
    return {"accepte": True, "resultat": {"jour": jour, "ecrit": ecrit, **calcul}}


def attentes_reception() -> list[dict[str, Any]]:
    """Les attentes « À voir » que les avis consignés font encore vivre (voir `reception_interne.attentes`). Lecture
    seule."""
    if stockage.connexion_courante() is None:
        return []
    avis = [a for a in _avis_reg().lire() if a.get("type_entree") == rec.TYPE_AVIS]
    return rec.attentes(avis, _lignes(borner=False)) if avis else []


_MAINTENANT = {
    "type": "string",
    "description": "Instant du contrôle, ISO-8601 avec fuseau (fourni par le planificateur).",
}
_JOUR = {"type": "string", "description": "Jour local de l'entreprise, AAAA-MM-JJ."}
_DELAI = {
    "type": "integer",
    "minimum": DELAI_MIN_S,
    "maximum": DELAI_MAX_S,
    "description": "Intervalle de contrôle réglé par l'administrateur, en secondes : une urgence encore ouverte après "
    "cet intervalle complet est signalée.",
}


def outils_reception_interne() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m1_lire_attentes_reception",
            description=(
                "Lit l'état de la réception à un instant (lecture seule) : conversations à rappeler (dont les rappels "
                "échus), rendez-vous à confirmer, plaintes ouvertes, urgences de sécurité toujours ouvertes, "
                "conversations restées sans suivi, rappels de rendez-vous dus, et combien d'avis « À voir » une "
                "consignation écrirait. Comptes et références pseudonymes seulement : aucun contact, aucun texte de "
                "client. N'écrit rien et ne contacte personne."
            ),
            parametres={
                "type": "object",
                "properties": {"maintenant": _MAINTENANT, "jour": _JOUR, "delai_controle_s": _DELAI},
                "required": ["maintenant"],
                "additionalProperties": False,
            },
            fonction=lire_attentes_reception,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom="m1_consigner_a_voir_reception",
            description=(
                "Consigne au registre interne les avis de réception qui deviennent des attentes « À voir » : `digest` "
                "(le résumé du jour), `urgences` (une urgence de sécurité toujours ouverte après un intervalle "
                "complet de "
                "contrôle), `echeances` (un rappel dont l'échéance est passée, une conversation dont la fenêtre est "
                "terminée sans suite). Idempotent : chaque avis a une clé déterministe, rejouer n'écrit rien de plus. "
                "N'envoie rien, ne contacte aucun client."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "groupe": {"type": "string", "enum": sorted(rec.GROUPES)},
                    "maintenant": _MAINTENANT,
                    "jour": _JOUR,
                    "delai_controle_s": _DELAI,
                },
                "required": ["groupe", "maintenant"],
                "additionalProperties": False,
            },
            fonction=consigner_a_voir_reception,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m1_calculer_kpis",
            description=(
                "Calcule les KPI de réception du manifeste (taux de signaux qualifiés ; taux d'interdits bloqués) "
                "sur les "
                "`jours` jours finissant à `jour`, avec numérateur et dénominateur. Un KPI que le registre ne permet "
                "pas de "
                "calculer est dit non calculable avec ce qui manque, jamais zéro. `ecrire` faux : lecture seule."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "jour": _JOUR,
                    "maintenant": _MAINTENANT,
                    "jours": {"type": "integer", "minimum": 1, "maximum": rec.FENETRE_KPI_MAX},
                    "ecrire": {"type": "boolean"},
                },
                "required": ["jour", "maintenant"],
                "additionalProperties": False,
            },
            fonction=calculer_kpis,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
    )
