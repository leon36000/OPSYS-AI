"""Agenda fictif, vrais registres M2 et propriété réelle issue de qualification/réassignation."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from m2_revenue_crm import agenda_vendeurs as agenda
from m2_revenue_crm import assignation, encodage, ingestion, statuts
from m2_revenue_crm.registre import Registre

FICTIF = True
H = "2030-01-01T12:00:00+00:00"
AUTEUR = {"personne": "admin.fictif", "role": "admin"}
BASE = {"rendez_vous_id": "rdv-fictif-1", "lead_id": "lead-fictif-1", "vendeur_id": "vendeur.un",
        "debut": "2030-06-03T09:00-04:00", "fin": "2030-06-03T10:00-04:00", "titre": "Visite fictive",
        "statut": "actif", "revision_attendue": 0}


def monde():
    principal = Registre()
    for i, owner in [(1, "vendeur.un"), (2, "vendeur.deux"), (3, "vendeur.un")]:
        lead = f"lead-fictif-{i}"
        contrat = {"lead_id": lead, "conversation_id": f"conversation-fictive-{i}",
                   "contact": {"nom": f"Client fictif {i}", "courriel": f"fictif{i}@example.test"},
                   "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False,
                   "canal": "telephone"}
        resultat, verdict = ingestion.ingerer(contrat, principal, H)
        assert resultat is not None and verdict is None
        resultat, verdict = statuts.transitionner(lead, "qualifie", principal, H, owner=owner,
            prochaine_action={"description": "Visite fictive", "echeance": "2030-06-03T09:00:00-04:00"})
        assert resultat is not None and verdict is None
    return principal, Registre()


def mutation(arguments, cle="intention-fictive-1"):
    return {"appareil": "console:admin.fictif", "cle": cle,
            "empreinte_arguments": encodage.encoder_canonique(arguments)}


def enregistrer(principal, registre, changements=None, cle="intention-fictive-1", **options):
    args = {**BASE, **(changements or {})}
    confiance = {"auteur": AUTEUR, "mutation": mutation(args, cle), "horodatage": H, **options}
    return agenda.enregistrer(principal, registre, **args, **confiance)


def lire(principal, registre, **options):
    args = {"vendeur_id": "vendeur.un", "debut_periode": "2030-06-03", "fin_periode": "2030-06-04", **options}
    return agenda.lire(principal, registre, **args)["resultat"]


def reassigner(principal):
    resultat, verdict = assignation.reassigner(principal, BASE["lead_id"], "vendeur.deux", "Réassignation fictive",
                                              H, "admin.fictif", "admin", "appareil")
    assert resultat is not None and verdict is None


def test_creation_revision_et_historique_sans_mutation_principal():
    principal, registre = monde()
    avant = principal.lire()
    recu = enregistrer(principal, registre)
    assert recu["accepte"] and recu["rejoue"] is False
    assert recu["resultat"]["revision"] == 1 and recu["resultat"]["source_id"] == registre.tete()
    assert recu["resultat"]["propriete_courante"] is True and recu["resultat"]["auteur"] == AUTEUR
    vue = lire(principal, Registre(registre.lire()))
    assert vue["rendez_vous"] == [recu["resultat"]]
    assert vue["source_tete"] == registre.tete() and vue["source_nombre"] == 1
    assert vue["fuseau"] == "America/Montreal"
    enregistrer(principal, registre,
                {"titre": "Révision fictive <script>texte</script>", "revision_attendue": 1}, "rev2")
    historique = agenda.historique(principal, registre, BASE["rendez_vous_id"])["resultat"]
    assert [r["revision"] for r in historique["revisions"]] == [1, 2]
    assert historique["revision_courante"] == 2
    assert principal.lire() == avant and principal.valider_chaine() and registre.valider_chaine()
    historique["revisions"][0]["auteur"]["personne"] = "copie"
    premiere = agenda.historique(principal, registre, BASE["rendez_vous_id"])["resultat"]["revisions"][0]
    assert premiere["auteur"] == AUTEUR


def test_conflit_autre_lead_meme_vendeur_et_adjacence_autre_vendeur():
    principal, registre = monde()
    enregistrer(principal, registre)
    avant = registre.lire()
    with pytest.raises(agenda.Refus, match="CONFLIT-HORAIRE"):
        enregistrer(principal, registre, {"rendez_vous_id": "autre", "lead_id": "lead-fictif-3",
                     "debut": "2030-06-03T09:30-04:00", "fin": "2030-06-03T10:30-04:00"}, "conflit")
    assert registre.lire() == avant
    enregistrer(principal, registre, {"rendez_vous_id": "adjacent", "debut": BASE["fin"],
                 "fin": "2030-06-03T11:00-04:00"}, "adjacent")
    enregistrer(principal, registre, {"rendez_vous_id": "autre-vendeur", "lead_id": "lead-fictif-2",
                 "vendeur_id": "vendeur.deux"}, "autre-vendeur")
    assert len(lire(principal, registre)["rendez_vous"]) == 2
    assert len(lire(principal, registre, vendeur_id="vendeur.deux")["rendez_vous"]) == 1


def test_reassignation_bloque_actif_reserve_creneau_mais_permet_annulation():
    principal, registre = monde()
    recu = enregistrer(principal, registre)
    reassigner(principal)
    avant = principal.lire(), registre.lire()
    assert lire(principal, registre)["rendez_vous"][0]["propriete_courante"] is False
    with pytest.raises(agenda.Refus, match="PROPRIETAIRE-MODIFIE"):
        enregistrer(principal, registre, {"revision_attendue": 1}, "modification")
    with pytest.raises(agenda.Refus, match="CONFLIT-HORAIRE"):
        enregistrer(principal, registre, {"rendez_vous_id": "autre", "lead_id": "lead-fictif-3"}, "occupe")
    assert enregistrer(principal, registre) == {**recu, "rejoue": True}
    assert (principal.lire(), registre.lire()) == avant
    annule = enregistrer(principal, registre, {"statut": "annule", "revision_attendue": 1}, "annule")
    assert annule["resultat"]["propriete_courante"] is False
    assert lire(principal, registre)["rendez_vous"][0]["statut"] == "annule"
    enregistrer(principal, registre, {"rendez_vous_id": "libere", "lead_id": "lead-fictif-3"}, "libere")
    for statut in ["actif", "annule"]:
        with pytest.raises(agenda.Refus, match="ARGUMENTS"):
            enregistrer(principal, registre, {"statut": statut, "revision_attendue": 2}, "terminal-"+statut)
    assert enregistrer(principal, registre, {"statut": "annule", "revision_attendue": 1}, "annule") == {
        **annule, "rejoue": True}


def test_cas_identites_immuables_et_intention_contradictoire():
    principal, registre = monde()
    enregistrer(principal, registre)
    avant = registre.lire()
    with pytest.raises(agenda.Refus, match="REVISION-PERIMEE"):
        enregistrer(principal, registre, cle="nouvelle-intention")
    for changement in [{"lead_id": "lead-fictif-3"}, {"vendeur_id": "vendeur.deux"}]:
        with pytest.raises(agenda.Refus, match="ARGUMENTS"):
            enregistrer(principal, registre, {**changement, "revision_attendue": 1}, "immutabilite")
    with pytest.raises(agenda.Refus, match="MUTATION-CONFLIT"):
        enregistrer(principal, registre, {"titre": "Autre fictif"})
    with pytest.raises(agenda.Refus, match="MUTATION-CONFLIT"):
        enregistrer(principal, registre, auteur={"personne": "autre.admin", "role": "admin"})
    assert registre.lire() == avant
    with pytest.raises(agenda.Refus, match="ARGUMENTS"):
        enregistrer(principal, registre, {"rendez_vous_id": "annulation-initiale", "statut": "annule"}, "initiale")


@pytest.mark.parametrize("debut,fin", [
    ("2030-03-10T02:30-05:00", "2030-03-10T03:30-04:00"),
    ("2030-06-03T09:00-05:00", "2030-06-03T10:00-05:00"),
    ("2030-06-03T09:00Z", "2030-06-03T10:00Z"),
    ("2030-06-03T09:00", "2030-06-03T10:00"),
    ("2030-06-03T09:00:01-04:00", "2030-06-03T10:00-04:00"),
    ("2030-06-03T09:00-04:00", "2030-06-03T09:00-04:00"),
    ("2030-06-03T09:00-04:00", "2030-06-03T08:00-04:00"),
    ("2030-06-03T00:00-04:00", "2030-06-03T12:01-04:00"),
    ("1899-06-03T09:00-04:00", "1899-06-03T10:00-04:00"),
])
def test_dates_refusees(debut, fin):
    principal, registre = monde()
    with pytest.raises(agenda.Refus, match="ARGUMENTS"):
        enregistrer(principal, registre, {"debut": debut, "fin": fin})
    assert registre.lire() == []


def test_dst_repetition_offsets_explicites_et_comparaison_utc():
    principal, registre = monde()
    enregistrer(principal, registre, {"debut": "2030-11-03T01:30-04:00", "fin": "2030-11-03T01:15-05:00"})
    with pytest.raises(agenda.Refus, match="CONFLIT-HORAIRE"):
        enregistrer(principal, registre, {"rendez_vous_id": "dst-conflit", "debut": "2030-11-03T01:00-05:00",
                     "fin": "2030-11-03T01:30-05:00"}, "dst-conflit")
    enregistrer(principal, registre, {"rendez_vous_id": "dst-adjacent", "debut": "2030-11-03T01:15:00-05:00",
                 "fin": "2030-11-03T02:00:00-05:00"}, "dst-adjacent")
    assert len(lire(principal, registre, debut_periode="2030-11-03", fin_periode="2030-11-04")["rendez_vous"]) == 2


def test_filtre_overlap_et_borne_fin_exclusive():
    principal, registre = monde()
    enregistrer(principal, registre, {"debut": "2030-06-02T23:30-04:00", "fin": "2030-06-03T00:30-04:00"})
    assert len(lire(principal, registre)["rendez_vous"]) == 1
    assert lire(principal, registre, debut_periode="2030-06-04", fin_periode="2030-06-05")["rendez_vous"] == []
    enregistrer(principal, registre, {"rendez_vous_id": "borne", "debut": "2199-12-31T09:00-05:00",
                 "fin": "2199-12-31T10:00-05:00"}, "borne")
    assert len(lire(principal, registre, debut_periode="2199-12-31", fin_periode="2200-01-01")["rendez_vous"]) == 1
    for debut, fin in [("2030-06-03", "2030-06-03"), ("2030-06-03", "2030-07-05"),
                       ("2030-6-3", "2030-06-04"), ("2200-01-01", "2200-01-02")]:
        with pytest.raises(agenda.Refus, match="ARGUMENTS"):
            lire(principal, registre, debut_periode=debut, fin_periode=fin)


@pytest.mark.parametrize("champ,valeur", [("revision_attendue", True), ("revision_attendue", -1),
    ("revision_attendue", "0"), ("revision_attendue", 0.0), ("titre", ""), ("titre", "x"*201),
    ("titre", "\ud800"), ("titre", "texte\x00"), ("titre", "texte\u202e"), ("titre", "texte\n"), ("titre", True),
    ("statut", "termine"), ("statut", True), ("lead_id", "x/y"), ("rendez_vous_id", "x y")])
def test_arguments_stricts(champ, valeur):
    principal, registre = monde()
    with pytest.raises(agenda.Refus, match="ARGUMENTS"):
        enregistrer(principal, registre, {champ: valeur})
    assert registre.lire() == []


def test_auteur_mutation_source_et_quota_refuses_avant_append():
    principal, registre = monde()
    avant = principal.lire()
    for options in [{"auteur": {"personne": "admin.fictif", "role": "seller"}},
                    {"auteur": {**AUTEUR, "extra": 1}}, {"horodatage": "2030-01-01"},
                    {"mutation": {**mutation(BASE), "empreinte_arguments": "0"*64}},
                    {"mutation": {**mutation(BASE), "cle": "x\x00"}}]:
        with pytest.raises(agenda.Refus):
            enregistrer(principal, registre, **options)
    for quota in [0, True, 10]:
        with pytest.raises(agenda.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
            enregistrer(principal, registre, limite_sortie=quota)
    assert registre.lire() == [] and principal.lire() == avant
    with pytest.raises(agenda.Refus, match="PROPRIETAIRE-MODIFIE"):
        enregistrer(principal, registre, {"lead_id": "inconnu"})
    enregistrer(principal, registre)
    for fonction in [lambda: lire(principal, registre, limite_sortie=10),
                     lambda: agenda.historique(principal, registre, BASE["rendez_vous_id"], limite_sortie=10)]:
        with pytest.raises(agenda.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
            fonction()
    assert agenda.refuser("ARGUMENTS")["verdict"]["code"] == "REJ-AGENDA-ARGUMENTS"


def test_corruptions_hash_semantique_et_intentions_dupliquees():
    principal, registre = monde()
    enregistrer(principal, registre)
    original = registre.lire()[0]
    with pytest.raises(agenda.Refus, match="SOURCE-INVALIDE"):
        lire(principal, Registre([{**original, "titre": "corruption"}]))
    for delta in [{"revision": True}, {"revision": 2}, {"revision_precedente": "0"*64},
                  {"source_principal_id": "0"*64}, {"propriete_a_ecriture": False},
                  {"statut": "annule"}, {"titre": "autre"}, {"extra": 1},
                  {"auteur": {**AUTEUR, "role": "seller"}}]:
        faux = Registre()
        faux.ajouter({**deepcopy(original), **delta})
        assert faux.valider_chaine()
        with pytest.raises(agenda.Refus, match="SOURCE-INVALIDE"):
            lire(principal, faux)
    faux = Registre(registre.lire())
    second = {**deepcopy(original), "revision": 2, "revision_precedente": original["ligne_id"]}
    second["mutation"]["empreinte_arguments"] = encodage.encoder_canonique({**BASE, "revision_attendue": 1})
    faux.ajouter(second)
    with pytest.raises(agenda.Refus, match="SOURCE-INVALIDE"):
        lire(principal, faux)
    principal_brise = principal.lire()
    principal_brise[-1]["owner"] = "autre"
    with pytest.raises(agenda.Refus, match="SOURCE-INVALIDE"):
        lire(Registre(principal_brise), registre)


def test_historique_conflictuel_rechaine_refuse_et_annulation_ancienne_coherente():
    principal, registre = monde()
    enregistrer(principal, registre)
    enregistrer(principal, registre, {"statut": "annule", "revision_attendue": 1}, "annule")
    enregistrer(principal, registre, {"rendez_vous_id": "successeur"}, "successeur")
    assert len(lire(principal, registre)["rendez_vous"]) == 2
    maillons = registre.lire()
    faux = Registre()
    faux.ajouter(maillons[0])
    faux.ajouter(maillons[2])
    assert faux.valider_chaine()
    with pytest.raises(agenda.Refus, match="SOURCE-INVALIDE"):
        lire(principal, faux)


def test_plafond_sources_avant_lecture_et_rejeu_registre_plein(monkeypatch):
    class TropGrand:
        def taille(self):
            return 10001

    principal, registre = monde()
    with pytest.raises(agenda.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        lire(TropGrand(), registre)
    with pytest.raises(agenda.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        lire(principal, TropGrand())
    capacite = principal.taille()
    monkeypatch.setattr(agenda, "MAX_SOURCES", capacite)
    original = enregistrer(principal, registre)
    for i in range(1, capacite):
        enregistrer(principal, registre, {"revision_attendue": i}, f"revision-{i}")
    avant = registre.lire()
    with pytest.raises(agenda.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        enregistrer(principal, registre, {"revision_attendue": capacite}, "plein")
    assert enregistrer(principal, registre) == {**original, "rejoue": True}
    assert registre.lire() == avant


def test_lectures_refusent_101_resultats_et_101_revisions_sans_tronquer():
    principal, registre = monde()
    debut = datetime.fromisoformat(BASE["debut"])
    for i in range(101):
        enregistrer(principal, registre, {"rendez_vous_id": f"borne-{i}",
                     "debut": (debut + timedelta(minutes=30*i)).isoformat(),
                     "fin": (debut + timedelta(minutes=30*(i+1))).isoformat()}, f"borne-{i}")
    with pytest.raises(agenda.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        lire(principal, registre, fin_periode="2030-06-06")
    versions = Registre()
    for i in range(101):
        enregistrer(principal, versions, {"revision_attendue": i}, f"historique-{i}")
    with pytest.raises(agenda.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        agenda.historique(principal, versions, BASE["rendez_vous_id"])


def test_owner_historique_ne_se_valide_pas_avec_etat_futur():
    principal, registre = monde()
    enregistrer(principal, registre)
    original = registre.lire()[0]
    reassigner(principal)
    assert lire(principal, registre)["rendez_vous"][0]["propriete_courante"] is False
    faux = Registre()
    faux.ajouter({**original, "source_principal_id": principal.tete()})
    assert faux.valider_chaine()
    with pytest.raises(agenda.Refus, match="SOURCE-INVALIDE"):
        lire(principal, faux)
    # Même en falsifiant le témoin booléen pour suivre la nouvelle source, un actif
    # ne pouvait être créé pour le vendeur précédent à ce rang de propriété.
    faux = Registre()
    faux.ajouter({**original, "source_principal_id": principal.tete(), "propriete_a_ecriture": False})
    with pytest.raises(agenda.Refus, match="SOURCE-INVALIDE"):
        lire(principal, faux)


def test_owner_legacy_libre_sur_autre_lead_ne_bloque_pas_agenda():
    principal, registre = monde()
    lead = "lead-legacy-fictif"
    contrat = {"lead_id": lead, "conversation_id": "conversation-legacy-fictive",
               "contact": {"nom": "Client legacy fictif"}, "type_travaux": "renovation_totale",
               "ville": "Québec", "urgence_declaree": False, "canal": "telephone"}
    resultat, verdict = ingestion.ingerer(contrat, principal, H)
    assert resultat is not None and verdict is None
    resultat, verdict = statuts.transitionner(lead, "qualifie", principal, H, owner="Vendeur historique fictif",
        prochaine_action={"description": "Suivi fictif", "echeance": "2030-06-03T09:00:00-04:00"})
    assert resultat is not None and verdict is None
    avant = principal.lire()
    recu = enregistrer(principal, registre)
    assert lire(principal, registre)["rendez_vous"] == [recu["resultat"]]
    assert agenda.historique(principal, registre, BASE["rendez_vous_id"])["resultat"]["revision_courante"] == 1
    with pytest.raises(agenda.Refus, match="PROPRIETAIRE-MODIFIE"):
        enregistrer(principal, registre, {"rendez_vous_id": "legacy-incompatible", "lead_id": lead}, "legacy")
    assert principal.lire() == avant


def test_rencontres_exact_lead_annulation_et_anciens_vendeurs():
    p, a = monde()
    enregistrer(p, a)
    enregistrer(p, a, {"statut": "annule", "revision_attendue": 1}, "annulation")
    reassigner(p)
    enregistrer(p, a, {"rendez_vous_id": "nouvelle-visite", "vendeur_id": "vendeur.deux"}, "nouveau")
    enregistrer(p, a, {"rendez_vous_id": "autre-projet", "lead_id": "lead-fictif-3"}, "autre")
    avant = (p.lire(), a.lire())
    page = agenda.lire_rencontres_lead(p, a, BASE["lead_id"])["resultat"]
    assert page["total"] == 2
    assert {r["statut"] for r in page["rendez_vous"]} == {"actif", "annule"}
    assert {r["vendeur_id"]: r["propriete_courante"] for r in page["rendez_vous"]} == {
        "vendeur.un": False, "vendeur.deux": True}
    assert page["source_principal"] == p.tete() and page["source_agenda"] == a.tete()
    page["rendez_vous"][0]["auteur"]["personne"] = "alteration"
    assert (p.lire(), a.lire()) == avant
    assert agenda.lire_rencontres_lead(p, a, "lead-fictif-2")["resultat"]["total"] == 0
    with pytest.raises(agenda.Refus, match="LEAD-INCONNU"):
        agenda.lire_rencontres_lead(p, a, "lead-inconnu")


def test_rencontres_pagination_source_liee_au_lead_et_deux_registres():
    p, a = monde()
    for i in range(26):
        jour = datetime(2030, 6, 1) + timedelta(days=i)
        enregistrer(p, a, {"rendez_vous_id": f"visite-{i:02}",
                          "debut": jour.strftime("%Y-%m-%dT09:00-04:00"),
                          "fin": jour.strftime("%Y-%m-%dT10:00-04:00")}, f"intention-{i}")
    premiere = agenda.lire_rencontres_lead(p, a, BASE["lead_id"])["resultat"]
    empreinte = premiere["source_empreinte"]
    suite = agenda.lire_rencontres_lead(p, a, BASE["lead_id"], 25, empreinte)["resultat"]
    assert len(premiere["rendez_vous"]) == 25 and len(suite["rendez_vous"]) == 1
    assert premiere["decalage_suivant"] == 25 and suite["decalage_suivant"] is None
    assert [r["rendez_vous_id"] for r in premiere["rendez_vous"] + suite["rendez_vous"]] == [
        f"visite-{i:02}" for i in range(26)]
    with pytest.raises(agenda.Refus, match="SOURCE-MODIFIEE"):
        agenda.lire_rencontres_lead(p, a, "lead-fictif-3", 0, empreinte)
    with pytest.raises(agenda.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        agenda.lire_rencontres_lead(p, a, BASE["lead_id"], limite_sortie=10)
    ancien = Registre(a.lire())
    enregistrer(p, a, {"rendez_vous_id": "addition", "debut": "2030-07-01T09:00-04:00",
                      "fin": "2030-07-01T10:00-04:00"}, "addition")
    with pytest.raises(agenda.Refus, match="SOURCE-MODIFIEE"):
        agenda.lire_rencontres_lead(p, a, BASE["lead_id"], 25, empreinte)
    reassigner(p)
    with pytest.raises(agenda.Refus, match="SOURCE-MODIFIEE"):
        agenda.lire_rencontres_lead(p, ancien, BASE["lead_id"], 25, empreinte)


@pytest.mark.parametrize("offset,source", [(True, ""), (25, ""), (1, ""), (-25, ""), (10025, "a" * 64),
    (0, None), (0, "G" * 64), (0, "a" * 65), ("0", ""), (0.0, "")])
def test_rencontres_refuse_pagination_invalide(offset, source):
    p, a = monde()
    with pytest.raises(agenda.Refus, match="ARGUMENTS"):
        agenda.lire_rencontres_lead(p, a, BASE["lead_id"], offset, source)


def test_rencontres_refuse_source_alteree_et_decalage_hors_liste():
    p, a = monde()
    enregistrer(p, a)
    empreinte = agenda.lire_rencontres_lead(p, a, BASE["lead_id"])["resultat"]["source_empreinte"]
    with pytest.raises(agenda.Refus, match="ARGUMENTS"):
        agenda.lire_rencontres_lead(p, a, BASE["lead_id"], 25, empreinte)
    lignes = a.lire()
    lignes[0]["titre"] = "falsifie"
    with pytest.raises(agenda.Refus, match="SOURCE-INVALIDE"):
        agenda.lire_rencontres_lead(p, Registre(lignes), BASE["lead_id"])


def test_refus_agenda_appartiennent_au_catalogue_ferme():
    from m2_revenue_crm import verdicts

    suffixes = [
        "ARGUMENTS",
        "CONFLIT-HORAIRE",
        "IDENTITE",
        "LEAD-INCONNU",
        "MUTATION-CONFLIT",
        "PROPRIETAIRE-MODIFIE",
        "REVISION-PERIMEE",
        "SORTIE-TROP-VOLUMINEUSE",
        "SOURCE-INVALIDE",
        "SOURCE-MODIFIEE",
        "SOURCES-TROP-VOLUMINEUSES",
        "ECRITURE-NON-QUALIFIEE",
        "MUTATION-ABSENTE",
        "VENDEUR-INACTIF",
        "VENDEUR-INCONNU",
    ]
    for suffixe in suffixes:
        code = agenda.refuser(suffixe)["verdict"]["code"]
        assert verdicts.est_verdict(code)
        assert code == "REJ-AGENDA-" + suffixe
    with pytest.raises(verdicts.CodeVerdictInconnu):
        agenda.refuser("INVENTE")
