"""Entrepôt de M8 : scénario de bout en bout multi-départements et cas négatifs, sur le VRAI bus.

Sept départements publient (M1, M2, M3, M4, M5, M6, M7 : charges du catalogue, validées à la publication), les
`consommateurs()` réels de M8 rangent, l'outil réel `m8_construire_entrepot` bâtit l'entrepôt, puis la mesure se lit
par le wallboard, par le copilote et par la mémoire (M10) et M9 : un chiffre, une provenance, une fraîcheur, de la
source au dernier écran. Ce que ce fichier NE prouve PAS : les producteurs réels de M5, M6 et M7 (ils sont couverts
par leurs suites et par `test_cascade_marge_m5_m8_m10.py`, `test_cascade_cash_libre_m5_m8.py`) ni aucun service externe.

Cas négatifs : ordre de livraison inversé, rejeu complet sous d'autres identifiants, constat incohérent (forgé)
accepté par le schéma, source obsolète, source absente, panne de M8 en pleine chaîne, charge personnelle qui ne
traverse pas. Données fictives.
"""

from __future__ import annotations

import json

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m8_analytics import entrepot_stockage, moteur_mesures

from opsys import evenements, stockage
from opsys.capacites import Capacites

FICTIF = True
M1, M2, M3, M4, M5, M6, M7, M8, M9, M10 = (
    "m01-front-office",
    "m02-revenue-crm",
    "m03-estimation",
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
PERSONNEL = ("Jeanne", "jeanne.fictive", "example.test", "514-555", "fournisseur-fictif", "chantier-fictif")


def _scenario(suffixe: str = "") -> list[tuple[str, str, dict, str]]:
    """(producteur, type, charge, evenement_id) : trois demandes de M1 dont deux deviennent des leads de M2, trois devis
    acceptés de M3 et trois chantiers terminés de M4 (dont un dont M5 n'a pas pu chiffrer la marge), la rentabilité,
    le cash libre et les mesures comptables de M5, deux réceptions de M6, deux relevés de dépense avec un jour sans
    relevé, une
    conversion et une anomalie critique de M7."""
    jour = f"{JOUR}T"
    ev = []

    def pub(producteur, type_, charge, nom):
        ev.append((producteur, type_, charge, f"{nom}{suffixe}"))

    for i in (1, 2, 3):
        pub(M1, "m1.lead_qualifie", ch.lead_qualifie_m1(f"lead-{i}", horodatage=f"{jour}08:0{i}:00-04:00"), f"m1-{i}")
    for i in (1, 2):
        pub(
            M2,
            "m2.client_associe",
            ch.client_associe(lead_id=f"lead-{i}", horodatage_association=f"{jour}08:1{i}:00-04:00"),
            f"m2-{i}",
        )
    prix = {1: ("10000.00", "7000.00"), 2: ("8000.00", "6000.00"), 3: ("5000.00", "3500.00")}
    minutes = {1: 120, 2: 90, 3: 60}
    for i in (1, 2, 3):
        pub(
            M3,
            "m3.devis_accepte",
            ch.devis_accepte(f"devis-{i}", *prix[i], horodatage_acceptation=f"{jour}09:0{i}:00-04:00"),
            f"m3-{i}",
        )
        pub(
            M4,
            "m4.travaux_termines",
            ch.travaux_termines(f"wct-{i}", f"devis-{i}", minutes[i], horodatage_completion=f"{jour}14:0{i}:00-04:00"),
            f"m4-{i}",
        )
    pub(M5, "m5.rentabilite_chantier", ch.rentabilite("wct-1", "devis-1", 1, "3200.00"), "m5-r1")
    pub(M5, "m5.rentabilite_chantier", ch.rentabilite("wct-2", "devis-2", 1, "-500.00"), "m5-r2")
    pub(M5, "m5.rentabilite_chantier", ch.rentabilite("wct-3", "devis-3", 1, None), "m5-r3")
    pub(M5, "m5.cash_libre_constate", ch.cash_libre(3, JOUR, "459.91"), "m5-cash")
    pub(M5, "m5.mesures_comptables_constatees", ch.mesures_comptables(jour=JOUR), "m5-compta")
    for i in (1, 2):
        pub(
            M6,
            "m6.reception_enregistree",
            ch.reception_m6(
                f"po-{i}",
                i,
                "CONFORME" if i == 1 else "RECEPTION_INFERIEURE",
                horodatage_reception=f"{jour}11:0{i}:00-04:00",
            ),
            f"m6-{i}",
        )
    for i in (1, 2):
        pub(
            M1,
            "m1.commande_courriel_envoyee",
            ch.commande_envoyee(f"po-{i}", i, envoye_le=f"{jour}10:0{i}:00-04:00"),
            f"m1-cmd{i}",
        )
    pub(
        M7,
        "m7.depenses_marketing_constatees",
        ch.depense_marketing("releve-1", jour="2026-10-26", montant="100.00", releve_le=f"{jour}06:00:00-04:00"),
        "m7-d1",
    )
    pub(
        M7,
        "m7.depenses_marketing_constatees",
        ch.depense_marketing("releve-2", jour="2026-10-28", montant="50.00", releve_le=f"{jour}06:00:00-04:00"),
        "m7-d2",
    )
    pub(
        M7,
        "m7.signaux_marketing_constates",
        ch.signaux_marketing("google_ads", JOUR, f"{jour}06:00:00-04:00", fraicheur_fenetre_h=48),
        "m7-sig",
    )
    pub(
        M7,
        "m7.conversion_hors_ligne_importee",
        ch.conversion_hors_ligne(importee_le=f"{jour}09:00:00-04:00"),
        "m7-conv",
    )
    pub(
        M7,
        "m7.anomalie_depense_detectee",
        ch.anomalie_depense(severite="critique", detectee_le=f"{jour}07:00:00-04:00"),
        "m7-ano",
    )
    return ev


class _Restreint:
    """M10 réel, mais abonné au seul `m8.fait_consolide` : ses autres consommateurs (par exemple l'attente d'un WCT, qui
    suppose M4 et M5 réels) sont hors du sujet de ce fichier et ne doivent pas mettre la chaîne en quarantaine."""

    def __init__(self, departement, types):
        self._departement = departement
        self._types = types

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


def _publier(evs):
    for producteur, type_, charge, ident in evs:
        evenements.publier(type_, producteur, charge, evenement_id=ident)


def _m8(monde, outil, **arguments):
    reponse = Capacites(monde.departements, stockage.transaction, filtre={M8}, memoire=False).appeler(outil, arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _registres(monde):
    return {
        "chantier": monde.registre(M8, "faits_chantier"),
        "entonnoir": monde.registre(M8, "faits_entonnoir"),
        "contenus": monde.registre(M8, "faits_contenus"),
        "cash_libre": monde.registre(M8, "faits_cash_libre"),
        "operations": monde.registre(M8, "faits_operations"),
    }


def _pages(monde, outil, cle, **arguments):
    """Toutes les pages d'une lecture bornée par le socle (`prochain_depart`), mises bout à bout."""
    depart, lignes = 0, []
    while depart is not None:
        page = _m8(monde, outil, depart=depart, **arguments)
        lignes += page[cle]
        depart = page["prochain_depart"]
    return lignes


def _mesures(monde, maintenant=MAINTENANT, **plus):
    return {m["metric_id"]: m for m in _pages(monde, "m8_lire_mesures", "mesures", maintenant=maintenant, **plus)}


def _tuiles(monde, wallboard_id, maintenant=MAINTENANT):
    return {
        t["id"]: t
        for t in _pages(monde, "m8_lire_wallboard", "tuiles", maintenant=maintenant, wallboard_id=wallboard_id)
    }


ATTENDU = {
    "m8_chantiers_marge_reelle": "2",
    "m8_marge_reelle_cumulee_cad": "2700.00",
    "m8_chantiers_en_perte": "1",
    "m8_ecart_marge_cumule_cad": "-2300.00",  # (3200 - 3000) + (-500 - 2000)
    "m8_creances_ouvertes_cad": "7210.55",
    "m8_creances_90_jours_plus_cad": "0.00",
    "m8_comptes_a_payer_cad": "459.91",
    "m8_releves_depense_pub_cad": "150.00",
    "m8_conversions_hors_ligne": "1",
    "m8_anomalies_depense_critiques": "1",
    "m8_heures_sur_site_chantiers": "4.50",
    "m8_commandes_envoyees": "2",
    "m8_receptions_materiaux": "2",
    "m8_receptions_avec_ecart": "1",
    "m8_demandes_qualifiees_m1": "3",
    "m8_demandes_m1_sans_lead_m2": "1",
    "m8_leads_recus": "2",
    "m8_devis_acceptes": "3",
    "m8_chantiers_termines": "3",
}


# ================================================================================================ de bout en bout
def test_de_l_evenement_du_departement_producteur_jusqu_au_wallboard_au_copilote_et_a_la_memoire(monde):
    _publier(_scenario())
    resume = monde.repartir(departements=(M8,))
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert monde.quarantaines() == [] and monde.ecritures_hors_propriete() == []

    # 1. l'entrepôt : une construction, les 62 mesures, la provenance, la couverture partielle dite
    construction = _m8(monde, "m8_construire_entrepot", maintenant=MAINTENANT)
    assert construction["statut"] == "construit" and construction["construction"]["nb_mesures"] == 62
    with stockage.transaction() as cnx:
        lignes = {ligne["metric_id"]: ligne for ligne in entrepot_stockage.lire_mesures_courantes(cnx)}
    for metric_id, valeur in ATTENDU.items():
        assert lignes[metric_id]["valeur"] == valeur and lignes[metric_id]["statut"] == "calculee", metric_id
    marge = lignes["m8_marge_reelle_cumulee_cad"]
    assert "2 chantier(s) sur 3" in marge["detail"] and marge["proprietaire"] == "m05-financecore"
    assert "m5.rentabilite_chantier" in marge["source"] and len(marge["version_definition"]) == 64
    assert lignes["m8_releves_depense_pub_cad"]["detail"].startswith("couverture partielle")  # le 27 : aucun relevé
    assert lignes["m8_ecart_depense_pub_comptabilisee_cad"]["valeur"] is None
    lecture = _m8(monde, "m8_lire_entrepot", metric_id="m8_creances_ouvertes_cad")
    assert lecture["statut"] == "a_jour" and lecture["historique"][0]["valeur"] == "7210.55"

    # 2. la mesure par le moteur : la même valeur, la fraîcheur et la couverture
    mesures = _mesures(monde)
    assert mesures["m8_creances_ouvertes_cad"]["fraicheur"] == "a_jour"
    assert mesures["m8_releves_depense_pub_cad"]["statut"] == "calculee"

    # 3. le wallboard « finance et opérations » (même moteur, même fraîcheur)
    etat = _m8(monde, "m8_lire_wallboard", maintenant=MAINTENANT, wallboard_id="finance-operations")
    tuiles = _tuiles(monde, "finance-operations")
    assert tuiles["creances"]["valeur"] == "7210.55" and tuiles["a-payer"]["valeur"] == "459.91"
    assert tuiles["receptions-ecart"]["valeur"] == "1" and tuiles["heures"]["valeur"] == "4.50"
    assert tuiles["marge-cumulee"]["partielle"] is True and tuiles["marge-cumulee"]["valeur"] == "2700.00"
    assert "marge-cumulee" in etat["banniere"]["partielles"] and etat["banniere"]["niveau"] != "ok"

    # 4. le copilote répond avec la valeur exacte et dit la couverture partielle
    reponse = _m8(monde, "m8_repondre_question", question="Quelle est la marge réelle cumulée ?", maintenant=MAINTENANT)
    assert reponse["statut"] == "repondu" and reponse["mesures"][0]["valeur"] == "2700.00"
    assert "Couverture PARTIELLE" in reponse["texte"] and "2 chantier(s) sur 3" in reponse["texte"]
    compte = _m8(monde, "m8_repondre_question", question="Combien de comptes à payer ?", maintenant=MAINTENANT)
    assert compte["mesures"][0]["valeur"] == "459.91" and compte["mention"]

    # 5. la mémoire : M10 mémorise les 62 mesures telles que M8 les publie ; M9 reçoit le résumé
    publication = _m8(monde, "m8_publier_faits_consolides", maintenant=MAINTENANT)
    assert publication["nouvelle"] is True and publication["n_mesures"] == 62
    monde.repartir(departements=(M9, M10))
    (fait,) = monde.registre(M10, "faits_analytiques")
    memorisees = {m["metric_id"]: m for m in fait["mesures"]}
    for metric_id, valeur in ATTENDU.items():
        assert memorisees[metric_id]["valeur"] == valeur, metric_id
    assert memorisees["m8_creances_ouvertes_cad"]["proprietaire"] == "m05-financecore"
    assert monde.taille(M9, "signaux_gestion_recus") == 2  # l'anomalie critique de M7 et le résumé de la consolidation
    assert monde.quarantaines() == [] and monde.ecritures_hors_propriete() == []


def test_rien_de_personnel_dans_aucune_sortie_de_bout_en_bout(monde):
    _publier(_scenario())
    monde.repartir(departements=(M8,))
    sorties = [
        _m8(monde, "m8_construire_entrepot", maintenant=MAINTENANT),
        _m8(monde, "m8_lire_mesures", maintenant=MAINTENANT),
        _m8(monde, "m8_lire_wallboard", maintenant=MAINTENANT, wallboard_id="finance-operations"),
        _m8(monde, "m8_lire_wallboard", maintenant=MAINTENANT, wallboard_id="marketing"),
        _m8(
            monde,
            "m8_repondre_question",
            question="Combien de demandes qualifiées par le front office ?",
            maintenant=MAINTENANT,
        ),
        _m8(monde, "m8_publier_faits_consolides", maintenant=MAINTENANT),
    ]
    with stockage.transaction() as cnx:
        sorties.append(entrepot_stockage.lire_mesures_courantes(cnx))
        sorties.append({nom: entrepot_stockage.lire_table(cnx, nom) for nom in entrepot_stockage.tables()})
    monde.repartir(departements=(M9, M10))
    sorties.append(monde.registre(M10, "faits_analytiques"))
    texte = json.dumps(sorties, default=str, ensure_ascii=False)
    for interdit in PERSONNEL:
        assert interdit not in texte, interdit


# ================================================================================================ ordre, rejeu, doublon
def _mesures_valeurs(monde):
    return {k: (v["valeur"], v["statut"]) for k, v in _mesures(monde).items()}


def test_l_ordre_de_livraison_ne_change_aucune_mesure(tmp_path, monkeypatch):
    resultats = []
    for nom, ordre in (("a", lambda e: e), ("b", lambda e: list(reversed(e)))):
        m = im.monter(tmp_path / nom, monkeypatch, (M8,)) if (tmp_path / nom).mkdir() is None else None
        m.surveiller(monkeypatch)
        try:
            evs = ordre(_scenario())
            # un état plus récent de M5 PUBLIÉ AVANT l'ancien, dans les deux mondes
            evs.insert(0, (M5, "m5.rentabilite_chantier", ch.rentabilite("wct-1", "devis-1", 2, "3300.00"), "m5-r1-s2"))
            evs.append(
                (M5, "m5.cash_libre_constate", ch.cash_libre(2, "2026-10-28", "1.00"), "m5-cash-ancien")
            )  # sequence 2 < 3
            _publier(evs)
            m.repartir(departements=(M8,))
            valeurs = _mesures_valeurs(m)
            resultats.append(valeurs)
            assert m.quarantaines() == []
        finally:
            im.demonter()
    assert resultats[0] == resultats[1]
    assert resultats[0]["m8_marge_reelle_cumulee_cad"][0] == "2800.00"  # la trace de sequence 2 (3300) l'emporte
    assert (
        resultats[0]["m8_comptes_a_payer_cad"][0] == "459.91"
    )  # le constat de sequence 3 l'emporte sur celui de sequence 2


def test_un_rejeu_complet_sous_d_autres_identifiants_ne_change_ni_registres_ni_entrepot(monde):
    _publier(_scenario())
    monde.repartir(departements=(M8,))
    avant = {
        nom: monde.taille(M8, nom)
        for nom in (
            "faits_chantier",
            "faits_entonnoir",
            "faits_contenus",
            "faits_cash_libre",
            "faits_operations",
            "snapshots",
        )
    }
    premiere = _m8(monde, "m8_construire_entrepot", maintenant=MAINTENANT)
    _publier(_scenario(suffixe="-rejeu"))
    resume = monde.repartir(departements=(M8,))
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert {nom: monde.taille(M8, nom) for nom in avant} == avant
    seconde = _m8(monde, "m8_construire_entrepot", maintenant="2026-10-30T19:00:00-04:00")
    assert (
        seconde["statut"] == "inchange"
        and seconde["construction"]["construction_id"] == premiere["construction"]["construction_id"]
    )


def test_la_meme_enveloppe_publiee_deux_fois_est_un_no_op_du_bus(monde):
    evs = _scenario()
    _publier(evs)
    _publier(evs)
    assert len(monde.sortants("m5.mesures_comptables_constatees")) == 1
    monde.repartir(departements=(M8,))
    monde.repartir(departements=(M8,))
    assert monde.taille(M8, "faits_operations") == len(
        [e for e in evs if e[1].startswith(("m7.", "m5.mesures", "m6.", "m1.commande"))]
    )


# ================================================================================================ forgé, obsolète,
# absent
def test_un_constat_comptable_incoherent_passe_le_schema_mais_pas_la_mesure(monde):
    forge = ch.mesures_comptables(jour=JOUR, version="f" * 16)
    forge["creances"]["total"] = "999999.00"  # conforme au catalogue, mais pas la somme des tranches d'âge
    evenements.publier("m5.mesures_comptables_constatees", M5, forge, evenement_id="forge-1")
    monde.repartir(departements=(M8,))
    assert monde.taille(M8, "faits_operations") == 1 and monde.quarantaines() == []
    creances = _mesures(monde)["m8_creances_ouvertes_cad"]
    assert creances["statut"] == "non_calculable" and creances["valeur"] is None
    brutes = {m["metric_id"]: m for m in moteur_mesures.lire(_registres(monde))}
    # C4 : l'incohérence n'est plus un « non calculable » parmi d'autres, c'est un ÉCHEC DE QUALITÉ nommé (QUALITY_FAIL)
    bloquee = brutes["m8_creances_ouvertes_cad"]
    assert bloquee["qualite"]["statut"] == "echec" and bloquee["qualite"]["echecs"][0]["regle"] == (
        "Q-CREANCES-TOTAL-EGALE-TRANCHES")
    assert "contrôle de qualité" in bloquee["manque"][0]["raison"] and "tranches" in bloquee["manque"][0]["raison"]
    assert creances["pastille"] == "QUALITY_FAIL"
    reponse = _m8(monde, "m8_repondre_question", question="Quelles sont nos créances ouvertes ?", maintenant=MAINTENANT)
    assert reponse["mesures"][0]["valeur"] is None and "999999" not in json.dumps(reponse)
    # le fait garde sa provenance : type d'événement et empreinte de la charge reçue, pour la preuve
    (fait,) = monde.registre(M8, "faits_operations")
    assert (
        fait["provenance"]["evenement"] == "m5.mesures_comptables_constatees"
        and len(fait["provenance"]["empreinte"]) == 64
    )


def test_une_source_obsolete_est_perimee_jamais_montree_comme_a_jour(monde):
    _publier(_scenario())
    monde.repartir(departements=(M8,))
    frais = _mesures(monde)
    assert (
        frais["m8_creances_ouvertes_cad"]["fraicheur"] == "a_jour"
        and frais["m8_receptions_materiaux"]["fraicheur"] == "a_jour"
    )
    trois_jours = "2026-11-02T18:00:00-04:00"
    vieux = _mesures(monde, trois_jours)
    for metric_id in (
        "m8_creances_ouvertes_cad",
        "m8_releves_depense_pub_cad",
        "m8_receptions_materiaux",
        "m8_comptes_a_payer_cad",
    ):
        assert vieux[metric_id]["fraicheur"] == "perime", metric_id
    assert vieux["m8_heures_sur_site_chantiers"]["fraicheur"] == "non_applicable"  # cumul de chantiers terminés
    etat = _m8(monde, "m8_lire_wallboard", maintenant=trois_jours, wallboard_id="finance-operations")
    assert "creances" in etat["banniere"]["perimees"] and etat["banniere"]["niveau"] != "ok"
    assert _tuiles(monde, "finance-operations", trois_jours)["creances"]["a_jour"] is False
    reponse = _m8(
        monde, "m8_repondre_question", question="Quelles sont nos créances ouvertes ?", maintenant=trois_jours
    )
    assert "PÉRIMÉE" in reponse["texte"] and reponse["mesures"][0]["a_jour"] is False


def test_la_fenetre_de_m7_et_celle_de_l_appelant_resserrent_la_fraicheur(monde):
    _publier(_scenario())
    monde.repartir(departements=(M8,))
    # relevés lus à 06:00 : 12 h plus tard (18:00), à jour avec la fenêtre de 24 h du catalogue
    assert _mesures(monde)["m8_releves_depense_pub_cad"]["fraicheur"] == "a_jour"
    assert _mesures(monde, fraicheur_max_s=3600)["m8_releves_depense_pub_cad"]["fraicheur"] == "perime"
    # M7 déclare 5 h pour sa source publicitaire : plus stricte que le catalogue, elle s'applique sans que l'appelant
    # la demande
    evenements.publier(
        "m7.signaux_marketing_constates",
        M7,
        ch.signaux_marketing("google_ads", JOUR, f"{JOUR}T07:00:00-04:00", fraicheur_fenetre_h=5),
        evenement_id="sig-5h",
    )
    monde.repartir(departements=(M8,))
    releves = _mesures(monde)["m8_releves_depense_pub_cad"]
    assert releves["fraicheur"] == "perime"
    assert releves["fenetre_s"] == 5 * 3600 and releves["origine_fenetre"] == "source"


def test_une_source_absente_reste_inconnue_et_jamais_un_zero(monde):
    seulement_m5 = [e for e in _scenario() if e[0] == M5]
    _publier(seulement_m5)
    monde.repartir(departements=(M8,))
    mesures = _mesures(monde)
    for metric_id in (
        "m8_releves_depense_pub_cad",
        "m8_conversions_hors_ligne",
        "m8_anomalies_depense_critiques",
        "m8_receptions_materiaux",
        "m8_demandes_qualifiees_m1",
        "m8_heures_sur_site_chantiers",
    ):
        assert mesures[metric_id]["statut"] == "non_calculable" and mesures[metric_id]["valeur"] is None, metric_id
    assert mesures["m8_creances_ouvertes_cad"]["valeur"] == "7210.55"
    # M5 a publié la rentabilité mais M4 n'a livré aucun chantier terminé : pas de dénominateur, pas de marge cumulée
    assert mesures["m8_marge_reelle_cumulee_cad"]["statut"] == "non_calculable"
    construction = _m8(monde, "m8_construire_entrepot", maintenant=MAINTENANT)
    assert construction["statut"] == "construit"
    with stockage.transaction() as cnx:
        lignes = {ligne["metric_id"]: ligne for ligne in entrepot_stockage.lire_mesures_courantes(cnx)}
    assert (
        lignes["m8_conversions_hors_ligne"]["valeur"] is None
        and "rien livré" in lignes["m8_conversions_hors_ligne"]["detail"]
    )


def test_la_panne_de_m8_en_pleine_chaine_puis_la_reprise_donnent_les_memes_mesures(monde):
    evs = _scenario()
    _publier(evs[: len(evs) // 2])
    monde.repartir(departements=(M8,))
    monde.pannes.add(M8)
    _publier(evs[len(evs) // 2 :])
    monde.repartir(passes=1, departements=(M8,))
    assert monde.quarantaines() == [] and any(r["statut"] == "echec" for r in monde.recus(consommateur=M8))
    monde.pannes.clear()
    monde.repartir(departements=(M8,))
    assert monde.quarantaines() == []
    assert all(r["statut"] == "traite" for r in monde.recus(consommateur=M8))
    mesures = _mesures(monde)
    for metric_id, valeur in ATTENDU.items():
        assert mesures[metric_id]["valeur"] == valeur, metric_id
    assert monde.ecritures_hors_propriete() == []


def test_la_cle_de_contenu_distingue_deux_commandes_envoyees_au_meme_instant_et_deux_receptions_d_un_meme_bon(monde):
    """La clé est le bon de commande (commandes) ou le bon et le mouvement de stock (réceptions), jamais l'instant."""
    instant = f"{JOUR}T10:00:00-04:00"
    for i in (1, 2):
        evenements.publier(
            "m1.commande_courriel_envoyee",
            M1,
            ch.commande_envoyee(f"po-m{i}", i, envoye_le=instant),
            evenement_id=f"cmd-meme-instant-{i}",
        )
        evenements.publier("m6.reception_enregistree", M6, ch.reception_m6("po-unique", i), evenement_id=f"rec-{i}")
    monde.repartir(departements=(M8,))
    faits = monde.registre(M8, "faits_operations")
    assert sum(1 for f in faits if f["type_entree"] == "commande_envoyee") == 2
    assert sum(1 for f in faits if f["type_entree"] == "reception_materiaux") == 2
    mesures = _mesures(monde)
    assert mesures["m8_commandes_envoyees"]["valeur"] == "2" and mesures["m8_receptions_materiaux"]["valeur"] == "2"
