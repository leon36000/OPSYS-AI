"""M10-02, tranche 1 : mémoire des transferts et plaintes ouverts par M1.

Deux types du bus, un seul fait par transfert : `m1.transfert_ouvert` et sa spécialisation
`m1.plainte_ouverte` peuvent arriver dans les deux ordres, le fait canonique est le même et le rejeu est un no-op.
M10 ne garde qu'une liste blanche (transfert, lead, type, catégories, niveau, instant) : JAMAIS le pseudonyme de
conversation, le canal, le déclencheur, un contact, un texte ou la charge complète. Le fait est CLIENT_PRIVATE et ne
sort que dans le paquet d'une affaire, pour M1 et M2.

Un transfert sans `lead_id` n'est jamais rattaché par déduction : le consommateur rend un résultat explicite
(`memorise: False`, `TRANSFERT-SANS-AFFAIRE`) et n'écrit rien. Les charges sont fictives (`@example.test`, 555).
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from m10_memoire import amont, confidentialite, consolidation, paquets, recherche_affaire, registre, transferts
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.evenements.schemas import erreurs_charge
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS

FICTIF = True
LEAD = "LEAD-M10-02-A"
AUTRE_LEAD = "LEAD-M10-02-B"
TRANSFERT = "tr-" + "a" * 20
AUTRE_TRANSFERT = "tr-" + "b" * 20
CONVERSATION = "pseudo-conversation-fictive-9f3a"
HORODATAGE = "2026-11-03T09:15:00-05:00"
HORODATAGE_PAQUET = "2026-11-03T10:00:00-05:00"
CATEGORIES = ["insatisfaction", "securite"]


def _charge(
    type_transfert: str = "ventes",
    lead_id: str | None = LEAD,
    transfert_id: str = TRANSFERT,
    **surcharges,
) -> dict:
    charge = {
        "evenement_id": f"m1-transfert-ouvert-{transfert_id}",
        "transfert_id": transfert_id,
        "conversation_id": CONVERSATION,
        "lead_id": lead_id,
        "type_transfert": type_transfert,
        "categories": list(CATEGORIES),
        "niveau": "N4",
        "canal": "sms",
        "declenche_par": "regles",
        "horodatage": HORODATAGE,
    }
    charge.update(surcharges)
    return charge


def _plainte(**surcharges) -> dict:
    surcharges.setdefault("type_transfert", "plainte")
    charge = _charge(**surcharges)
    charge["evenement_id"] = f"m1-plainte-ouverte-{charge['transfert_id']}"
    return charge


def _maillons(reg) -> list[dict]:
    return [m for m in reg.lire() if transferts.est_maillon(m)]


def _memoriser(reg, type_evenement, charge):
    resultat, verdict = transferts.memoriser(type_evenement, charge, reg)
    assert verdict is None, verdict
    return resultat


def _paquet(reg_evenements, affaire_id, agent):
    return paquets.assembler_paquet_contexte(
        affaire_id, HORODATAGE_PAQUET, reg_evenements, registre.Registre(), agent=agent
    )


def _evenements_paquet(paquet) -> list[dict]:
    return next(c for c in paquet["couches"] if c["nom"] == paquets.COUCHE_EVENEMENTS_RECENTS)["faits"]


# =========================================================================================
# 1. Contrat du catalogue et liste blanche
# =========================================================================================
@pytest.mark.parametrize(
    ("type_evenement", "charge"),
    [
        (transferts.TYPE_TRANSFERT_OUVERT, _charge()),
        (transferts.TYPE_PLAINTE_OUVERTE, _plainte()),
    ],
)
def test_les_charges_de_test_sont_conformes_au_catalogue_du_socle(type_evenement, charge):
    assert erreurs_charge(type_evenement, charge) == []


def test_le_resume_distingue_un_generique_d_une_specialisation_meme_si_le_type_dit_plainte():
    generique = {
        "type_evenement": transferts.TYPE_TRANSFERT_OUVERT,
        "type_transfert": "plainte",
        "niveau": "N4",
        "categories": ["insatisfaction"],
    }
    assert transferts.resume(generique).startswith("Transfert plainte ouvert")


def test_est_maillon_refuse_chaque_condition_isolement():
    valide = {
        "type_entree": "evenement_memorise",
        "type_evenement": transferts.TYPE_TRANSFERT_OUVERT,
        "transfert_id": TRANSFERT,
        "lead_id": LEAD,
    }
    assert transferts.est_maillon(valide) is True
    assert transferts.est_maillon("pas un maillon") is False
    for cas in (
        {**valide, "type_entree": "autre"},
        {**valide, "type_evenement": "m1.transfert_inconnu"},
        {**valide, "transfert_id": 123},
        {**valide, "transfert_id": "tr-xyz"},
        {**valide, "lead_id": "LEAD AVEC ESPACE"},
        {**valide, "lead_id": None},
    ):
        assert transferts.est_maillon(cas) is False, cas


def test_un_transfert_garde_une_liste_blanche_et_jamais_le_pseudonyme_de_conversation():
    reg = registre.Registre()
    charge = _charge(canal="sms<script>alerte</script>", conversation_id="PII-FICTIVE-NE-DOIT-PAS-SORTIR")

    resultat = _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, charge)

    assert resultat["maillon"] is not None
    assert resultat["ecrit"] is True
    assert resultat["deja_memorise"] is False
    maillon = resultat["maillon"]
    assert maillon["type_entree"] == "evenement_memorise"
    assert maillon["type_evenement"] == transferts.TYPE_TRANSFERT_OUVERT
    assert maillon["confidentialite"] == confidentialite.NIVEAU_CLIENT_PRIVE
    assert maillon["transfert_id"] == TRANSFERT
    assert maillon["lead_id"] == LEAD
    assert maillon["type_transfert"] == "ventes"
    assert maillon["categories"] == ["insatisfaction", "securite"]
    assert maillon["niveau"] == "N4"
    assert maillon["horodatage"] == HORODATAGE
    assert set(maillon) == {
        "type_entree", "type_evenement", "confidentialite", "transfert_id", "lead_id",
        "type_transfert", "categories", "niveau", "horodatage", "ligne_id", "precedent_ligne_id",
    }
    serialise = json.dumps(maillon, ensure_ascii=False)
    for interdit in (CONVERSATION, "PII-FICTIVE-NE-DOIT-PAS-SORTIR", "<script>", "sms", "evenement_id"):
        assert interdit not in serialise


def test_les_categories_sont_triees_et_un_doublon_ou_un_code_inconnu_est_refuse():
    reg = registre.Registre()
    resultat = _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge(categories=["securite", "insatisfaction"]))
    assert resultat["maillon"]["categories"] == ["insatisfaction", "securite"]

    for categories in (["insatisfaction", "insatisfaction"], ["inconnue"], "insatisfaction"):
        resultat, verdict = transferts.memoriser(
            transferts.TYPE_TRANSFERT_OUVERT, _charge(categories=categories), reg
        )
        assert resultat is None
        assert verdict["code"] == transferts.REJ_TRANSFERT_CHAMP_INVALIDE


@pytest.mark.parametrize(
    "categorie_non_textuelle",
    [
        ["MARQUEUR-CATEGORIE-FICTIF"],
        {"MARQUEUR-CATEGORIE-FICTIF": "VALEUR-FICTIVE"},
    ],
    ids=("liste-imbriquee", "dictionnaire-imbrique"),
)
def test_une_categorie_non_textuelle_est_refusee_sans_fuite(categorie_non_textuelle):
    reg = registre.Registre()
    charge = _charge(categories=[categorie_non_textuelle])

    resultat, verdict = transferts.memoriser(transferts.TYPE_TRANSFERT_OUVERT, charge, reg)

    assert resultat is None
    assert verdict["code"] == transferts.REJ_TRANSFERT_CHAMP_INVALIDE
    assert verdict["detail"] == "categories"
    assert "MARQUEUR-CATEGORIE-FICTIF" not in json.dumps(verdict, ensure_ascii=False)
    assert "VALEUR-FICTIVE" not in json.dumps(verdict, ensure_ascii=False)
    assert reg.lire() == []


# =========================================================================================
# 2. Contrat réel de chaque champ, refus sans recopier la valeur
# =========================================================================================
@pytest.mark.parametrize(
    "surcharges",
    [
        {"transfert_id": "tr-xyz"},
        {"lead_id": "LEAD AVEC ESPACE"},
        {"lead_id": "a" * 65},
        {"type_transfert": "inconnu"},
        {"niveau": "N9"},
        {"canal": ""},
        {"canal": "x" * 41},
        {"declenche_par": "humain"},
        {"evenement_id": ""},
        {"horodatage": "2026-11-03T09:15:00"},
        {"horodatage": 42},
    ],
)
def test_un_champ_hors_contrat_est_refuse(surcharges):
    reg = registre.Registre()
    resultat, verdict = transferts.memoriser(
        transferts.TYPE_TRANSFERT_OUVERT, {**_charge(), **surcharges}, reg
    )
    assert resultat is None, surcharges
    assert verdict["code"].startswith("REJ-TRANSFERT-")
    assert reg.lire() == []


def test_les_bornes_exactes_des_champs_texte_sont_incluses():
    reg = registre.Registre()
    assert _memoriser(
        reg, transferts.TYPE_TRANSFERT_OUVERT,
        _charge(evenement_id="e" * 128, conversation_id="c" * 200, canal="x" * 40),
    )["maillon"] is not None

    for surcharges in (
        {"evenement_id": "e" * 129},
        {"conversation_id": "c" * 201},
    ):
        resultat, verdict = transferts.memoriser(
            transferts.TYPE_TRANSFERT_OUVERT, {**_charge(), **surcharges}, registre.Registre()
        )
        assert resultat is None
        assert verdict["code"] == transferts.REJ_TRANSFERT_CHAMP_INVALIDE


def test_un_champ_manquant_ou_en_trop_est_refuse_sans_recopier_la_valeur():
    reg = registre.Registre()
    manquante = _charge()
    manquante.pop("conversation_id")
    resultat, verdict = transferts.memoriser(transferts.TYPE_TRANSFERT_OUVERT, manquante, reg)
    assert resultat is None and verdict["code"] == transferts.REJ_TRANSFERT_CHAMP_MANQUANT
    assert "conversation_id" in verdict["detail"]

    secret = "SECRET-FICTIF-INTERDIT-123456"
    en_trop = _charge(texte=secret, contact={"courriel": "client@example.test"})
    resultat, verdict = transferts.memoriser(transferts.TYPE_TRANSFERT_OUVERT, en_trop, reg)
    assert resultat is None and verdict["code"] == transferts.REJ_TRANSFERT_CHAMP_INATTENDU
    assert secret not in json.dumps(verdict, ensure_ascii=False)
    assert "client@example.test" not in json.dumps(verdict, ensure_ascii=False)
    assert reg.lire() == []


def test_la_specialisation_plainte_refuse_un_transfert_ordinaire_et_accepte_l_urgence():
    reg = registre.Registre()
    resultat, verdict = transferts.memoriser(
        transferts.TYPE_PLAINTE_OUVERTE, _plainte(type_transfert="ventes"), reg
    )
    assert resultat is None and verdict["code"] == transferts.REJ_TRANSFERT_CHAMP_INVALIDE

    resultat = _memoriser(reg, transferts.TYPE_PLAINTE_OUVERTE, _plainte(type_transfert="urgence"))
    assert resultat["maillon"]["type_evenement"] == transferts.TYPE_PLAINTE_OUVERTE
    assert resultat["maillon"]["type_transfert"] == "urgence"


def test_un_transfert_generique_de_plainte_est_deja_la_specialisation():
    reg = registre.Registre()
    resultat = _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge(type_transfert="plainte"))
    assert resultat["maillon"]["type_evenement"] == transferts.TYPE_PLAINTE_OUVERTE


# =========================================================================================
# 3. Idempotence : deux événements, un seul fait, les deux ordres, rejeu
# =========================================================================================
@pytest.mark.parametrize("ordre", [("generique", "plainte"), ("plainte", "generique")])
def test_les_deux_ordres_generique_et_plainte_donnent_un_seul_fait_identique(ordre):
    reg = registre.Registre()
    charges = {
        "generique": (transferts.TYPE_TRANSFERT_OUVERT, _charge(type_transfert="plainte")),
        "plainte": (transferts.TYPE_PLAINTE_OUVERTE, _plainte()),
    }
    for nom in ordre:
        _memoriser(reg, *charges[nom])

    maillons = _maillons(reg)
    assert len(maillons) == 1
    assert maillons[0]["type_evenement"] == transferts.TYPE_PLAINTE_OUVERTE
    assert maillons[0]["transfert_id"] == TRANSFERT

    avant = reg.lire()
    for nom in reversed(ordre):
        resultat = _memoriser(reg, *charges[nom])
        assert resultat["deja_memorise"] is True
        assert resultat["identique"] is True
    assert reg.lire() == avant


def test_la_plainte_seule_et_le_generique_seul_produisent_le_meme_fait():
    seul_generique = registre.Registre()
    seule_plainte = registre.Registre()
    _memoriser(seul_generique, transferts.TYPE_TRANSFERT_OUVERT, _charge(type_transfert="plainte"))
    _memoriser(seule_plainte, transferts.TYPE_PLAINTE_OUVERTE, _plainte())
    assert _maillons(seul_generique) == _maillons(seule_plainte)


def test_un_meme_transfert_relivre_sous_un_autre_evenement_id_est_un_no_op():
    reg = registre.Registre()
    _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge(evenement_id="m1-transfert-ouvert-rejoue"))
    _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge(evenement_id="m1-transfert-ouvert-rejoue-2"))
    assert len(_maillons(reg)) == 1


def test_un_second_fait_contradictoire_pour_le_meme_transfert_ne_deplace_jamais_l_affaire():
    reg = registre.Registre()
    _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge(lead_id=LEAD))
    resultat = _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge(lead_id=AUTRE_LEAD))
    assert resultat["identique"] is False
    assert resultat["deja_memorise"] is True
    assert len(_maillons(reg)) == 1
    assert _maillons(reg)[0]["lead_id"] == LEAD


# =========================================================================================
# 4. lead_id null : aucun rattachement par déduction, aucun fait
# =========================================================================================
def test_lead_null_ne_cree_aucun_fait_et_rend_un_resultat_explicite():
    reg = registre.Registre()
    resultat = _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge(lead_id=None))
    assert resultat["maillon"] is None
    assert resultat["rattachee"] is False
    assert resultat["verdict"] == transferts.SANS_AFFAIRE
    assert resultat["deja_memorise"] is False
    assert resultat["ecrit"] is False
    assert reg.lire() == []

    encore = _memoriser(reg, transferts.TYPE_PLAINTE_OUVERTE, _plainte(lead_id=None))
    assert encore["maillon"] is None
    assert encore["rattachee"] is False
    assert reg.lire() == []


def test_un_lead_d_opportunite_ou_mal_forme_n_est_pas_un_rattachement():
    reg = registre.Registre()
    for lead_id in (f"{LEAD}~opp~WCT-1", "LEAD\nINJECTE", ""):
        resultat, verdict = transferts.memoriser(
            transferts.TYPE_TRANSFERT_OUVERT, _charge(lead_id=lead_id), reg
        )
        assert resultat is None
        assert verdict["code"] == transferts.REJ_TRANSFERT_CHAMP_INVALIDE
    assert reg.lire() == []


# =========================================================================================
# 5. Deux affaires, deux faits : aucun identifiant d'une autre affaire dans un paquet
# =========================================================================================
def test_un_lead_valide_sans_lead_qualifie_reste_rattache_sans_inventer_son_origine():
    reg = registre.Registre()
    _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge())

    paquet = _paquet(reg, LEAD, "m01-front-office")

    assert [f["identifiant"] for f in _evenements_paquet(paquet)] == [TRANSFERT]
    assert paquet["affaire"] == {
        "connue": True,
        "origine_recue": False,
        "origine": None,
        "verdict": amont.AMONT_ORIGINE_NON_RECUE,
    }


def test_deux_transferts_sur_deux_leads_ne_se_melangent_jamais():
    reg = registre.Registre()
    _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge(lead_id=LEAD, transfert_id=TRANSFERT))
    _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge(lead_id=AUTRE_LEAD, transfert_id=AUTRE_TRANSFERT))

    paquet_a = _paquet(reg, LEAD, "m01-front-office")
    paquet_b = _paquet(reg, AUTRE_LEAD, "m02-revenue-crm")

    assert [f["identifiant"] for f in _evenements_paquet(paquet_a)] == [TRANSFERT]
    assert [f["identifiant"] for f in _evenements_paquet(paquet_b)] == [AUTRE_TRANSFERT]
    assert AUTRE_TRANSFERT not in json.dumps(paquet_a, ensure_ascii=False)
    assert TRANSFERT not in json.dumps(paquet_b, ensure_ascii=False)


# =========================================================================================
# 6. Vues autorisées : M1/M2 seulement, jamais M3, employé, inconnu, M10 ou développement
# =========================================================================================
@pytest.mark.parametrize("agent", ["m01-front-office", "m02-revenue-crm"])
def test_le_paquet_m1_et_m2_voit_le_fait_client_prive(agent):
    reg = registre.Registre()
    _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge())

    paquet = _paquet(reg, LEAD, agent)

    faits = _evenements_paquet(paquet)
    assert [f["source"] for f in faits] == ["m1.transfert_ouvert"]
    assert faits[0]["identifiant"] == TRANSFERT
    assert faits[0]["confidentialite"] == confidentialite.NIVEAU_CLIENT_PRIVE
    assert "Transfert" in faits[0]["resume"] and "insatisfaction" in faits[0]["resume"]
    assert CONVERSATION not in json.dumps(paquet, ensure_ascii=False)


def test_le_paquet_m1_montre_une_plainte_avec_sa_specialisation():
    reg = registre.Registre()
    _memoriser(reg, transferts.TYPE_PLAINTE_OUVERTE, _plainte())

    faits = _evenements_paquet(_paquet(reg, LEAD, "m01-front-office"))

    assert [f["source"] for f in faits] == ["m1.plainte_ouverte"]
    assert faits[0]["resume"].startswith("Plainte ouverte")
    assert faits[0]["confidentialite"] == confidentialite.NIVEAU_CLIENT_PRIVE


@pytest.mark.parametrize("agent", ["m03-estimation", "m04-field-ops", "m10-memoire", None])
def test_le_paquet_m3_employe_inconnu_ou_m10_ne_voit_jamais_le_fait(agent):
    reg = registre.Registre()
    _memoriser(reg, transferts.TYPE_TRANSFERT_OUVERT, _charge())

    paquet = _paquet(reg, LEAD, agent)

    assert _evenements_paquet(paquet) == []
    assert paquet["confidentialite"]["nb_retenus"] == 1
    assert TRANSFERT not in json.dumps(paquet, ensure_ascii=False)
    assert CONVERSATION not in json.dumps(paquet, ensure_ascii=False)


def test_la_recherche_publique_ne_rend_jamais_un_transfert_client_prive():
    reg_evenements, reg_affaires = registre.Registre(), registre.Registre()
    _memoriser(reg_evenements, transferts.TYPE_TRANSFERT_OUVERT, _charge(type_transfert="plainte"))

    resultat = recherche_affaire.rechercher(LEAD, "plainte", 8, 0, reg_evenements, reg_affaires)

    assert resultat["resultats"] == []
    assert TRANSFERT not in json.dumps(resultat, ensure_ascii=False)


def test_la_consolidation_d_un_jour_avec_plainte_reste_client_privee_et_invisible_de_m3():
    reg_evenements, reg_affaires = registre.Registre(), registre.Registre()
    _memoriser(reg_evenements, transferts.TYPE_TRANSFERT_OUVERT, _charge(type_transfert="plainte"))

    resultat = consolidation.consolider_affaire(
        LEAD, "2026-11-03", "2026-11-04T03:00:00-05:00", reg_evenements, reg_affaires
    )

    assert resultat["ecrit"] is True
    fait = resultat["fait"]
    assert fait["confidentialite"] == confidentialite.NIVEAU_CLIENT_PRIVE
    assert fait["resume"] == "1 plainte(s) ouverte(s)"
    assert TRANSFERT not in fait["resume"]

    paquet_m1 = _paquet_avec_affaires(reg_evenements, reg_affaires, "m01-front-office")
    paquet_m3 = _paquet_avec_affaires(reg_evenements, reg_affaires, "m03-estimation")
    assert any("plainte" in f["resume"] for f in _faits_affaire(paquet_m1))
    assert _faits_affaire(paquet_m3) == []
    assert paquet_m3["confidentialite"]["nb_retenus"] >= 1


def test_la_consolidation_compte_un_transfert_ordinaire_sans_le_confondre_avec_une_plainte():
    reg_evenements, reg_affaires = registre.Registre(), registre.Registre()
    _memoriser(reg_evenements, transferts.TYPE_TRANSFERT_OUVERT, _charge(type_transfert="ventes"))

    resultat = consolidation.consolider_affaire(
        LEAD, "2026-11-03", "2026-11-04T03:00:00-05:00", reg_evenements, reg_affaires
    )

    assert resultat["fait"]["resume"] == "1 transfert(s) ouvert(s)"
    assert resultat["fait"]["confidentialite"] == confidentialite.NIVEAU_CLIENT_PRIVE


def _paquet_avec_affaires(reg_evenements, reg_affaires, agent):
    return paquets.assembler_paquet_contexte(
        LEAD, HORODATAGE_PAQUET, reg_evenements, reg_affaires, agent=agent
    )


def _faits_affaire(paquet) -> list[dict]:
    return next(c for c in paquet["couches"] if c["nom"] == paquets.COUCHE_FAITS_AFFAIRE)["faits"]


# =========================================================================================
# 7. Vrai bus : consommation, acquittement explicite, rejeu et panne transactionnelle
# =========================================================================================
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _dep_m10():
    return {"m10-memoire": charger_departements()["m10-memoire"]}


def _maillons_durables():
    return list(stockage.maillons("m10-memoire", "evenements"))


def _recevoir(evenement_id: str):
    with stockage.transaction() as cnx:
        ligne = next(
            dict(ligne) for ligne in cnx.execute(
                select(EVENEMENTS_RECUS).where(
                    EVENEMENTS_RECUS.c.evenement_id == evenement_id,
                    EVENEMENTS_RECUS.c.consommateur == "m10-memoire",
                )
            ).mappings()
        )
        ligne["resultat"] = codec.decoder(ligne["resultat"]) if ligne["resultat"] is not None else None
        return ligne


def test_le_vrai_bus_memorise_et_le_paquet_m1_montre_le_fait(base_durable):
    evenements.publier(transferts.TYPE_TRANSFERT_OUVERT, "m01-front-office", _charge(), evenement_id="evt-m10-02-1")

    resume = evenements.repartir(_dep_m10(), maintenant="2026-11-03T09:20:00-05:00")

    assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
    maillons = _maillons_durables()
    assert len(maillons) == 1
    recu = _recevoir("evt-m10-02-1")
    assert recu["statut"] == "traite"
    assert recu["resultat"]["memorise"] is True
    assert recu["resultat"]["rattachee"] is True
    assert recu["resultat"]["identifiant"] == TRANSFERT
    instantane = registre.Registre(maillons=maillons)
    paquet_m1 = _paquet(instantane, LEAD, "m01-front-office")
    paquet_m2 = _paquet(instantane, LEAD, "m02-revenue-crm")
    paquet_m3 = _paquet(instantane, LEAD, "m03-estimation")
    assert [f["identifiant"] for f in _evenements_paquet(paquet_m1)] == [TRANSFERT]
    assert [f["identifiant"] for f in _evenements_paquet(paquet_m2)] == [TRANSFERT]
    assert _evenements_paquet(paquet_m3) == []
    assert CONVERSATION not in json.dumps([paquet_m1, paquet_m2, paquet_m3], ensure_ascii=False)

    assert evenements.repartir(_dep_m10(), maintenant="2026-11-03T09:20:00-05:00") == {
        "livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert len(_maillons_durables()) == 1


def test_le_vrai_bus_acquitte_sans_ecrire_un_transfert_sans_lead_et_le_dit(base_durable):
    evenements.publier(
        transferts.TYPE_TRANSFERT_OUVERT, "m01-front-office", _charge(lead_id=None), evenement_id="evt-m10-02-null"
    )

    resume = evenements.repartir(_dep_m10(), maintenant="2026-11-03T09:20:00-05:00")

    assert resume == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert _maillons_durables() == []
    recu = _recevoir("evt-m10-02-null")
    assert recu["statut"] == "traite"
    assert recu["resultat"]["memorise"] is False
    assert recu["resultat"]["rattachee"] is False
    assert recu["resultat"]["verdict"] == transferts.SANS_AFFAIRE
    assert evenements.etat()["quarantaine"] == []


def test_une_panne_apres_ecriture_annule_le_fait_puis_le_rejeu_l_ecrit_une_seule_fois(base_durable, monkeypatch):
    evenements.publier(transferts.TYPE_TRANSFERT_OUVERT, "m01-front-office", _charge(), evenement_id="evt-m10-02-panne")
    original = transferts.memoriser
    appels = {"n": 0}

    def panne_apres_ecriture(*args, **kwargs):
        resultat = original(*args, **kwargs)
        appels["n"] += 1
        if appels["n"] == 1:
            raise RuntimeError("panne fictive après écriture")
        return resultat

    monkeypatch.setattr(transferts, "memoriser", panne_apres_ecriture)

    premier = evenements.repartir(_dep_m10(), maintenant="2026-11-03T09:20:00-05:00")
    assert premier == {"livres": 1, "traites": 0, "echecs": 1, "quarantaines": 0, "ignores": 0}
    assert _maillons_durables() == []
    assert _recevoir("evt-m10-02-panne")["statut"] == "echec"

    second = evenements.repartir(_dep_m10(), maintenant="2026-11-03T09:20:05-05:00")
    assert second == {"livres": 1, "traites": 1, "echecs": 0, "quarantaines": 0, "ignores": 0}
    assert len(_maillons_durables()) == 1
    assert _recevoir("evt-m10-02-panne")["statut"] == "traite"


def test_une_charge_hors_contrat_part_en_quarantaine_visible_sans_ecriture(base_durable):
    evenements.publier(
        transferts.TYPE_TRANSFERT_OUVERT, "m01-front-office", _charge(lead_id="LEAD AVEC ESPACE"),
        evenement_id="evt-m10-02-invalide",
    )
    maintenant = dt.datetime(2026, 11, 3, 14, 20, tzinfo=dt.UTC)
    for _ in range(5):
        evenements.repartir(_dep_m10(), maintenant=maintenant.isoformat())
        maintenant += dt.timedelta(seconds=100)

    assert _maillons_durables() == []
    quarantaine = [q for q in evenements.etat()["quarantaine"] if q["consommateur"] == "m10-memoire"]
    assert len(quarantaine) == 1
    assert "TransfertRefuse" in quarantaine[0]["derniere_erreur"]
