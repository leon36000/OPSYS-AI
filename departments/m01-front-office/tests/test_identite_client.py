"""M1.10 : la machine d'états de la vérification d'identité. Inconnu -> à vérifier -> vérifié (n moyens) ->
refusé/expiré.

Module pur : `maintenant` est toujours fourni. Données fictives."""

from __future__ import annotations

import datetime as dt

import pytest
from m1_front_office import identite_client as ic

T0 = "2026-11-02T10:00:00-05:00"
VID = "vi-0123456789abcdef"
SEL = "sel-fictif"
CODE = "482915"


def _t(minutes: int) -> str:
    return (dt.datetime.fromisoformat(T0) + dt.timedelta(minutes=minutes)).isoformat()


def _ouverte(finalite="statut_dossier", retention=90):
    return ic.ligne_ouverture(
        verification_id=VID,
        cle="courriel-abc",
        canal="courriel",
        finalite=finalite,
        signal_id="courriel:x",
        maintenant=T0,
        sel=SEL,
        empreinte=ic.empreinte_code(SEL, CODE),
        brouillon_id="b1",
        retention_jours=retention,
    )


def _essai(minutes, reussi=True, signal="courriel:r1"):
    return {
        "type_entree": ic.TYPE_ESSAI,
        "horodatage": _t(minutes),
        "verification_id": VID,
        "signal_id": signal,
        "reussi": reussi,
        "moyen": ic.MOYEN_CODE,
    }


def _att(minutes, moyen="rappel_numero_dossier"):
    return {
        "type_entree": ic.TYPE_ATTESTATION,
        "horodatage": _t(minutes),
        "verification_id": VID,
        "moyen": moyen,
        "par": "admin.fictif",
    }


def _dec(minutes, decision):
    return {"type_entree": ic.TYPE_DECISION, "horodatage": _t(minutes), "verification_id": VID, "decision": decision}


def _p(lignes, minutes=1):
    return ic.projeter(lignes, VID, _t(minutes))


def test_inconnu_puis_a_verifier_puis_verifie_par_un_moyen_puis_deux():
    assert _p([]).etat == "inconnu" and _p([]).niveau_acces == "aucun"
    p = _p([_ouverte()])
    assert (p.etat, p.niveau_acces, p.nb_moyens, p.essais_restants) == ("a_verifier", "aucun", 0, 3)
    p = _p([_ouverte(), _essai(2)], 3)
    assert (p.etat, p.niveau_acces, p.moyens_valides) == ("verifie", "probable", ("code_courriel",))
    p = _p([_ouverte(), _essai(2), _att(3)], 4)
    assert (p.etat, p.niveau_acces, p.nb_moyens) == ("verifie", "general", 2)


def test_la_reponse_autorisee_suit_le_niveau_et_dit_toujours_la_phrase_de_repli():
    v = _p([_ouverte()]).vers_json()["reponse_autorisee"]
    assert v == {"statut_general": False, "sensible": False, "texte_si_refuse": "Je vais vérifier avec l'équipe."}
    g = _p([_ouverte(), _essai(2), _att(3)], 4).vers_json()["reponse_autorisee"]
    assert g["statut_general"] is True and g["sensible"] is False


def test_un_seul_moyen_ne_donne_jamais_le_statut_general():
    p = _p([_ouverte(), _essai(2)], 3)
    assert not ic.exiger_niveau(p, "statut_dossier") and "un_seul_moyen" in p.raisons


def test_l_action_sensible_exige_la_decision_d_une_personne_meme_avec_deux_moyens():
    lignes = [_ouverte("facturation"), _essai(2), _att(3)]
    p = _p(lignes, 4)
    assert p.niveau_acces == "general" and not ic.exiger_niveau(p, "facturation")
    p2 = _p([*lignes, _dec(5, "valider")], 6)
    assert (
        p2.niveau_acces == "sensible" and ic.exiger_niveau(p2, "facturation") and ic.exiger_niveau(p2, "statut_dossier")
    )


def test_valider_sans_moyen_valide_n_eleve_rien():
    p = _p([_ouverte(), _dec(2, "valider")], 3)
    assert p.niveau_acces == "aucun" and p.etat in ("a_verifier", "expire")


def test_le_code_expire_apres_30_minutes_et_le_moyen_apres_60():
    assert _p([_ouverte()], 31).etat == "expire"
    assert _p([_ouverte(), _essai(2)], 62).etat == "verifie"
    p = _p([_ouverte(), _essai(2)], 63)
    assert p.etat == "expire" and p.niveau_acces == "aucun" and "moyens_expires" in p.raisons


def test_un_code_renvoye_apres_l_expiration_du_code_ne_compte_pas():
    p = _p([_ouverte(), _essai(40)], 41)
    assert p.nb_moyens == 0 and p.niveau_acces == "aucun"


def test_trois_echecs_verrouillent_24_heures_puis_expirent():
    echecs = [_essai(i + 1, reussi=False, signal=f"s{i}") for i in range(3)]
    p = _p([_ouverte(), *echecs], 5)
    assert (p.etat, p.niveau_acces, p.essais_restants) == ("refuse", "aucun", 0) and "essais_epuises" in p.raisons
    assert _p([_ouverte(), *echecs], 60 * 25).etat == "expire"


def test_un_refus_humain_est_definitif_pour_24_heures_meme_avec_des_moyens():
    p = _p([_ouverte(), _essai(2), _att(3), _dec(4, "refuser")], 5)
    assert (p.etat, p.niveau_acces, p.decision) == ("refuse", "aucun", "refuser")


def test_la_validation_humaine_expire_apres_4_heures():
    lignes = [_ouverte("facturation"), _essai(2), _att(3), _dec(4, "valider")]
    assert _p(lignes, 200).niveau_acces == "general" or _p(lignes, 200).etat == "expire"
    assert _p(lignes, 250).niveau_acces == "aucun"


def test_la_retention_borne_la_vie_de_la_ligne():
    ligne = _ouverte(retention=1)
    assert _p([ligne, _essai(2)], 60 * 24 + 5).etat == "expire"
    with pytest.raises(ic.RefusIdentite, match="RETENTION"):
        _ouverte(retention=366)
    with pytest.raises(ic.RefusIdentite, match="RETENTION"):
        _ouverte(retention=0)
    with pytest.raises(ic.RefusIdentite, match="FINALITE"):
        _ouverte(finalite="curiosite")


def test_le_code_est_verifie_par_empreinte_salee_et_en_temps_constant():
    e = ic.empreinte_code(SEL, CODE)
    assert (
        ic.code_valide(SEL, e, CODE) and not ic.code_valide(SEL, e, "000000") and not ic.code_valide("autre", e, CODE)
    )
    assert CODE not in e and ic.empreinte_code(SEL, CODE) != ic.empreinte_code("autre", CODE)


def test_extraire_code_exige_un_code_et_un_seul():
    assert ic.extraire_code("Voici le code : 482915 merci") == "482915"
    assert ic.extraire_code("482915 et 111111") is None and ic.extraire_code("pas de code") is None
    assert ic.extraire_code("1234567") is None and ic.extraire_code("12345") is None


@pytest.mark.parametrize(
    "texte", ["permis A1234-567890-12", "numéro 123456789", "ABCD 12345678", "carte 4500123412341234"]
)
def test_aucun_numero_de_piece_n_est_conserve(texte):
    with pytest.raises(ic.RefusIdentite, match="DONNEE-IDENTIFIANTE"):
        ic.exiger_sans_donnee_identifiante(texte)


def test_un_texte_court_et_propre_est_conserve_tronque():
    assert ic.exiger_sans_donnee_identifiante("  vu en personne  ") == "vu en personne"
    assert (
        len(ic.exiger_sans_donnee_identifiante("x" * 500)) == 200 and ic.exiger_sans_donnee_identifiante(None) is None
    )


def test_un_instant_sans_fuseau_est_refuse():
    with pytest.raises(ic.RefusIdentite, match="HORODATAGE"):
        ic.projeter([_ouverte()], VID, "2026-11-02T10:00:00")
