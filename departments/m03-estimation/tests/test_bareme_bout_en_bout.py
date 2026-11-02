"""Scénario de bout en bout M3-C1 + M3-C2, VRAIS outils, base SQLite migrée, données fictives, horloge injectée.

Barème déclaré v1 -> estimation par ``bareme_ref`` -> reçu rejouable -> barème v2 (révision) -> l'ancienne estimation se
rejoue avec la version 1 -> estimation sans référence, périmée ou inconnue refusée avec un message lisible -> mesure
déclarée à bornes larges -> plage et revue requise (jusque dans la revue d'envoi du devis) -> mesure suffisante ->
soumission avec exclusions, hypothèses, délai et validité -> un agent qui tente un barème libre est refusé.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from html import unescape
from pathlib import Path

import pytest
from m2_preparation_estimation import marqueur_m2

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"  # la source de CE département (la copie jetable des mutations)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_bareme as cb  # noqa: E402
from m3_estimation import devis_durable, revue_devis  # noqa: E402
from m3_estimation import outils as outils_m3  # noqa: E402

from opsys import contexte, evenements, horloge, identite, stockage  # noqa: E402
from opsys.outils import executer_atomique  # noqa: E402

_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"
SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
CONTRAT = {
    "lead_id": cb.LEAD, "conversation_id": "conv-e2e-001", "type_travaux": cb.SERVICE, "ville": "Quebec",
    "canal": "formulaire", "contact": {"nom": "Durand", "telephone": "5145550000"}, "urgence_declaree": False,
}
LEAD2 = "lead-bareme-002"
PHOTOS = [{"photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7, "angle": "face",
           "reference_echelle": {"type": "porte", "dimensions_connues": True}}]


def _appeler(nom, arguments, *, qui=None, mcp=False):
    outil = next(o for o in outils_m3.outils() if o.nom == nom)

    def appel():
        if not mcp:
            return executer_atomique(outil, arguments)
        with contexte.transport_mcp():
            return executer_atomique(outil, arguments)

    if qui is None:
        reponse = appel()
    else:
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne=qui[0], role=qui[1])):
            reponse = appel()
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


PROPRIO = ("proprio.un", "admin")
VENDEUR = ("vendeur.un", "seller")


def _estimer_par_agent(**refs):
    """Un agent (transport MCP, aucune identité d'appareil) estime avec des références."""
    return _appeler("m3_estimer_projet", {
        "contrat": CONTRAT, "marqueur": marqueur_m2(cb.LEAD, contrat=CONTRAT), "photos": PHOTOS, "seuils": SEUILS,
        **refs,
    }, mcp=True)


@pytest.fixture
def instance(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-e2e-bareme.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(horloge, "maintenant", lambda: cb.MAINTENANT)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "proprio.un", "Proprio Un", _MOT_DE_PASSE, roles=["admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", _MOT_DE_PASSE, roles=["seller"])
    with stockage.transaction():
        evenements.publier(
            "m2.lead_assigne", "m02-revenue-crm",
            {"lead_id": cb.LEAD, "proprietaire": "vendeur.un", "horodatage_assignation": "2026-11-01T09:00:00-04:00"},
            evenement_id=f"m2-lead-assigne-{cb.LEAD}",
        )
    yield monkeypatch
    stockage.liberer()


def test_le_parcours_complet_du_bareme_declare_a_la_soumission(instance, monkeypatch):
    # -- 1. le propriétaire déclare le barème v1 (aucune valeur ne vient du code) --------------------------------
    v1 = _appeler("m3_declarer_bareme", {
        "bareme_id": "bareme-fictif", "version_attendue": 0, "lignes": cb.lignes(), "date_effet": cb.JOUR_EFFET_V1,
        "parametres": deepcopy(cb.PARAMETRES), "soumission": deepcopy(cb.SOUMISSION)}, qui=PROPRIO)["resultat"]
    ref_v1 = {"bareme_id": "bareme-fictif", "version": 1}

    # -- 2. un agent sans mesure ne peut pas chiffrer : le refus dit quoi déclarer ----------------------------------
    sans_mesure = _estimer_par_agent(bareme_ref=ref_v1)
    assert sans_mesure["accepte"] is False and sans_mesure["verdict"]["code"] == "REJ-MESURE-REQUISE"
    assert "m3_declarer_mesure" in sans_mesure["verdict"]["detail"]

    # -- 3. mesure à bornes LARGES (confiance moyenne), déclarée par le vendeur du lead --------------------------------
    large = _appeler("m3_declarer_mesure", {
        "mesure_id": "mesure-e2e", "revision_attendue": 0, "lead_id": cb.LEAD, "service": cb.SERVICE,
        "grandeur": "surface de revêtement", "valeur": "1200", "unite": "pi2", "borne_basse": "1020",
        "borne_haute": "1380", "methode": "plan", "confiance": "moyenne",
        "mesure_le": "2026-11-02T09:00:00+00:00", "pieces": ["plan-fictif-1"]}, qui=VENDEUR)
    assert large["accepte"] is True and large["resultat"]["auteur"] == {"personne": "vendeur.un", "role": "seller"}
    refs = {"bareme_ref": ref_v1, "mesure_ref": {"mesure_id": "mesure-e2e"}}

    # -- 4. estimation par références : plage honnête + revue humaine requise + reçu -------------------------------
    e1 = _estimer_par_agent(**refs)
    assert e1["accepte"] is True
    bloc1 = e1["declaration"]
    assert bloc1["bareme_ref"] == {
        "bareme_id": "bareme-fictif", "version": 1, "empreinte": v1["bareme_ref"]["empreinte"]}
    assert bloc1["revue_humaine_requise"] is True and bloc1["statut_prix"] == "a_revoir"
    assert (bloc1["quantite_basse"], bloc1["quantite_haute"]) == ("1020", "1380")
    intervalle1 = e1["estimation"]["intervalle_confiance"]
    # plus large que pour 1 200 pi2 exactement
    assert intervalle1["borne_basse"] < 10400 and intervalle1["borne_haute"] > 14700
    estimation_1 = e1["estimation"]["hash_maillon"]
    devis_large = _appeler("m3_creer_devis", {
        "devis_id": e1["estimation"]["devis_id"], "lead_id": cb.LEAD, "chantier_id": None, "taux_marge": "0.30",
        "horodatage": "2026-11-02T12:00:00+00:00", "estimation_source_hash": estimation_1,
        "lignes": [{"description": "Revêtement", "quantite": "1200", "unite": "pi2", "cout_unitaire": "10.00",
                    "reference_besoin_materiau": None}]})
    assert devis_large["accepte"] is True, devis_large

    # -- 5. le reçu se rejoue ---------------------------------------------------------------------------------------
    rejeu = _appeler("m3_rejouer_estimation", {"estimation_id": estimation_1}, mcp=True)["resultat"]
    assert rejeu["identique"] is True and rejeu["bareme_ref"]["version"] == 1

    # -- 6. révision : barème v2 (prix plus élevés), effet le 10 novembre -------------------------------------------
    _appeler("m3_declarer_bareme", {
        "bareme_id": "bareme-fictif", "version_attendue": 1, "date_effet": cb.JOUR_EFFET_V2,
        "lignes": cb.lignes(cout_unitaire_min="9.50", cout_unitaire_mode="11.50", cout_unitaire_max="16.00"),
        "parametres": deepcopy(cb.PARAMETRES), "soumission": deepcopy(cb.SOUMISSION)}, qui=PROPRIO)
    monkeypatch.setattr(horloge, "maintenant", lambda: cb.APRES_V2)      # le 12 novembre
    # (la validité de 30 jours de la mesure déclarée le 2 novembre n'est pas atteinte)

    # -- 7. l'ancienne estimation reste rejouable avec la version 1 ------------------------------------------------
    rejeu = _appeler("m3_rejouer_estimation", {"estimation_id": estimation_1}, mcp=True)["resultat"]
    assert rejeu["identique"] is True and rejeu["bareme_ref"]["version"] == 1
    assert rejeu["bareme_toujours_en_vigueur"] is False

    # -- 8. références périmées, inconnues, absentes : refus lisibles, rien n'est écrit -------------------------------
    perimee = _estimer_par_agent(**refs)
    assert perimee["verdict"]["code"] == "REJ-BAREME-PERIME"
    assert "référencer la version 2" in perimee["verdict"]["detail"]
    inconnue = _estimer_par_agent(bareme_ref={"bareme_id": "fantome", "version": 1}, mesure_ref=refs["mesure_ref"])
    assert inconnue["verdict"]["code"] == "REJ-BAREME-INTROUVABLE"
    assert "m3_declarer_bareme" in inconnue["verdict"]["detail"]
    aucune = _estimer_par_agent()
    assert aucune["verdict"]["code"] == "REJ-BAREME-REFERENCE-REQUISE"
    assert "m3_declarer_mesure" in aucune["verdict"]["detail"]

    # -- 9. un agent qui tente un barème libre est refusé (même avec la variable d'essai : il vient du MCP) --------
    libre = _estimer_par_agent(bareme={"version": "x", "unite": "pi2", "postes": {
        cb.SERVICE: {"cout_unitaire_min": 1.0, "cout_unitaire_max": 2.0}}}, quantite=1, plancher_rentable=0)
    assert libre["verdict"]["code"] == "REJ-BAREME-LIBRE-REFUSE"
    avec_ref_et_libre = _estimer_par_agent(**refs, quantite=5)
    assert avec_ref_et_libre["verdict"]["code"] == "REJ-BAREME-LIBRE-REFUSE"

    # -- 10. mesure précisée (révision), barème v2 en vigueur : plage étroite, aucune revue -------------------------
    precise = _appeler("m3_declarer_mesure", {
        "mesure_id": "mesure-e2e", "revision_attendue": 1, "lead_id": cb.LEAD, "service": cb.SERVICE,
        "grandeur": "surface de revêtement", "valeur": "1190", "unite": "pi2", "borne_basse": "1185",
        "borne_haute": "1195", "methode": "releve_sur_place", "confiance": "elevee",
        "mesure_le": "2026-11-12T10:00:00+00:00", "pieces": ["photo-fictive-2"]}, qui=VENDEUR)
    assert precise["accepte"] is True and precise["resultat"]["revision"] == 2
    e2 = _estimer_par_agent(bareme_ref={"bareme_id": "bareme-fictif", "version": 2}, mesure_ref=refs["mesure_ref"])
    assert e2["accepte"] is True
    bloc2 = e2["declaration"]
    assert bloc2["bareme_ref"]["version"] == 2 and bloc2["mesure_ref"]["revision"] == 2
    assert bloc2["revue_humaine_requise"] is False and bloc2["statut_prix"] == "retenu"
    assert e2["estimation"]["bareme_version"] == "bareme-fictif@v2"
    intervalle2 = e2["estimation"]["intervalle_confiance"]
    largeur1 = intervalle1["borne_haute"] - intervalle1["borne_basse"]
    assert intervalle2["borne_haute"] - intervalle2["borne_basse"] < largeur1
    # la première estimation reste exactement rejouable après la révision de la mesure ET du barème
    assert _appeler("m3_rejouer_estimation", {"estimation_id": estimation_1}, mcp=True)["resultat"]["identique"] is True

    # -- 11. la revue d'envoi du devis fondé sur la mesure à bornes larges nomme la mesure ---------------------------
    with stockage.transaction():
        devis_source, _ = devis_durable.lire_devis(outils_m3.registre_devis_production(), e1["estimation"]["devis_id"])
        revue, verdict = outils_m3._evaluer_revue_source(devis_source, None, {})
    assert verdict is None and revue["source_estimation"]["statut"] == "faits_canoniques"
    motif = next(m for m in revue["motifs"] if m["code"] == revue_devis.MESURE_INCERTAINE)
    assert motif["donnee"] == {"nom": "mesure_a_bornes_larges", "valeur": "vrai", "source": "estimation_canonique"}
    assert "revue humaine requise" in motif["explication"]

    # -- 12. second chantier, mesure suffisante : devis puis soumission complète --------------------------------------
    contrat2 = {**CONTRAT, "lead_id": LEAD2}
    with stockage.transaction():
        evenements.publier(
            "m2.lead_assigne", "m02-revenue-crm",
            {"lead_id": LEAD2, "proprietaire": "vendeur.un", "horodatage_assignation": "2026-11-01T09:00:00-04:00"},
            evenement_id=f"m2-lead-assigne-{LEAD2}")
    _appeler("m3_declarer_mesure", {
        "mesure_id": "mesure-e2e-2", "revision_attendue": 0, "lead_id": LEAD2, "service": cb.SERVICE,
        "grandeur": "surface de revêtement", "valeur": "1190", "unite": "pi2", "borne_basse": "1185",
        "borne_haute": "1195", "methode": "releve_sur_place", "confiance": "elevee",
        "mesure_le": "2026-11-12T10:00:00+00:00", "pieces": ["photo-fictive-3"]}, qui=VENDEUR)
    e3 = _appeler("m3_estimer_projet", {
        "contrat": contrat2, "marqueur": marqueur_m2(LEAD2, contrat=contrat2), "photos": PHOTOS, "seuils": SEUILS,
        "bareme_ref": {"bareme_id": "bareme-fictif", "version": 2},
        "mesure_ref": {"mesure_id": "mesure-e2e-2"}}, mcp=True)
    assert e3["accepte"] is True and e3["declaration"]["statut_prix"] == "retenu"
    devis_id = e3["estimation"]["devis_id"]
    cree = _appeler("m3_creer_devis", {
        "devis_id": devis_id, "lead_id": LEAD2, "chantier_id": None, "taux_marge": "0.30",
        "horodatage": "2026-11-12T12:00:00+00:00", "estimation_source_hash": e3["estimation"]["hash_maillon"],
        "lignes": [{"description": "Revêtement posé", "quantite": "1190", "unite": "pi2", "cout_unitaire": "11.50",
                    "reference_besoin_materiau": None}]})
    assert cree["accepte"] is True, cree
    brouillon = _appeler("m3_generer_soumission_brouillon", {"devis_id": devis_id, "format": "html"}, qui=PROPRIO)
    assert brouillon["accepte"] is True
    html = unescape(brouillon["resultat"])
    for attendu in (cb.SOUMISSION["exclusions"][0], cb.SOUMISSION["hypotheses"][0],
                    "Quantité retenue : 1190 pi2 (surface de revêtement), établie par un relevé sur place le "
                    "12 novembre 2026.",
                    "La quantité est une plage de 1185 à 1195 pi2 ; la valeur retenue est 1190 pi2.",
                    "environ 49,6 heures de main-d'œuvre",     # 1 190 pi2 x 2,5 min = 2 975 min = 49,58 h
                    "Aucune date de début ni de fin n'est promise",
                    "Cette soumission est valide jusqu'au 12 décembre 2026."):
        assert attendu in html, attendu
    for interdit in ("11.50", "0.30", "Feuille de prix", "garantie"):
        assert interdit not in html, interdit
    # le devis fondé sur la mesure à bornes larges, lui, dit sa plage (hypothèse de la mesure déclarée)
    plage = unescape(_appeler("m3_generer_soumission_brouillon", {
        "devis_id": e1["estimation"]["devis_id"], "format": "html"}, qui=PROPRIO)["resultat"])
    assert "La quantité est une plage de 1020 à 1380 pi2 ; la valeur retenue est 1200 pi2." in plage
    assert "Cette soumission est valide jusqu'au 2 décembre 2026." in plage    # la version 1 déclarée, pas la 2
