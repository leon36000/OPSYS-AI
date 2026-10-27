"""CRM-02 : annotations sur vrais plans appliqués; toutes les données sont fictives."""
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
from m4_field_ops import annotations_calendrier as notes
from m4_field_ops import calendrier_civil, cedule_tournees, encodage, etats
from m4_field_ops.registre import Registre

_spec = importlib.util.spec_from_file_location(
    "fixture_annotations_calendrier", Path(__file__).with_name("test_calendrier_civil.py"))
pur = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pur)
FICTIF = True
AUTEUR = {"personne": "admin.fictif", "role": "admin"}
TEXTE = "  FICTIF : accès par la cour <script>texte</script>\r\nTéléphoner\tavant.  "
CHAMPS_ANCRE = ("intervention_id", "plan_id", "source_application_id", "source_ligne_id")


def monde():
    principal, ids, positions = pur._monde()
    plan = pur._reussi(pur._proposer(principal, ids, positions))["plan_id"]
    pur._reussi(cedule_tournees.appliquer(principal, plan, positions, pur.HORODATAGE, "admin.fictif"))
    calendrier_civil.confirmer(principal, plan, {"0": "2030-06-03"}, 0, "admin.fictif", pur.HORODATAGE)
    ligne = calendrier_civil.lire_semaine(principal, "2030-06-03")["interventions"][0]
    return principal, Registre(), {k: ligne[k] for k in CHAMPS_ANCRE}, ids, positions


def arguments(ancre, texte=TEXTE, revision=0):
    return {"ancre": deepcopy(ancre), "texte_libre": texte, "revision_attendue": revision}


def mutation(args, cle="intention-fictive"):
    return {"appareil": "console:admin.fictif", "cle": cle, "empreinte_arguments": encodage.empreinte(args)}


def ajouter(principal, registre, ancre, texte=TEXTE, revision=0, cle="intention-fictive", **options):
    args = arguments(ancre, texte, revision)
    return notes.enregistrer(principal, registre, **args, auteur=AUTEUR, mutation=mutation(args, cle),
                             horodatage=pur.HORODATAGE, **options)


def lecture(principal, registre, ancre, **options):
    return notes.lire(principal, registre, ancre["intervention_id"], **options)["resultat"]


def test_annotation_exacte_et_sources_sans_changement_principal():
    principal, registre, ancre, _, _ = monde()
    avant = principal.lire()
    badge = notes.resumer(principal, registre, [ancre])["resultat"]["annotations"][0]
    assert badge["total_ancre"] == badge["revision_courante"] == 0
    assert badge["source_courante"] and badge["validite"] == "date_confirmee"
    assert badge["creneau"]["debut"].startswith("2030-06-03T")
    resultat = ajouter(principal, registre, ancre)
    assert resultat["accepte"] and resultat["rejoue"] is False
    assert "texte_libre" not in resultat["resultat"]
    assert resultat["resultat"]["annotation_id"] == registre.tete()
    vue = lecture(principal, registre, ancre)
    assert vue["total"] == vue["revision_courante"] == vue["revision_max"] == 1
    assert vue["annotations"][0]["texte_libre"] == TEXTE
    assert vue["annotations"][0]["ancre"] == ancre
    assert vue["annotations"][0]["creneau"] == badge["creneau"]
    assert vue["annotations"][0]["auteur"] == AUTEUR
    assert vue["annotations"][0]["horodatage"] == pur.HORODATAGE
    assert principal.lire() == avant and principal.valider_chaine() and registre.valider_chaine()
    vue["annotations"][0]["ancre"]["plan_id"] = "copie-modifiee"
    assert lecture(principal, Registre(registre.lire()), ancre)["annotations"][0]["ancre"] == ancre


def test_report_orange_ne_revalide_pas_le_creneau():
    principal, registre, ancre, _, _ = monde()
    pur._reussi(etats.transitionner(ancre["intervention_id"], "reportee", principal, pur.HORODATAGE, motif="meteo"))
    avant = principal.lire()
    ajouter(principal, registre, ancre)
    ligne = lecture(principal, registre, ancre)["annotations"][0]
    assert ligne["source_courante"] and ligne["validite"] == "a_reconfirmer"
    assert principal.lire() == avant
    pur._reussi(etats.transitionner(ancre["intervention_id"], "planifiee", principal, pur.HORODATAGE))
    assert lecture(principal, registre, ancre)["annotations"][0]["validite"] == "a_reconfirmer"


def test_redatation_garde_historique_et_revision_par_intervention():
    principal, registre, ancre, _, _ = monde()
    premier = ajouter(principal, registre, ancre)
    datee = calendrier_civil.confirmer(principal, ancre["plan_id"], {"0": "2030-06-10"}, 1,
                                      "admin.fictif", pur.HORODATAGE)
    nouvelle = {**ancre, "source_ligne_id": datee["ligne_id"]}
    avant = principal.lire(), registre.lire()
    with pytest.raises(notes.Refus, match="SOURCE-REMPLACEE"):
        ajouter(principal, registre, ancre, revision=1, cle="ancienne-source-fictive")
    with pytest.raises(notes.Refus, match="REVISION-PERIMEE"):
        ajouter(principal, registre, nouvelle, cle="revision-fictive")
    assert (principal.lire(), registre.lire()) == avant
    badge = notes.resumer(principal, registre, [nouvelle])["resultat"]["annotations"][0]
    assert badge["total_ancre"] == 0 and badge["total_historique"] == badge["revision_courante"] == 1
    second = ajouter(principal, registre, nouvelle, "Nouvelle date FICTIVE", 1, "nouvelle-intention-fictive")
    assert second["resultat"]["revision"] == 2
    historique = lecture(principal, registre, nouvelle)["annotations"]
    assert [m["validite"] for m in historique] == ["historique", "date_confirmee"]
    assert historique[0]["ancre"] == ancre and historique[1]["ancre"] == nouvelle
    assert historique[0]["creneau"]["debut"].startswith("2030-06-03T")
    assert registre.lire()[1]["revision_precedente"] == premier["resultat"]["annotation_id"]


def test_plan_remplace_refuse_nouvelle_ecriture_mais_conserve_lecture():
    principal, registre, ancre, ids, positions = monde()
    ajouter(principal, registre, ancre)
    args = pur._aide._arguments(ids)
    for chantier in args["chantiers"]:
        chantier["fenetre"]["debut_min"] = 600
    plan = pur._reussi(pur._proposer(principal, ids, positions, args))["plan_id"]
    pur._reussi(cedule_tournees.appliquer(principal, plan, positions, pur.HORODATAGE, "admin.fictif"))
    avant = principal.lire(), registre.lire()
    with pytest.raises(notes.Refus, match="SOURCE-REMPLACEE"):
        ajouter(principal, registre, ancre, revision=1, cle="remplace-fictif")
    assert lecture(principal, registre, ancre)["annotations"][0]["validite"] == "historique"
    assert (principal.lire(), registre.lire()) == avant


def test_rejeu_retrouve_original_apres_correction_et_redatation():
    principal, registre, ancre, _, _ = monde()
    original = ajouter(principal, registre, ancre)
    ajouter(principal, registre, ancre, "Correction FICTIVE", 1, "correction-fictive")
    calendrier_civil.confirmer(principal, ancre["plan_id"], {"0": "2030-06-10"}, 1, "admin.fictif", pur.HORODATAGE)
    avant = principal.lire(), registre.lire()
    args = arguments(ancre)
    recu = notes.retrouver_rejeu(principal, Registre(registre.lire()), args, AUTEUR, mutation(args))
    assert recu == {**original, "rejoue": True}
    assert ajouter(principal, registre, ancre) == recu
    for autres_args, auteur in [(arguments(ancre, "Autre texte"), AUTEUR),
                               (args, {"personne": "autre.admin.fictif", "role": "admin"})]:
        with pytest.raises(notes.Refus, match="MUTATION-CONFLIT"):
            notes.retrouver_rejeu(principal, registre, autres_args, auteur, mutation(autres_args))
    assert notes.retrouver_rejeu(principal, registre, args, AUTEUR, mutation(args, "inconnue-fictive")) is None
    assert (principal.lire(), registre.lire()) == avant


@pytest.mark.parametrize("valeur", ["", "  ", "x" * 2001, "texte\x00", "texte\x7f", "texte\ud800", 1, None])
def test_texte_invalide_refuse_sans_mutation(valeur):
    principal, registre, ancre, _, _ = monde()
    avant = principal.lire()
    with pytest.raises(notes.Refus):
        ajouter(principal, registre, ancre, valeur)
    assert registre.lire() == [] and principal.lire() == avant


@pytest.mark.parametrize("revision", [True, -1, 1.0, "0", 10001])
def test_revision_strictement_entiere(revision):
    principal, registre, ancre, _, _ = monde()
    with pytest.raises(notes.Refus):
        ajouter(principal, registre, ancre, revision=revision)
    assert registre.lire() == []


def test_bornes_sortie_avant_append_et_lecture_integrale():
    principal, registre, ancre, _, _ = monde()
    texte = "😀" * 2000
    avant = principal.lire()
    with pytest.raises(notes.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        ajouter(principal, registre, ancre, texte, limite_sortie=40)
    assert registre.lire() == []
    ajouter(principal, registre, ancre, texte)
    assert lecture(principal, registre, ancre)["annotations"][0]["texte_libre"] == texte
    maillons = registre.lire()
    with pytest.raises(notes.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        lecture(principal, registre, ancre, limite_sortie=1000)
    with pytest.raises(notes.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        notes.resumer(principal, registre, [ancre], limite_sortie=40)
    assert registre.lire() == maillons and principal.lire() == avant


def test_pagination_stable_et_revision_independante_d_autre_intervention():
    principal, registre, ancre, _, _ = monde()
    for i in range(3):
        ajouter(principal, registre, ancre, f"Note FICTIVE {i}", i, f"page-fictive-{i}")
    premiere = lecture(principal, registre, ancre, limite=1)
    assert premiere["revision_max"] == 3 and premiere["suivant"] == 1
    ajouter(principal, registre, ancre, "Nouvelle FICTIVE", 3, "apres-page-fictive")
    suite = lecture(principal, registre, ancre, limite=20, decalage=1, revision_max=3)
    assert [m["revision"] for m in suite["annotations"]] == [2, 3]
    assert suite["total"] == 3 and suite["revision_courante"] == 4 and suite["suivant"] is None
    ligne = next(ligne for ligne in calendrier_civil.lire_semaine(principal, "2030-06-03")["interventions"]
                 if ligne["intervention_id"] != ancre["intervention_id"])
    autre = {k: ligne[k] for k in CHAMPS_ANCRE}
    assert ajouter(principal, registre, autre, cle="autre-intervention-fictive")["resultat"]["revision"] == 1
    with pytest.raises(notes.Refus):
        lecture(principal, registre, ancre, revision_max=5)
    for options in [{"limite": True}, {"limite": 0}, {"limite": 21}, {"decalage": -1}, {"revision_max": True}]:
        with pytest.raises(notes.Refus):
            lecture(principal, registre, ancre, **options)
    with pytest.raises(notes.Refus, match="INTERVENTION-INCONNUE"):
        notes.lire(principal, registre, "inconnue-fictive")


def test_ancre_fermee_et_sources_croisees_refusees():
    principal, registre, ancre, _, _ = monde()
    proposition = next(m for m in principal.lire() if m["type_entree"] == cedule_tournees.TYPE_PROPOSEE)
    for mauvaise in [{**ancre, "jour": 0}, {k: v for k, v in ancre.items() if k != "plan_id"},
                     {**ancre, "plan_id": "0" * 64}, {**ancre, "intervention_id": "inconnue-fictive"},
                     {**ancre, "source_application_id": proposition["ligne_id"]},
                     {**ancre, "source_ligne_id": ancre["source_application_id"]},
                     {**ancre, "source_ligne_id": True}]:
        with pytest.raises(notes.Refus):
            ajouter(principal, registre, mauvaise)
    assert registre.lire() == []
    with pytest.raises(notes.Refus):
        notes.resumer(principal, registre, [ancre, ancre])
    with pytest.raises(notes.Refus):
        notes.resumer(principal, registre, [ancre] * 201)


def test_auteur_intention_et_heure_fermes():
    principal, registre, ancre, _, _ = monde()
    args = arguments(ancre)
    communs = {"auteur": AUTEUR, "mutation": mutation(args), "horodatage": pur.HORODATAGE}
    for options in [{"auteur": {"personne": "admin.fictif", "role": "employee"}},
                    {"auteur": {**AUTEUR, "usurpe": True}}, {"auteur": {**AUTEUR, "personne": "x\x00"}},
                    {"mutation": {**mutation(args), "empreinte_arguments": "0" * 64}},
                    {"mutation": {**mutation(args), "cle": "\udfff"}},
                    {"mutation": {**mutation(args), "extra": 1}},
                    {"horodatage": "2030-01-01T00:00:00"}]:
        with pytest.raises(notes.Refus):
            notes.enregistrer(principal, registre, **args, **{**communs, **options})
    assert registre.lire() == []


def test_corruption_hash_et_semantique_meme_rechainee_refusees():
    principal, registre, ancre, _, _ = monde()
    ajouter(principal, registre, ancre)
    original = registre.lire()[0]
    alteree = deepcopy(original)
    alteree["texte_libre"] = "Altération FICTIVE"
    with pytest.raises(notes.Refus):
        lecture(principal, Registre([alteree]), ancre)
    changements = [
        {"revision": 2}, {"revision": True}, {"revision_precedente": "0" * 64},
        {"ancre": {**ancre, "plan_id": "0" * 64}}, {"extra": "interdit"},
        {"texte_libre": "Altération FICTIVE"}, {"auteur": {**AUTEUR, "role": "employee"}},
        {"creneau": {**original["creneau"], "jour": False}},
        {"creneau": {**original["creneau"], "debut": "2031-01-01T08:00:00-05:00"}},
    ]
    for changement in changements:
        faux = Registre()
        faux.ajouter({**deepcopy(original), **changement})
        assert faux.valider_chaine()
        with pytest.raises(notes.Refus):
            lecture(principal, faux, ancre)
    duplique = Registre(registre.lire())
    duplique.ajouter(original)
    with pytest.raises(notes.Refus):
        lecture(principal, duplique, ancre)
    with pytest.raises(notes.Refus):
        notes.lire(principal, principal, ancre["intervention_id"])


@pytest.mark.parametrize("defaut", ["visites_ambigues", "empreinte_application", "sortie_recalculee",
                                    "etat_modifie", "application_dupliquee", "revision_date", "fuseau_date",
                                    "report_avant_date"])
def test_sources_rechainees_mais_non_liees_refusees(defaut):
    principal, registre, ancre, _, _ = monde()
    faux, correspondances = Registre(), {}
    empreinte_sortie = None
    for m in principal.lire():
        ancien_id = m["ligne_id"]
        if defaut == "visites_ambigues" and m["type_entree"] == cedule_tournees.TYPE_PROPOSEE:
            route = next(r for r in m["sortie"]["plan"]
                         if any(v["chantier"] == ancre["intervention_id"] for v in r["visites"]))
            route["visites"].append(deepcopy(next(v for v in route["visites"]
                                                 if v["chantier"] == ancre["intervention_id"])))
        if defaut == "sortie_recalculee" and m["type_entree"] == cedule_tournees.TYPE_PROPOSEE:
            m["sortie"]["plan"][0]["visites"][0]["debut_min"] += 1
            del m["sortie"]["meta"]["empreinte_sortie"]
            empreinte_sortie = encodage.empreinte(m["sortie"])
            m["sortie"]["meta"]["empreinte_sortie"] = m["empreinte_sortie"] = empreinte_sortie
        if defaut == "etat_modifie" and m["type_entree"] == cedule_tournees.TYPE_PROPOSEE:
            m["etat"] = []
        if defaut == "empreinte_application" and m["type_entree"] == cedule_tournees.TYPE_APPLIQUEE:
            m["empreinte_sortie"] = "0" * 64
        if defaut == "sortie_recalculee" and m["type_entree"] == cedule_tournees.TYPE_APPLIQUEE:
            m["empreinte_sortie"] = empreinte_sortie
        if m["type_entree"] == calendrier_civil.TYPE_DATEE:
            if defaut == "report_avant_date":
                pur._reussi(etats.transitionner(ancre["intervention_id"], "reportee", faux,
                                               pur.HORODATAGE, motif="meteo"))
            m["source_application_id"] = correspondances[m["source_application_id"]]
            if defaut == "revision_date":
                m["revision"] = 2
            if defaut == "fuseau_date":
                m["fuseau"] = "UTC"
        correspondances[ancien_id] = faux.ajouter(m)
        if defaut == "application_dupliquee" and m["type_entree"] == cedule_tournees.TYPE_APPLIQUEE:
            faux.ajouter(m)
    mauvaise = {**ancre, "source_application_id": correspondances[ancre["source_application_id"]],
                "source_ligne_id": correspondances[ancre["source_ligne_id"]]}
    assert faux.valider_chaine()
    with pytest.raises(notes.Refus, match="SOURCE-INVALIDE"):
        ajouter(faux, registre, mauvaise)
    assert registre.lire() == []


def test_plafond_sources_refuse_avant_append_et_rejeu_reste_possible(monkeypatch):
    assert notes.MAX_SOURCES == 10000
    principal, registre, ancre, _, _ = monde()
    with pytest.raises(notes.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        lecture(principal, Registre([{}] * 10001), ancre)
    with pytest.raises(notes.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        notes.resumer(Registre([{}] * 10001), Registre(), [])
    capacite = principal.taille()
    monkeypatch.setattr(notes, "MAX_SOURCES", capacite)
    original = ajouter(principal, registre, ancre)
    for i in range(1, capacite):
        ajouter(principal, registre, ancre, "Note de borne FICTIVE", i, f"borne-fictive-{i}")
    avant = registre.lire()
    with pytest.raises(notes.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        ajouter(principal, registre, ancre, "Autre FICTIVE", capacite, "pleine-fictive")
    assert ajouter(principal, registre, ancre) == {**original, "rejoue": True}
    assert registre.lire() == avant
