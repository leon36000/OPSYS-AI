"""La voie « certifiée » du coût complet d'un chantier : une journée d'ÉQUIPE pointée en V3, sur une vraie visite.

Contrat produit (PR #861) : un WCT M4 qui n'a qu'une durée scalaire (la journée « legacy » de l'employé, pointages
individuels) ne permet PAS à M5 de chiffrer la main-d'œuvre (`REJ-COUT-TEMPS-POINTE-ABSENT`, coût partiel, marge
inconnue). Le coût complet ne se calcule que par trois pièces ensemble, que ce module fournit à tous les tests E2E :

1. des pointages d'équipe V3 (`m4_field_ops.equipes_pointees_v3.enregistrer`) sur une vraie visite du plan appliqué ;
2. une projection M4 vérifiée : la politique de service `m4.verifier_v3` (ligne `SERVICE_POLITIQUES`) de M5 ;
3. un tarif d'équipe M5 (`m5_outils._inscrire_tarif_equipe`).

Rien ici ne contourne ce contrat : aucune écriture directe du temps pointé, aucune durée fournie à M5. Les gestes sont
ceux de l'admin sur la console (déclarations explicites, jamais déduites d'une présence individuelle) et de l'employé
sur son appareil (consentement, dépôt de la photo et de la signature, « Terminer »).

Fictif (`fictif: true`, AGENTS.md). Extrait de `tests/e2e/test_verticale_affaire_durable.py`, qui l'importe : le
suffixe de clés vaut `""` pour la verticale, ce qui laisse ses clés d'idempotence inchangées ; un autre test en passe
un pour que ses clés ne croisent pas celles d'un autre chantier de la même base.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import yaml
from harnais_e2e import iso
from harnais_e2e_chantier import MATERIAU_ID, QUANTITE_PREVUE, SEL, VILLE, AppEmploye, Chantier, png_minimal
from m4_field_ops import encodage, equipes_pointees_v3, visites_ecriture
from m4_field_ops import outils as m4_outils
from m4_field_ops.registre import Registre
from m5_financecore import outils as m5_outils
from sqlalchemy import insert, select

from opsys import (
    cli,
    contexte,
    equipes,
    service_capability,
    service_lecture_m4,
    service_recalcul_m4,
    stockage,
    taxonomie,
)
from opsys.console.securite import Session
from opsys.stockage.schema import APPROBATIONS, OPSYS_INSTANCE, SERVICE_POLITIQUES

EQUIPE_VERTICALE = "eq-verticale-fictive"


def _cle(base: str, suffixe: str) -> str:
    return f"{base}-{suffixe}" if suffixe else base


def appel_porte(moteur: Any, porte: Any, outil: str, args: dict[str, Any], *, cle: str | None = None) -> Any:
    """Un geste par la porte d'appareil, réponse HTTP 200 non tronquée exigée (comme `_app` de la verticale)."""
    reponse = porte.appeler(outil, args, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant) if cle else None)
    assert reponse.statut == 200, reponse.corps
    assert not reponse.mesure.tronque, reponse.corps
    return reponse


# -- l'équipe déclarée, avant la journée ----------------------------------------------------------------------
def profil_equipes(equipe_id: str, membres: list[str], services: dict[str, Any]) -> dict[str, Any]:
    """Profil des équipes de l'entreprise (même forme que `EQUIPES_FICTIVES` de la verticale) : une seule équipe,
    un dépôt à Repentigny, un quart de 8 h à 17 h le jour 0 de la semaine de cédule."""
    return {
        "liste": [{
            "id": equipe_id, "membres": list(membres), "competences": ["gouttieres"],
            "depot": {"id": "depot-fictif", "latitude_microdegres": 45735000, "longitude_microdegres": -73455000},
            "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}],
        }],
        "services": services,
        "cedule": {"facteur_detour_milliemes": 1300, "vitesse_moyenne_kmh": 50, "marge_par_trajet_secondes": 600,
                   "iterations": 500, "cout_non_cedule_m": 500000},
        "fenetre_par_defaut": {"jours": [0], "debut_min": 480, "fin_min": 1020},
    }


def declarer_profil(dossier: Any, commande: str, contenu: dict[str, Any]) -> None:
    """Déclare un profil (`equipes` ou `meteo`) par la commande réelle du socle, comme le fait Nathan."""
    fichier = dossier / f"{commande}-equipe-certifiee-fictive.yaml"
    fichier.write_text(yaml.safe_dump(contenu), encoding="utf-8")
    assert cli.main([commande, "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0


def affecter_a_l_equipe(
    moteur: Any, admin: Any, chantier: Chantier, equipe_id: str, *, suffixe: str = "",
    arguments_cedule: dict[str, Any] | None = None,
) -> None:
    """Confirme la localisation du chantier, propose puis applique la cédule : l'intervention devient celle de
    l'ÉQUIPE (assignation native de `m4_appliquer_cedule`, jamais fabriquée ici). Le profil des équipes est déjà
    déclaré (`declarer_profil`). `arguments_cedule` complète `m4_proposer_cedule` pour ce que le profil ne porte pas
    (lead v1 : durées et compétences par type de travaux ; intervention déjà `planifiee` : sa fenêtre)."""
    localisation = appel_porte(moteur, admin, "m4_confirmer_localisation", {
        "chantier_id": chantier.lead_id, "action": "confirmee", "horodatage": iso(moteur.horloge.maintenant),
        "confirme_par": "nathan",
        "adresse": {"numero_municipal": "1", "odonyme": "Rue Fictive", "municipalite": "Repentigny"},
        "source": "manuel", "latitude_microdegres": 45740117, "longitude_microdegres": -73454833,
        "motif": "Coordonnées de test fictives confirmées."}, cle=_cle("localisation-equipe-certifiee", suffixe))
    assert localisation.metier["accepte"] is True, localisation.corps
    plan = appel_porte(moteur, admin, "m4_proposer_cedule", {
        "horodatage": iso(moteur.horloge.maintenant), "intervention_ids": [chantier.intervention_id],
        **(arguments_cedule or {})},
        cle=_cle("cedule-proposee-equipe-certifiee", suffixe))
    assert plan.metier["accepte"] is True, plan.corps
    applique = appel_porte(moteur, admin, "m4_appliquer_cedule", {
        "plan_id": plan.resultat["plan_id"], "horodatage": iso(moteur.horloge.maintenant),
        "confirme_par": "nathan"}, cle=_cle("cedule-appliquee-equipe-certifiee", suffixe))
    assert applique.metier["accepte"] is True, applique.corps
    (assignation,) = [a for a in applique.resultat["assignations"] if a["intervention_id"] == chantier.intervention_id]
    assert assignation["technicien_id"] == equipe_id, "assignation native, jamais fabriquée par le test"


# -- les deux pièces de M5 : tarif d'équipe et politique de service ------------------------------------------
def service_m4_et_tarif_fictifs(chantier: Chantier, equipe_id: str = EQUIPE_VERTICALE, *, suffixe: str = "") -> None:
    """Politique et tarif d'équipe de test (50,00 $ l'heure d'équipe, le jour du chantier), dans la seule base
    éphémère du test : le tarif par `m5_outils._inscrire_tarif_equipe`, la politique `m4.verifier_v3` en base."""
    with (stockage.transaction() as cnx,
          contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin", source="console")),
          contexte.appeler_en_tant_que("m05-financecore", origine="console")):
        source = m5_outils._lire_tarifs_equipes()["source"]
        m5_outils._inscrire_tarif_equipe({
            "equipe_id": equipe_id, "taux": "50.00", "unite": "heure-equipe",
            "devise": "CAD", "source": "tarif-vertical-fictif", "version": "1",
            "date_effet": chantier.debut.date().isoformat(), "date_fin": chantier.debut.date().isoformat(),
            "remplace_id": None,
        }, mutation_id=_cle("tarif-equipe-vertical-fictif", suffixe), source_attendue=source)
        instance_id = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
        cnx.execute(insert(SERVICE_POLITIQUES).values(
            instance_id=instance_id, consommateur="m05-financecore", operation="m4.verifier_v3",
            revision=1, active=True, expire_le=int(time.time()) + 3600))


# -- la journée ---------------------------------------------------------------------------------------------
def journee_equipe_certifiee(
    moteur: Any, admin: Any, employe: Any, chantier: Chantier, equipe_id: str = EQUIPE_VERTICALE, *,
    suffixe: str = "",
) -> tuple[AppEmploye, Any]:
    """Déclarations admin explicites sur une vraie visite, sans déduire de présence individuelle. Rend l'app de
    l'employé et la réponse de « Terminer » (elle porte le `wct_id`). Arrivée à 08 h, départ à 11 h (heure du
    chantier) : 180 minutes d'équipe, `chantier.technicien` donnant son consentement et sa complétion."""
    app = AppEmploye(moteur, employe, chantier, derive_appareil_s=0)
    with stockage.transaction():
        principal = Registre(stockage.maillons("m04-field-ops", "principal"))
        applications = [m for m in principal.lire() if m.get("type_entree") == "cedule_appliquee"]
        assert len(applications) == 1
        plan_id = applications[0]["plan_id"]
    datee = appel_porte(moteur, admin, "m4_confirmer_dates_cedule", {
        "plan_id": plan_id, "calendrier": {"0": chantier.debut.date().isoformat()}, "revision_attendue": 0,
    }, cle=_cle("date-verticale-equipe", suffixe))
    assert datee.metier["accepte"] is True, datee.corps
    with stockage.transaction():
        principal = Registre(stockage.maillons("m04-field-ops", "principal"))
        date = next(m for m in principal.lire() if m.get("ligne_id") == datee.resultat["ligne_id"])
        ancre = {"intervention_id": chantier.intervention_id, "plan_id": plan_id,
                 "source_application_id": date["source_application_id"], "source_ligne_id": date["ligne_id"]}

    def admin_console(instant):
        return (contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin", source="console")),
                contexte.appeler_en_tant_que("m04-field-ops", origine="console"),
                contexte.receptionne_de(contexte.HorodatageAppareil("console:nathan", instant, instant)))

    def evenement_visite(cnx, args, cle, instant):
        mutation = {"appareil": "console:nathan", "cle": _cle(cle, suffixe),
                    "empreinte_arguments": encodage.empreinte(args)}
        return visites_ecriture.executer_evenement(
            cnx, args, {"personne": "nathan", "role": "admin"}, mutation, instant.isoformat(),
            m4_outils._autoriser_annotation)

    instant = moteur.horloge.maintenant
    with stockage.transaction() as cnx:
        c1, c2, c3 = admin_console(instant)
        with c1, c2, c3:
            args = {"ancre": ancre, "revision_attendue": 0}
            mutation = {"appareil": "console:nathan", "cle": _cle("visite-verticale-fictive", suffixe),
                        "empreinte_arguments": encodage.empreinte(args)}
            recu = visites_ecriture.enregistrer(cnx, args, {"personne": "nathan", "role": "admin"}, mutation,
                                                instant.isoformat(), m4_outils._autoriser_annotation)
            visite_id = recu["visite_id"]
            evenement_visite(cnx, {"operation": "ouvrir", "visite_id": visite_id,
                                   "source_attendue": visites_ecriture.empreinte_sources(cnx)},
                             "ouverture-verticale-fictive", instant)
    # Plusieurs chantiers peuvent coexister dans la même base : celui-ci doit être parmi ceux de l'employé.
    assert chantier.intervention_id in {i["intervention_id"] for i in app.chantiers_du_jour().resultat}
    app.attendre(minutes=1)
    assert app.donner_consentement_gps().metier["accepte"] is True
    app.attendre(minutes=29)
    route = appel_porte(moteur, admin, "m4_demarrer_route", {
        "intervention_id": chantier.intervention_id, "technicien_id": equipe_id,
        "horodatage": iso(moteur.horloge.maintenant),
    }, cle=_cle("route-equipe-verticale", suffixe))
    assert route.metier["accepte"] is True, route.corps
    app.attendre(minutes=30)

    def pointer_equipe(action):
        instant = moteur.horloge.maintenant
        with stockage.transaction() as cnx:
            c1, c2, c3 = admin_console(instant)
            with c1, c2, c3:
                args = {"intervention_id": chantier.intervention_id, "technicien_id": equipe_id,
                        "action": action, "horodatage": instant.isoformat(), "fix_gps": None,
                        "attestation": {"fictif": True, "appareil_id": "console:nathan"},
                        "fenetre_travail": chantier.fenetre, "referentiel_villes": chantier.referentiel_villes,
                        "ville": VILLE, "sel": SEL}
                recu = equipes_pointees_v3.enregistrer(
                    cnx, args, visite_id, equipe_id, _cle("pointage-equipe-verticale-" + action, suffixe),
                    equipes_pointees_v3.empreinte_sources(cnx))
                principal = Registre(stockage.maillons("m04-field-ops", "principal"))
                demandes = [m for m in principal.lire() if m.get("type_entree") == "demande_revue"
                            and m.get("pointage_ligne_id") == recu["pointage_id"]]
        for demande in demandes:
            reponse = appel_porte(moteur, admin, "m4_resoudre_demande", {
                "demande_id": demande["demande_id"], "decision": "validee", "horodatage": instant.isoformat(),
                "motif": "Contrôle fictif."}, cle=_cle("controle-pointage-" + action, suffixe))
            assert reponse.metier["accepte"] is True, reponse.corps

    pointer_equipe("arrivee")
    app.attendre(hours=2, minutes=55)
    photo = app.deposer_fichier(png_minimal(largeur=4))
    signature = app.deposer_fichier(png_minimal(largeur=2))
    app.attendre(minutes=5)
    pointer_equipe("depart")
    instant = moteur.horloge.maintenant
    with stockage.transaction() as cnx:
        c1, c2, c3 = admin_console(instant)
        with c1, c2, c3:
            evenement_visite(cnx, {"operation": "fermer", "visite_id": visite_id,
                                   "source_attendue": visites_ecriture.empreinte_sources(cnx)},
                             "fermeture-verticale-fictive", instant)
    app.attendre(minutes=5)
    return app, app.terminer(photo, signature)


# -- le chantier de bout en bout, jusqu'à la variance --------------------------------------------------------
def confier_a_l_equipe_lead_v1(
    moteur: Any, admin: Any, chantier: Chantier, dossier: Any, equipe_id: str, *, suffixe: str = "",
) -> None:
    """Un chantier de `preparer_chantier` (lead v1, `type_travaux` « renovation_totale », intervention planifiée à
    `etienne`) passe à l'ÉQUIPE `equipe_id`, dont `etienne` est membre : profil des équipes déclaré (`dossier` : où
    écrire le fichier), localisation confirmée, cédule proposée puis appliquée. Pour un lead v1 et une intervention déjà
    `planifiee`, durée, compétences et fenêtre se passent en arguments de la cédule (le profil est par service)."""
    declarer_profil(dossier, "equipes", profil_equipes(equipe_id, [chantier.technicien], {
        "gouttieres": {"duree_min": 90, "competences": ["gouttieres"]}}))
    affecter_a_l_equipe(moteur, admin, chantier, equipe_id, suffixe=suffixe, arguments_cedule={
        "durees_par_type_travaux": {"renovation_totale": 90},
        "competences_par_type_travaux": {"renovation_totale": []},
        "chantiers": [{"intervention_id": chantier.intervention_id, "creneau_fige": None,
                       "fenetre": {"jours": [0], "debut_min": 480, "fin_min": 1020}}]})


def retirer_le_profil_des_equipes() -> None:
    """Remet l'instance à l'état « aucun profil des équipes déclaré », une fois la journée certifiée terminée. Pour un
    test dont d'autres lectures (la préparation d'une intervention, volet « équipe ») documentent cet état dans une
    fixture contractuelle : la voie certifiée a dû déclarer une équipe, ce n'est pas ce que ces lectures vérifient."""
    taxonomie._ecrire_cle_du_profil(equipes.CLE_EQUIPES, {}, None, None, "entreprise.equipes", {})
    assert equipes.lire_equipes() is None


def declarer_materiaux_comme_admin(
    moteur: Any, admin: Any, chantier: Chantier, wct_id: str, quantite: float, *, suffixe: str = "",
) -> Any:
    """Le même formulaire que `AppEmploye.declarer_materiaux`, posé par l'admin authentifié : le WCT est celui d'une
    ÉQUIPE, M6 n'y autorise pas l'employé (`REJ-INTERVENTION-NON-ASSIGNEE`)."""
    return appel_porte(moteur, admin, "m6_declarer_materiaux_utilises", {
        "wct_id": wct_id, "formulaire": {
            "wct_id": wct_id, "intervention_id": chantier.intervention_id, "chantier_id": chantier.chantier_id,
            "lignes_materiaux": [{"type_ligne": "prevu", "materiau_id": MATERIAU_ID, "quantite": quantite,
                                  "unite": "pi", "quantite_estimee": QUANTITE_PREVUE}]}},
        cle=_cle("mut-materiaux-equipe-certifiee", suffixe))


def terminer_chantier_certifie(
    moteur: Any, admin: Any, employe: Any, chantier: Chantier, quantite: float, equipe_id: str, *, suffixe: str = "",
) -> tuple[AppEmploye, Any, Any]:
    """La voie certifiée jusqu'à la variance (tarif et politique, journée d'équipe, « Terminer », le bus livre la
    complétion, l'admin déclare `quantite` pi, le bus livre la variance) ; un écart critique laisse la complétion en
    revue : l'admin la fait (cause classée, revue décidée), le bus livre. Rend l'app, la complétion et la déclaration.
    Le recalcul qualifié (`recalcul_certifie_qa`) vient APRÈS toute entrée de M5 qui change (facture envoyée...)."""
    service_m4_et_tarif_fictifs(chantier, equipe_id, suffixe=suffixe)
    app, completion = journee_equipe_certifiee(moteur, admin, employe, chantier, equipe_id, suffixe=suffixe)
    wct_id = completion.resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    app.attendre(minutes=5)
    declaration = declarer_materiaux_comme_admin(moteur, admin, chantier, wct_id, quantite, suffixe=suffixe)
    moteur.drainer_bus(moteur.horloge.maintenant)
    if app.statut().resultat["statut"] == "completed_pending_review":
        # Le coût certifié n'est exploitable qu'une fois la revue finale faite ; le signal critique de M6 reste dit.
        revue_completion_verifiee(moteur, admin, app, chantier, wct_id, suffixe=suffixe)
        moteur.drainer_bus(moteur.horloge.maintenant)
    return app, completion, declaration


# -- la revue humaine d'un écart critique ---------------------------------------------------------------------
def sources_pour_revue(appeler, intervention_id, wct_id, prefixe):
    """Fictif : lecture M6 puis causes humaines déclarées, sans vérité photo inférée."""
    liste = appeler("m6_lister_variances_classables_wct_appareil",
                    {"wct_id": wct_id, "decalage": 0, "limite": 8})
    assert liste.metier["accepte"] is True, liste.corps
    dto = liste.resultat
    assert dto["wct"]["wct_id"] == wct_id and dto["wct"]["intervention_id"] == intervention_id
    assert dto["pagination"]["reste"] == 0 and dto["pagination"]["decalage_suivant"] is None
    critiques = [ligne for ligne in dto["lignes"] if ligne["source_ligne"]["critique"] is True]
    assert critiques, "ce scénario doit publier une variance critique, pas inventer une cause"
    for ligne in critiques:
        assert ligne["classement_courant"] is None, "source initiale de cette fixture"
        classement = appeler("m6_classer_cause_variance_appareil", {
            "selection": ligne["selection"], "cause": "breakage",
            "motif": "FICTIF : cause de bris déclarée pour le scénario, sans attestation photo.",
            "classement_attendu": None, "references_pieces": [],
        }, cle=f"{prefixe}-{ligne['selection']['position_ligne']}")
        assert classement.metier["accepte"] is True, classement.corps
    dossier = appeler("m4_lire_dossier_revue_completion_appareil",
                      {"intervention_id": intervention_id, "demande_id": None})
    assert dossier.metier["accepte"] is True, dossier.corps
    assert dossier.resultat["wct"] == dto["wct"]
    assert dossier.resultat["couverture"]["positions_sans_classement"] == []
    return dossier.resultat["sources"]


def revue_completion_verifiee(
    moteur: Any, admin: Any, app: AppEmploye, chantier: Chantier, wct_id: str, *, suffixe: str = "",
    empreinte: Any = None,
) -> None:
    """La revue humaine d'une complétion `completed_pending_review` (écart critique de matériaux) : l'admin relit les
    sources M4/M6, classe la cause de chaque variance critique, résout la revue (demande N4) puis la décide. Le coût
    certifié n'est exploitable qu'une fois cette revue finale faite (`completed_verified`). `empreinte` : l'état durable
    qui ne doit pas bouger pendant les lectures (celui du moteur par défaut)."""
    empreinte = empreinte or moteur.empreinte_etat

    def appeler_revue(outil, arguments, *, cle=None):
        avant_lecture = empreinte() if cle is None else None
        reponse = appel_porte(moteur, admin, outil, arguments, cle=cle)
        if cle is None:
            assert empreinte() == avant_lecture, "lecture de sources sans mutation"
        return reponse

    sources = sources_pour_revue(
        appeler_revue, chantier.intervention_id, wct_id, _cle("classement-verticale", suffixe))
    revue = appel_porte(
        moteur,
        admin,
        "m4_resoudre_revue_completion_sources",
        {
            "intervention_id": chantier.intervention_id,
            "decision": "verifiee",
            "horodatage": iso(moteur.horloge.maintenant),
            "motif": "Revue fictive des sources M4/M6 relues.",
            "sources": sources,
        },
        cle=_cle("revue-verticale", suffixe),
    )
    assert revue.enveloppe["statut"] == "en_attente_approbation", revue.corps
    with stockage.transaction() as cnx:
        assert cnx.scalar(
            select(APPROBATIONS.c.niveau).where(APPROBATIONS.c.id == revue.enveloppe["demande_id"])
        ) == "N4"
    decision = appel_porte(
        moteur,
        admin,
        "m9_decider_demande_approbation",
        {"demande_id": revue.enveloppe["demande_id"], "decision": "approuver", "motif": "Revue fictive."},
        cle=_cle("decision-revue-verticale", suffixe),
    )
    assert decision.resultat["statut"] == "executee", decision.corps
    preuve = decision.resultat["preuve_completion"]
    assert preuve["sources"] == sources and preuve["wct_id"] == wct_id
    assert preuve["demande_approbation_id"] == revue.enveloppe["demande_id"]
    assert preuve["association_decision"]["intention_uuid"] == _cle("decision-revue-verticale", suffixe)
    assert preuve["association_decision"]["appareil_id"] == admin.appareil_id
    assert preuve["association_decision"]["horodatage_appareil_declare"] == iso(moteur.horloge.maintenant)
    assert app.statut().resultat["statut"] == "completed_verified"


# -- les deux coutures QA qui rendent la voie certifiée VISIBLE ---------------------------------------------
# Elles ne sont routées par aucune route de production (`ouvrir` refuse : « décision et revue » manquantes) ; ce sont
# les mêmes coutures que `tests/e2e/test_verticale_affaire_durable.py` et `tests/test_qa_m4_core_m5.py`. Sans elles,
# la cascade du bus trace un coût partiel (le signal de variance de M6 n'arrive qu'après le WCT, et seul le WCT porte
# une capacité de service) et la lecture de l'admin reste partielle.
def _session_qa() -> Session:
    return Session("nathan", frozenset({"admin"}), "csrf-fictif", time.time() + 3600)


def _politique(operation: str) -> None:
    with stockage.transaction() as cnx:
        instance_id = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
        cnx.execute(insert(SERVICE_POLITIQUES).values(
            instance_id=instance_id, consommateur="m05-financecore", operation=operation,
            revision=1, active=True, expire_le=int(time.time()) + 3600))


def recalcul_certifie_qa(chantier: Chantier, wct_id: str, *, suffixe: str = "") -> dict[str, Any]:
    """Une fois le WCT ET la variance reçus par M5 : le recalcul qualifié `m4.recalculer_v3` (couture QA) refait le
    coût depuis la projection M4 vérifiée et le tarif d'équipe, le trace (ventilation V3) et le publie."""
    _politique("m4.recalculer_v3")
    intention = hashlib.sha256(f"intention-recalcul-{chantier.lead_id}-{suffixe}".encode()).hexdigest()
    with stockage.transaction() as cnx:
        recalcul = service_recalcul_m4._executer_qa(
            cnx, _session_qa(), wct_id=wct_id, devis_id=chantier.devis_id, intention_id=intention)
    assert recalcul["statut"] == "publiee", recalcul
    assert recalcul["attestation"]["operation"] == "m4.recalculer_v3"
    return recalcul


def lecture_m5_sous_portee_qa(moteur: Any, monkeypatch: Any, chantier: Chantier, wct_id: str) -> None:
    """La lecture `m5_lire_rentabilite_chantier` d'UN devis s'exécute sous la portée de relecture M4
    (`m4.relire_faits_pour_m5_v1`, couture QA) : elle revalide la projection et rend le coût certifié. Les autres
    lectures (autre devis, devis inconnu, arguments invalides) restent l'ordinaire. Une portée refusée n'autorise
    aucune donnée : la lecture ordinaire, partielle, est rendue. Le serveur MCP lie la fonction de l'outil à son
    démarrage : il est donc redémarré (même base, mêmes appareils) pour prendre la couture."""
    _politique("m4.relire_faits_pour_m5_v1")
    original = m5_outils.lire_rentabilite_chantier

    def lire(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("devis_id") != chantier.devis_id:
            return original(*args, **kwargs)
        try:
            with (stockage.transaction() as cnx,
                  service_lecture_m4._ouvrir_qa(cnx, _session_qa(), wct_id=wct_id, devis_id=chantier.devis_id)):
                return original(*args, **kwargs)
        except service_capability.RefusAutorite:
            return original(*args, **kwargs)

    monkeypatch.setattr(m5_outils, "lire_rentabilite_chantier", lire)
    moteur.arreter()
    moteur.demarrer()
