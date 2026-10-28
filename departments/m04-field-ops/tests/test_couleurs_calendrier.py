"""CRM-01 : repères fictifs sur vrais créneaux, sans effet opérationnel."""
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
from m4_field_ops import calendrier_civil, cedule_tournees, encodage, etats
from m4_field_ops import couleurs_calendrier as couleurs
from m4_field_ops.registre import Registre

_spec = importlib.util.spec_from_file_location(
    "fixture_couleurs_calendrier", Path(__file__).with_name("test_annotations_calendrier.py"))
pur = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pur)
FICTIF = True
AUTEUR = pur.AUTEUR
HORODATAGE = pur.pur.HORODATAGE


def arguments(ancre, couleur="bleu", revision=0):
    return {"ancre": deepcopy(ancre), "couleur": couleur, "revision_attendue": revision}


def mutation(args, cle="couleur-fictive-1"):
    return {"appareil": "console:admin.fictif", "cle": cle, "empreinte_arguments": encodage.empreinte(args)}


def ajouter(principal, registre, ancre, couleur="bleu", revision=0, cle="couleur-fictive-1", **options):
    args = arguments(ancre, couleur, revision)
    communs = {"auteur": AUTEUR, "mutation": mutation(args, cle), "horodatage": HORODATAGE}
    return couleurs.enregistrer(principal, registre, **args, **{**communs, **options})


def badge(principal, registre, ancre):
    return couleurs.resumer(principal, registre, [ancre])["resultat"]["couleurs"][0]


def historique(principal, registre, ancre, **options):
    return couleurs.lire(principal, registre, ancre["intervention_id"], **options)["resultat"]


def test_palette_fermee_pose_reset_et_principal_inchange():
    assert couleurs.PALETTE == {"aucune": "Sans repère", "bleu": "Bleu", "violet": "Violet", "vert": "Vert",
                               "rose": "Rose", "ambre": "Ambre", "gris": "Gris"}
    principal, registre, ancre, _, _ = pur.monde()
    avant = principal.lire()
    initial = badge(principal, registre, ancre)
    assert initial["couleur"] == "aucune" and initial["revision_courante"] == 0
    assert initial["source_courante"] and initial["validite"] == "date_confirmee"
    for i, couleur in enumerate(couleurs.PALETTE):
        recu = ajouter(principal, registre, ancre, couleur, i, f"palette-fictive-{i}")
        assert recu["resultat"]["couleur_id"] == registre.tete()
        assert recu["rejoue"] is False and recu["resultat"]["revision"] == i + 1
        assert badge(principal, registre, ancre)["couleur"] == couleur
    ajouter(principal, registre, ancre, "aucune", 7, "reset-fictif")
    assert badge(principal, registre, ancre)["couleur"] == "aucune"
    assert historique(principal, registre, ancre)["total"] == 8
    assert principal.lire() == avant and principal.valider_chaine() and registre.valider_chaine()
    vue = historique(principal, Registre(registre.lire()), ancre)
    assert vue["couleurs"][0]["auteur"] == AUTEUR and vue["couleurs"][0]["horodatage"] == HORODATAGE
    vue["couleurs"][0]["ancre"]["plan_id"] = "copie"
    assert historique(principal, registre, ancre)["couleurs"][0]["ancre"] == ancre


def test_report_ne_reconfirme_pas_et_redatation_ne_transfere_pas():
    principal, registre, ancre, _, _ = pur.monde()
    pur.pur._reussi(etats.transitionner(ancre["intervention_id"], "reportee", principal, HORODATAGE, motif="meteo"))
    avant = principal.lire()
    ajouter(principal, registre, ancre)
    assert principal.lire() == avant
    assert badge(principal, registre, ancre)["validite"] == "a_reconfirmer"
    pur.pur._reussi(etats.transitionner(ancre["intervention_id"], "planifiee", principal, HORODATAGE))
    assert badge(principal, registre, ancre)["validite"] == "a_reconfirmer"
    datee = calendrier_civil.confirmer(principal, ancre["plan_id"], {"0": "2030-06-10"}, 1,
                                      "admin.fictif", HORODATAGE)
    nouvelle = {**ancre, "source_ligne_id": datee["ligne_id"]}
    assert badge(principal, registre, nouvelle)["couleur"] == "aucune"
    assert badge(principal, registre, nouvelle)["revision_courante"] == 1
    assert badge(principal, registre, ancre)["couleur"] == "bleu"
    assert badge(principal, registre, ancre)["validite"] == "historique"
    avant = principal.lire(), registre.lire()
    with pytest.raises(couleurs.Refus, match="SOURCE-REMPLACEE"):
        ajouter(principal, registre, ancre, "rose", 1, "ancien-fictif")
    with pytest.raises(couleurs.Refus, match="REVISION-PERIMEE"):
        ajouter(principal, registre, nouvelle, "rose", 0, "revision-fictive")
    assert (principal.lire(), registre.lire()) == avant
    ajouter(principal, registre, nouvelle, "rose", 1, "nouvelle-fictive")
    assert [c["validite"] for c in historique(principal, registre, ancre)["couleurs"]] == [
        "historique", "date_confirmee"]


def test_rejeu_original_apres_modification_redatation_et_conflits():
    principal, registre, ancre, _, _ = pur.monde()
    recu = ajouter(principal, registre, ancre)
    ajouter(principal, registre, ancre, "vert", 1, "correction-fictive")
    calendrier_civil.confirmer(principal, ancre["plan_id"], {"0": "2030-06-10"}, 1, "admin.fictif", HORODATAGE)
    avant = principal.lire(), registre.lire()
    assert ajouter(principal, Registre(registre.lire()), ancre) == {**recu, "rejoue": True}
    with pytest.raises(couleurs.Refus, match="MUTATION-CONFLIT"):
        ajouter(principal, registre, ancre, "rose")
    with pytest.raises(couleurs.Refus, match="MUTATION-CONFLIT"):
        ajouter(principal, registre, ancre, auteur={"personne": "autre.admin.fictif", "role": "admin"})
    assert (principal.lire(), registre.lire()) == avant


def test_revision_par_intervention_et_pagination_stable():
    principal, registre, ancre, _, _ = pur.monde()
    for i in range(3):
        ajouter(principal, registre, ancre, "bleu", i, f"page-fictive-{i}")
    page = historique(principal, registre, ancre, limite=1)
    assert page["revision_max"] == 3 and page["suivant"] == 1
    ajouter(principal, registre, ancre, "gris", 3, "page-fictive-3")
    page = historique(principal, registre, ancre, decalage=1, revision_max=3)
    assert [c["revision"] for c in page["couleurs"]] == [2, 3]
    assert page["revision_courante"] == 4 and page["total"] == 3 and page["suivant"] is None
    ligne = next(item for item in calendrier_civil.lire_semaine(principal, "2030-06-03")["interventions"]
                 if item["intervention_id"] != ancre["intervention_id"])
    autre = {k: ligne[k] for k in pur.CHAMPS_ANCRE}
    assert ajouter(principal, registre, autre, cle="autre-fictif")["resultat"]["revision"] == 1
    for options in [{"limite": True}, {"limite": 0}, {"limite": 21}, {"decalage": -1},
                    {"revision_max": True}, {"revision_max": 5}]:
        with pytest.raises(couleurs.Refus):
            historique(principal, registre, ancre, **options)
    with pytest.raises(couleurs.Refus, match="INTERVENTION-INCONNUE"):
        couleurs.lire(principal, registre, "inconnue-fictive")


@pytest.mark.parametrize("valeur", ["", "bleu ", "BLEU", "red", "#fff", "<script>", "bleu\x00", "\ud800",
                                  True, 0, None, {}, ["bleu"]])
def test_palette_refuse_texte_arbitraire_et_types(valeur):
    principal, registre, ancre, _, _ = pur.monde()
    avant = principal.lire()
    with pytest.raises(couleurs.Refus):
        ajouter(principal, registre, ancre, valeur)
    assert registre.lire() == [] and principal.lire() == avant


@pytest.mark.parametrize("revision", [True, -1, 1.0, "0", 10001])
def test_revision_stricte(revision):
    principal, registre, ancre, _, _ = pur.monde()
    with pytest.raises(couleurs.Refus):
        ajouter(principal, registre, ancre, revision=revision)
    assert registre.lire() == []


def test_bornes_avant_append_et_lectures_sans_troncature():
    principal, registre, ancre, _, _ = pur.monde()
    avant = principal.lire()
    with pytest.raises(couleurs.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        ajouter(principal, registre, ancre, limite_sortie=10)
    assert registre.lire() == []
    ajouter(principal, registre, ancre)
    maillons = registre.lire()
    with pytest.raises(couleurs.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        historique(principal, registre, ancre, limite_sortie=10)
    with pytest.raises(couleurs.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        couleurs.resumer(principal, registre, [ancre], limite_sortie=10)
    for ancres in [[ancre, ancre], [ancre] * 201, (ancre,)]:
        with pytest.raises(couleurs.Refus):
            couleurs.resumer(principal, registre, ancres)
    assert registre.lire() == maillons and principal.lire() == avant


def test_ancre_auteur_intention_heure_invalides():
    principal, registre, ancre, _, _ = pur.monde()
    for mauvaise in [{**ancre, "jour": 0}, {**ancre, "plan_id": "0" * 64},
                     {**ancre, "source_ligne_id": True}, {**ancre, "intervention_id": "inconnue-fictive"},
                     {**ancre, "source_application_id": ancre["source_ligne_id"]}]:
        with pytest.raises(couleurs.Refus):
            ajouter(principal, registre, mauvaise)
    for options in [{"auteur": {**AUTEUR, "role": "employee"}}, {"auteur": {**AUTEUR, "extra": True}},
                    {"horodatage": "2030-06-01T12:00:00"},
                    {"mutation": {**mutation(arguments(ancre)), "empreinte_arguments": "0" * 64}},
                    {"mutation": {**mutation(arguments(ancre)), "cle": "\ud800"}}]:
        with pytest.raises(couleurs.Refus):
            ajouter(principal, registre, ancre, **options)
    assert registre.lire() == []
    assert couleurs.refuser("ARGUMENTS")["verdict"]["code"] == "REJ-COULEUR-CALENDRIER-ARGUMENTS"


def test_corruption_hash_et_semantique_rechainee():
    principal, registre, ancre, _, _ = pur.monde()
    ajouter(principal, registre, ancre)
    original = registre.lire()[0]
    avec_hash_faux = {**original, "couleur": "vert"}
    with pytest.raises(couleurs.Refus):
        historique(principal, Registre([avec_hash_faux]), ancre)
    for changement in [{"revision": 2}, {"revision": True}, {"revision_precedente": "0" * 64},
                       {"couleur": "vert"}, {"couleur": "non-palette"}, {"extra": 1},
                       {"auteur": {**AUTEUR, "role": "employee"}},
                       {"ancre": {**ancre, "plan_id": "0" * 64}},
                       {"creneau": {**original["creneau"], "jour": False}}]:
        faux = Registre()
        faux.ajouter({**deepcopy(original), **changement})
        assert faux.valider_chaine()
        with pytest.raises(couleurs.Refus):
            historique(principal, faux, ancre)
    duplique = Registre(registre.lire())
    second = {**deepcopy(original), "revision": 2, "revision_precedente": original["ligne_id"]}
    second["mutation"]["empreinte_arguments"] = encodage.empreinte(arguments(ancre, revision=1))
    duplique.ajouter(second)
    with pytest.raises(couleurs.Refus, match="REGISTRE-INVALIDE"):
        historique(principal, duplique, ancre)
    with pytest.raises(couleurs.Refus):
        couleurs.lire(principal, principal, ancre["intervention_id"])


def test_source_application_forgee_refusee_meme_rechainee():
    principal, registre, ancre, _, _ = pur.monde()
    faux, correspondances = Registre(), {}
    for m in principal.lire():
        ancien_id = m["ligne_id"]
        if m["type_entree"] == cedule_tournees.TYPE_APPLIQUEE:
            m["empreinte_sortie"] = "0" * 64
        if m["type_entree"] == calendrier_civil.TYPE_DATEE:
            m["source_application_id"] = correspondances[m["source_application_id"]]
        correspondances[ancien_id] = faux.ajouter(m)
    mauvaise = {**ancre, "source_application_id": correspondances[ancre["source_application_id"]],
                "source_ligne_id": correspondances[ancre["source_ligne_id"]]}
    assert faux.valider_chaine()
    with pytest.raises(couleurs.Refus, match="SOURCE-INVALIDE"):
        ajouter(faux, registre, mauvaise)
    assert registre.lire() == []


def test_sources_plafonnees_et_rejeu_si_registre_plein(monkeypatch):
    assert couleurs.MAX_SOURCES == 10000
    principal, registre, ancre, _, _ = pur.monde()
    for p, r in [(Registre([{}] * 10001), registre), (principal, Registre([{}] * 10001))]:
        with pytest.raises(couleurs.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
            couleurs.resumer(p, r, [])
    capacite = principal.taille()
    monkeypatch.setattr(couleurs, "MAX_SOURCES", capacite)
    original = ajouter(principal, registre, ancre)
    for i in range(1, capacite):
        ajouter(principal, registre, ancre, "vert", i, f"borne-fictive-{i}")
    avant = registre.lire()
    with pytest.raises(couleurs.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        ajouter(principal, registre, ancre, "rose", capacite, "plein-fictif")
    assert ajouter(principal, registre, ancre) == {**original, "rejoue": True}
    assert registre.lire() == avant
