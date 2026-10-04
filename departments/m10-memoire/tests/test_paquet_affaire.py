"""PLAN T4.18-b : le paquet de contexte dit d'abord CE QU'IL SAIT de l'affaire, et quels jours l'historique omis attend
encore d'être consolidé.

Deux blocs ADDITIFS, au même niveau que `signaux` et `confidentialite` (les quatre couches et leur ordre ne bougent
pas : le core les valide) :

- `affaire` : `{connue, origine_recue, origine, verdict}`. Une affaire dont M10 n'a reçu aucun fait est dite INCONNUE
  (`AMONT-AFFAIRE-INCONNUE`), au lieu de quatre couches vides qu'on lirait comme « rien à signaler ». Une affaire dont
  on n'a pas reçu l'étape qui l'ouvre l'est aussi (`AMONT-ORIGINE-NON-RECUE`) : le lead qualifié de M1 pour un lead,
  le client associé de M2 pour l'opportunité qu'elle ouvre. L'origine est la PREMIÈRE étape de l'historique : celle que
  le budget de la couche omet en premier, donc celle que seul ce bloc garde.
- `consolidation` : `{a_consolider, nb_a_consolider}`. Les jours (au plus 10, les plus anciens d'abord) dont un
  événement a été omis par le budget de la couche des événements et qu'aucun fait durable ne résume, chacun avec
  l'affaire : `{affaire_id, jour}` est l'argument exact de `m10_consolider_affaire`.

Aucun des deux ne porte de renseignement personnel : un vocabulaire fermé (booléens, type d'événement du bus, code de
verdict) et des dates. Toutes les données sont fictives (`fictif: true`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from m10_memoire import amont, consolidation, etapes, paquets, registre, wct

FICTIF = True
LEAD = "LEAD-B-1"
OPPORTUNITE = "LEAD-B-1~opp~WCT-B-9"
CLIENT_ID = "9f" * 32
CONFIDENCES = ("Camille", "Testeur", "514 555 0142", "camille.testeur@exemple.test", "Repentigny", CLIENT_ID)
HORODATAGE_PAQUET = "2026-10-01T08:00:00-04:00"
TYPE_LEAD = etapes.TYPE_LEAD_QUALIFIE
TYPE_CLIENT = etapes.TYPE_CLIENT_ASSOCIE
TYPE_ACCEPTE = etapes.TYPE_DEVIS_ACCEPTE
CODE_INCONNUE = "AMONT-AFFAIRE-INCONNUE"
CODE_ORIGINE_NON_RECUE = "AMONT-ORIGINE-NON-RECUE"


def _jour(numero, heure="16:00:00"):
    return f"2026-09-{numero:02d}T{heure}-04:00"


LEAD_A = _jour(1, "09:15:00")
CLIENT_A = _jour(1, "09:15:30")
ACCEPTE_A = _jour(14)
TERMINE_A = _jour(15, "14:00:00")


def _lead(lead_id=LEAD, horodatage=LEAD_A):
    lead = {"lead_id": lead_id, "service": "gouttieres", "canal": "texte", "urgence_declaree": False}
    return {"lead": lead, "horodatage": horodatage}


def _client(lead_id=LEAD, horodatage=CLIENT_A):
    return {"lead_id": lead_id, "client_id": CLIENT_ID, "horodatage_association": horodatage}


def _accepte(devis_id, lead_id=LEAD, horodatage=ACCEPTE_A):
    return {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None, "horodatage_acceptation": horodatage,
        "cout_total": "812.50", "prix_total": "1249.75", "taux_marge": "0.35",
    }


def _wct(wct_id="WCT-B-1", lead_id=LEAD, horodatage=TERMINE_A):
    return {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": lead_id, "technicien_id": "TECH-1",
        "horodatage_completion": horodatage, "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90, "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"], "devis_id": None,
    }


@pytest.fixture
def registres():
    return registre.Registre(), registre.Registre()


def _memoriser(registre_evenements, type_evenement, charge):
    resultat, verdict = amont.memoriser(type_evenement, charge, registre_evenements)
    assert verdict is None, verdict
    return resultat


def _paquet(registres, affaire_id=LEAD, **options):
    registre_evenements, registre_affaires = registres
    options.setdefault("agent", "m03-estimation")
    return paquets.assembler_paquet_contexte(
        affaire_id, HORODATAGE_PAQUET, registre_evenements, registre_affaires, **options)


def _evenements(paquet):
    return next(c for c in paquet["couches"] if c["nom"] == paquets.COUCHE_EVENEMENTS_RECENTS)


def _jours_a_consolider(paquet):
    return [entree["jour"] for entree in paquet["consolidation"]["a_consolider"]]


# =========================================================================================
# 1. Le bloc `affaire` : connue ou non, origine reçue, verdict
# =========================================================================================
def test_une_affaire_dont_m10_n_a_rien_recu_est_dite_inconnue_plutot_que_quatre_couches_vides(registres):
    paquet = _paquet(registres, "LEAD-JAMAIS-VU")

    assert paquet["affaire"] == {"connue": False, "origine_recue": False, "origine": None, "verdict": CODE_INCONNUE}
    assert all(couche["vide"] for couche in paquet["couches"])
    assert paquet["consolidation"] == {"a_consolider": [], "nb_a_consolider": 0}


def test_une_affaire_connue_par_un_seul_wct_n_a_pas_son_origine_et_le_dit(registres):
    """M10 ne déduit pas d'où vient un lead : sans `m1.lead_qualifie`, il le dit (T4.18), maintenant dans le paquet."""
    wct.memoriser_wct(_wct(), registres[0])

    paquet = _paquet(registres)

    assert paquet["affaire"] == {
        "connue": True, "origine_recue": False, "origine": None, "verdict": CODE_ORIGINE_NON_RECUE}


def test_un_lead_dont_m1_a_publie_la_qualification_a_son_origine(registres):
    _memoriser(registres[0], TYPE_LEAD, _lead())

    paquet = _paquet(registres)

    assert paquet["affaire"] == {"connue": True, "origine_recue": True, "origine": TYPE_LEAD, "verdict": None}


def test_le_client_associe_seul_n_est_pas_l_origine_d_un_lead(registres):
    """Un lead saisi hors de M1 n'a que le client associé de M2 : M10 n'en fait pas une origine qu'il n'a pas reçue."""
    _memoriser(registres[0], TYPE_CLIENT, _client())

    paquet = _paquet(registres)

    assert paquet["affaire"] == {
        "connue": True, "origine_recue": False, "origine": None, "verdict": CODE_ORIGINE_NON_RECUE}


def test_l_opportunite_que_m2_ouvre_a_pour_origine_le_client_associe_jamais_le_lead_de_m1(registres):
    _memoriser(registres[0], TYPE_CLIENT, _client(OPPORTUNITE))

    paquet = _paquet(registres, OPPORTUNITE)

    assert paquet["affaire_id"] == OPPORTUNITE
    assert paquet["affaire"] == {"connue": True, "origine_recue": True, "origine": TYPE_CLIENT, "verdict": None}


def test_une_opportunite_dont_on_n_a_que_le_devis_n_a_pas_son_origine(registres):
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-B-9", OPPORTUNITE))

    paquet = _paquet(registres, OPPORTUNITE)

    assert paquet["affaire"] == {
        "connue": True, "origine_recue": False, "origine": None, "verdict": CODE_ORIGINE_NON_RECUE}


def test_l_opportunite_et_son_lead_d_origine_sont_deux_affaires_l_une_ne_rend_pas_l_autre_connue(registres):
    _memoriser(registres[0], TYPE_LEAD, _lead())

    du_lead = _paquet(registres, LEAD)
    de_l_opportunite = _paquet(registres, OPPORTUNITE)

    assert du_lead["affaire"]["connue"] is True
    assert de_l_opportunite["affaire"] == {
        "connue": False, "origine_recue": False, "origine": None, "verdict": CODE_INCONNUE}
    assert _evenements(de_l_opportunite)["nb_total"] == 0


def test_le_bloc_dit_l_origine_meme_quand_le_budget_de_la_couche_l_a_omise(registres):
    """L'origine est le fait le plus ANCIEN : la couche des événements l'omet en premier. Le bloc, lui, ne dépend pas
    de la troncature (comme le décompte des signaux)."""
    _memoriser(registres[0], TYPE_LEAD, _lead())
    for numero in range(2, 8):
        _memoriser(registres[0], TYPE_ACCEPTE, _accepte(f"DEVIS-B-{numero}", horodatage=_jour(numero)))

    paquet = _paquet(registres, n_faits_max_par_couche=3)

    sources = [fait["source"] for fait in _evenements(paquet)["faits"]]
    assert TYPE_LEAD not in sources and _evenements(paquet)["nb_omis"] == 4
    assert paquet["affaire"] == {"connue": True, "origine_recue": True, "origine": TYPE_LEAD, "verdict": None}


@pytest.mark.parametrize("agent", [None, "m01-front-office", "m02-revenue-crm", "m03-estimation", "m10-memoire"])
def test_le_bloc_est_le_meme_pour_tous_et_ne_porte_aucun_renseignement_personnel(registres, agent):
    for type_evenement, charge in ((TYPE_LEAD, _lead()), (TYPE_CLIENT, _client()),
                                   (TYPE_ACCEPTE, _accepte("DEVIS-B-2"))):
        _memoriser(registres[0], type_evenement, charge)

    paquet = _paquet(registres, agent=agent)

    assert paquet["affaire"] == {"connue": True, "origine_recue": True, "origine": TYPE_LEAD, "verdict": None}
    texte = json.dumps([paquet["affaire"], paquet["consolidation"]], ensure_ascii=False)
    for confidence in CONFIDENCES:
        assert confidence not in texte, confidence
    # un vocabulaire fermé : des booléens, un type d'événement du bus, un code de verdict
    assert set(paquet["affaire"]) == {"connue", "origine_recue", "origine", "verdict"}
    assert paquet["affaire"]["origine"] in {None, *etapes.types_consommes()}


def test_les_quatre_couches_gardent_leur_forme_et_les_deux_blocs_s_ajoutent(registres):
    paquet = _paquet(registres)

    assert [couche["nom"] for couche in paquet["couches"]] == [
        paquets.COUCHE_REGLES_ENTREPRISE, paquets.COUCHE_FAITS_AFFAIRE, paquets.COUCHE_EVENEMENTS_RECENTS,
        paquets.COUCHE_SIGNAUX_NON_RESOLUS]
    assert set(paquet) == {
        "affaire_id", "horodatage", "budget_caracteres", "caracteres_utilises", "couches", "signaux",
        "confidentialite", "affaire", "consolidation"}
    assert paquet["caracteres_utilises"] == sum(couche["caracteres"] for couche in paquet["couches"])  # cadrage exclu


# =========================================================================================
# 2. Le bloc `consolidation` : quels (affaire, jour) attendent, liste bornée
# =========================================================================================
def _huit_jours(registres):
    for numero in range(1, 9):
        _memoriser(registres[0], TYPE_ACCEPTE, _accepte(f"DEVIS-B-{numero}", horodatage=_jour(numero)))


def test_sans_troncature_rien_n_est_a_consolider(registres):
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-B-1"))

    paquet = _paquet(registres)

    assert _evenements(paquet)["tronque"] is False
    assert paquet["consolidation"] == {"a_consolider": [], "nb_a_consolider": 0}


def test_les_jours_dont_un_evenement_est_omis_sont_dits_les_plus_anciens_d_abord_avec_l_affaire(registres):
    _huit_jours(registres)

    paquet = _paquet(registres, n_faits_max_par_couche=3)

    assert [fait["horodatage"][:10] for fait in _evenements(paquet)["faits"]] == ["2026-09-08", "2026-09-07",
                                                                                  "2026-09-06"]
    assert paquet["consolidation"] == {
        "a_consolider": [{"affaire_id": LEAD, "jour": f"2026-09-0{numero}"} for numero in range(1, 6)],
        "nb_a_consolider": 5,
    }


def test_un_jour_deja_consolide_n_est_plus_a_consolider(registres):
    _huit_jours(registres)
    consolidation.consolider_affaire(LEAD, "2026-09-02", HORODATAGE_PAQUET, registres[0], registres[1])

    paquet = _paquet(registres, n_faits_max_par_couche=3)

    assert _jours_a_consolider(paquet) == ["2026-09-01", "2026-09-03", "2026-09-04", "2026-09-05"]
    assert paquet["consolidation"]["nb_a_consolider"] == 4


def test_un_evenement_tardif_omis_rend_le_jour_a_consolider(registres):
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-TARDIF-A", horodatage=_jour(2, "09:00:00")))
    consolidation.consolider_affaire(LEAD, "2026-09-02", HORODATAGE_PAQUET, registres[0], registres[1])
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-TARDIF-B", horodatage=_jour(2, "16:00:00")))
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-TARDIF-C", horodatage=_jour(2, "17:00:00")))

    paquet = _paquet(registres, n_faits_max_par_couche=1)

    assert _jours_a_consolider(paquet) == ["2026-09-02"]


def test_la_consolidation_d_une_autre_affaire_ne_compte_pas(registres):
    _huit_jours(registres)
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-AUTRE", "LEAD-AUTRE", _jour(2)))
    consolidation.consolider_affaire("LEAD-AUTRE", "2026-09-02", HORODATAGE_PAQUET, registres[0], registres[1])

    paquet = _paquet(registres, n_faits_max_par_couche=3)

    assert "2026-09-02" in _jours_a_consolider(paquet)


def test_un_jour_dont_seule_une_partie_est_omise_est_a_consolider(registres):
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-B-3", horodatage=_jour(3)))
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-B-6a", horodatage=_jour(6, "09:00:00")))
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-B-6b", horodatage=_jour(6, "16:00:00")))
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-B-8", horodatage=_jour(8)))

    paquet = _paquet(registres, n_faits_max_par_couche=2)

    assert [fait["identifiant"] for fait in _evenements(paquet)["faits"]] == ["DEVIS-B-8", "DEVIS-B-6b"]
    assert _jours_a_consolider(paquet) == ["2026-09-03", "2026-09-06"]  # le 6 : un devis vu, un devis omis


def test_le_jour_est_celui_de_l_evenement_tel_qu_il_est_ecrit_comme_la_consolidation(registres):
    """23 h 30 à l'heure de l'Est est déjà le lendemain en UTC : la consolidation groupe par la date ÉCRITE."""
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-B-1", horodatage="2026-09-15T23:30:00-04:00"))
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-B-2", horodatage=_jour(20)))

    paquet = _paquet(registres, n_faits_max_par_couche=1)

    assert _jours_a_consolider(paquet) == ["2026-09-15"]
    fait = consolidation.consolider_affaire(LEAD, "2026-09-15", HORODATAGE_PAQUET, registres[0], registres[1])
    assert fait["ecrit"] is True  # le jour listé est exactement celui que l'outil sait consolider


def test_la_liste_est_bornee_et_le_compte_dit_le_reste(registres):
    for numero in range(1, 14):
        _memoriser(registres[0], TYPE_ACCEPTE, _accepte(f"DEVIS-B-{numero}", horodatage=_jour(numero)))

    paquet = _paquet(registres, n_faits_max_par_couche=2)

    assert paquets.NB_JOURS_A_CONSOLIDER_MAX == 10
    assert _jours_a_consolider(paquet) == [f"2026-09-{numero:02d}" for numero in range(1, 11)]  # les plus anciens
    assert paquet["consolidation"]["nb_a_consolider"] == 11  # onze jours omis (du 1er au 11) : dix sont listés


def test_consolider_ce_que_le_paquet_liste_vide_la_liste(registres):
    """La boucle se ferme : chaque entrée est l'argument exact de `m10_consolider_affaire`, et la liste se vide."""
    _huit_jours(registres)
    paquet = _paquet(registres, n_faits_max_par_couche=3)

    for entree in paquet["consolidation"]["a_consolider"]:
        fait = consolidation.consolider_affaire(
            entree["affaire_id"], entree["jour"], HORODATAGE_PAQUET, registres[0], registres[1])
        assert fait["ecrit"] is True and fait["verdict"] is None, entree
    apres = _paquet(registres, n_faits_max_par_couche=3)

    assert apres["consolidation"] == {"a_consolider": [], "nb_a_consolider": 0}
    assert _evenements(apres)["nb_omis"] == 5  # l'historique est toujours omis de la couche : il est résumé, pas rendu


def test_un_evenement_retenu_par_confidentialite_ne_donne_pas_son_jour_a_qui_ne_le_voit_pas(registres):
    """Le client associé est CLIENT_PRIVATE : M3 ne le voit pas, son jour n'est donc pas dit ; M1 le voit et l'omet."""
    _memoriser(registres[0], TYPE_CLIENT, _client(horodatage=_jour(1)))
    for numero in range(2, 6):
        _memoriser(registres[0], TYPE_ACCEPTE, _accepte(f"DEVIS-B-{numero}", horodatage=_jour(numero)))

    pour_m3 = _paquet(registres, agent="m03-estimation", n_faits_max_par_couche=3)
    pour_m1 = _paquet(registres, agent="m01-front-office", n_faits_max_par_couche=3)
    sans_agent = _paquet(registres, agent=None, n_faits_max_par_couche=3)

    assert _jours_a_consolider(pour_m3) == ["2026-09-02"]
    assert _jours_a_consolider(sans_agent) == ["2026-09-02"]
    assert _jours_a_consolider(pour_m1) == ["2026-09-01", "2026-09-02"]
    assert "2026-09-01" not in json.dumps(pour_m3["consolidation"])


# =========================================================================================
# 3. Le budget de la couche des événements, tel que le code le calcule et que la documentation le dit
# =========================================================================================
def test_le_budget_par_defaut_est_partage_egalement_entre_les_quatre_couches():
    assert paquets.BUDGET_CARACTERES_DEFAUT == 4000
    assert paquets.NB_FAITS_MAX_PAR_COUCHE_DEFAUT == 5
    assert paquets.budget_par_couche() == 1000
    assert paquets.budget_par_couche(4003) == 1000  # division entière : le reste n'est jamais dépensé
    assert paquets.budget_par_couche(400) == 100


def test_la_couche_garde_les_plus_recents_et_omet_par_le_bout_ancien_au_premier_des_deux_plafonds(registres):
    """Deux plafonds : le nombre de faits, et les caractères de la couche. Le premier atteint coupe."""
    _huit_jours(registres)

    par_le_nombre = _paquet(registres, budget_caracteres=99_000, n_faits_max_par_couche=3)
    par_les_caracteres = _paquet(registres, budget_caracteres=paquets.budget_par_couche() * 4,
                                 n_faits_max_par_couche=99)

    assert _evenements(par_le_nombre)["nb_inclus"] == 3
    assert [f["horodatage"][:10] for f in _evenements(par_le_nombre)["faits"]] == ["2026-09-08", "2026-09-07",
                                                                                   "2026-09-06"]
    couche = _evenements(par_les_caracteres)
    assert couche["nb_inclus"] < 8 and couche["caracteres"] <= paquets.budget_par_couche()
    assert couche["nb_omis"] == 8 - couche["nb_inclus"]


def test_le_premier_fait_d_une_couche_est_toujours_garde_meme_s_il_depasse_son_budget(registres):
    _huit_jours(registres)

    paquet = _paquet(registres, budget_caracteres=8, n_faits_max_par_couche=5)

    couche = _evenements(paquet)
    assert couche["nb_inclus"] == 1 and couche["nb_omis"] == 7
    assert couche["caracteres"] > paquets.budget_par_couche(8)  # le fait dépasse les 2 caractères de sa couche


def test_avec_des_identifiants_reels_quatre_faits_tiennent_et_l_origine_sort_la_premiere(registres):
    """La documentation chiffre ce cas : lead de 64 caractères, un fait pèse 180 à 270 caractères, quatre tiennent
    dans les 1 000 de la couche. L'affaire complète en compte davantage : son ORIGINE sort la première."""
    lead = "9f3a7c1e5b2d40868a1c3e5f7092b4d6e8f0a2c4e6081a3c5e7f9b1d3f5a7c9e"
    assert len(lead) == 64
    _memoriser(registres[0], TYPE_LEAD, _lead(lead, _jour(10, "09:15:00")))
    _memoriser(registres[0], etapes.TYPE_DEVIS_ENVOYE, {
        "lead_id": lead, "devis_id": "DEVIS-2026-0042", "chantier_id": None, "horodatage_envoi": _jour(11, "09:00:00")})
    _memoriser(registres[0], TYPE_ACCEPTE, _accepte("DEVIS-2026-0042", lead, _jour(14)))
    _memoriser(registres[0], etapes.TYPE_DEVIS_SANS_REPONSE, {
        "lead_id": lead, "devis_id": "DEVIS-2026-0043", "chantier_id": None, "statut": "envoye",
        "horodatage_devis": _jour(5, "10:00:00"), "horodatage_reference": _jour(12, "08:00:00"),
        "delai_relance_jours": 7})
    wct.memoriser_wct(_wct("WCT-2026-0042", lead, _jour(15, "14:00:00")), registres[0])
    _memoriser(registres[0], etapes.TYPE_DEVIS_SANS_REPONSE, {
        "lead_id": lead, "devis_id": "DEVIS-2026-0044", "chantier_id": None, "statut": "envoye",
        "horodatage_devis": _jour(6, "10:00:00"), "horodatage_reference": _jour(16, "08:00:00"),
        "delai_relance_jours": 7})

    paquet = _paquet(registres, lead)

    couche = _evenements(paquet)
    taille_par_fait = [len(json.dumps(f, ensure_ascii=False, sort_keys=True)) for f in couche["faits"]]
    assert all(180 <= taille <= 270 for taille in taille_par_fait), taille_par_fait
    assert couche["nb_total"] == 6 and couche["nb_inclus"] == 4 and couche["nb_omis"] == 2
    sources = [fait["source"] for fait in couche["faits"]]
    assert TYPE_LEAD not in sources  # l'origine est omise de la couche...
    assert paquet["affaire"]["origine"] == TYPE_LEAD  # ... et le bloc la garde
    assert _jours_a_consolider(paquet) == ["2026-09-10", "2026-09-11"]


def _milliers(nombre):
    """`4000` -> `4 000`, comme la documentation l'écrit."""
    return f"{nombre:,}".replace(",", " ")


RACINE = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("document", [
    RACINE / "departments" / "m10-memoire" / "README.md",
    RACINE / "docs" / "decisions" / "ADR-0010-memoire.md",
], ids=lambda chemin: chemin.name)
def test_la_documentation_du_budget_dit_ce_que_le_code_calcule(document):
    """Le budget de la couche des événements est DOCUMENTÉ, et la documentation est vérifiée : si un chiffre du code
    change, ce test rougit au lieu de laisser un texte périmé."""
    texte = document.read_text(encoding="utf-8")

    assert f"{_milliers(paquets.BUDGET_CARACTERES_DEFAUT)} caractères" in texte
    assert f"{_milliers(paquets.budget_par_couche())} caractères chacune" in texte
    assert f"{paquets.NB_FAITS_MAX_PAR_COUCHE_DEFAUT} faits par couche" in texte
    assert f"{paquets.NB_JOURS_A_CONSOLIDER_MAX} jours" in texte
    for nom in ("BUDGET_CARACTERES_DEFAUT", "NB_FAITS_MAX_PAR_COUCHE_DEFAUT", "NB_JOURS_A_CONSOLIDER_MAX",
                "budget_par_couche", "m10_consolider_affaire"):
        assert nom in texte, nom
