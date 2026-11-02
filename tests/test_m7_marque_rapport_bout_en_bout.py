"""M7 de bout en bout : profil de marque déclaré -> contenus de chantier -> porte qualité à scores -> trois semaines
simulées
-> rapport hebdomadaire planifié (une fois par semaine, recommandations sourcées) -> observations m7.* -> leçons M10
gouvernées, consultables.

VRAIS outils (M7, M8, M10), VRAI bus et répartiteur, VRAI planificateur durable, VRAIS registres, base SQLite migrée,
horloge INJECTÉE (aucun sleep). Seuls le réseau et les services externes sont absents. Les maillons amont qui viennent
d'AUTRES départements sans lesquels le scénario serait trop long (chantier terminé de M4, lead qualifié de M1, lead
associé
de M2) sont publiés avec la charge du catalogue, comme dans `test_interconnexion_scenarios.py`. Données FICTIVES.

Limites dites : SQLite seulement ; aucune publication réelle n'est exécutée (la publication est un geste humain hors du
scénario) ; aucun modèle de langage n'écrit un texte (les textes « du modèle » sont des chaînes fixes) ; aucun service
externe (Google, Meta, WordPress) n'est contacté.
"""

from __future__ import annotations

import datetime as dt
import json

import interconnexion_charges as ch
import planif_m8_monde as pm
import pytest
from m7_marketing import outils as m7_outils
from m7_marketing.usine import mesure
from sqlalchemy import select

from opsys import approbations, contexte, evenements, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.connecteurs_planification import etat
from opsys.mnemo import cli as mnemo_cli
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
M4, M7, M8, M10 = pm.M4, pm.M7, pm.M8, pm.M10
NOM = "m7.rapport-hebdo"
NATHAN = ("nathan", "admin")
ADMIN = ("admin.fictif", "admin")
LUNDIS = ["2026-10-12", "2026-10-19", "2026-10-26"]  # trois semaines de travail ; rapports les lundis suivants
APPRENTISSAGE = "m7.apprentissage_marketing_constate"
PROFIL = {
    "name": "Toitures Boréales Fictive Inc.",
    "tagline": "Rénovation extérieure au Québec, sans surprise",
    "tone": "professionnel, factuel",
    "colors": ["#1a1a1a", "#ffffff"],
    "langue": "fr",
    "site_url": "https://exemple-fictif.ca/",
    "promesse": "Un chantier propre et bien expliqué du début à la fin",
    "garanties_validees": ["Garantie légale de qualité des travaux"],
    "garanties_a_valider": ["Garantie de dix ans sur tout le revêtement"],
    "mots_interdits": ["pas cher", "bas de gamme"],
    "messages_interdits": ["vous ne trouverez pas mieux ailleurs"],
    "voix": {"adresse": "vous", "exclamations_max": 1, "majuscules_max_pct": 30, "emojis_max": 1},
    "validation_champs": {"promesse": {"statut": "valide", "par": "nathan", "le": "2026-10-01"}},
}
BON = (
    "Chantier terminé à Repentigny : gouttières et descentes. Vous avez un projet semblable ? "
    "Écrivez-nous pour demander une soumission, nous vous répondrons avec plaisir."
)
OUTILS_M7 = {o.nom: o for o in m7_outils.outils()}


@pytest.fixture
def monde(tmp_path, monkeypatch, declarer_services):
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    m.bus.departements[M10]._types.add(APPRENTISSAGE)  # noqa: SLF001 — M10 réel, abonné aussi à l'apprentissage de M7
    yield m
    pm.demonter()


def m7(nom, *, appareil=None, **arguments):
    if appareil is None:
        return executer_atomique(OUTILS_M7[nom], arguments)
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(*appareil)):
        return executer_atomique(OUTILS_M7[nom], arguments)


def metier(reponse):
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def registre_m7(nom):
    with stockage.transaction():
        return list(stockage.maillons(M7, nom))


def wct(k, jour):
    return ch.travaux_termines(
        wct_id=f"wct-e2e-{k}",
        devis_id=None,
        ville="Repentigny",
        type_travaux="gouttières",
        horodatage_completion=f"{jour}T14:00:00-04:00",
        photos=["photo-1", "photo-2"],
        description_factuelle="Installation terminée, sans imprévu.",
        consentement_marketing=True,
        client_satisfait=True,
        consentement_recueilli_par="etienne",
        consentement_recueilli_le=f"{jour}T18:05:00+00:00",
        consentement_version_texte="consentement-client-fr-CA-v1",
    )


def recevoir_chantier(monde, k, jour):
    evenements.publier("m4.travaux_termines", M4, wct(k, jour), evenement_id=f"e2e-wct-{k}")
    monde.bus.repartir(departements=(M7,))


def contenus(k):
    return {
        c["plateforme"]: c
        for c in metier(m7("m7_lister_contenus_chantier", appareil=ADMIN, wct_id=f"wct-e2e-{k}"))["contenus"]
    }


def approuver_et_exporter(k, jour):
    cles = {}
    for plateforme, c in contenus(k).items():
        if plateforme == "demande_temoignage":
            continue
        decision = metier(
            m7(
                "m7_decider_contenu",
                appareil=NATHAN,
                contenu_id=c["contenu_id"],
                decision="approuver",
                horodatage=f"{jour}T10:00:00-04:00",
            )
        )
        assert decision["accepte"] is True, decision
        sortie = metier(
            m7(
                "m7_exporter_paquet_manuel",
                appareil=NATHAN,
                contenu_id=c["contenu_id"],
                horodatage=f"{jour}T11:00:00-04:00",
            )
        )
        assert sortie["accepte"] is True, sortie
        cles[plateforme] = mesure.utm_content_de(c["contenu_id"], plateforme)
    return cles


def leads_de_la_semaine(monde, k, jour, cle_facebook):
    """Deux leads M1 qui ont suivi le lien du contenu Facebook (clé `utm_content`) ; M2 les associe à la source."""
    for i in range(2):
        lead_id = f"lead-e2e-{k}-{i}"
        evenements.publier(
            "m1.lead_qualifie",
            pm.M1,
            ch.lead_qualifie_m1(
                lead_id,
                lead={
                    "schema_version": 2,
                    "lead_id": lead_id,
                    "conversation_id": f"conv-{lead_id}",
                    "contact": {"nom": "Jeanne Fictive", "courriel": "jeanne.fictive@example.test"},
                    "service": "gouttieres",
                    "ville": "Repentigny",
                    "urgence_declaree": False,
                    "canal": "formulaire",
                    "utm": {
                        "utm_source": "facebook",
                        "utm_medium": "social",
                        "utm_campaign": "contenu-chantier",
                        "utm_content": cle_facebook,
                    },
                },
                horodatage=f"{jour}T09:00:00-04:00",
                signal_id=f"formulaire:{lead_id}",
            ),
            evenement_id=f"e2e-m1-{lead_id}",
        )
        evenements.publier(
            "m2.client_associe",
            pm.M2,
            ch.client_associe(
                lead_id,
                utm={"utm_source": "facebook", "utm_campaign": "contenu-chantier"},
                horodatage_association=f"{jour}T09:05:00-04:00",
            ),
            evenement_id=f"e2e-m2-{lead_id}",
        )
    monde.bus.repartir(departements=(M7, M8))


def avis_de_la_semaine(k, jour):
    for i in range(2):
        reponse = m7(
            "m7_importer_avis_manuel",
            appareil=ADMIN,
            plateforme="google_business_profile",
            avis_source_id=f"avis-e2e-{k}-{i}",
            date_avis=jour,
            note=1,
            texte="Je suis très déçu, le travail est resté inachevé.",
            source_url=f"https://exemple-fictif.test/avis/{k}-{i}",
        )
        assert metier(reponse)["accepte"] is True


def lundi_suivant(lundi):
    return dt.date.fromisoformat(lundi) + dt.timedelta(days=7)


def poser_horloge(monde, jour):
    monde.horloge.t = dt.datetime.combine(jour, dt.time(14, 0), tzinfo=dt.UTC).timestamp()


def publies(type_evenement):
    with stockage.transaction() as cnx:
        return [
            json.loads(r["charge"]) if isinstance(r["charge"], str) else r["charge"]
            for r in cnx.execute(
                select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
            ).mappings()
        ]


def caps(monde, ident):
    return Capacites(monde.bus.departements, stockage.transaction, filtre={ident}, appelant=ident)


def humain(monde, nom, args):
    c = caps(monde, M10)
    demande = c.appeler(nom, args)
    assert demande["ok"] is True and demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx,
            demande["demande_id"],
            True,
            "nathan",
            outils_executables(monde.bus.departements, stockage.transaction),
            monde.bus.departements,
        )


# ==============================================================================================================
# scénario
def test_sans_profil_de_marque_tout_est_fail_closed_et_rien_n_est_compose(monde):
    recevoir_chantier(monde, 0, "2026-10-13")
    assert registre_m7("contenus_chantier") == []  # le WCT est reçu, mais aucun contenu sous un nom inventé
    audit = metier(
        m7("m7_auditer_contenu_marque", contenus=[{"reference": "a", "plateforme": "facebook", "texte": BON}])
    )
    assert audit["statut"] == "profil_marque_non_configure" and "audits" not in audit
    assert metier(m7("m7_guide_de_ton_marque"))["statut"] == "profil_marque_non_configure"
    proposition = metier(m7("m7_proposer_contenus_chantier", wct_id="wct-e2e-0"))
    assert proposition["statut"] == "profil_marque_non_configure" and proposition["contenus"] == []


def test_la_porte_qualite_refuse_mot_interdit_garantie_non_validee_et_prix_invente_et_laisse_passer_le_conforme(monde):
    configure = metier(
        m7("m7_configurer_profil_marque", appareil=NATHAN, profil=PROFIL, horodatage="2026-10-01T09:00:00-04:00")
    )
    assert configure["statut"] == "configure" and configure["profil"]["mots_interdits"] == ["pas cher", "bas de gamme"]
    recevoir_chantier(monde, 1, "2026-10-13")
    cinq = contenus(1)
    assert len(cinq) == 5 and {c["conformite"].split("/")[0] for c in cinq.values()} <= {
        "conforme",
        "conforme_avec_reserves",
    }
    cas = {
        "mot-interdit": "Du travail pas cher pour tous. Écrivez-nous pour demander une soumission, merci.",
        "garantie-non-validee": "Garantie de dix ans sur tout le revêtement. Écrivez-nous pour une soumission, merci.",
        "prix-invente": "Installation dès 500 $ seulement. Écrivez-nous pour demander une soumission, merci.",
        "conforme": BON,
    }
    audit = metier(
        m7(
            "m7_auditer_contenu_marque",
            contenus=[{"reference": ref, "plateforme": "facebook", "texte": texte} for ref, texte in cas.items()],
        )
    )
    par_ref = {a["reference"]: a for a in audit["audits"]}
    assert par_ref["conforme"]["verdict"] == "conforme" and par_ref["conforme"]["score_global"] == 100
    attendu = {
        "mot-interdit": "REJ-MARQUE-MOT-INTERDIT",
        "garantie-non-validee": "REJ-MARQUE-PROMESSE-NON-VALIDEE",
        "prix-invente": "REJ-PRIX",
    }
    for ref, code in attendu.items():
        assert par_ref[ref]["verdict"] == "refuse" and code in [r["code"] for r in par_ref[ref]["raisons"]], ref
        assert par_ref[ref]["score_global"] < 100
    # La même porte, côté usine : le texte « du modèle » refusé n'est jamais enregistré ; le conforme l'est, avec son
    # score.
    avant = len(registre_m7("contenus_chantier"))
    recevoir_chantier(monde, 2, "2026-10-13")
    resultat = metier(m7("m7_proposer_contenus_chantier", wct_id="wct-e2e-2", textes={"facebook": cas["mot-interdit"]}))
    fb = next(c for c in resultat["contenus"] if c["plateforme"] == "facebook")
    assert fb["statut"] == "deja_propose"  # le consommateur du bus avait déjà proposé le gabarit du code
    sans_gabarit = metier(m7("m7_proposer_contenus_chantier", wct_id="wct-e2e-2", textes={}))
    assert sans_gabarit["statut"] in ("deja_propose", "propose")
    assert len(registre_m7("contenus_chantier")) == avant + 5
    guide = metier(m7("m7_guide_de_ton_marque"))
    assert "Mot interdit : pas cher" in guide["texte"] and "Garantie de dix ans" in guide["texte"]


def test_trois_semaines_rapport_unique_par_semaine_evenements_m7_et_lecons_m10_consultables(monde):
    metier(m7("m7_configurer_profil_marque", appareil=NATHAN, profil=PROFIL, horodatage="2026-10-01T09:00:00-04:00"))
    avant_semaines = publies("m5.depense_publicitaire_constatee")
    assert avant_semaines == []
    mode_vu = []
    for k, lundi in enumerate(LUNDIS):
        jour = f"{lundi[:8]}{int(lundi[8:]) + 1:02d}"  # le mardi de la semaine
        recevoir_chantier(monde, 10 + k, jour)
        cles = approuver_et_exporter(10 + k, jour)
        monde.bus.repartir(departements=(M8,))
        leads_de_la_semaine(monde, k, jour, cles["facebook"])
        avis_de_la_semaine(k, jour)
        rapport_le = lundi_suivant(lundi)
        poser_horloge(monde, rapport_le)
        if k == 0:
            monde.plan.activer(NOM, "ombre", intervalle_s=86400)
            monde.plan.tour(avance=1)
            assert registre_m7("rapports_hebdomadaires") == [] and publies(APPRENTISSAGE) == []  # l'ombre n'écrit rien
            monde.plan.activer(NOM, "actif", intervalle_s=86400)
        resume = monde.plan.tour(avance=1)
        mode_vu.append(resume["executeurs"][NOM])
        # idempotence : le même jour et les six suivants ne refont rien
        for _ in range(6):
            monde.plan.tour(avance=86400)
        rapports = [r for r in registre_m7("rapports_hebdomadaires") if r["type"] == "rapport_hebdo"]
        assert [r["semaine"] for r in rapports][-1] == lundi and len(rapports) == k + 1
        monde.horloge.t = dt.datetime.combine(rapport_le, dt.time(14, 0), tzinfo=dt.UTC).timestamp()
        monde.bus.repartir(departements=(M10, M8, M7))

    rapports = [r["rapport"] for r in registre_m7("rapports_hebdomadaires") if r["type"] == "rapport_hebdo"]
    dernier = rapports[-1]
    # le rapport dit ce que les données permettent, rien de plus
    assert dernier["semaine"] == {"debut": "2026-10-26", "fin": "2026-11-01"}
    assert dernier["sources"]["m8_mesures"] == dernier["sources"]["m8_contenus"] == "disponible"
    assert dernier["contenus"]["statut"] == "calcule" and dernier["contenus"]["meilleurs"][0]["leads"] == 2
    assert dernier["contenus"]["meilleurs"][0]["canal"] == "facebook"
    assert dernier["roi"]["roi"] is None and "ne recalcule pas la finance" in dernier["roi"]["raison"]
    assert dernier["cout_par_lead"]["statut"] in ("donnees_insuffisantes", "source_absente")  # aucun relevé de dépense
    assert dernier["reputation"]["avis_semaine"] == 2 and dernier["reputation"]["negatifs_sans_reponse"] == 2
    assert dernier["leads_par_canal"]["statut"] == "calcule"
    assert (
        dernier["leads_par_canal"]["canaux"][0]["canal"] == "facebook"
        and dernier["leads_par_canal"]["canaux"][0]["leads"] == 2
    )
    assert dernier["recommandations"]
    from m7_marketing.rapport_hebdo import recommandations

    for r in rapports:
        assert recommandations.verifier_liaison(r) == []
        assert all(x["sources"] or x["hypothese"] for x in r["recommandations"])
        assert r["empreinte"]
    regles = {x["regle"] for x in dernier["recommandations"]}
    assert {"avis_negatifs_sans_reponse", "contenu_gagnant"} <= regles
    # tâches internes de niveau bas, visibles dans « À voir », sans rien d'exécuté
    taches = registre_m7("taches_marketing")
    assert 1 <= len([t for t in taches if t["semaine"] == "2026-10-26"]) <= 5 and all(
        t["niveau"] == "N1" for t in taches
    )
    with stockage.transaction():
        attentes = [a for a in m7_outils.attentes() if a["type"] == "tache_marketing"]
    assert attentes and all(a["niveau"] == "N1" for a in attentes)
    assert registre_m7("exports_calendrier") == [] and registre_m7("publications_sociales") == []  # aucune publication
    # événements m7.* : minimaux, sans texte ni coordonnée, un par observation et par semaine
    annonces = publies(APPRENTISSAGE)
    assert len(annonces) == len({a["observation_id"] for a in annonces}) >= 9
    texte = json.dumps(annonces, ensure_ascii=False)
    for personnel in ("Jeanne", "example.test", "@", "wct-e2e", "lead-e2e", "Je suis très déçu", "Repentigny"):
        assert personnel not in texte
    assert {a["genre_observation"] for a in annonces} >= {"contenu_gagnant", "objection_frequente", "avis_constate"}
    assert monde.bus.quarantaines() == []
    # M10 a mémorisé chaque observation une fois, dans son propre registre
    faits = monde.bus.registre(M10, "faits_marketing")
    assert len(faits) == len(annonces) and monde.bus.ecritures_hors_propriete() == []

    # --- leçons gouvernées de M10
    # --------------------------------------------------------------------------------------
    m10 = caps(monde, M10)
    bilan = metier(m10.appeler("m10_extraire_lecons", {}))
    assert len(bilan["proposees"]) >= 3
    lecons = metier(m10.appeler("m10_lire_lecons", {"genre": "apprentissage_marketing"}))["lecons"]
    cles = {x["cle"]: x for x in lecons}
    assert {
        "contenu_gagnant:facebook",
        "objection_frequente:avis_clients:urgence",
        "avis_constate:avis_clients",
    } <= set(cles)
    gagnante = cles["contenu_gagnant:facebook"]
    assert (
        gagnante["cible"] == M7 and gagnante["etat"] == "proposee" and gagnante["contenu"]["semaines_distinctes"] == 3
    )
    assert "Jeanne" not in json.dumps(lecons) and not any(c.isdigit() for c in gagnante["texte_agent"])
    assert metier(caps(monde, M7).appeler("opsys_lecons_actives", {"cle_application": "chantier-1"}))["lecons"] == []
    ident = gagnante["lecon_id"]
    mesure_hors_ligne = metier(m10.appeler("m10_evaluer_lecon", {"lecon_id": ident}))
    assert mesure_hors_ligne["mesure"]["mesurable"] is False  # dit : aucune amélioration chiffrée hors ligne
    stockage.liberer()
    garde = mnemo_cli.garde_lecon(ident, "operateur.fictif")
    assert garde["departement"] == M7 and garde["regressions"] == []
    sans_humain = m10.appeler(
        "m10_decider_lecon", {"lecon_id": ident, "etape": "complete", "motif": "Décision de test."}
    )
    assert sans_humain["statut"] == "en_attente_approbation"  # un agent seul ne promeut rien
    r = humain(
        monde,
        "m10_decider_lecon",
        {"lecon_id": ident, "etape": "canari", "pourcentage": 50, "motif": "Essai sur la moitié des cas."},
    )
    assert r["statut"] == "executee"
    r = humain(
        monde,
        "m10_decider_lecon",
        {"lecon_id": ident, "etape": "complete", "motif": "Les contenus gagnants se confirment."},
    )
    assert r["statut"] == "executee"
    actives = metier(caps(monde, M7).appeler("opsys_lecons_actives", {"cle_application": "chantier-1"}))
    assert [x["lecon_id"] for x in actives["lecons"]] == [ident]
    assert metier(caps(monde, pm.M5).appeler("opsys_lecons_actives", {"cle_application": "chantier-1"}))["lecons"] == []
    decidees = publies("m10.lecon_decidee")
    assert {d["genre"] for d in decidees} == {"apprentissage_marketing"} and all(d["cible"] == M7 for d in decidees)
    # le journal du planificateur et les reçus du bus ne portent rien de personnel
    from opsys.stockage.schema import EVENEMENTS_RECUS, PLANIFICATEUR_JOURNAL

    with stockage.transaction() as cnx:
        journal = json.dumps([dict(r) for r in cnx.execute(select(PLANIFICATEUR_JOURNAL).where(
            PLANIFICATEUR_JOURNAL.c.executeur == NOM)).mappings()], default=str, ensure_ascii=False)
        recus = json.dumps([dict(r) for r in cnx.execute(select(EVENEMENTS_RECUS).where(
            EVENEMENTS_RECUS.c.evenement_id.like("m7-appr-%"))).mappings()], default=str)
    assert NOM in journal and "m7-appr-" in recus
    for personnel in ("Jeanne", "example.test", "jeanne", "Repentigny", "lead-e2e", "wct-e2e", "Je suis très déçu"):
        assert personnel not in journal and personnel not in recus, personnel
    # rien d'externe n'est parti : aucune publication, aucun courriel, aucune dépense
    with stockage.transaction() as cnx:
        types = {t for (t,) in cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement).distinct())}
    assert not types & {
        "m7.publication_faite",
        "m7.publication_echouee",
        "m1.courriel_envoye",
        "m7.depenses_marketing_constatees",
    }
    assert etat.definition(NOM).niveau == "N2"
