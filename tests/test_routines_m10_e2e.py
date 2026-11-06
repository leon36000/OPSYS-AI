"""Routines planifiées de M10 (mémoire), de bout en bout : une journée d'affaires FICTIVE publiée sur le VRAI bus,
livrée par le
VRAI répartiteur, mémorisée par les VRAIS consommateurs de M10, puis une nuit simulée du VRAI planificateur durable
avec une
horloge INJECTÉE (aucun sleep). On prouve que l'énumérateur désigne exactement les affaires touchées la veille, que la
consolidation
tourne et se consulte, qu'un redémarrage ou une deuxième instance ne double rien, qu'une panne n'arrête pas les autres,
que
l'audit hebdomadaire trouve un oubli injecté et que les KPI sont calculés ou dits non calculables.

Limite dite sans euphémisme : SQLite seulement, horloge injectée, données fictives, aucun service externe.
"""

from __future__ import annotations

import json

import planif_routines_monde as w
import pytest
from sqlalchemy import insert, select

from opsys import stockage
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, PLANIFICATEUR_JOURNAL

LUNDI, MARDI = "2026-11-09", "2026-11-10"
CONSOLIDATION = "m10.routine.consolidation-affaires"
AUDIT = "m10.routine.audit-non-oubli"
KPIS = "m10.routine.kpis-memoire"
TOUCHEES = ["aff-chantier", "aff-devis", "aff-lead"]


@pytest.fixture
def plan(tmp_path, monkeypatch, declarer_services):
    plan = w.monter(tmp_path, monkeypatch, declarer_services)
    w.aller_a(plan, w.local(LUNDI, "20:00"))
    yield plan
    w.demonter()


def _outil(nom):
    from m10_memoire import outils

    return next(o for o in outils.outils() if o.nom == nom).fonction


def _lister(jour, limite=50):
    with stockage.transaction():
        return _outil("m10_lister_affaires_a_consolider")(jour, limite)["resultat"]


def _faits():
    return sorted((f["affaire_id"], f["jour"]) for f in w.faits_consolides())


def test_l_enumerateur_designe_exactement_les_affaires_touchees_la_veille(plan):
    w.semer_une_journee_d_affaires(plan)
    lundi = _lister(LUNDI)
    assert lundi["a_consolider"] == TOUCHEES and lundi["touchees"] == 3 and lundi["reste"] == 0
    # L'affaire touchée la veille de la veille n'est pas désignée pour lundi ; elle l'est pour son propre jour.
    assert "aff-veille" not in lundi["a_consolider"]
    assert _lister("2026-11-08")["a_consolider"] == ["aff-veille"]
    assert _lister("2026-11-07")["a_consolider"] == [] and _lister("2026-11-07")["touchees"] == 0
    # Un identifiant d'affaire forgé dans un événement (hors de la forme fermée) n'est JAMAIS désigné : il est compté.
    assert lundi["affaires_refusees"] == 1 and "forge x;DROP" not in json.dumps(lundi)
    # La borne et le tri : deux lectures du même état donnent la même liste ; `reste` dit le surplus, sans rien perdre.
    page = _lister(LUNDI, 2)
    assert page["a_consolider"] == TOUCHEES[:2] and page["reste"] == 1
    assert _lister(LUNDI) == _lister(LUNDI)
    # Le critère est EXACTEMENT celui de la consolidation : ce qui est désigné écrit un maillon, le reste n'écrit rien.
    consolider = _outil("m10_consolider_affaire")
    with stockage.transaction():
        for affaire in TOUCHEES:
            assert consolider(affaire, LUNDI, "2026-11-10T03:00:00-05:00")["ecrit"] is True
        assert consolider("aff-veille", LUNDI, "2026-11-10T03:00:00-05:00")["ecrit"] is False  # rien ce jour-là
    assert _lister(LUNDI)["a_consolider"] == [] and _lister(LUNDI)["deja_consolidees"] == 3


def test_rien_ne_tourne_par_defaut(plan):
    w.semer_une_journee_d_affaires(plan)
    resume = w.tour(plan, w.local(MARDI, "03:00"))
    assert {resume[n]["statut"] for n in w.ROUTINES_M10} == {"inactif"}
    assert w.faits_consolides() == [] and w.rapports_m10() == []


def test_la_nuit_consolide_les_affaires_touchees_et_le_resultat_se_consulte(plan):
    w.semer_une_journee_d_affaires(plan)
    w.activer(plan, w.ROUTINES_M10)
    # Avant 3 h (cron « 0 3 * * * » de la planification suivie) : rien.
    w.tour(plan, w.local(MARDI, "02:50"))
    assert w.tour(plan, w.local(MARDI, "02:58"))[CONSOLIDATION]["statut"] == "pas_echu"
    assert w.faits_consolides() == []
    # Le sondage de 15 min passe à 3 h 05, la première fois que l'heure déclarée est atteinte : les trois affaires
    # touchées la
    # veille sont consolidées, chacune sous son bail ; la ressource du journal est une empreinte, jamais l'identifiant.
    resume = w.tour(plan, w.local(MARDI, "03:05"))
    assert resume[CONSOLIDATION]["statut"] == "ok" and resume[CONSOLIDATION]["ressources"] == 3
    assert resume[CONSOLIDATION]["affaires"] == 3
    assert _faits() == [("aff-chantier", LUNDI), ("aff-devis", LUNDI), ("aff-lead", LUNDI)]
    chantier = next(f for f in w.faits_consolides() if f["affaire_id"] == "aff-chantier")
    assert chantier["resume"] == "1 travaux terminés, 1 rentabilité(s) de chantier" and len(chantier["sources"]) == 2
    assert all(s["registre"] == "evenements" and s["ligne_id"] for f in w.faits_consolides() for s in f["sources"])
    # Les sondages suivants ne font rien (plus rien à consolider) ; le journal ne porte aucun identifiant d'affaire.
    for heure in ("03:20", "03:35", "11:00"):
        assert w.tour(plan, w.local(MARDI, heure))[CONSOLIDATION].get("ressources", 0) == 0
    assert len(w.faits_consolides()) == 3
    texte = json.dumps(w.journal(CONSOLIDATION), ensure_ascii=False)
    assert not any(a in texte for a in (*TOUCHEES, "forge", "aff-veille", "wct-"))
    # Consultable : par l'outil de lecture, et par les paquets de contexte existants (un fait durable qui cite ses
    # sources).
    with stockage.transaction():
        lecture = _outil("m10_lire_rapports_routine")("consolidation", 3)["resultat"]
        paquet = _outil("m10_paquet_contexte_affaire")("aff-chantier", "2026-11-10T09:00:00-05:00")
    assert lecture["jours"] == [{"jour": LUNDI, "faits": 3, "affaires": 3}]
    assert "1 travaux terminés" in json.dumps(paquet, ensure_ascii=False)


def test_redemarrage_ou_deuxieme_instance_ne_double_rien_et_un_evenement_tardif_est_repris(plan):
    w.semer_une_journee_d_affaires(plan)
    w.activer(plan, w.ROUTINES_M10)
    w.tour(plan, w.local(MARDI, "03:05"))
    avant = list(w.faits_consolides())
    # La réservation du créneau est perdue : chaque routine est de nouveau due, au même instant.
    w.rembobiner(plan, w.ROUTINES_M10)
    resume = w.tour(plan, w.local(MARDI, "03:05"))
    assert resume[CONSOLIDATION].get("ressources", 0) == 0 and w.faits_consolides() == avant
    # Un événement arrivé TARD pour la veille (livré après la consolidation) : le sondage suivant le reprend, en
    # AJOUTANT un
    # fait qui cite toutes les sources (jamais en réécrivant l'ancien) — et seulement cette affaire.
    import interconnexion_charges as ch

    w.publier(
        "m2.client_associe",
        "m02-revenue-crm",
        ch.client_associe("aff-lead", horodatage_association="2026-11-09T22:00:00-05:00"),
    )
    w.repartir(plan)
    resume = w.tour(plan, w.local(MARDI, "03:30"))
    assert resume[CONSOLIDATION]["affaires"] == 1
    apres = w.faits_consolides()
    assert len(apres) == 4 and apres[:3] == avant  # les trois premiers maillons sont intacts (append-only)
    nouveau = apres[3]
    assert nouveau["affaire_id"] == "aff-lead" and len(nouveau["sources"]) == 2
    w.tour(plan, w.local(MARDI, "03:45"))
    assert len(w.faits_consolides()) == 4


def test_la_panne_d_une_affaire_n_arrete_pas_les_autres_ni_les_autres_routines(plan, monkeypatch):
    from m10_memoire import outils as m10

    original = m10.consolider_affaire

    def en_panne(affaire_id, jour, horodatage):
        if affaire_id == "aff-devis":
            raise RuntimeError("panne simulée")
        return original(affaire_id, jour, horodatage)

    monkeypatch.setattr(m10, "consolider_affaire", en_panne)
    w.semer_une_journee_d_affaires(plan)
    w.activer(plan, w.ROUTINES_M10)
    resume = w.tour(plan, w.local(MARDI, "04:50"))  # après 3 h et après 4 h 45 : consolidation ET KPI sont dus
    assert resume[CONSOLIDATION]["statut"] == "erreur" and resume[CONSOLIDATION]["erreurs"] == 1
    assert resume[CONSOLIDATION]["affaires"] == 2
    assert resume[KPIS]["statut"] == "ok"  # une autre routine du même tour n'est pas arrêtée
    assert _faits() == [("aff-chantier", LUNDI), ("aff-lead", LUNDI)]
    monkeypatch.setattr(m10, "consolider_affaire", original)
    resume = w.tour(plan, w.local(MARDI, "05:10"))  # le sondage suivant reprend l'affaire restante, et elle seule
    assert resume[CONSOLIDATION]["affaires"] == 1 and resume[CONSOLIDATION]["statut"] == "ok"
    assert _faits() == [("aff-chantier", LUNDI), ("aff-devis", LUNDI), ("aff-lead", LUNDI)]


def test_l_ombre_dit_ce_qu_elle_ferait_sans_rien_ecrire(plan):
    w.semer_une_journee_d_affaires(plan)
    w.activer(plan, w.ROUTINES_M10, mode="ombre")
    avant = (w.affaires_m10(), w.rapports_m10())
    for heure in ("03:05", "03:20", "04:50", "05:10"):
        resume = w.tour(plan, w.local(MARDI, heure))
        assert {v["statut"] for n, v in resume.items() if n in w.ROUTINES_M10} <= {"ombre", "pas_echu"}
    assert (w.affaires_m10(), w.rapports_m10()) == avant  # l'ombre n'a rien écrit
    aurait = [x for x in w.journal() if x["executeur"] == CONSOLIDATION and x["evenement"] == "aurait"]
    assert len(aurait) == 3 and all(
        x["mode"] == "ombre" and x["details"] == {"aurait": 1} for x in aurait
    )  # une fois chacune
    # Passer à l'actif le même jour : les « aurait » d'ombre n'empêchent rien.
    w.activer(plan, w.ROUTINES_M10, mode="actif")
    assert w.tour(plan, w.local(MARDI, "05:20"))[CONSOLIDATION]["affaires"] == 3


def _rapports(genre):
    return [r for r in w.rapports_m10() if r["genre"] == genre]


def _oubli_injecte():
    """Un chantier terminé que le bus dit avoir livré à M10 (reçu « traité ») mais qui n'a AUCUNE trace au registre :
    l'oubli que l'audit doit trouver (le reçu est écrit à la main, comme le ferait un accusé de réception perdu)."""
    import interconnexion_charges as ch

    ident = w.publier(
        "m4.travaux_termines",
        "m04-field-ops",
        ch.travaux_termines(
            "wct-perdu",
            "devis-perdu",
            lead_id="aff-perdu",
            horodatage_completion="2026-11-11T10:00:00-05:00",
            consommateurs_cibles=["M10"],
        ),
    )
    with stockage.transaction() as cnx:
        cnx.execute(
            insert(EVENEMENTS_RECUS).values(
                evenement_id=ident, consommateur="m10-memoire", statut="traite", tentatives=1, resultat="{}"
            )
        )
    return ident


def test_l_audit_hebdomadaire_trouve_un_oubli_injecte_et_les_jours_non_consolides(plan):
    import interconnexion_charges as ch

    w.semer_une_journee_d_affaires(plan)
    w.activer(plan, w.ROUTINES_M10)
    w.tour(plan, w.local(MARDI, "03:05"))  # la nuit du lundi au mardi est consolidée
    _oubli_injecte()
    # Un lead du jeudi 12 que personne n'a consolidé (le serveur a été arrêté de mardi à lundi : pas de rattrapage).
    w.publier(
        "m1.lead_qualifie", "m01-front-office", ch.lead_qualifie_m1("aff-jeudi", horodatage="2026-11-12T08:00:00-05:00")
    )
    w.repartir(plan)
    # Le lundi suivant, avant 4 h 30 : rien ; au sondage de 4 h 35 : l'audit, une seule fois.
    assert w.tour(plan, w.local("2026-11-16", "04:20"))[AUDIT]["statut"] in ("ok", "pas_echu")
    assert _rapports("audit_non_oubli") == []
    resume = w.tour(plan, w.local("2026-11-16", "04:35"))
    assert resume[AUDIT]["rapports"] == 1 and resume[AUDIT]["oublis"] == 1
    w.tour(plan, w.local("2026-11-16", "04:50"))
    w.tour(plan, w.local("2026-11-16", "18:00"))
    (rapport,) = _rapports("audit_non_oubli")
    contenu = rapport["contenu"]
    assert contenu["nb_oublis"] == 1 and contenu["oublis"] == [
        {"type_evenement": "m4.travaux_termines", "identifiant": "wct-perdu", "verdict": "REJ-AUDIT-TRACE-ABSENTE"}
    ]
    questions = {q["id"]: q for q in contenu["questions"]}
    # Chaque question a son compte ; aucun score opaque.
    assert questions["trace_des_evenements_livres"]["denominateur"] > 1
    assert (
        questions["trace_des_evenements_livres"]["numerateur"]
        == questions["trace_des_evenements_livres"]["denominateur"] - 1
    )
    assert questions["trace_des_evenements_livres"]["reponse"] is False
    assert questions["chaines_intactes"]["reponse"] is True
    jours = questions["jours_consolides"]
    assert (jours["numerateur"], jours["denominateur"], jours["plus_ancien_non_consolide"]) == (3, 4, "2026-11-12")
    assert questions["revisions_en_attente"]["valeur"] == 0
    assert questions["fraicheur_memoire"]["heures"] is not None
    assert contenu["livraison"]["en_echec"] == 0 and contenu["livraison"]["quarantaine"] == 0
    # Rejouer le même rapport (deuxième instance, redémarrage) n'ajoute rien ; il est consultable.
    w.rembobiner(plan, (AUDIT,))
    w.tour(plan, w.local("2026-11-16", "18:00"))
    assert len(_rapports("audit_non_oubli")) == 1
    with stockage.transaction():
        lu = _outil("m10_lire_rapports_routine")("audit_non_oubli", 1)["resultat"]
    assert lu["rapports"][0]["contenu"]["nb_oublis"] == 1 and lu["rapports"][0]["fin"] == rapport["fin"]


def test_un_evenement_en_attente_de_livraison_ou_en_quarantaine_n_est_pas_un_oubli_mais_est_dit(plan):
    import interconnexion_charges as ch

    w.semer_une_journee_d_affaires(plan)
    # Publié mais jamais livré : en attente, ni oubli ni trace attendue.
    w.publier(
        "m4.travaux_termines",
        "m04-field-ops",
        ch.travaux_termines(
            "wct-en-route",
            "devis-en-route",
            lead_id="aff-route",
            horodatage_completion="2026-11-11T10:00:00-05:00",
            consommateurs_cibles=["M10"],
        ),
    )
    w.activer(plan, w.ROUTINES_M10)
    w.tour(plan, w.local("2026-11-16", "04:35"))
    (rapport,) = _rapports("audit_non_oubli")
    assert rapport["contenu"]["nb_oublis"] == 0 and rapport["contenu"]["livraison"]["en_attente"] == 1
    assert {q["id"]: q for q in rapport["contenu"]["questions"]}["trace_des_evenements_livres"]["reponse"] is True


def test_les_kpi_sont_calcules_ou_dits_non_calculables(plan):
    w.semer_une_journee_d_affaires(plan)
    w.activer(plan, w.ROUTINES_M10)
    w.tour(plan, w.local(MARDI, "03:05"))
    resume = w.tour(plan, w.local(MARDI, "04:50"))
    assert resume[KPIS]["rapports"] == 1
    (rapport,) = _rapports("kpis")
    kpis = rapport["contenu"]["kpis"]
    import yaml
    from m10_memoire import routines

    manifeste = yaml.safe_load((w.RACINE / "departments/m10-memoire/department.yaml").read_text(encoding="utf-8"))
    assert set(kpis) == {k["id"] for k in manifeste["kpis"]} == set(routines.kpi_ids())  # exactement ceux du manifeste
    assert kpis["nb_affaires_consolidees_jour"] == {"calculable": True, "valeur": 3, "jour": MARDI}
    for kpi in (
        "taux_revisions_arbitrees",
        "taux_preflight_insuffisant",
        "nb_references_forgees_detectees",
        "nb_oublis_detectes_audit",
    ):
        assert kpis[kpi]["calculable"] is False and kpis[kpi]["manque"], kpi  # jamais zéro, jamais cent
        assert "valeur" not in kpis[kpi] and "valeur_pct" not in kpis[kpi]
    assert kpis["taux_preflight_insuffisant"]["refus_traces"] == 0
    # Un audit existe : le KPI « oublis » devient calculable ; une révision signalée puis arbitrée donne un taux avec
    # ses comptes.
    w.tour(plan, w.local("2026-11-16", "04:35"))
    from m10_memoire import outils as m10
    from m10_memoire import revision

    with stockage.transaction():
        lignes = [m["ligne_id"] for m in w.faits_consolides()[:2]]
        signal, _ = revision.signaler_revision(
            m10._REGISTRE_AFFAIRES, lignes[0], lignes[1], "2026-11-16T05:00:00-05:00"
        )
        autre, _ = revision.signaler_revision(m10._REGISTRE_AFFAIRES, lignes[1], lignes[0], "2026-11-16T05:01:00-05:00")
        revision.arbitrer_revision(
            m10._REGISTRE_AFFAIRES, signal["ligne_id"], "distincts_confirmes", "2026-11-16T05:02:00-05:00"
        )
        assert autre is not None
    w.tour(plan, w.local("2026-11-16", "04:50"))
    kpis = _rapports("kpis")[-1]["contenu"]["kpis"]
    assert kpis["nb_oublis_detectes_audit"] == {
        "calculable": True,
        "valeur": 0,
        "audit_du": kpis["nb_oublis_detectes_audit"]["audit_du"],
    }
    assert kpis["taux_revisions_arbitrees"] == {
        "calculable": True,
        "valeur_pct": 50.0,
        "numerateur": 1,
        "denominateur": 2,
    }
    assert kpis["nb_affaires_consolidees_jour"]["valeur"] == 0  # rien n'a été consolidé ce jour-là : un vrai zéro


def test_rien_de_personnel_dans_les_journaux_et_les_rapports_de_m10(plan):
    w.semer_une_journee_d_affaires(plan)
    w.activer(plan, w.ROUTINES_M10)
    for instant in (w.local(MARDI, "03:05"), w.local(MARDI, "04:50"), w.local("2026-11-16", "04:35")):
        w.tour(plan, instant)
    with stockage.transaction() as cnx:
        journal = json.dumps(
            [dict(r) for r in cnx.execute(select(PLANIFICATEUR_JOURNAL)).mappings()], ensure_ascii=False
        )
    rapports = json.dumps(w.rapports_m10(), ensure_ascii=False)
    for personnel in (*w.PERSONNEL, "Jeanne", "jeanne.fictive", "514-555", "Québec"):
        assert personnel not in journal and personnel not in rapports, personnel
    assert "aff-lead" not in journal  # le journal du planificateur ne porte aucun identifiant d'affaire


def test_rien_d_externe_ne_part_depuis_m10(plan):
    w.semer_une_journee_d_affaires(plan)
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id)).all()
    w.activer(plan, w.ROUTINES_M10)
    for instant in (w.local(MARDI, "03:05"), w.local(MARDI, "04:50"), w.local("2026-11-16", "04:35")):
        w.tour(plan, instant)
    with stockage.transaction() as cnx:
        assert (
            cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id)).all() == avant
        )  # aucun événement publié par les routines
    assert plan.ports.service_courriel is None and plan.ports.client_wordpress is None


def test_une_affaire_en_echec_reste_eligible_apres_le_changement_de_jour(plan, monkeypatch):
    import interconnexion_charges as ch
    from m10_memoire import outils as m10

    w.publier(
        "m1.lead_qualifie",
        "m01-front-office",
        ch.lead_qualifie_m1("aff-ancienne", horodatage="2026-11-09T14:00:00-05:00"),
    )
    w.repartir(plan)
    original = m10.consolider_affaire
    w.activer(plan, (CONSOLIDATION,))

    def echec(affaire_id, jour, horodatage):
        raise RuntimeError("panne fictive au premier jour")

    with monkeypatch.context() as panne:
        panne.setattr(m10, "consolider_affaire", echec)
        premier = w.tour(plan, w.local(MARDI, "03:05"))[CONSOLIDATION]
    assert premier["statut"] == "erreur" and premier["erreurs"] == 1
    assert _faits() == []

    monkeypatch.setattr(m10, "consolider_affaire", original)
    reprise = w.tour(plan, w.local("2026-11-11", "03:05"))[CONSOLIDATION]
    assert reprise["affaires"] == 1 and reprise["statut"] == "ok"
    assert ("aff-ancienne", LUNDI) in _faits()


def test_un_backlog_ancien_en_echec_ne_bloque_pas_la_veille(plan, monkeypatch):
    import interconnexion_charges as ch
    from m10_memoire import outils as m10

    for i in range(51):
        w.publier(
            "m1.lead_qualifie",
            "m01-front-office",
            ch.lead_qualifie_m1(f"aff-ancienne-{i:03}", horodatage="2026-11-09T14:00:00-05:00"),
        )
    w.repartir(plan, passes=100)
    original = m10.consolider_affaire
    w.activer(plan, (CONSOLIDATION,))

    def seul_nouveau_reussit(affaire_id, jour, horodatage):
        if affaire_id != "aff-nouvelle-veille":
            raise RuntimeError("panne fictive persistante sur l'ancien jour")
        return original(affaire_id, jour, horodatage)

    monkeypatch.setattr(m10, "consolider_affaire", seul_nouveau_reussit)
    premier = w.tour(plan, w.local(MARDI, "03:05"))[CONSOLIDATION]
    assert premier["ressources"] == 50 and premier["erreurs"] == 50

    w.publier(
        "m1.lead_qualifie",
        "m01-front-office",
        ch.lead_qualifie_m1("aff-nouvelle-veille", horodatage="2026-11-10T14:00:00-05:00"),
    )
    w.repartir(plan, passes=100)
    reprise = w.tour(plan, w.local("2026-11-11", "03:05"))[CONSOLIDATION]
    assert reprise["ressources"] == 50 and reprise["erreurs"] == 49
    assert reprise["affaires"] == 1 and reprise["statut"] == "erreur"
    assert ("aff-nouvelle-veille", MARDI) in _faits()

    curseurs = [e for e in w.journal(CONSOLIDATION) if e["evenement"] == "curseur"]
    ressources = {e["ressource"] for e in curseurs}
    assert {f"{LUNDI}|rotation", f"{MARDI}|rotation", "arriere|rotation"} <= ressources


def test_un_jour_entierement_manque_sans_marqueur_n_est_pas_rattrape(plan):
    import interconnexion_charges as ch

    w.publier(
        "m1.lead_qualifie",
        "m01-front-office",
        ch.lead_qualifie_m1("aff-jour-manque", horodatage="2026-11-09T14:00:00-05:00"),
    )
    w.repartir(plan, passes=100)
    w.activer(plan, (CONSOLIDATION,))
    # Aucun passage ne fonctionne le mardi : le mercredi, la routine ne prend que la veille (mardi), sans deviner
    # qu'elle devrait balayer le lundi non engagé.
    reprise = w.tour(plan, w.local("2026-11-11", "03:05"))[CONSOLIDATION]
    assert reprise["ressources"] == 0 and _faits() == []


def test_une_source_tardive_repend_un_jour_deja_marque_et_consolide(plan):
    import interconnexion_charges as ch

    w.publier(
        "m1.lead_qualifie",
        "m01-front-office",
        ch.lead_qualifie_m1("aff-source-tardive", horodatage="2026-11-09T14:00:00-05:00"),
    )
    w.repartir(plan, passes=100)
    w.activer(plan, (CONSOLIDATION,))
    premier = w.tour(plan, w.local(MARDI, "03:05"))[CONSOLIDATION]
    assert premier["affaires"] == 1 and ("aff-source-tardive", LUNDI) in _faits()

    w.publier(
        "m2.client_associe",
        "m02-revenue-crm",
        ch.client_associe("aff-source-tardive", horodatage_association="2026-11-09T22:00:00-05:00"),
    )
    w.repartir(plan, passes=100)
    reprise = w.tour(plan, w.local("2026-11-11", "03:05"))[CONSOLIDATION]
    assert reprise["affaires"] == 1 and reprise["statut"] == "ok"
    faits = [f for f in w.faits_consolides() if f["affaire_id"] == "aff-source-tardive"]
    assert sorted(len(f["sources"]) for f in faits) == [1, 2]
    marqueurs = [
        e for e in w.journal(CONSOLIDATION) if e["evenement"] == "curseur" and e["ressource"] == f"{LUNDI}|rotation"
    ]
    assert len(marqueurs) == 1


def test_un_curseur_ombre_ne_declenche_pas_un_rattrapage_actif(plan):
    import interconnexion_charges as ch

    w.publier(
        "m1.lead_qualifie",
        "m01-front-office",
        ch.lead_qualifie_m1("aff-ombre-seule", horodatage="2026-11-09T14:00:00-05:00"),
    )
    w.repartir(plan, passes=100)
    w.activer(plan, (CONSOLIDATION,), mode="ombre")
    w.tour(plan, w.local(MARDI, "03:05"))
    assert _faits() == []

    w.activer(plan, (CONSOLIDATION,), mode="actif")
    actif = w.tour(plan, w.local("2026-11-11", "03:05"))[CONSOLIDATION]
    assert actif["ressources"] == 0 and _faits() == []


def test_l_ombre_de_l_audit_et_des_kpi_calcule_a_blanc_sans_ecrire_puis_l_actif_ecrit(plan):
    w.semer_une_journee_d_affaires(plan)
    w.activer(plan, w.ROUTINES_M10, mode="ombre")
    for heure in ("04:35", "04:50", "05:10"):
        w.tour(plan, w.local("2026-11-16", heure))
    assert w.rapports_m10() == []  # l'ombre n'écrit aucun rapport
    ombres = [x for x in w.journal() if x["evenement"] == "aurait" and x["executeur"] in (AUDIT, KPIS)]
    assert sorted(x["executeur"] for x in ombres) == [AUDIT, KPIS] and all(x["mode"] == "ombre" for x in ombres)
    assert next(x for x in ombres if x["executeur"] == AUDIT)["details"] == {"aurait": 1, "oublis": 0}
    assert next(x for x in ombres if x["executeur"] == KPIS)["details"]["aurait"] == 1
    w.activer(plan, w.ROUTINES_M10, mode="actif")
    resume = w.tour(plan, w.local("2026-11-16", "05:20"))
    assert resume[AUDIT]["rapports"] == 1 and resume[KPIS]["rapports"] == 1
    assert sorted(r["genre"] for r in w.rapports_m10()) == ["audit_non_oubli", "kpis"]


def test_la_rotation_fait_avancer_la_51e_affaire_malgre_50_echecs_repetes(plan, monkeypatch):
    import interconnexion_charges as ch
    from m10_memoire import outils as m10

    for i in range(51):
        affaire = f"aff-{i:03}"
        w.publier(
            "m1.lead_qualifie",
            "m01-front-office",
            ch.lead_qualifie_m1(affaire, horodatage="2026-11-09T14:00:00-05:00"),
        )
    w.repartir(plan, passes=100)
    original = m10.consolider_affaire
    essais_51 = []

    def echec_des_cinquante_premieres(affaire_id, jour, horodatage):
        if affaire_id != "aff-050":
            raise RuntimeError("panne fictive persistante")
        essais_51.append(affaire_id)
        return original(affaire_id, jour, horodatage)

    monkeypatch.setattr(m10, "consolider_affaire", echec_des_cinquante_premieres)
    w.activer(plan, (CONSOLIDATION,))
    premiere = w.tour(plan, w.local(MARDI, "03:05"))[CONSOLIDATION]
    assert premiere["ressources"] == 50 and premiere["erreurs"] == 50
    assert premiere["statut"] == "erreur" and essais_51 == []

    seconde = w.tour(plan, w.local(MARDI, "03:20"))[CONSOLIDATION]
    assert seconde["ressources"] == 50 and seconde["erreurs"] == 49
    assert seconde["statut"] == "erreur" and essais_51 == ["aff-050"]
    assert ("aff-050", LUNDI) in _faits()

    # Le nouveau passage reconstruit l'exécuteur et relit le curseur append-only. La liste pendante est passée de 51
    # à 50 ; l'offset 49 est normalisé sur cette liste raccourcie et la consolidation de la 51e reste idempotente.
    troisieme = w.tour(plan, w.local(MARDI, "03:35"))[CONSOLIDATION]
    assert troisieme["ressources"] == 50 and troisieme["erreurs"] == 50
    assert essais_51 == ["aff-050"] and _faits().count(("aff-050", LUNDI)) == 1

    curseurs = [
        e
        for e in w.journal(CONSOLIDATION)
        if e["evenement"] == "curseur" and e["ressource"] == "arriere|rotation"
    ]
    assert len(curseurs) == 3 and all(e["details"]["ressources"] <= 50 for e in curseurs)
    texte = json.dumps(w.journal(CONSOLIDATION), ensure_ascii=False)
    assert not any(f"aff-{i:03}" in texte for i in range(51))


def test_ombre_utilise_un_curseur_distinct_et_ne_consolide_rien(plan, monkeypatch):
    import interconnexion_charges as ch
    from m10_memoire import outils as m10

    for i in range(51):
        w.publier(
            "m1.lead_qualifie",
            "m01-front-office",
            ch.lead_qualifie_m1(f"aff-{i:03}", horodatage="2026-11-09T14:00:00-05:00"),
        )
    w.repartir(plan, passes=100)
    original = m10.consolider_affaire
    essais_actifs = []

    def suivie_active(affaire_id, jour, horodatage):
        if affaire_id != "aff-050":
            raise RuntimeError("panne fictive persistante")
        essais_actifs.append(affaire_id)
        return original(affaire_id, jour, horodatage)

    monkeypatch.setattr(m10, "consolider_affaire", suivie_active)
    w.activer(plan, (CONSOLIDATION,), mode="ombre")
    premiere = w.tour(plan, w.local(MARDI, "03:05"))[CONSOLIDATION]
    assert premiere["ressources"] == 50 and premiere["statut"] == "ombre"
    seconde = w.tour(plan, w.local(MARDI, "03:20"))[CONSOLIDATION]
    assert seconde["ressources"] == 1 and seconde["statut"] == "ombre"
    assert _faits() == [] and essais_actifs == []

    # Une source tardive peut s'insérer hors de la page courante déjà constatée : même un passage à vide doit
    # avancer le curseur pour que l'ombre finisse par l'observer, sans consolider l'affaire.
    w.publier(
        "m1.lead_qualifie",
        "m01-front-office",
        ch.lead_qualifie_m1("aff-047a", horodatage="2026-11-09T14:00:00-05:00"),
    )
    w.repartir(plan, passes=100)
    passage_vide = w.tour(plan, w.local(MARDI, "03:35"))[CONSOLIDATION]
    assert passage_vide["ressources"] == 0 and passage_vide["statut"] == "ombre"
    passage_tardif = w.tour(plan, w.local(MARDI, "03:50"))[CONSOLIDATION]
    assert passage_tardif["ressources"] == 1 and passage_tardif["statut"] == "ombre"
    assert _faits() == [] and essais_actifs == []

    # Le mode actif repart sur son propre curseur 0; les 50 « auraient » ne sont ni des succès ni des échecs actifs.
    w.activer(plan, (CONSOLIDATION,), mode="actif")
    active = w.tour(plan, w.local(MARDI, "04:05"))[CONSOLIDATION]
    assert active["ressources"] == 50 and active["erreurs"] == 50 and essais_actifs == []


def test_un_arret_apres_l_avancement_du_curseur_reprend_au_passage_suivant(plan, monkeypatch):
    import interconnexion_charges as ch

    from opsys.connecteurs_planification.exec_m10 import ConsolidationAffaires
    from opsys.connecteurs_planification.planificateur import RefusExecuteur

    for i in range(51):
        w.publier(
            "m1.lead_qualifie",
            "m01-front-office",
            ch.lead_qualifie_m1(f"aff-{i:03}", horodatage="2026-11-09T14:00:00-05:00"),
        )
    w.repartir(plan, passes=100)
    w.activer(plan, (CONSOLIDATION,))

    def panne_immediatement_apres_selection(self, ressource, ctx, bail):
        raise RefusExecuteur("REJ-PLAN-CRASH-FICTIF")

    with monkeypatch.context() as panne:
        panne.setattr(ConsolidationAffaires, "traiter", panne_immediatement_apres_selection)
        interruption = w.tour(plan, w.local(MARDI, "03:05"))[CONSOLIDATION]
    assert interruption["ressources"] == 50 and interruption["erreurs"] == 50
    assert interruption["statut"] == "erreur"
    assert _faits() == []

    reprise = w.tour(plan, w.local(MARDI, "03:20"))[CONSOLIDATION]
    assert reprise["ressources"] == 50 and reprise["statut"] == "ok"
    assert reprise["affaires"] == 50 and ("aff-050", LUNDI) in _faits()
