"""Monde de la preuve « routines planifiées » (tests seulement) : les VRAIS départements M1 et M10 sur une base SQLite
migrée,
le VRAI planificateur durable avec une horloge INJECTÉE (jamais de sleep) et des données FICTIVES (`@example.test`,
numéros en
555). Les données sont semées par les vrais outils et registres de chaque département ; les routines les lisent.

Seuls le réseau et les services externes sont absents : aucune routine n'en appelle un (le port courriel, entre autres,
reste
`None`, et un test le vérifie).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import planif_qa as pq
import yaml

from opsys import identite, stockage, taxonomie
from opsys.connecteurs_planification import etat, planificateur

RACINE = Path(__file__).resolve().parents[2]
FICTIF = True
M1, M10 = "m01-front-office", "m10-memoire"
EST = dt.timezone(
    dt.timedelta(hours=-5)
)  # heure normale de l'Est (le changement d'heure a eu lieu le 1er novembre 2026)
FENETRE_MIN = 120
ROUTINES_M1 = (
    "m1.routine.digest-reception",
    "m1.routine.rappels-et-suivis",
    "m1.routine.urgences",
    "m1.routine.kpis-reception",
)
ROUTINES_M10 = ("m10.routine.consolidation-affaires", "m10.routine.audit-non-oubli", "m10.routine.kpis-memoire")
TOUTES = ROUTINES_M1 + ROUTINES_M10
# Ce qui ne doit JAMAIS apparaître dans un journal, une attente ou un avis : un numéro, un texte de client.
PERSONNEL = ("+1514", "5145550", "@example.test", "gouttières fuient", "fil électrique", "Danger", "déçu")


def local(jour: str, heure: str) -> dt.datetime:
    """Un instant de l'heure locale de l'entreprise (EST), ex. `local("2026-11-09", "15:00")`."""
    return dt.datetime.fromisoformat(f"{jour}T{heure}:00").replace(tzinfo=EST)


def monter(
    tmp_path: Any, monkeypatch: Any, declarer_services: Any, departements: tuple[str, ...] = (M1, M10)
) -> pq.Planif:
    """Une instance fictive : base migrée, profil d'entreprise (services, zone, fenêtre de conversation, vocabulaire de
    plaintes du fichier FICTIF de M1), registres durables, un admin de console."""
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "instance-fictive"))
    plan = pq.monter(tmp_path, monkeypatch, departements)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    taxonomie.enregistrer_fenetre_conversation(FENETRE_MIN)
    corpus = yaml.safe_load(
        (RACINE / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml").read_text(encoding="utf-8")
    )
    assert corpus["fictif"] is True
    taxonomie.enregistrer_signaux_plainte(corpus["signaux_plainte"])
    from m1_front_office import outils as m1

    m1.utiliser_stockage_durable()
    _horloge_du_bus(plan, monkeypatch)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    return plan


def _horloge_du_bus(plan: pq.Planif, monkeypatch: Any) -> None:
    """La date de publication d'un événement (`cree_le`) est celle de l'horloge INJECTÉE du plan, jamais celle de la
    machine :
    la fenêtre de l'audit hebdomadaire se prouve donc sans dépendre du jour où le test tourne."""
    import types

    from opsys.evenements import bus

    class _Horloge(dt.datetime):
        @classmethod
        def now(cls, tz: Any = None) -> dt.datetime:
            return dt.datetime.fromtimestamp(plan.horloge(), tz or dt.UTC)

    monkeypatch.setattr(bus, "dt", types.SimpleNamespace(datetime=_Horloge, UTC=dt.UTC, timedelta=dt.timedelta))


def demonter() -> None:
    from m1_front_office import outils as m1

    m1.reinitialiser_registre()
    m1.utiliser_stockage_durable()
    pq.demonter()


def activer(
    plan: pq.Planif, noms: tuple[str, ...] = TOUTES, mode: str = "actif", intervalle_s: int | None = None
) -> None:
    """Le geste d'admin de la console, pour chacune des routines (intervalle par défaut : celui de la déclaration)."""
    for nom in noms:
        with stockage.transaction() as cnx:
            etat.appliquer(
                cnx,
                pq.session_admin(),
                nom,
                mode,
                motif="preuve fictive",
                maintenant=plan.horloge(),
                intervalle_s=intervalle_s,
            )


def aller_a(plan: pq.Planif, instant: dt.datetime) -> None:
    plan.horloge.t = instant.timestamp()


def tour(plan: pq.Planif, instant: dt.datetime | None = None, **options: Any) -> dict[str, Any]:
    """Un tour du planificateur à l'instant donné (l'horloge est posée, jamais attendue) ; rend le résumé des
    routines."""
    if instant is not None:
        aller_a(plan, instant)
    resume = planificateur.tour(plan.departements, ports=plan.ports, **options)
    return {n: v for n, v in resume["executeurs"].items() if ".routine." in n}


# -- M1 : une journée de réception
# ---------------------------------------------------------------------------------------
def sms(expediteur: str, message_id: str, quand: dt.datetime, texte: str) -> dict[str, Any]:
    from m1_front_office.outils import recevoir_message_canal

    with stockage.transaction():
        return recevoir_message_canal(
            canal="sms", expediteur=expediteur, message_id=message_id, recu_le=quand.isoformat(), texte=texte
        )


def appel_manque(numero: str, n: int, quand: dt.datetime) -> str:
    """Un appel manqué importé : rend l'identifiant du transfert (la tâche de rappel)."""
    from m1_front_office import outils as m1

    with stockage.transaction():
        reponse = m1.importer_appel_manuellement(
            source="Journal FICTIF",
            evenement_id=f"evt-fictif-{n}",
            appel_id=f"appel-fictif-{n}",
            recu_le=quand.isoformat(),
            telephone=numero,
            statut="manque",
        )
    assert reponse["accepte"] and reponse["tache_rappel"] is not None
    return reponse["tache_rappel"]["transfert_id"]


def lignes_m1() -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons("m01-front-office", "principal"))


def avis_m1() -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons("m01-front-office", "reception_interne"))


def attentes_m1() -> list[dict[str, Any]]:
    from m1_front_office import outils as m1

    with stockage.transaction():
        return m1.attentes()


class FauxM4:
    """Le port privé de lecture de M4 (contrat `m4.capacite_equipe` v1) : une capacité confortable pour chaque
    semaine."""

    def __call__(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert outil == "m4_lire_capacite_equipe", outil
        semaine = arguments["debut_semaine"]
        return {
            "ok": True,
            "resultat": {
                "accepte": True,
                "resultat": {
                    "contrat": "m4.capacite_equipe",
                    "version": 1,
                    "semaine_debut": semaine,
                    "unite": "heures_declarees",
                    "portee": "semaine_type",
                    "calculable": True,
                    "manque": [],
                    "sources": {"profil_empreinte": "e" * 64, "registre_tete": "l1"},
                    "equipes": [{"equipe_id": "eq-a", "minutes_disponibles": 2400, "minutes_planifiees": 600}],
                },
            },
        }


def rendez_vous_retenu(signal_id: str, quand: dt.datetime, semaine: str = "2026-11-16") -> str:
    """Un rendez-vous dont la fenêtre est retenue (à confirmer par une personne, la cédule de M4 devant être datée)."""
    from m1_front_office import rendez_vous_outils as rdv

    with stockage.transaction():
        proposition = rdv.proposer_fenetres(
            FauxM4(), f"rdv-fictif-{signal_id[-6:]}", signal_id, "visite_evaluation", 60, [semaine], quand.isoformat()
        )
        rdv_id = proposition["resultat"]["rdv_id"]
        retenu = rdv.retenir_fenetre(FauxM4(), rdv_id, semaine, quand.isoformat())
    assert retenu["accepte"] and retenu["resultat"]["etat"] == "retenue"
    return rdv_id


def suivi_rappel_par_admin(
    transfert_id: str, action: str, quand: dt.datetime, prochaine: dt.datetime | None = None
) -> dict[str, Any]:
    """Une personne (admin de console) prend le rappel en charge ou consigne une tentative sans contact."""
    from m1_front_office import outils as m1
    from m1_front_office import transferts

    from opsys import contexte

    with stockage.transaction():
        snapshot = transferts.projection_suivi_rappel(m1._obtenir_registre().lire(), transfert_id)["snapshot_suivi"]
        with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin", source="console")):
            reponse = m1.consigner_suivi_rappel(
                transfert_id, action, snapshot, quand.isoformat(), None if prochaine is None else prochaine.isoformat()
            )
    assert reponse["accepte"] is True, reponse
    return reponse


def clore_transfert(transfert_id: str, quand: dt.datetime) -> dict[str, Any]:
    """Une personne (admin d'appareil) clôt un transfert : il sort de « À voir »."""
    from m1_front_office import outils as m1

    from opsys import contexte

    with stockage.transaction(), contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin")):
        reponse = m1.clore_transfert(
            transfert_id, "Pris en charge par téléphone avec le client (fictif).", quand.isoformat()
        )
    assert reponse["accepte"] is True, reponse
    return reponse


def transferts_ouverts() -> dict[str, dict[str, Any]]:
    from m1_front_office import transferts

    return {e.identifiant: dict(e.ouverture) for e in transferts.lire(lignes_m1()) if e.ouvert}


def journal(executeur: str | None = None) -> list[dict[str, Any]]:
    from opsys.connecteurs_planification import journal as j

    with stockage.transaction() as cnx:
        return j.lire(cnx, executeur, 500)


def rembobiner(plan: pq.Planif, noms: tuple[str, ...] = TOUTES) -> None:
    """Simule un redémarrage ou une deuxième instance qui a perdu la réservation de créneau : le prochain passage est dû
    DE NOUVEAU à l'instant courant. Les routines doivent alors ne rien écrire de plus pour le même créneau."""
    from sqlalchemy import update

    from opsys.stockage.schema import PLANIFICATEUR_EXECUTEURS

    with stockage.transaction() as cnx:
        for nom in noms:
            cnx.execute(
                update(PLANIFICATEUR_EXECUTEURS)
                .where(PLANIFICATEUR_EXECUTEURS.c.executeur == nom)
                .values(prochain_passage=int(plan.horloge()) - 1)
            )


def transferer_a_une_personne(type_transfert: str, expediteur: str) -> dict[str, Any]:
    """L'agent de M1 passe la conversation à une personne (`m1_transferer`) : le suivi de M1 se ferme, un transfert
    s'ouvre."""
    from m1_front_office import outils as m1

    with stockage.transaction():
        reponse = m1.transferer(type_transfert, "sms", expediteur)
    assert reponse.get("accepte", True) is not False, reponse
    return reponse


# -- M10 : une nuit d'affaires
# ----------------------------------------------------------------------------------------------
JOUR_TOUCHE = "2026-11-09"  # la veille de la nuit simulée (mardi 10 novembre, 3 h)


def publier(type_evenement: str, producteur: str, charge: dict[str, Any], evenement_id: str | None = None) -> str:
    from opsys import evenements

    return evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)


def repartir(plan: pq.Planif, passes: int = 3) -> dict[str, int]:
    """Livre à M10 (VRAI répartiteur, VRAIS consommateurs) ce que le bus lui doit ; l'horloge du bus est celle du
    plan."""
    from opsys import evenements

    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0}
    for _ in range(passes):
        resume = evenements.repartir(
            {M10: plan.departements[M10]},
            limite=500,
            maintenant=dt.datetime.fromtimestamp(plan.horloge(), dt.UTC).isoformat(),
        )
        for cle in total:
            total[cle] += resume.get(cle, 0)
        if resume.get("livres", 0) == 0:
            break
    return total


def semer_une_journee_d_affaires(plan: pq.Planif) -> dict[str, str]:
    """Le lundi 9 novembre 2026 : trois affaires touchées (un lead qualifié ; un chantier terminé avec sa rentabilité ;
    un devis accepté), une affaire touchée la VEILLE de la veille seulement, et un chantier terminé dont l'identifiant
    d'affaire
    est forgé (hors de la forme fermée). Publié sur le VRAI bus, livré par le VRAI répartiteur, mémorisé par les VRAIS
    consommateurs de M10."""
    import interconnexion_charges as ch

    lundi = "2026-11-09T{}-05:00"
    publier(
        "m1.lead_qualifie", "m01-front-office", ch.lead_qualifie_m1("aff-lead", horodatage=lundi.format("08:00:00"))
    )
    publier(
        "m4.travaux_termines",
        "m04-field-ops",
        ch.travaux_termines(
            "wct-chantier",
            "devis-chantier",
            lead_id="aff-chantier",
            horodatage_completion=lundi.format("14:00:00"),
            consommateurs_cibles=["M10"],
        ),
    )
    publier(
        "m5.rentabilite_chantier",
        "m05-financecore",
        ch.rentabilite("wct-chantier", "devis-chantier", horodatage_completion=lundi.format("14:00:00")),
    )
    publier(
        "m3.devis_accepte",
        "m03-estimation",
        ch.devis_accepte("devis-accepte", lead_id="aff-devis", horodatage_acceptation=lundi.format("09:00:00")),
    )
    publier(
        "m1.lead_qualifie",
        "m01-front-office",
        ch.lead_qualifie_m1("aff-veille", horodatage="2026-11-08T08:00:00-05:00"),
    )
    publier(
        "m4.travaux_termines",
        "m04-field-ops",
        ch.travaux_termines(
            "wct-forge",
            "devis-forge",
            lead_id="forge x;DROP",
            horodatage_completion=lundi.format("15:00:00"),
            consommateurs_cibles=["M10"],
        ),
    )
    livraison = repartir(plan)
    assert livraison["quarantaines"] == 0, livraison
    return {"touchees": "aff-chantier,aff-devis,aff-lead", "veille": "aff-veille"}


def evenements_m10() -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons(M10, "evenements"))


def affaires_m10() -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons(M10, "affaires"))


def rapports_m10() -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons(M10, "rapports_routine"))


def faits_consolides() -> list[dict[str, Any]]:
    return [m for m in affaires_m10() if m["type_entree"] == "fait_consolide"]
