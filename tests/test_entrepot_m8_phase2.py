"""Entrepôt de M8, PHASE 2 (D1 à D3, D5, D6, D7) : sept départements publient un RÉSUMÉ agrégé, M8 le consomme, de bout
en bout.

Sur le VRAI bus et les `consommateurs()` réels de M8, M9 et M10 : M5 (dépense publicitaire comptabilisée, factures
émises),
M7 (valeurs de signaux, relevés de dépense), M4 (capacité d'équipe), M2 (pipeline, leads avec leur source UTM), M6
(disponibilité du matériel) et M1 (plaintes) publient des événements du catalogue ; le propriétaire déclare ses canaux
publicitaires ; M8 les range, bâtit l'entrepôt, puis le chiffre se lit par le moteur, les wallboards, le copilote et la
mémoire de M10. Aucun département ne lit un autre : M8 n'appelle aucun outil de ses sources.

Ce que ce fichier prouve en plus des cinq garanties de `test_entrepot_m8_garanties.py` : la valeur exacte de chaque
mesure
depuis l'événement ; le coût par lead n'existe qu'avec la correspondance déclarée par le propriétaire ; une panne de M8
qui
fait arriver une VERSION PLUS ANCIENNE après une plus récente ne la remplace pas (`publie_le`) ; un rejeu complet sous
d'autres
identifiants ne change rien ; la cadence de la source (D7) élargit la fenêtre de fraîcheur de la capacité hebdomadaire
sans
rendre les autres mesures indulgentes. Données fictives.
"""

from __future__ import annotations

import json

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m8_analytics import entrepot_stockage

from opsys import evenements, stockage, taxonomie
from opsys.capacites import Capacites

FICTIF = True
M1, M2, M4, M5, M6, M7, M8, M9, M10 = (
    "m01-front-office",
    "m02-revenue-crm",
    "m04-field-ops",
    "m05-financecore",
    "m06-material-control",
    "m07-marketing",
    "m08-analytics",
    "m09-strategic-intelligence",
    "m10-memoire",
)
MAINTENANT = "2026-10-30T18:00:00-04:00"
JOUR = "2026-10-30"
CONSTATE = "2026-10-30T07:00:00-04:00"
PERSONNEL = (
    "Jeanne",
    "jeanne.fictive",
    "example.test",
    "514-555",
    "fournisseur-fictif",
    "chantier-fictif",
    "client-fictif",
)


class _Restreint:
    """M10 réel, abonné au seul `m8.fait_consolide` (ses autres consommateurs supposent M4 et M5 réels)."""

    def __init__(self, departement, types):
        self._departement, self._types = departement, types

    def __getattr__(self, nom):
        return getattr(self._departement, nom)

    @property
    def evenements_consomme(self):
        return tuple(t for t in self._departement.evenements_consomme if t in self._types)

    def charger_consommateurs(self):
        return {t: f for t, f in self._departement.charger_consommateurs().items() if t in self._types}


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M8, M9, M10))
    m.surveiller(monkeypatch)
    m.departements[M10] = _Restreint(m.departements[M10], {"m8.fait_consolide"})
    yield m
    im.demonter()


def _declarer_canaux():
    taxonomie.enregistrer_canaux_marketing({"google_ads": ["google", "google-ads"], "meta": ["facebook"]})


def _scenario(suffixe: str = "") -> list[tuple[str, str, dict, str]]:
    ev: list[tuple[str, str, dict, str]] = []

    def pub(producteur, type_, charge, nom):
        ev.append((producteur, type_, charge, f"{nom}{suffixe}"))

    for rang, source in ((1, "google"), (2, "facebook"), (3, "google-ads"), (4, None)):
        extra = {"utm": {"utm_source": source}} if source else {}
        pub(M2, "m2.client_associe", ch.client_associe(lead_id=f"lead-{rang}", **extra), f"m2-lead{rang}")
    pub(
        M7,
        "m7.depenses_marketing_constatees",
        ch.depense_marketing("g-27", jour="2026-10-27", montant="125.40"),
        "m7-g27",
    )
    pub(
        M7,
        "m7.depenses_marketing_constatees",
        ch.depense_marketing("g-28", jour="2026-10-28", montant="100.00"),
        "m7-g28",
    )
    pub(
        M7,
        "m7.depenses_marketing_constatees",
        ch.depense_marketing("m-28", jour="2026-10-28", montant="50.00", canal="meta"),
        "m7-m28",
    )
    pub(
        M5,
        "m5.depense_publicitaire_constatee",
        ch.depense_comptabilisee(
            1, "2026-10-27", "2026-10-28", "200.00", brouillons_en_attente=1, brouillons_en_attente_cad="75.40"
        ),
        "m5-dep",
    )
    pub(M5, "m5.facture_emise_constatee", ch.facture_emise("facture-1", "ENVOYEE", "10000.00"), "m5-f1e")
    pub(M5, "m5.facture_emise_constatee", ch.facture_emise("facture-1", "PAYEE", "10000.00"), "m5-f1p")
    pub(M5, "m5.facture_emise_constatee", ch.facture_emise("facture-2", "ENVOYEE", "2500.00"), "m5-f2")
    pub(M5, "m5.facture_emise_constatee", ch.facture_emise("facture-3", "ENVOYEE", "800.00"), "m5-f3e")
    pub(M5, "m5.facture_emise_constatee", ch.facture_emise("facture-3", "ANNULEE", "800.00"), "m5-f3a")
    pub(M7, "m7.performance_signaux_constatee", ch.performance_signaux("search_console", clics="120"), "m7-sc")
    pub(
        M7,
        "m7.performance_signaux_constatee",
        ch.performance_signaux("bing_webmaster", "e" * 16, clics="15", impressions="600"),
        "m7-bing",
    )
    pub(
        M7,
        "m7.performance_signaux_constatee",
        ch.performance_signaux(
            "umami", "f" * 16, clics=None, impressions=None, visites="410", jours_couverts=6, fraicheur_fenetre_h=24
        ),
        "m7-umami",
    )
    pub(M4, "m4.capacite_equipe_constatee", ch.capacite_equipe(), "m4-cap")
    pub(M2, "m2.pipeline_constate", ch.pipeline_constate(), "m2-pipe")
    pub(M6, "m6.disponibilite_constatee", ch.disponibilite_constatee(), "m6-dispo")
    pub(M1, "m1.plaintes_constatees", ch.plaintes_constatees(), "m1-plaintes")
    return ev


def _publier(evs):
    for producteur, type_, charge, ident in evs:
        evenements.publier(type_, producteur, charge, evenement_id=ident)


def _m8(monde, outil, **arguments):
    reponse = Capacites(monde.departements, stockage.transaction, filtre={M8}, memoire=False).appeler(outil, arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _pages(monde, outil, cle, **arguments):
    depart, lignes = 0, []
    while depart is not None:
        page = _m8(monde, outil, depart=depart, **arguments)
        lignes += page[cle]
        depart = page["prochain_depart"]
    return lignes


def _mesures(monde, maintenant=MAINTENANT):
    return {m["metric_id"]: m for m in _pages(monde, "m8_lire_mesures", "mesures", maintenant=maintenant)}


def _tuiles(monde, wallboard_id):
    return {
        t["id"]: t
        for t in _pages(monde, "m8_lire_wallboard", "tuiles", maintenant=MAINTENANT, wallboard_id=wallboard_id)
    }


ATTENDU = {
    "m8_depense_pub_comptabilisee_cad": "200.00",
    "m8_ecart_depense_pub_comptabilisee_cad": "75.40",  # relevés 275,40 $ moins 200,00 $ : le brouillon en attente
    "m8_factures_emises": "2",
    "m8_facturation_emise_cad": "12500.00",
    "m8_clics_recherche": "135",
    "m8_impressions_recherche": "4900",
    "m8_visites_site": "410",
    "m8_capacite_heures_disponibles": "80.00",
    "m8_capacite_heures_planifiees": "62.00",
    "m8_charge_planifiee_pct": "77.50",
    "m8_pipeline_leads_ouverts": "12",
    "m8_taux_conversion_resolus_pct": "37.50",
    "m8_valeur_ponderee_pipeline_cad": "41250.00",
    "m8_articles_en_rupture": "3",
    "m8_articles_sur_reserves": "1",
    "m8_reservations_incompletes": "2",
    "m8_plaintes_periode": "2",
    "m8_leads_publicitaires": "3",
    "m8_cout_par_lead_pub_cad": "91.80",  # 275,40 $ de relevés pour 3 leads rattachés par la correspondance du
    # propriétaire
    "m8_releves_depense_pub_cad": "275.40",
}


# ================================================================================================ de bout en bout
def test_de_l_evenement_de_chaque_producteur_jusqu_au_wallboard_au_copilote_et_a_la_memoire(monde):
    _declarer_canaux()
    _publier(_scenario())
    resume = monde.repartir(departements=(M8,))
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert monde.quarantaines() == [] and monde.ecritures_hors_propriete() == []

    construction = _m8(monde, "m8_construire_entrepot", maintenant=MAINTENANT)
    assert construction["statut"] == "construit" and construction["construction"]["nb_mesures"] == 59
    with stockage.transaction() as cnx:
        lignes = {ligne["metric_id"]: ligne for ligne in entrepot_stockage.lire_mesures_courantes(cnx)}
    for metric_id, valeur in ATTENDU.items():
        assert lignes[metric_id]["valeur"] == valeur and lignes[metric_id]["statut"] == "calculee", metric_id
    assert lignes["m8_ecart_depense_pub_comptabilisee_cad"]["detail"].startswith("couverture partielle")
    assert lignes["m8_clics_recherche"]["proprietaire"] == "m07-marketing"
    assert "m5.facture_emise_constatee" in lignes["m8_facturation_emise_cad"]["source"]

    mesures = _mesures(monde)
    # D7 : la capacité se constate par semaine (cadence 7 j) ; les autres mesures gardent la fenêtre de 24 h
    assert mesures["m8_capacite_heures_disponibles"]["fraicheur"] == "a_jour"
    assert mesures["m8_cout_par_lead_pub_cad"]["statut"] == "calculee"

    acquisition = _tuiles(monde, "acquisition")
    assert acquisition["clics-recherche"]["valeur"] == "135" and acquisition["cout-par-lead"]["valeur"] == "91.80"
    assert (
        acquisition["depense-comptabilisee"]["partielle"] is True and acquisition["visites-site"]["partielle"] is True
    )
    ventes = _tuiles(monde, "ventes-clientele")
    assert ventes["leads-ouverts"]["valeur"] == "12" and ventes["factures-emises"]["valeur"] == "2"
    assert ventes["plaintes"]["valeur"] == "2" and ventes["facturation"]["valeur"] == "12500.00"
    equipes = _tuiles(monde, "equipes-materiel")
    assert equipes["charge-planifiee"]["valeur"] == "77.50" and equipes["ruptures"]["valeur"] == "3"

    cout = _m8(monde, "m8_repondre_question", question="Quel est notre coût par lead ?", maintenant=MAINTENANT)
    assert cout["statut"] == "repondu" and cout["mesures"][0]["valeur"] == "91.80" and cout["mention"]
    volume = _m8(monde, "m8_repondre_question", question="Quel est le volume de demandes ?", maintenant=MAINTENANT)
    assert (
        volume["mesures"][0]["metric_id"] == "m8_demandes_qualifiees_m1"
    )  # D5 : le volume de demandes, ce sont les qualifiées

    publication = _m8(monde, "m8_publier_faits_consolides", maintenant=MAINTENANT)
    assert publication["nouvelle"] is True and publication["n_mesures"] == 59
    monde.repartir(departements=(M9, M10))
    (fait,) = monde.registre(M10, "faits_analytiques")
    memorisees = {m["metric_id"]: m for m in fait["mesures"]}
    for metric_id, valeur in ATTENDU.items():
        assert memorisees[metric_id]["valeur"] == valeur, metric_id
    assert monde.quarantaines() == [] and monde.ecritures_hors_propriete() == []


def test_sans_correspondance_declaree_le_cout_par_lead_est_non_calculable_de_bout_en_bout(monde):
    _publier(_scenario())  # le propriétaire n'a rien déclaré
    monde.repartir(departements=(M8,))
    mesures = _mesures(monde)
    for metric_id in ("m8_leads_publicitaires", "m8_cout_par_lead_pub_cad"):
        assert mesures[metric_id]["statut"] == "non_calculable" and mesures[metric_id]["valeur"] is None, metric_id
        assert mesures[metric_id]["manque"] == ["canaux_marketing"]
    assert mesures["m8_releves_depense_pub_cad"]["valeur"] == "275.40"  # le reste de l'entrepôt n'en dépend pas
    tuile = _tuiles(monde, "acquisition")["cout-par-lead"]
    assert tuile["valeur"] is None and tuile["statut_mesure"] == "non_calculable"
    _declarer_canaux()  # dès que le propriétaire déclare, la mesure se calcule, sans nouvel événement
    assert _mesures(monde)["m8_cout_par_lead_pub_cad"]["valeur"] == "91.80"


def test_un_profil_invalide_n_est_pas_lu_comme_une_absence(monde, tmp_path):
    _publier(_scenario())
    monde.repartir(departements=(M8,))
    profil = taxonomie.fichier_profil()
    profil.parent.mkdir(parents=True, exist_ok=True)
    profil.write_text(
        "canaux_marketing:\n  google_ads: [google]\n  meta: [google]\n", encoding="utf-8"
    )  # une source, deux canaux
    m = _mesures(monde)["m8_cout_par_lead_pub_cad"]
    assert m["statut"] == "non_calculable" and m["manque"] == ["canaux_marketing"]


# ================================================================================================ ordre, rejeu
VERSIONNES = [
    # (producteur, type, version ancienne, version plus récente, mesure, valeur ancienne, valeur récente)
    (
        M4,
        "m4.capacite_equipe_constatee",
        lambda: ch.capacite_equipe(version="1" * 16, heures_disponibles="40", constate_le="2026-10-30T06:00:00-04:00"),
        lambda: ch.capacite_equipe(version="2" * 16, heures_disponibles="80", constate_le="2026-10-30T09:00:00-04:00"),
        "m8_capacite_heures_disponibles",
        "40.00",
        "80.00",
    ),
    (
        M2,
        "m2.pipeline_constate",
        lambda: ch.pipeline_constate(version="1" * 16, ouverts=5, constate_le="2026-10-30T06:00:00-04:00"),
        lambda: ch.pipeline_constate(version="2" * 16, ouverts=12, constate_le="2026-10-30T09:00:00-04:00"),
        "m8_pipeline_leads_ouverts",
        "5",
        "12",
    ),
    (
        M6,
        "m6.disponibilite_constatee",
        lambda: ch.disponibilite_constatee(
            version="1" * 16, articles_en_rupture=9, constate_le="2026-10-30T06:00:00-04:00"
        ),
        lambda: ch.disponibilite_constatee(
            version="2" * 16, articles_en_rupture=3, constate_le="2026-10-30T09:00:00-04:00"
        ),
        "m8_articles_en_rupture",
        "9",
        "3",
    ),
    (
        M7,
        "m7.performance_signaux_constatee",
        lambda: ch.performance_signaux(version="1" * 16, clics="100"),
        lambda: ch.performance_signaux(version="2" * 16, clics="130"),
        "m8_clics_recherche",
        "100",
        "130",
    ),
    (
        M1,
        "m1.plaintes_constatees",
        lambda: ch.plaintes_constatees(empreinte_contenu="01" * 32, nombre=1),
        lambda: ch.plaintes_constatees(empreinte_contenu="02" * 32, nombre=4),
        "m8_plaintes_periode",
        "1",
        "4",
    ),
]


@pytest.mark.parametrize(
    ("producteur", "type_", "ancienne", "recente", "mesure", "v_ancienne", "v_recente"),
    VERSIONNES,
    ids=[v[1] for v in VERSIONNES],
)
def test_une_version_plus_ancienne_livree_apres_la_plus_recente_ne_la_remplace_pas(
    monde, producteur, type_, ancienne, recente, mesure, v_ancienne, v_recente
):
    """M8 en panne à la première livraison : l'ancienne version est reprise APRÈS la récente. Le bus donne à M8
    l'instant de
    PUBLICATION (`publie_le`) : la version publiée en dernier fait foi, pas la dernière livrée."""
    evenements.publier(type_, producteur, ancienne(), evenement_id="version-ancienne")
    monde.pannes.add(M8)
    monde.repartir(passes=1, departements=(M8,))
    assert monde.statut("version-ancienne", M8) == "echec"
    monde.pannes.clear()
    evenements.publier(type_, producteur, recente(), evenement_id="version-recente")
    monde.repartir(passes=1, departements=(M8,))
    assert _mesures(monde)[mesure]["valeur"] == v_recente
    monde.repartir(departements=(M8,))  # la reprise de l'ancienne arrive en dernier
    assert monde.statut("version-ancienne", M8) == "traite"
    assert _mesures(monde)[mesure]["valeur"] == v_recente, "la plus récemment publiée l'emporte, pas la dernière livrée"
    assert monde.quarantaines() == []


HORAIRES = [
    # (producteur, type, fabrique(version, heure, valeur), mesure, valeur A, valeur B)
    (
        M4,
        "m4.capacite_equipe_constatee",
        lambda v, h, x: ch.capacite_equipe(
            version=v, heures_disponibles=x, constate_le=f"2026-10-30T{h:02d}:00:00-04:00"
        ),
        "m8_capacite_heures_disponibles",
        ("80", "80.00"),
        ("40", "40.00"),
    ),
    (
        M2,
        "m2.pipeline_constate",
        lambda v, h, x: ch.pipeline_constate(version=v, ouverts=int(x), constate_le=f"2026-10-30T{h:02d}:00:00-04:00"),
        "m8_pipeline_leads_ouverts",
        ("12", "12"),
        ("5", "5"),
    ),
    (
        M6,
        "m6.disponibilite_constatee",
        lambda v, h, x: ch.disponibilite_constatee(
            version=v, articles_en_rupture=int(x), constate_le=f"2026-10-30T{h:02d}:00:00-04:00"
        ),
        "m8_articles_en_rupture",
        ("3", "3"),
        ("9", "9"),
    ),
]


@pytest.mark.parametrize(
    ("producteur", "type_", "fabrique", "mesure", "a", "b"), HORAIRES, ids=[h[1] for h in HORAIRES]
)
def test_un_retour_a_une_version_anterieure_des_donnees_est_un_constat_de_plus_et_l_emporte(
    monde, producteur, type_, fabrique, mesure, a, b
):
    """A, puis B, puis A de nouveau (même version de données qu'au départ, constatée plus tard) : trois constats
    distincts, et
    le dernier publié fait foi. Sans l'instant du constat dans l'identifiant et dans la clé de contenu, le troisième
    serait
    pris pour un doublon du premier et M8 resterait sur B."""
    va, vb = "a" * 16, "b" * 16
    evenements.publier(type_, producteur, fabrique(va, 6, a[0]), evenement_id="constat-1")
    evenements.publier(type_, producteur, fabrique(vb, 7, b[0]), evenement_id="constat-2")
    evenements.publier(type_, producteur, fabrique(va, 8, a[0]), evenement_id="constat-3")
    monde.repartir(departements=(M8,))
    assert monde.taille(M8, "faits_operations") == 3
    assert _mesures(monde)[mesure]["valeur"] == a[1], "le retour à la version A, publié en dernier, fait foi"
    assert monde.quarantaines() == []


def test_un_retour_a_une_version_anterieure_de_la_depense_comptabilisee_l_emporte_par_son_sequence(monde):
    for sequence, montant in ((1, "100.00"), (2, "200.00"), (3, "100.00")):
        evenements.publier(
            "m5.depense_publicitaire_constatee",
            M5,
            ch.depense_comptabilisee(sequence, comptabilise=montant),
            evenement_id=f"dep-{sequence}",
        )
    monde.repartir(departements=(M8,))
    m = _mesures(monde)["m8_depense_pub_comptabilisee_cad"]
    assert m["valeur"] == "100.00" and m["statut"] == "calculee"
    assert _mesures(monde)["m8_depense_pub_comptabilisee_cad"]["valeur"] == "100.00"


def test_un_rejeu_complet_sous_d_autres_identifiants_ne_change_ni_registres_ni_mesures(monde):
    _declarer_canaux()
    _publier(_scenario())
    monde.repartir(departements=(M8,))
    avant = {nom: monde.registre(M8, nom) for nom in ("faits_operations", "faits_entonnoir")}
    valeurs = {k: (v["valeur"], v["statut"]) for k, v in _mesures(monde).items()}
    _publier(_scenario(suffixe="-rejeu"))
    resume = monde.repartir(departements=(M8,))
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0
    assert {nom: monde.registre(M8, nom) for nom in avant} == avant
    assert {k: (v["valeur"], v["statut"]) for k, v in _mesures(monde).items()} == valeurs


def test_l_ordre_de_livraison_des_factures_ne_change_pas_l_etat_courant(tmp_path, monkeypatch):
    resultats = []
    for nom, ordre in (("a", lambda e: e), ("b", lambda e: list(reversed(e)))):
        (tmp_path / nom).mkdir()
        m = im.monter(tmp_path / nom, monkeypatch, (M8,))
        m.surveiller(monkeypatch)
        try:
            _publier(ordre([e for e in _scenario() if e[1] == "m5.facture_emise_constatee"]))
            m.repartir(departements=(M8,))
            mesures = _mesures(m)
            resultats.append((mesures["m8_factures_emises"]["valeur"], mesures["m8_facturation_emise_cad"]["valeur"]))
        finally:
            im.demonter()
    assert resultats[0] == resultats[1] == ("2", "12500.00")


# ================================================================================================ D7 : cadence et
# fraîcheur
def test_la_capacite_hebdomadaire_reste_a_jour_cinq_jours_les_autres_mesures_sont_perimees(monde):
    _declarer_canaux()
    _publier(_scenario())
    monde.repartir(departements=(M8,))
    cinq_jours = "2026-11-04T07:00:00-05:00"
    mesures = _mesures(monde, maintenant=cinq_jours)
    capacite = mesures["m8_capacite_heures_disponibles"]
    assert capacite["fraicheur"] == "a_jour", capacite
    assert mesures["m8_pipeline_leads_ouverts"]["fraicheur"] == "perime"
    assert mesures["m8_articles_en_rupture"]["fraicheur"] == "perime"
    huit_jours = "2026-11-07T07:00:00-05:00"
    assert _mesures(monde, maintenant=huit_jours)["m8_capacite_heures_disponibles"]["fraicheur"] == "perime"


# ================================================================================================ minimisation
def test_rien_de_personnel_dans_aucune_sortie_de_la_phase_2(monde):
    _declarer_canaux()
    _publier(_scenario())
    monde.repartir(departements=(M8,))
    sorties = [
        _m8(monde, "m8_construire_entrepot", maintenant=MAINTENANT),
        _m8(monde, "m8_lire_mesures", maintenant=MAINTENANT),
        *[
            _m8(monde, "m8_lire_wallboard", maintenant=MAINTENANT, wallboard_id=w)
            for w in ("acquisition", "ventes-clientele", "equipes-materiel")
        ],
        _m8(monde, "m8_repondre_question", question="Combien de plaintes avons-nous reçues ?", maintenant=MAINTENANT),
        _m8(monde, "m8_publier_faits_consolides", maintenant=MAINTENANT),
        monde.registre(M8, "faits_operations"),
        monde.registre(M8, "faits_entonnoir"),
    ]
    monde.repartir(departements=(M9, M10))
    sorties.append(monde.registre(M10, "faits_analytiques"))
    texte = json.dumps(sorties, default=str, ensure_ascii=False)
    for interdit in PERSONNEL:
        assert interdit not in texte, interdit
    # le registre des leads ne garde que la source UTM en minuscules, jamais la campagne ni le client
    assert "client_id" not in json.dumps(monde.registre(M8, "faits_entonnoir"))
