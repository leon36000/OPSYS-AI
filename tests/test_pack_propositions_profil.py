"""Propositions de profil de réception d'un pack (M1-A) : chargeur strict, adoption signée, rien d'actif avant.

Le pack porte, pour M1, des PROPOSITIONS : questions de qualification par service, vocabulaire des plaintes et des
urgences, destinataires de transfert (rôles), fenêtre de conversation et poids du score. Tout est `a_valider`. Ce
fichier prouve :

- le chargeur est fermé et réutilise les validateurs du profil (une proposition que le profil refuserait est refusée
  AVANT d'être adoptable) ; un pack ne livre jamais un élément « validé » ;
- choisir un pack n'active RIEN : M1 ne lit que `entreprise.yaml`, et les propositions n'y entrent que par un geste
  d'adoption signé au journal d'audit, élément par élément ;
- l'adoption n'écrase jamais ce que le propriétaire a déclaré, est idempotente, refuse un pack altéré ou non choisi.

Données FICTIVES. Ce qui n'est PAS prouvé ici : que ces propositions soient les bonnes (aucun vrai message de client) ;
voir `tests/test_m1_pack_renovation_bout_en_bout.py` pour ce que M1 en fait.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from opsys import cli, packs, taxonomie
from opsys.packs import RefusPack
from opsys.packs import manifeste as mf
from opsys.packs.codes import CODES_PACK
from opsys.stockage.schema import JOURNAL

RACINE = Path(__file__).resolve().parents[1]
PACKS = RACINE / "packs"
RENOVATION = "renovation-exterieure-qc"
GENERIQUE = "generique-pme"
ELEMENTS = ("questions_qualification", "signaux_plainte", "destinataires_transfert", "fenetre_conversation_minutes",
            "poids_score_lead")


@pytest.fixture
def copie(tmp_path):
    cible = tmp_path / "packs-copie"
    shutil.copytree(PACKS, cible)
    return cible


def sceller(dossier: Path) -> None:
    (dossier / "EMPREINTE.sha256").write_text(mf.calculer_empreinte(dossier) + "\n", encoding="utf-8")


def modifier(dossier: Path, fn) -> None:
    fichier = dossier / "pack.yaml"
    donnees = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    fn(donnees)
    fichier.write_text(yaml.safe_dump(donnees, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sceller(dossier)


def refus(dossier: Path, code: str, chemin: str | None = None) -> RefusPack:
    with pytest.raises(RefusPack) as exc:
        packs.charger_dossier(dossier)
    assert exc.value.code == code, str(exc.value)
    if chemin is not None:
        assert exc.value.chemin == chemin, str(exc.value)
    return exc.value


def _brut() -> dict:
    return yaml.safe_load((PACKS / RENOVATION / "pack.yaml").read_text(encoding="utf-8"))["propositions_profil"]


def _profil_yaml() -> dict:
    fichier = taxonomie.fichier_profil()
    return yaml.safe_load(fichier.read_text(encoding="utf-8")) if fichier.exists() else {}


def _choisir() -> None:
    packs.enregistrer_pack(RENOVATION)


# ============================================================================================ le pack livré
def test_le_pack_renovation_propose_les_cinq_elements_du_profil_de_reception():
    p = packs.charger_pack(RENOVATION).propositions_profil
    assert p is not None and tuple(p.elements) == ELEMENTS
    assert set(p.elements["questions_qualification"]) == {s.code for s in packs.charger_pack(RENOVATION).services}
    assert set(p.elements["signaux_plainte"]) == set(taxonomie.CATEGORIES_SIGNAL_PLAINTE)
    assert set(p.elements["destinataires_transfert"]) == set(taxonomie.TYPES_TRANSFERT)
    assert p.elements["fenetre_conversation_minutes"] == 30
    assert p.elements["poids_score_lead"] == {"urgence": 30, "completude": 50, "zone": 20}
    assert p.source.strip()


def test_le_texte_du_pack_ne_marque_aucun_element_comme_valide():
    """Le chargeur le refuse (voir plus bas) ; ici le YAML brut : chaque entrée dit `a_valider`, sans exception."""
    brut = _brut()
    statuts = []
    for questions in brut["questions_qualification"].values():
        statuts += [q["statut"] for q in questions]
    statuts += [c["statut"] for c in brut["signaux_plainte"].values()]
    statuts += [d["statut"] for d in brut["destinataires_transfert"].values()]
    statuts += [brut["fenetre_conversation_minutes"]["statut"], brut["poids_score_lead"]["statut"]]
    assert len(statuts) > 40 and set(statuts) == {"a_valider"}


def test_les_valeurs_chiffrees_proposees_sont_etiquetees_recommandation_non_validee():
    brut = _brut()
    for cle in ("fenetre_conversation_minutes", "poids_score_lead"):
        assert brut[cle]["etiquette"] == "recommandation, non validée" and brut[cle]["justification"].strip()


def test_les_services_des_questions_sont_ceux_du_catalogue_et_le_pack_generique_ne_propose_rien():
    assert packs.charger_pack(GENERIQUE).propositions_profil is None
    questions = packs.charger_pack(RENOVATION).propositions_profil.elements["questions_qualification"]
    assert list(questions) == list(taxonomie.codes_catalogue())
    for liste in questions.values():
        assert 3 <= len(liste) <= 10


def test_chaque_service_propose_des_questions_de_texte_et_au_moins_une_demande_de_photos():
    questions = packs.charger_pack(RENOVATION).propositions_profil.elements["questions_qualification"]
    for service, liste in questions.items():
        assert any(q.photos for q in liste), service
        assert any(not q.photos and q.mots_cles for q in liste), service
        assert len({q.code for q in liste}) == len(liste)


def test_aucune_proposition_ne_porte_de_montant_de_coordonnee_ni_de_nom_de_personne():
    """Rôles seulement ; aucun chiffre monétaire ; aucune adresse, aucun numéro."""
    texte = yaml.safe_dump(_brut(), allow_unicode=True)
    assert "@" not in texte and "$" not in texte
    assert not re.search(r"\d{3}[ -.]?\d{3}[ -.]?\d{4}", texte)
    for role in packs.charger_pack(RENOVATION).propositions_profil.elements["destinataires_transfert"].values():
        assert role in taxonomie.ROLES_DESTINATAIRES_TRANSFERT


def test_aucune_question_proposee_ne_demande_de_budget_de_prix_ou_de_montant():
    """« Budget si accepté » du prompt de Nathan n'est PAS proposé : c'est à lui de décider s'il se demande."""
    questions = packs.charger_pack(RENOVATION).propositions_profil.elements["questions_qualification"]
    for liste in questions.values():
        for q in liste:
            assert not re.search(r"budget|prix|co[uû]t|tarif|montant|dollar|payer", q.question, re.IGNORECASE), q.code


def test_chaque_question_proposee_passe_le_garde_fou_des_interdits_de_m1():
    from m1_front_office import garde_fou

    questions = packs.charger_pack(RENOVATION).propositions_profil.elements["questions_qualification"]
    for service, liste in questions.items():
        for q in liste:
            verdict = garde_fou.verifier_sortie(q.question)
            assert verdict["code"] == "OK", (service, q.code, verdict)


# ============================================================================================ le chargeur est fermé
def test_un_element_valide_dans_un_pack_est_refuse(copie):
    def f(d):
        d["propositions_profil"]["questions_qualification"]["gouttieres"][0]["statut"] = "valide"
    modifier(copie / RENOVATION, f)
    refus(copie / RENOVATION, "REJ-PACK-PROPOSITION-VALIDEE",
          "propositions_profil.questions_qualification.gouttieres[0].statut")


@pytest.mark.parametrize("chemin_cle", [
    ("signaux_plainte", "avocat"), ("destinataires_transfert", "plainte"),
    ("fenetre_conversation_minutes",), ("poids_score_lead",),
])
def test_un_statut_absent_ou_autre_que_a_valider_est_refuse_partout(copie, chemin_cle):
    def f(d):
        noeud = d["propositions_profil"]
        for c in chemin_cle:
            noeud = noeud[c]
        noeud["statut"] = "adopte"
    modifier(copie / RENOVATION, f)
    refus(copie / RENOVATION, "REJ-PACK-PROPOSITION-VALIDEE")


def test_un_statut_manquant_est_refuse(copie):
    def f(d):
        del d["propositions_profil"]["signaux_plainte"]["securite"]["statut"]
    modifier(copie / RENOVATION, f)
    refus(copie / RENOVATION, "REJ-PACK-PROPOSITION-VALIDEE")


def test_une_proposition_que_le_profil_refuserait_est_refusee_par_le_pack(copie):
    def f(d):
        del d["propositions_profil"]["questions_qualification"]["revetement"][1]["mots_cles"]
    modifier(copie / RENOVATION, f)
    e = refus(copie / RENOVATION, "REJ-PACK-PROPOSITION-INVALIDE")
    assert "mots_cles" in e.detail and e.chemin.startswith("propositions_profil.questions_qualification")


@pytest.mark.parametrize(("modif", "morceau"), [
    (lambda p: p["destinataires_transfert"]["plainte"].update(role="client"), "destinataires_transfert"),
    (lambda p: p["destinataires_transfert"]["plainte"].update(role="system_agent"), "destinataires_transfert"),
    (lambda p: p["destinataires_transfert"].update(type_inconnu={"role": "admin", "statut": "a_valider"}),
     "destinataires_transfert"),
    (lambda p: p["fenetre_conversation_minutes"].update(valeur=0), "fenetre_conversation_minutes"),
    (lambda p: p["fenetre_conversation_minutes"].update(valeur=True), "fenetre_conversation_minutes"),
    (lambda p: p["fenetre_conversation_minutes"].update(valeur=10081), "fenetre_conversation_minutes"),
    (lambda p: p["poids_score_lead"]["valeurs"].pop("zone"), "poids_score_lead"),
    (lambda p: p["poids_score_lead"]["valeurs"].update(zone=1.5), "poids_score_lead"),
    (lambda p: p["signaux_plainte"].update(categorie_inventee={"statut": "a_valider", "termes": ["abc"]}),
     "signaux_plainte"),
    (lambda p: p["signaux_plainte"]["avocat"].update(termes=["ab"]), "signaux_plainte"),
    (lambda p: p["signaux_plainte"]["avocat"].update(termes=["avocat", "AVOCAT"]), "signaux_plainte"),
    (lambda p: p["questions_qualification"]["gouttieres"].append(
        copy.deepcopy(p["questions_qualification"]["gouttieres"][0])), "questions_qualification"),
    (lambda p: p["questions_qualification"].update(
        service_inconnu=copy.deepcopy(p["questions_qualification"]["gouttieres"])), "questions_qualification"),
])
def test_chaque_valeur_refusee_par_les_validateurs_du_profil_l_est_aussi_par_le_pack(copie, modif, morceau):
    modifier(copie / RENOVATION, lambda d: modif(d["propositions_profil"]))
    e = refus(copie / RENOVATION, "REJ-PACK-PROPOSITION-INVALIDE")
    assert e.chemin.startswith(f"propositions_profil.{morceau}"), e.chemin


@pytest.mark.parametrize("cle", ["fenetre_conversation_minutes", "poids_score_lead"])
@pytest.mark.parametrize("etiquette", ["valide", "recommandation validée", "", "Recommandation, non validée"])
def test_une_valeur_chiffree_doit_porter_l_etiquette_recommandation_non_validee(copie, cle, etiquette):
    modifier(copie / RENOVATION, lambda d: d["propositions_profil"][cle].update(etiquette=etiquette))
    e = refus(copie / RENOVATION, "REJ-PACK-PROPOSITION-INVALIDE", f"propositions_profil.{cle}.etiquette")
    assert "recommandation" in e.detail


def test_une_valeur_chiffree_sans_justification_est_refusee(copie):
    modifier(copie / RENOVATION, lambda d: d["propositions_profil"]["poids_score_lead"].pop("justification"))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE")


def test_une_cle_inconnue_dans_les_propositions_est_refusee(copie):
    modifier(copie / RENOVATION, lambda d: d["propositions_profil"].update(zone_desservie=["Laval"]))
    refus(copie / RENOVATION, "REJ-PACK-CLE-INCONNUE")
    modifier(copie / RENOVATION, lambda d: d["propositions_profil"].pop("zone_desservie"))
    modifier(copie / RENOVATION, lambda d: d["propositions_profil"]["destinataires_transfert"]["ventes"]
             .update(courriel="x@example.test"))
    refus(copie / RENOVATION, "REJ-PACK-CLE-INCONNUE")


def test_un_pack_generique_qui_propose_un_profil_est_refuse(copie):
    modifier(copie / GENERIQUE, lambda d: d.update(propositions_profil=copy.deepcopy(_brut())))
    refus(copie / GENERIQUE, "REJ-PACK-GENERIQUE-NON-VIDE", "propositions_profil")


def test_une_modification_des_propositions_sans_revue_casse_l_empreinte(copie):
    fichier = copie / RENOVATION / "pack.yaml"
    texte = fichier.read_text(encoding="utf-8").replace("Quelle est l'adresse", "Quelle est l'adresse exacte", 1)
    fichier.write_text(texte, encoding="utf-8")
    refus(copie / RENOVATION, "REJ-PACK-EMPREINTE")


def test_les_codes_de_refus_nouveaux_sont_au_catalogue_et_documentes():
    nouveaux = {"REJ-PACK-PROPOSITION-INVALIDE", "REJ-PACK-PROPOSITION-VALIDEE", "REJ-PACK-ADOPTION-ELEMENT-INCONNU",
                "REJ-PACK-ADOPTION-PACK-INACTIF", "REJ-PACK-ADOPTION-ECRASE", "REJ-PACK-ADOPTION-SANS-SIGNATURE"}
    assert nouveaux <= set(CODES_PACK)
    doc = (RACINE / "docs" / "architecture" / "PACKS-SECTORIELS.md").read_text(encoding="utf-8")
    assert [c for c in nouveaux if c not in doc] == []


# ============================================================================================ rien d'actif avant
def test_choisir_un_pack_n_active_aucune_proposition_dans_le_profil():
    _choisir()
    assert _profil_yaml() == {"pack": RENOVATION}
    assert taxonomie.charger_questions_qualification()[1]["code"] == taxonomie.VERDICT_QUESTIONS_NON_CONFIGUREES
    assert taxonomie.charger_signaux_plainte()[1]["code"] == taxonomie.VERDICT_SIGNAUX_PLAINTE_NON_CONFIGURES
    assert (taxonomie.charger_destinataire_du_transfert("plainte")[1]["code"]
            == taxonomie.VERDICT_DESTINATAIRE_NON_CONFIGURE)
    assert taxonomie.charger_fenetre_conversation()[0] is None
    assert taxonomie.charger_poids_score_lead()[0] is None


def test_lire_les_propositions_n_ecrit_rien():
    _choisir()
    avant = taxonomie.fichier_profil().read_bytes()
    etat = packs.etat_des_propositions()
    assert [e["element"] for e in etat] == list(ELEMENTS) and {e["etat"] for e in etat} == {"non_adoptee"}
    assert taxonomie.fichier_profil().read_bytes() == avant


# ============================================================================================ adoption
def test_adopter_les_questions_ecrit_exactement_la_proposition_sans_toucher_aux_autres_cles(session):
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval"])
    _choisir()
    avant = _profil_yaml()
    resultat = packs.adopter_proposition("questions_qualification", par="nathan-fictif")
    assert resultat["ecrit"] is True and resultat["pack"] == RENOVATION
    apres = _profil_yaml()
    assert {k: v for k, v in apres.items() if k != "questions_qualification"} == avant
    voulu = packs.charger_pack(RENOVATION).propositions_profil.elements["questions_qualification"]
    assert taxonomie.lire_questions_qualification() == voulu
    assert "statut" not in json.dumps(apres["questions_qualification"])  # le statut du pack n'entre pas dans le profil
    assert taxonomie.charger_questions_qualification()[1] is None
    assert taxonomie.verifier_profil() == []


@pytest.mark.parametrize("element", ELEMENTS)
def test_chaque_element_s_adopte_seul_et_les_autres_restent_inactifs(element, session):
    _choisir()
    packs.adopter_proposition(element, par="nathan-fictif")
    cles = {k for k in _profil_yaml() if k != "pack"}
    assert cles == {element}
    etats = {e["element"]: e["etat"] for e in packs.etat_des_propositions()}
    assert etats[element] == "adoptee"
    assert {e for e, s in etats.items() if s == "non_adoptee"} == set(ELEMENTS) - {element}


def test_adopter_les_cinq_elements_donne_un_profil_complet_et_valide(session):
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    _choisir()
    for element in ELEMENTS:
        packs.adopter_proposition(element, par="nathan-fictif")
    assert {e["etat"] for e in packs.etat_des_propositions()} == {"adoptee"}
    assert taxonomie.verifier_profil() == []
    p = packs.charger_pack(RENOVATION).propositions_profil.elements
    assert taxonomie.lire_signaux_plainte() == p["signaux_plainte"]
    assert taxonomie.lire_destinataires_transfert() == p["destinataires_transfert"]
    assert taxonomie.lire_fenetre_conversation() == 30
    assert taxonomie.lire_poids_score_lead() == {"urgence": 30, "completude": 50, "zone": 20}


def test_l_adoption_est_signee_au_journal_d_audit_sans_texte_de_proposition(session):
    _choisir()
    packs.adopter_proposition("signaux_plainte", par="nathan-fictif")
    with session() as cnx:
        lignes = cnx.execute(select(JOURNAL.c.action, JOURNAL.c.par, JOURNAL.c.details)
                             .where(JOURNAL.c.action == "entreprise.adoption_proposition")).all()
    assert len(lignes) == 1 and lignes[0].par == "nathan-fictif"
    details = json.loads(lignes[0].details)
    reno = packs.charger_pack(RENOVATION)
    assert details["element"] == "signaux_plainte" and details["pack"] == RENOVATION
    assert details["version"] == reno.version and details["empreinte"] == reno.empreinte
    assert details["entrees"] == len(taxonomie.CATEGORIES_SIGNAL_PLAINTE)  # des comptes
    assert "avocat" not in lignes[0].details.lower() and "mise en demeure" not in lignes[0].details  # pas les mots


def test_adopter_deux_fois_est_idempotent_et_ne_journalise_pas_une_seconde_fois(session):
    _choisir()
    premier = packs.adopter_proposition("poids_score_lead", par="nathan-fictif")
    octets = taxonomie.fichier_profil().read_bytes()
    second = packs.adopter_proposition("poids_score_lead", par="nathan-fictif")
    assert premier["ecrit"] is True and second["ecrit"] is False
    assert taxonomie.fichier_profil().read_bytes() == octets
    with session() as cnx:
        n = len(cnx.execute(select(JOURNAL.c.id).where(JOURNAL.c.action == "entreprise.adoption_proposition")).all())
    assert n == 1


def test_l_adoption_n_ecrase_jamais_ce_que_le_proprietaire_a_deja_declare(session):
    _choisir()
    taxonomie.enregistrer_fenetre_conversation(90)
    avant = taxonomie.fichier_profil().read_bytes()
    with pytest.raises(RefusPack) as exc:
        packs.adopter_proposition("fenetre_conversation_minutes", par="nathan-fictif")
    assert exc.value.code == "REJ-PACK-ADOPTION-ECRASE" and "90" in exc.value.detail
    assert taxonomie.fichier_profil().read_bytes() == avant
    etats = {e["element"]: e["etat"] for e in packs.etat_des_propositions()}
    assert etats["fenetre_conversation_minutes"] == "differente"


def test_un_vocabulaire_du_proprietaire_different_n_est_pas_ecrase(session):
    _choisir()
    taxonomie.enregistrer_signaux_plainte({"avocat": ["notaire"]})
    with pytest.raises(RefusPack) as exc:
        packs.adopter_proposition("signaux_plainte", par="nathan-fictif")
    assert exc.value.code == "REJ-PACK-ADOPTION-ECRASE"
    assert taxonomie.lire_signaux_plainte() == {"avocat": ("notaire",)}


def test_adopter_sans_signature_ou_avec_un_element_inconnu_n_ecrit_rien(session):
    _choisir()
    avant = taxonomie.fichier_profil().read_bytes()
    for par in (None, "", "   "):
        with pytest.raises(RefusPack) as exc:
            packs.adopter_proposition("signaux_plainte", par=par)
        assert exc.value.code == "REJ-PACK-ADOPTION-SANS-SIGNATURE"
    for element in ("zone_desservie", "services", "pack", "../etc", "", "SIGNAUX_PLAINTE"):
        with pytest.raises(RefusPack) as exc:
            packs.adopter_proposition(element, par="nathan-fictif")
        assert exc.value.code == "REJ-PACK-ADOPTION-ELEMENT-INCONNU", element
    assert taxonomie.fichier_profil().read_bytes() == avant


def test_adopter_exige_que_le_pack_soit_celui_du_profil(session):
    with pytest.raises(RefusPack) as exc:  # aucun pack choisi : le générique est effectif, rien à adopter
        packs.adopter_proposition("signaux_plainte", par="nathan-fictif")
    assert exc.value.code == "REJ-PACK-ADOPTION-PACK-INACTIF"
    assert not taxonomie.fichier_profil().exists()
    packs.enregistrer_pack(GENERIQUE)
    with pytest.raises(RefusPack) as exc:  # le pack du profil ne propose rien
        packs.adopter_proposition("signaux_plainte", par="nathan-fictif")
    assert exc.value.code == "REJ-PACK-ADOPTION-ELEMENT-INCONNU"
    with pytest.raises(RefusPack) as exc:  # pack nommé explicitement mais autre que celui du profil
        packs.adopter_proposition("signaux_plainte", par="nathan-fictif", pack_id=RENOVATION)
    assert exc.value.code == "REJ-PACK-ADOPTION-PACK-INACTIF"
    assert "signaux_plainte" not in _profil_yaml()


def test_adopter_depuis_un_pack_altere_est_refuse_et_n_ecrit_rien(copie, monkeypatch, session):
    monkeypatch.setenv("OPSYS_PACKS", str(copie))
    _choisir()
    fichier = copie / RENOVATION / "pack.yaml"
    fichier.write_text(fichier.read_text(encoding="utf-8").replace("avocat, avocate", "avocat, avocate, tribunaux", 1),
                       encoding="utf-8")
    avant = taxonomie.fichier_profil().read_bytes()
    with pytest.raises(RefusPack) as exc:
        packs.adopter_proposition("signaux_plainte", par="nathan-fictif")
    assert exc.value.code == "REJ-PACK-EMPREINTE"
    assert taxonomie.fichier_profil().read_bytes() == avant


def test_adopter_dans_un_profil_illisible_est_un_refus_typé(session):
    _choisir()
    taxonomie.fichier_profil().write_text("pack: renovation-exterieure-qc\nzone_desservie: [x\n", encoding="utf-8")
    with pytest.raises(RefusPack) as exc:
        packs.adopter_proposition("signaux_plainte", par="nathan-fictif")
    assert exc.value.code in ("REJ-PACK-PROFIL-INVALIDE",)


def test_un_profil_invalide_deja_ecrit_pour_l_element_n_est_pas_lu_comme_absent(session):
    _choisir()
    fichier = taxonomie.fichier_profil()
    fichier.write_text(f"pack: {RENOVATION}\nfenetre_conversation_minutes: beaucoup\n", encoding="utf-8")
    with pytest.raises(RefusPack) as exc:
        packs.adopter_proposition("fenetre_conversation_minutes", par="nathan-fictif")
    assert exc.value.code == "REJ-PACK-PROFIL-INVALIDE"
    assert "beaucoup" in fichier.read_text(encoding="utf-8")


def test_une_adoption_qui_echoue_au_journal_laisse_un_etat_connu(session, monkeypatch):
    """Le journal est écrit APRÈS le profil (même patron que `taxonomie`) : si le journal échoue, l'erreur remonte et
    la relecture dit l'élément adopté (idempotent au second essai, sans doublon d'écriture)."""
    _choisir()
    import opsys.etat as etat

    def casse(*a, **k):
        raise RuntimeError("journal indisponible")

    monkeypatch.setattr(etat, "journaliser", casse)
    with pytest.raises(RuntimeError):
        packs.adopter_proposition("poids_score_lead", par="nathan-fictif")
    assert {e["element"]: e["etat"] for e in packs.etat_des_propositions()}["poids_score_lead"] == "adoptee"


# ============================================================================================ CLI
def _cli(capsys, *args):
    code = cli.main(["pack", *args])
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def test_cli_propositions_et_adopter(capsys, session):
    _choisir()
    code, sortie, _ = _cli(capsys, "propositions")
    etat = json.loads(sortie)
    assert code == 0 and etat["pack"] == RENOVATION and [e["element"] for e in etat["elements"]] == list(ELEMENTS)
    code, sortie, _ = _cli(capsys, "adopter", "destinataires_transfert", "--par", "nathan-fictif")
    assert code == 0 and json.loads(sortie)["ecrit"] is True
    etats = {e["element"]: e["etat"] for e in json.loads(_cli(capsys, "propositions")[1])["elements"]}
    assert etats["destinataires_transfert"] == "adoptee" and etats["signaux_plainte"] == "non_adoptee"


def test_cli_adopter_exige_par_et_rend_les_refus_typés_en_json(capsys, session):
    _choisir()
    with pytest.raises(SystemExit):
        cli.main(["pack", "adopter", "signaux_plainte"])  # --par est obligatoire (argparse)
    capsys.readouterr()
    code, _, erreur = _cli(capsys, "adopter", "zone_desservie", "--par", "nathan-fictif")
    assert code == 2 and json.loads(erreur)["code"] == "REJ-PACK-ADOPTION-ELEMENT-INCONNU"
    taxonomie.enregistrer_fenetre_conversation(45)
    code, _, erreur = _cli(capsys, "adopter", "fenetre_conversation_minutes", "--par", "nathan-fictif")
    assert code == 2 and json.loads(erreur)["code"] == "REJ-PACK-ADOPTION-ECRASE"
