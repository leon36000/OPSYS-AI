"""Revue adverse rvi : interconnexion des départements (livraison hors ordre après panne transitoire).

La livraison du bus n'est pas ordonnée : un réessai fait arriver un événement ancien APRÈS un récent. Les consommateurs
qui retiennent « le dernier état » ou « la révision à proposer » ne doivent pas se fier à l'ordre d'arrivée.
Bus réel, consommateurs réels, une panne transitoire injectée. Données fictives.
"""

from __future__ import annotations

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m5_financecore import charges_marketing_recues as cmr
from m6_material_control import outils as m6
from m6_material_control import rapprochements_recus as rr
from m8_analytics import operations_recues as op

from opsys import contexte, evenements, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante

FICTIF = True
M5, M6, M7, M8 = "m05-financecore", "m06-material-control", "m07-marketing", "m08-analytics"
ADMIN = IdentiteAppelante("admin.fictif", "admin")


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch)
    m.surveiller(monkeypatch)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictif", "mot-de-passe-admin-1234", ["admin"])
    yield m
    im.demonter()


def _en_panne_une_fois(monkeypatch, module, nom, quand):
    """Remplace `module.nom` : la première fois que `quand(*args)` est vrai, lève une panne transitoire."""
    vrai = getattr(module, nom)
    etat = {"pannes": 0}

    def enveloppe(*args, **kwargs):
        if etat["pannes"] == 0 and quand(*args, **kwargs):
            etat["pannes"] += 1
            raise ConnectionError("panne transitoire")
        return vrai(*args, **kwargs)

    monkeypatch.setattr(module, nom, enveloppe)
    return etat


# ------------------------------------------------------------------------------------------------ M6 (rvi-01)
def _attentes_m6():
    with stockage.transaction():
        return [a for a in m6.attentes() if a["type"] == "rapprochement_po_a_voir"]


def _publier_rappo(verdict, ident, **plus):
    evenements.publier(
        "m5.rapprochement_po_constate", M5, ch.rapprochement_po(facture="ff-1", verdict=verdict, **plus),
        evenement_id=ident)


def test_m6_meme_jour_un_ecart_publie_apres_n_est_pas_masque_par_un_etat_concordant_livre_apres(monde, monkeypatch):
    """CONCORDANT publié, puis ECART publié (même jour) ; la livraison de CONCORDANT échoue une fois puis est reprise
    APRÈS celle de ECART : l'écart réel doit rester signalé."""
    _publier_rappo("CONCORDANT", "a")
    _publier_rappo("ECART", "b", sens="FACTURE_SUPERIEURE_AU_RECU", facture_avant_taxes="1300.00",
                   ecart_avant_taxes="100.00")
    etat = _en_panne_une_fois(monkeypatch, rr, "fait", lambda charge, *a, **k: charge["verdict"] == "CONCORDANT")
    monde.repartir()
    assert etat["pannes"] == 1
    assert [a["id"] for a in _attentes_m6()] == ["ff-1"], "l'écart réel est masqué par l'état périmé"


def test_m6_meme_jour_un_etat_concordant_publie_apres_leve_l_attente_malgre_la_livraison_hors_ordre(monde, monkeypatch):
    """Négatif : ECART publié puis CONCORDANT publié ; ECART est livré en retard : l'attente ne doit pas revenir."""
    _publier_rappo("ECART", "a", sens="FACTURE_SUPERIEURE_AU_RECU", facture_avant_taxes="1300.00",
                   ecart_avant_taxes="100.00")
    _publier_rappo("CONCORDANT", "b")
    _en_panne_une_fois(monkeypatch, rr, "fait", lambda charge, *a, **k: charge["verdict"] == "ECART")
    monde.repartir()
    assert _attentes_m6() == []


def test_m6_l_ordre_normal_de_livraison_reste_correct(monde):
    _publier_rappo("CONCORDANT", "a")
    _publier_rappo("ECART", "b", sens="FACTURE_SUPERIEURE_AU_RECU", facture_avant_taxes="1300.00",
                   ecart_avant_taxes="100.00")
    monde.repartir()
    assert [a["id"] for a in _attentes_m6()] == ["ff-1"]


def test_m6_pure_la_publication_departage_deux_etats_du_meme_jour_sans_horloge():
    ancien = rr.fait(ch.rapprochement_po(verdict="CONCORDANT"), "2026-11-02T10:00:00+00:00")
    recent = rr.fait(
        ch.rapprochement_po(verdict="ECART", sens="FACTURE_SUPERIEURE_AU_RECU"), "2026-11-02T10:00:05.250000+00:00")
    for ordre in ((ancien, recent), (recent, ancien)):
        assert rr.derniers_etats(ordre)["ff-fictive-1"]["verdict"] == "ECART"
    # fait antérieur au champ (aucune publication connue) : il passe avant, puis l'ordre d'arrivée départage
    sans = rr.fait(ch.rapprochement_po(verdict="INCOMPLET"))
    assert rr.derniers_etats((recent, sans))["ff-fictive-1"]["verdict"] == "ECART"
    # un instant illisible ou sans fuseau n'est jamais présumé récent
    illisible = {**recent, "verdict": "INCOMPLET", "publie_le": "n'importe quoi"}
    assert rr.derniers_etats((recent, illisible))["ff-fictive-1"]["verdict"] == "ECART"


# ------------------------------------------------------------------------------------------------ M8 (rvi-02)
def _vue(monde):
    capacites = Capacites(monde.departements, stockage.transaction, filtre={M8}, memoire=False)
    with contexte.appele_par_appareil(ADMIN):
        reponse = capacites.appeler("m8_lire_vue_executive", {"aujourd_hui": "2026-11-02"})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def test_m8_meme_jour_la_version_comptable_publiee_en_dernier_fait_foi_malgre_la_livraison_hors_ordre(
        monde, monkeypatch):
    evenements.publier("m5.mesures_comptables_constatees", M5, ch.mesures_comptables(version="aaaaaaaaaaaaaaaa"),
                       evenement_id="m1")
    nouvelle = ch.mesures_comptables(version="bbbbbbbbbbbbbbbb", ecritures_definitives=99)
    evenements.publier("m5.mesures_comptables_constatees", M5, nouvelle, evenement_id="m2")
    _en_panne_une_fois(
        monkeypatch, op, "fait", lambda type_entree, charge, *a, **k: charge["version_donnees"] == "a" * 16)
    monde.repartir()
    dernier = _vue(monde)["operations_recues"]["comptabilite"]["dernier"]
    assert dernier["version_donnees"] == "bbbbbbbbbbbbbbbb" and dernier["ecritures_definitives"] == 99


def test_m8_pure_la_publication_departage_deux_versions_du_meme_jour():
    a = op.fait(op.TYPE_MESURES_COMPTABLES, ch.mesures_comptables(version="a" * 16), "2026-11-02T10:00:00+00:00")
    b = op.fait(op.TYPE_MESURES_COMPTABLES, ch.mesures_comptables(version="b" * 16), "2026-11-02T10:00:09+00:00")
    for ordre in ([a, b], [b, a]):
        assert op.section(ordre)["comptabilite"]["dernier"]["version_donnees"] == "b" * 16
    assert "publie_le" not in op.section([a])["comptabilite"]["dernier"]
    # la date de référence reste prioritaire sur la publication
    autre_jour = op.fait(op.TYPE_MESURES_COMPTABLES, ch.mesures_comptables(jour="2026-10-29", version="c" * 16),
                         "2026-11-02T11:00:00+00:00")
    assert op.section([autre_jour, b])["comptabilite"]["dernier"]["version_donnees"] == "b" * 16
    # la publication n'est gardée que pour les constats comptables
    assert "publie_le" not in op.fait(op.TYPE_DEPENSE, ch.depense_marketing(), "2026-11-02T10:00:00+00:00")


# ------------------------------------------------------------------------------------------------ M5 (rvi-03)
def _gl_debits(monde):
    return [str(ligne["debit"]) for e in monde.registre(M5, "grand_livre") for ligne in e["lignes"]
            if ligne.get("debit")]


def test_m5_une_revision_perimee_livree_apres_la_plus_recente_ne_propose_pas_de_brouillon(monde, monkeypatch):
    from m5_financecore import grand_livre

    evenements.publier("m7.depenses_marketing_constatees", M7, ch.depense_marketing(revision=1, montant="100.00"),
                       evenement_id="r1")
    evenements.publier("m7.depenses_marketing_constatees", M7, ch.depense_marketing(revision=2, montant="130.00"),
                       evenement_id="r2")
    etat = _en_panne_une_fois(monkeypatch, grand_livre, "proposer_ecriture", lambda *a, **k: True)
    monde.repartir()
    assert etat["pannes"] == 1
    journal = {m["revision"]: m for m in monde.registre(M5, cmr.REGISTRE)}
    assert _gl_debits(monde) == [], "un brouillon au montant périmé (100.00) a été proposé"
    assert journal[1]["issue"] == cmr.REVISION_PERIMEE and journal[1]["revision_plus_recente_vue"] == 2
    assert journal[2]["issue"] == cmr.A_REVOIR_REVISION


def test_m5_l_ordre_normal_propose_toujours_la_revision_1_et_ecarte_la_2(monde):
    evenements.publier("m7.depenses_marketing_constatees", M7, ch.depense_marketing(revision=1, montant="100.00"),
                       evenement_id="r1")
    evenements.publier("m7.depenses_marketing_constatees", M7, ch.depense_marketing(revision=2, montant="130.00"),
                       evenement_id="r2")
    monde.repartir()
    assert _gl_debits(monde) == ["100.00"]
    assert [(m["revision"], m["issue"]) for m in monde.registre(M5, cmr.REGISTRE)] == [
        (1, cmr.BROUILLON_PROPOSE), (2, cmr.A_REVOIR_REVISION)]


def test_m5_pure_decision_revision_perimee_et_autres_relevés_inchanges():
    base = ch.depense_marketing()
    assert cmr.decision(base, {}, {base["releve_id"]: 2}) == cmr.REVISION_PERIMEE
    assert cmr.decision(base, {}, {"autre-releve": 5}) is None  # une autre révision d'un autre relevé n'y fait rien
    assert cmr.decision(base, {}, {base["releve_id"]: 1}) is None  # la même révision n'est pas périmée
    assert cmr.decision(base, {}) is None  # appel historique (sans les révisions vues)
    # taxes incluses : la raison fiscale prime, rien n'est proposé non plus
    assert cmr.decision({**base, "base_taxes": "TAXES_INCLUSES"}, {}, {base["releve_id"]: 2}) == cmr.A_COMPLETER_TAXES
