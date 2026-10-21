"""PLAN T1.4-m : la propriété d'un lead dans le temps (module pur `assignation.py`, sans base).

Le propriétaire est celui de la DERNIÈRE assignation : la qualification (rang 1), puis chaque réassignation. Ces
tests fixent le module pur : la lecture du propriétaire, les identifiants et la charge du fait `m2.lead_assigne`
(dont l'absence de collision entre deux leads), les refus de `reassigner` (chacun sans maillon écrit), et
l'alignement de `acces`, de la readiness et du digest sur cette seule lecture. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import itertools

import pytest
from m2_revenue_crm import acces, assignation, digest, ingestion, readiness, registre, statuts, verdicts

FICTIF = True

H0 = "2026-09-01T09:00:00-04:00"
H1 = "2026-09-01T09:05:00-04:00"
H2 = "2026-09-02T10:00:00-04:00"
H3 = "2026-09-03T10:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
MOTIF = "Le vendeur part en congé, le dossier passe à un collègue."
CONTRAT_V1 = {
    "lead_id": "l1", "conversation_id": "c1", "contact": {"nom": "Cliente Fictive", "courriel": "c@example.test"},
    "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
}


def _ingerer(reg, lead_id):
    accuse, verdict = ingestion.ingerer({**CONTRAT_V1, "lead_id": lead_id}, reg, H0)
    assert verdict is None and accuse["statut"] == "nouveau", verdict


def _qualifier(reg, lead_id, owner):
    accuse, verdict = statuts.transitionner(
        lead_id, "qualifie", reg, H1, owner=owner, prochaine_action=ACTION)
    assert verdict is None, verdict
    return accuse


def _registre(*leads):
    """Registre en mémoire : chaque lead (lead_id, owner) ingéré, puis qualifié si `owner` n'est pas None."""
    reg = registre.Registre()
    for lead_id, owner in leads:
        _ingerer(reg, lead_id)
        if owner is not None:
            _qualifier(reg, lead_id, owner)
    return reg


def _reassigner(reg, lead_id, nouveau, horodatage=H2, motif=MOTIF, par="admin.fictif", role="admin",
                voie=assignation.VOIE_APPAREIL):
    return assignation.reassigner(reg, lead_id, nouveau, motif, horodatage, par, role, voie)


# ---------------------------------------------------------------------------------------------------------
# Identifiants et charge du fait
# ---------------------------------------------------------------------------------------------------------
def test_rang_un_est_l_identifiant_et_la_charge_de_t1_4_k2_octet_pour_octet():
    evenement_id, charge = assignation.fait_assigne("lead-1", "vendeur.un", H1)

    assert evenement_id == "m2-lead-assigne-lead-1"
    assert charge == {"lead_id": "lead-1", "proprietaire": "vendeur.un", "horodatage_assignation": H1}


def test_un_rang_superieur_porte_le_rang_et_le_precedent_sous_une_autre_famille_d_identifiants():
    evenement_id, charge = assignation.fait_assigne("lead-1", "vendeur.deux", H2, 2, "vendeur.un")

    assert evenement_id == "m2-lead-reassigne-2-lead-1"
    assert charge == {
        "lead_id": "lead-1", "proprietaire": "vendeur.deux", "horodatage_assignation": H2, "rang": 2,
        "proprietaire_precedent": "vendeur.un",
    }


def test_aucun_identifiant_ne_se_confond_avec_celui_d_un_autre_lead_ou_d_un_autre_rang():
    """`lead_id` est une chaîne libre : un lead nommé comme le suffixe d'un autre ne doit jamais partager un
    identifiant d'événement (`publier` ignorerait alors le second en silence)."""
    leads = ["foo", "2-foo", "reassigne-2-foo", "r2", "foo-r2", "2", "", "foo-2", "assigne-foo", "m2-lead-assigne-foo"]
    identifiants = [
        assignation.identifiant_evenement(lead, rang) for lead in leads for rang in (1, 2, 3, 10, 11)
    ]

    assert len(identifiants) == len(set(identifiants)) == len(leads) * 5


def test_les_deux_familles_d_identifiants_sont_disjointes_par_leur_prefixe():
    rang_un = assignation.identifiant_evenement("x", 1)
    reassignation = assignation.identifiant_evenement("x", 2)

    assert rang_un.startswith("m2-lead-assigne-") and not rang_un.startswith("m2-lead-reassigne-")
    assert reassignation.startswith("m2-lead-reassigne-2-") and not reassignation.startswith("m2-lead-assigne-")


# ---------------------------------------------------------------------------------------------------------
# Lecture du propriétaire : la dernière assignation gagne
# ---------------------------------------------------------------------------------------------------------
def test_sans_reassignation_le_proprietaire_est_l_owner_de_la_qualification_comme_avant():
    reg = _registre(("l1", " vendeur.un "), ("l2", None), ("l3", "vendeur.deux"))

    assert assignation.proprietaires(reg) == {"l1": "vendeur.un", "l3": "vendeur.deux"}
    assert assignation.proprietaire_du_lead(reg, "l2") is None  # jamais qualifié
    assert assignation.proprietaire_du_lead(reg, "inconnu") is None


def test_la_derniere_reassignation_gagne_et_la_qualification_reste_lisible():
    reg = _registre(("l1", "vendeur.un"))
    _reassigner(reg, "l1", "vendeur.deux", H2)
    _reassigner(reg, "l1", "vendeur.trois", H3)

    assert assignation.proprietaire_du_lead(reg, "l1") == "vendeur.trois"
    faits = assignation.assignations(reg)
    assert [(f["rang"], f["proprietaire"], f["precedent"]) for f in faits] == [
        (1, "vendeur.un", None), (2, "vendeur.deux", "vendeur.un"), (3, "vendeur.trois", "vendeur.deux")]
    assert [f["horodatage"] for f in faits] == [H1, H2, H3]
    qualification = next(m for m in reg.lire() if m["type_entree"] == statuts.TYPE_ENTREE)
    assert qualification["owner"] == "vendeur.un", "le maillon de qualification n'est jamais modifié"


def test_reassigner_puis_revenir_au_premier_vendeur_donne_le_rang_trois():
    reg = _registre(("l1", "vendeur.un"))
    _reassigner(reg, "l1", "vendeur.deux", H2)
    accuse, verdict = _reassigner(reg, "l1", "vendeur.un", H3)

    assert verdict is None and accuse["rang"] == 3 and accuse["proprietaire_precedent"] == "vendeur.deux"
    assert assignation.proprietaire_du_lead(reg, "l1") == "vendeur.un"


def test_les_rangs_sont_par_lead_pas_globaux():
    reg = _registre(("l1", "vendeur.un"), ("l2", "vendeur.un"))
    _reassigner(reg, "l1", "vendeur.deux", H2)
    accuse, _ = _reassigner(reg, "l2", "vendeur.deux", H3)

    assert accuse["rang"] == 2
    assert assignation.proprietaires(reg) == {"l1": "vendeur.deux", "l2": "vendeur.deux"}


def test_le_module_pur_n_ecrit_le_proprietaire_que_dans_un_maillon_de_reassignation_complet():
    reg = _registre(("l1", "vendeur.un"))
    accuse, verdict = _reassigner(reg, "l1", "vendeur.deux", H2, motif="  " + MOTIF + "  ", par=" admin.fictif ")

    assert verdict is None
    maillon = next(m for m in reg.lire() if m["type_entree"] == assignation.TYPE_ENTREE)
    assert {k: v for k, v in maillon.items() if k not in ("ligne_id", "precedent_ligne_id")} == {
        "type_entree": "reassignation", "horodatage": H2, "lead_id": "l1", "rang": 2,
        "proprietaire_precedent": "vendeur.un", "nouveau_proprietaire": "vendeur.deux", "motif": MOTIF,
        "decide_par": "admin.fictif", "decide_role": "admin", "voie": "appareil",
    }
    assert accuse["ligne_id"] == maillon["ligne_id"] and accuse["tete_chaine"] == reg.tete()
    assert reg.valider_chaine() is True


def test_un_owner_vide_blanc_ou_non_texte_n_est_le_proprietaire_de_personne():
    """Le registre peut porter des qualifications d'avant les contrôles (owner vide, blanc) : elles n'ont pas de
    propriétaire, et un lead sans propriétaire ne se réassigne pas (il se qualifie)."""
    reg = registre.Registre()
    for lead_id, owner in (("l1", ""), ("l2", "   "), ("l3", None), ("l4", 12)):
        _ingerer(reg, lead_id)
        reg.ajouter({"type_entree": statuts.TYPE_ENTREE, "horodatage": H1, "lead_id": lead_id, "statut": "qualifie",
                     "statut_precedent": "nouveau", "owner": owner})

    assert assignation.proprietaires(reg) == {} and assignation.assignations(reg) == []
    for lead_id in ("l1", "l2", "l3", "l4"):
        accuse, verdict = _reassigner(reg, lead_id, "vendeur.deux")
        assert accuse is None and verdict["code"] == "REJ-OWNER-ABSENT", lead_id


# ---------------------------------------------------------------------------------------------------------
# Refus : chacun sans aucun maillon écrit
# ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("nom", "arguments", "code"), [
    ("horodatage sans fuseau", {"horodatage": "2026-09-02T10:00:00"}, "REJ-HORODATAGE-INVALIDE"),
    ("horodatage absent", {"horodatage": None}, "REJ-HORODATAGE-INVALIDE"),
    ("motif nul", {"motif": None}, "REJ-MOTIF-ABSENT"),
    ("motif vide", {"motif": ""}, "REJ-MOTIF-ABSENT"),
    ("motif d'espaces", {"motif": "          "}, "REJ-MOTIF-ABSENT"),
    ("motif trop court", {"motif": "pars"}, "REJ-MOTIF-INVALIDE"),
    ("motif de neuf caractères", {"motif": "123456789"}, "REJ-MOTIF-INVALIDE"),
    ("motif trop long", {"motif": "x" * 501}, "REJ-MOTIF-INVALIDE"),
    ("même propriétaire", {"nouveau": "vendeur.un"}, "REJ-PROPRIETAIRE-INCHANGE"),
    ("décideur vide", {"par": ""}, "REJ-HUMAIN-REQUIS"),
    ("décideur nul", {"par": None}, "REJ-HUMAIN-REQUIS"),
    ("rôle d'un vendeur", {"role": "seller"}, "REJ-HUMAIN-REQUIS"),
    ("rôle d'un agent", {"role": "system_agent"}, "REJ-HUMAIN-REQUIS"),
    ("voie inconnue", {"voie": "agent"}, "REJ-HUMAIN-REQUIS"),
    ("voie nulle", {"voie": None}, "REJ-HUMAIN-REQUIS"),
])
def test_un_refus_est_nomme_et_n_ecrit_aucun_maillon(nom, arguments, code):
    reg = _registre(("l1", "vendeur.un"))
    taille, tete = reg.taille(), reg.tete()
    demande = {"nouveau": "vendeur.deux", **arguments}

    accuse, verdict = _reassigner(reg, "l1", **demande)

    assert accuse is None and verdict["code"] == code, nom
    assert verdicts.est_verdict(verdict["code"])
    assert (reg.taille(), reg.tete()) == (taille, tete)


def test_les_bornes_du_motif_sont_incluses():
    for longueur in (assignation.MOTIF_MIN_CARACTERES, assignation.MOTIF_MAX_CARACTERES):
        reg = _registre(("l1", "vendeur.un"))
        accuse, verdict = _reassigner(reg, "l1", "vendeur.deux", motif="m" * longueur)
        assert verdict is None and accuse["rang"] == 2, longueur


def test_un_lead_inconnu_est_refuse_avec_son_propre_code():
    reg = _registre(("l1", "vendeur.un"))

    accuse, verdict = _reassigner(reg, "fantome", "vendeur.deux")

    assert accuse is None and verdict["code"] == "REJ-LEAD-INCONNU"
    assert reg.taille() == 2


def test_un_lead_nouveau_n_a_pas_de_proprietaire_a_qui_le_reprendre():
    reg = _registre(("l1", None))
    taille = reg.taille()

    accuse, verdict = _reassigner(reg, "l1", "vendeur.deux")

    assert accuse is None and verdict["code"] == "REJ-OWNER-ABSENT" and verdict["statut"] == "nouveau"
    assert "qualifiant" in verdict["detail"] and reg.taille() == taille


def test_l_ordre_des_controles_est_decideur_horodatage_motif_lead_proprietaire_puis_identique():
    """Quand plusieurs fautes se cumulent, l'ordre détermine le verdict : le décideur d'abord, puis l'horodatage, le
    motif, le lead, son propriétaire, et enfin l'identité du nouveau propriétaire."""
    reg = _registre(("l1", "vendeur.un"), ("l2", None))
    tout_faux = {"par": "", "horodatage": "faux", "motif": ""}

    def code(lead_id, nouveau, **reste):
        _, verdict = _reassigner(reg, lead_id, nouveau, **reste)
        return verdict["code"]

    assert code("fantome", "vendeur.un", **tout_faux) == "REJ-HUMAIN-REQUIS"
    assert code("fantome", "vendeur.un", horodatage="faux", motif="") == "REJ-HORODATAGE-INVALIDE"
    assert code("fantome", "vendeur.un", motif="") == "REJ-MOTIF-ABSENT"
    assert code("fantome", "vendeur.un") == "REJ-LEAD-INCONNU"
    assert code("l2", "vendeur.un") == "REJ-OWNER-ABSENT"
    assert code("l1", "vendeur.un") == "REJ-PROPRIETAIRE-INCHANGE"


def test_un_owner_en_texte_libre_se_reassigne_a_un_vendeur_c_est_le_recours():
    """Un `owner` saisi de travers par un agent laisse le lead à personne ; la réassignation le confie à un vendeur."""
    reg = _registre(("l1", "Marc Tremblay"))
    assert acces.controler_lead(reg, "l1", acces.Acteur("vendeur.un", "seller"))["code"] == "REJ-LEAD-NON-ASSIGNE"

    accuse, verdict = _reassigner(reg, "l1", "vendeur.un")

    assert verdict is None and accuse["proprietaire_precedent"] == "Marc Tremblay"
    assert acces.controler_lead(reg, "l1", acces.Acteur("vendeur.un", "seller")) is None


# ---------------------------------------------------------------------------------------------------------
# Les lecteurs du propriétaire s'alignent sur la même lecture
# ---------------------------------------------------------------------------------------------------------
def test_acces_suit_la_reassignation_l_ancien_ne_voit_plus_le_nouveau_voit():
    reg = _registre(("l1", "vendeur.un"), ("l2", "vendeur.un"))
    ancien, nouveau, admin = (acces.Acteur("vendeur.un", "seller"), acces.Acteur("vendeur.deux", "seller"),
                              acces.Acteur("admin.fictif", "admin"))
    assert acces.leads_visibles(reg, ["l1", "l2"], ancien) == {"l1", "l2"}

    _reassigner(reg, "l1", "vendeur.deux")

    assert acces.controler_lead(reg, "l1", ancien)["code"] == "REJ-LEAD-NON-ASSIGNE"
    assert acces.controler_lead(reg, "l1", nouveau) is None
    assert acces.controler_lead(reg, "l2", ancien) is None  # l'autre lead de l'ancien n'a pas bougé
    assert acces.leads_visibles(reg, ["l1", "l2"], ancien) == {"l2"}
    assert acces.leads_visibles(reg, ["l1", "l2"], nouveau) == {"l1"}
    assert acces.leads_visibles(reg, ["l1", "l2"], admin) is None
    assert acces.proprietaires(reg) == {"l1": "vendeur.deux", "l2": "vendeur.un"}
    assert acces.proprietaire_du_lead(reg, "l1") == "vendeur.deux"


def test_la_readiness_nomme_le_proprietaire_courant_et_ne_perd_pas_sa_condition_d_interaction():
    reg = _registre(("l1", "vendeur.un"))
    reg.ajouter({"type_entree": "interaction", "horodatage": H1, "lead_id": "l1", "auteur": "vendeur.un",
                 "resume": "premier appel"})
    avant = readiness.emettre_marqueur(reg, "l1", H1)[0]
    assert avant is not None and readiness.evaluer(reg, "l1") is True

    _reassigner(reg, "l1", "vendeur.deux", H2)

    assert readiness.evaluer(reg, "l1") is True, "l'interaction postérieure à la qualification compte toujours"
    cond = readiness._extraire_conditions(reg, "l1")
    assert cond["owner"] == "vendeur.deux" and cond["owner_valide"] is True
    assert readiness.verifier_marqueur(avant, reg) is False, "un maillon de plus déplace la tête : marqueur périmé"
    apres, verdict = readiness.emettre_marqueur(reg, "l1", H3)
    assert verdict is None and readiness.verifier_marqueur(apres, reg) is True


def test_le_digest_affiche_le_proprietaire_courant_a_la_date_du_jour():
    reg = _registre(("l1", "vendeur.un"))
    _reassigner(reg, "l1", "vendeur.deux", H3)

    avant_reassignation = digest.produire_digest(reg, "2026-09-02", H2)
    apres_reassignation = digest.produire_digest(reg, "2026-09-03", H3)

    assert "l1 statut=qualifie" in avant_reassignation and "owner=vendeur.un" in avant_reassignation
    assert "owner=vendeur.deux" not in avant_reassignation, "un maillon postérieur à date_jour est ignoré"
    assert "owner=vendeur.deux" in apres_reassignation and "owner=vendeur.un" not in apres_reassignation


def test_sans_reassignation_le_digest_et_la_readiness_sont_ceux_d_avant():
    """Aucune réassignation : le même texte, octet pour octet, qu'avec un registre qui ignore le type de maillon."""
    reg = _registre(("l1", "vendeur.un"), ("l2", None))

    sortie = digest.produire_digest(reg, "2026-09-02", H2)

    assert "owner=vendeur.un" in sortie and "l2 statut=nouveau" in sortie
    assert readiness._extraire_conditions(reg, "l1")["owner"] == "vendeur.un"


# ---------------------------------------------------------------------------------------------------------
# Toutes les combinaisons de refus laissent la chaîne intacte
# ---------------------------------------------------------------------------------------------------------
def test_une_suite_de_refus_puis_un_succes_laisse_une_chaine_valide():
    reg = _registre(("l1", "vendeur.un"))
    for nouveau, motif in itertools.product(["vendeur.un", "vendeur.deux"], ["", "court", MOTIF]):
        _reassigner(reg, "l1", nouveau, motif=motif)
    reg.assert_chaine()

    reassignations = [m for m in reg.lire() if m["type_entree"] == assignation.TYPE_ENTREE]
    assert len(reassignations) == 1, "un seul de ces essais est valide (vendeur.deux avec un vrai motif)"
    assert assignation.proprietaire_du_lead(reg, "l1") == "vendeur.deux"
