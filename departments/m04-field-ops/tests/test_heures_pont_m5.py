from pathlib import Path

import pytest
from m4_field_ops import registre as registre_mod
from m4_field_ops.outils import outils

from opsys import approbations, contexte, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import executer_atomique

RACINE = Path(__file__).resolve().parents[1]
OUTIL = "m4_lire_heures_regulieres_validees"
ORIGINE_M5 = "m05-financecore"
PERIODE = {"debut": "2026-09-14", "fin": "2026-09-14", "fuseau": "America/Montreal"}
CHAMPS_PRIVES_M5 = {
    "technicien_id",
    "periode",
    "minutes_regulieres",
    "ligne_id",
    "revision",
    "empreinte_sources",
    "couverture_complete",
    "classification_reguliere_confirmee",
}


def _points():
    return [
        {
            "type_entree": "transition_statut",
            "intervention_id": "I1",
            "statut": "en_route",
            "horodatage": "2026-09-14T12:45:00+00:00",
        },
        {
            "type_entree": "pointage",
            "intervention_id": "I1",
            "technicien_id": "tech1",
            "action": "arrivee",
            "horodatage": "2026-09-14T13:00:00+00:00",
        },
        {
            "type_entree": "pointage",
            "intervention_id": "I1",
            "technicien_id": "tech1",
            "action": "depart",
            "horodatage": "2026-09-14T15:00:00+00:00",
        },
    ]


def _creer_personnes():
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "tech1", "Technicien", "mot-de-passe-tech1-long", ["employee"])
        identite.creer_personne(cnx, "admin1", "Admin", "mot-de-passe-admin1-long", ["admin"])
        identite.creer_personne(cnx, "owner1", "Nathan", "mot-de-passe-owner1-long", ["nathan_owner"])
        identite.creer_personne(
            cnx,
            "inactive",
            "Inactive",
            "mot-de-passe-inactive-long",
            ["nathan_owner"],
            actif=False,
        )


def _ajouter_sources():
    reg = registre_mod.Registre(stockage.maillons("m04-field-ops", "principal"))
    for row in _points():
        reg.ajouter(row)


def _approuver_heures(par_nom):
    api = {"technicien_id": "tech1", **PERIODE}
    with (
        contexte.appele_par_appareil(contexte.IdentiteAppelante("admin1", "admin")),
        contexte.appeler_en_tant_que("m04-field-ops", origine="m04-field-ops"),
    ):
        preview = executer_atomique(par_nom["m4_previsualiser_heures_regulieres"], api)
    assert preview["resultat"]["accepte"] is True, preview
    proposition = preview["resultat"]["resultat"]
    arguments = {
        **api,
        "empreinte_sources": proposition["empreinte_sources"],
        "categories_minutes": proposition["categories_minutes"],
        "details_intervalles": proposition["details_intervalles"],
        "sources": proposition["sources"],
        "validation_precedente_attendue": proposition["validation_precedente"],
        "couverture_complete": True,
        "classification_reguliere_confirmee": True,
        "dispositions": {
            k: {"inclure": k == "travail", "source": "Décision humaine de test"}
            for k in ("travail", "deplacement", "pause")
        },
        "motif_correction": "Validation humaine de test.",
    }
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(
            cnx,
            "m04-field-ops",
            "m4_valider_heures_regulieres",
            arguments,
            niveau=approbations.Niveau.N4,
        )
        decision = approbations.decider(
            cnx,
            demande,
            True,
            "admin1",
            par_nom,
            {"m04-field-ops": lire_manifeste(RACINE)},
        )
    assert decision["statut"] == "executee", decision


def _identite(personne="owner1", role="nathan_owner", source="console"):
    return contexte.IdentiteAppelante(personne, role, source=source)


def _appeler(par_nom, identite_appelante, origine, args=None):
    with (
        contexte.appele_par_appareil(identite_appelante),
        contexte.appeler_en_tant_que(
            "m04-field-ops",
            origine=origine,
        ),
    ):
        return executer_atomique(par_nom[OUTIL], args or {"technicien_id": "tech1", **PERIODE})


class RegistreObserve(registre_mod.Registre):
    def __init__(self):
        super().__init__()
        self.appels_lire = 0

    def lire(self, depuis=None):
        self.appels_lire += 1
        return super().lire(depuis)


def test_nouveaux_outils_precedent_le_dernier_outil_historique():
    noms = [outil.nom for outil in outils()]
    assert noms[-1] == "m4_lire_retards_incidents"
    assert noms[-4:-1] == [
        "m4_previsualiser_heures_regulieres",
        "m4_valider_heures_regulieres",
        "m4_lire_heures_regulieres_validees",
    ]


@pytest.fixture
def contexte_paie(base_durable):
    _creer_personnes()
    _ajouter_sources()
    par_nom = {o.nom: o for o in outils()}
    _approuver_heures(par_nom)
    return par_nom


@pytest.mark.parametrize(
    ("personne", "role", "source", "origine"),
    [
        (None, None, None, ORIGINE_M5),
        ("owner1", "nathan_owner", "appareil", ORIGINE_M5),
        ("admin1", "admin", "console", ORIGINE_M5),
        ("owner1", "nathan_owner", "console", "m04-field-ops"),
        ("inactive", "nathan_owner", "console", ORIGINE_M5),
        ("owner1", "nathan_owner", "api", ORIGINE_M5),
    ],
)
def test_pont_m5_refuse_provenance_role_ou_personne_avant_lecture(
    base_durable,
    personne,
    role,
    source,
    origine,
):
    _creer_personnes()
    registre = RegistreObserve()
    par_nom = {o.nom: o for o in outils(registre_cible=registre)}
    appelante = None if personne is None else _identite(personne, role, source)
    reponse = _appeler(par_nom, appelante, origine)
    assert reponse["resultat"]["accepte"] is False
    assert "verdict" in reponse["resultat"]
    assert registre.appels_lire == 0


def test_pont_m5_rend_uniquement_projection_compacte_et_le_public_admin_reste_inchange(contexte_paie):
    par_nom = contexte_paie
    reponse = _appeler(par_nom, _identite(), ORIGINE_M5)
    assert reponse["resultat"]["accepte"] is True, reponse
    compact = reponse["resultat"]["resultat"]
    assert set(compact) == CHAMPS_PRIVES_M5
    assert compact["technicien_id"] == "tech1"
    assert compact["minutes_regulieres"] == 120
    assert compact["couverture_complete"] is True
    assert compact["classification_reguliere_confirmee"] is True

    public = _appeler(par_nom, contexte.IdentiteAppelante("admin1", "admin"), "m04-field-ops")
    assert public["resultat"]["accepte"] is True
    public_row = public["resultat"]["resultat"]
    assert "details_intervalles" in public_row and "motif_correction" in public_row
    assert {"latitude", "longitude", "salaire"}.isdisjoint(public_row)


def test_pont_m5_refuse_champs_nominatifs_forges_par_arguments(base_durable):
    _creer_personnes()
    registre = RegistreObserve()
    par_nom = {o.nom: o for o in outils(registre_cible=registre)}
    reponse = _appeler(
        par_nom,
        _identite(),
        ORIGINE_M5,
        {"technicien_id": "tech1", **PERIODE, "approuve_par": "owner1", "personne": "owner1"},
    )
    assert reponse["ok"] is False
    assert registre.appels_lire == 0


def test_pont_m5_refuse_si_pointages_changes_apres_validation(contexte_paie):
    par_nom = contexte_paie
    reg = registre_mod.Registre(stockage.maillons("m04-field-ops", "principal"))
    reg.ajouter(
        {
            "type_entree": "pointage",
            "intervention_id": "I1",
            "technicien_id": "tech1",
            "action": "depart",
            "horodatage": "2026-09-14T15:01:00+00:00",
        }
    )
    reponse = _appeler(par_nom, _identite(), ORIGINE_M5)
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-VALIDATION-INCOHERENTE"
    assert "resultat" not in reponse["resultat"]
