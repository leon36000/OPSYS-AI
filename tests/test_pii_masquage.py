"""Masquage déterministe des renseignements personnels québécois : validations, jetons stables, modes, coffre, mesure.

Toutes les valeurs sont FICTIVES : numéros fabriqués avec une somme de Luhn calculée, cartes d'essai publiées par les
réseaux, courriels en `@example.test`.
"""

from __future__ import annotations

import time

import pytest

from opsys import identite
from opsys.observabilite import cle_locale
from opsys.observabilite.corpus_pii import CORPUS, CasPII, _nas
from opsys.observabilite.erreurs import ErreurObservabilite
from opsys.observabilite.pii import (
    CoffrePII,
    CoffrePIIDuCoffre,
    CoffrePIIMemoire,
    MasqueurEnChaine,
    MasqueurMotifs,
    MasqueurPII,
    ModeMasquage,
    ResultatMasquage,
)
from opsys.observabilite.pii_detecteurs import entropie, luhn_valide
from opsys.observabilite.pii_mesure import mesurer
from opsys.secrets_coffre import cle_maitresse, coffre, masquage

FICTIF = True
CLE = b"k" * 32
NAS_1, NAS_2 = _nas("13069254"), _nas("27418395")


def _g(n: str, sep: str = " ") -> str:
    return f"{n[:3]}{sep}{n[3:6]}{sep}{n[6:]}"


@pytest.fixture
def masqueur() -> MasqueurMotifs:
    return MasqueurMotifs(CLE)


def _texte(masqueur: MasqueurMotifs, brut: str) -> str:
    return masqueur.masquer(brut).texte


# -- Luhn et validations ----------------------------------------------------------------------------------------------
def test_luhn_connait_les_numeros_d_essai_et_refuse_les_autres():
    assert luhn_valide("4111111111111111") and luhn_valide("5555555555554444") and luhn_valide(NAS_1)
    assert not luhn_valide("4111111111111112") and not luhn_valide(NAS_1[:-1] + str((int(NAS_1[-1]) + 1) % 10))
    assert not luhn_valide("") and not luhn_valide("12a4") and not luhn_valide("7")


def test_nas_valide_est_masque_et_nas_invalide_ne_l_est_pas(masqueur):
    assert "[[NAS:" in _texte(masqueur, f"NAS {_g(NAS_1)}")
    faux = NAS_1[:-1] + str((int(NAS_1[-1]) + 1) % 10)
    assert _texte(masqueur, f"NAS {_g(faux)}") == f"NAS {_g(faux)}"  # somme de Luhn fausse : pas un NAS


def test_nas_colle_exige_le_mot_de_contexte(masqueur):
    assert _texte(masqueur, f"valeur {NAS_1} seule") == f"valeur {NAS_1} seule"
    assert "[[NAS:" in _texte(masqueur, f"Numéro d'assurance sociale {NAS_1}")


def test_un_montant_ou_un_nombre_a_milliers_n_est_pas_un_nas(masqueur):
    assert "NAS" not in _texte(masqueur, f"Total {_g(NAS_2)} $ à payer")
    assert "NAS" not in _texte(masqueur, f"Montant {NAS_1},50 $")
    assert "NAS" not in _texte(masqueur, "Stock : 4 000 000 000 unités")


@pytest.mark.parametrize("carte", ["4111 1111 1111 1111", "5555-5555-5555-4444", "3782 822463 10005",
                                   "4012888888881881"])
def test_cartes_d_essai_masquees(masqueur, carte):
    assert "[[CARTE:" in _texte(masqueur, f"paiement {carte} ok")


def test_carte_sans_luhn_ou_sans_prefixe_d_emetteur_n_est_pas_masquee(masqueur):
    assert "CARTE" not in _texte(masqueur, "ref 4111 1111 1111 1112")  # Luhn faux
    assert "CARTE" not in _texte(masqueur, "ref 0000 0000 0000 0000")  # Luhn valide mais aucun émetteur
    assert "CARTE" not in _texte(masqueur, "ref 1234567890123456")


@pytest.mark.parametrize("tel", ["(514) 555-0199", "438.555.0142", "+1 418 555 0123", "1-800-555-0100",
                                 "819 555 0188 poste 22"])
def test_telephones_nord_americains_masques(masqueur, tel):
    assert "[[TEL:" in _texte(masqueur, f"Rappelez au {tel} svp")


def test_telephone_n11_ou_colle_sans_contexte_ne_l_est_pas(masqueur):
    assert "TEL" not in _texte(masqueur, "Appeler le 911 ou le 211")
    assert "TEL" not in _texte(masqueur, "Produit 5145550199 en stock")
    assert "[[TEL:" in _texte(masqueur, "Texto au 5145550177")


def test_courriel_masque_en_minuscules_pour_le_jeton(masqueur):
    a, b = _texte(masqueur, "Jean.T@Example.test"), _texte(masqueur, "jean.t@example.test")
    assert a == b and a.startswith("[[COURRIEL:")


def test_code_postal_et_adresse_civique(masqueur):
    assert "[[CP:" in _texte(masqueur, "H2X 1Y4") and "[[CP:" in _texte(masqueur, "G1A-1A1")
    assert "[[ADRESSE:" in _texte(masqueur, "au 1234 rue des Érables, app. 4")
    assert "[[ADRESSE:" in _texte(masqueur, "au 12 Maple Street")
    assert "ADRESSE" not in _texte(masqueur, "La rue Principale est fermée")
    assert "ADRESSE" not in _texte(masqueur, "Le 3e avenue est fermée")  # ordinal, pas un numéro civique
    assert "CP" not in _texte(masqueur, "id e3a1b9")  # collé et en minuscules : identifiant, pas un code postal


def test_ramq_exige_un_format_plausible(masqueur):
    assert "[[RAMQ:" in _texte(masqueur, "TREJ 8501 1512")
    assert "[[RAMQ:" in _texte(masqueur, "GAGL90561834")  # mois 56 = femme
    assert "RAMQ" not in _texte(masqueur, "TREJ 8513 1512")  # mois 13 impossible
    assert "RAMQ" not in _texte(masqueur, "trej 8501 1512")  # la carte est en majuscules


def test_neq_exige_son_contexte_et_les_numeros_d_entreprise_leur_forme(masqueur):
    assert "[[NEQ:" in _texte(masqueur, "NEQ : 1143456789")
    assert "NEQ" not in _texte(masqueur, "Réf 1143456789")
    assert "[[NE:" in _texte(masqueur, "TPS 123456789 RT0001") and "[[NE:" in _texte(masqueur, "TVQ 1234567890 TQ 0001")
    assert "NE:" not in _texte(masqueur, "lot 123456789")


@pytest.mark.parametrize("secret", ["ghp_" + "aB3dE5gH7j" * 4, "AKIAABCDEFGH12345678", "api_key=Zx9Qw3Er7Ty1Ui5Op",
                                    "password: correct-horse-9", "Kd82Lq0PzX4mN7vB1cR6tY9wE3uA5sGh",
                                    "https://u:S3cretPw@interne.example.test/x"])
def test_secrets_masques(masqueur, secret):
    sortie = _texte(masqueur, f"valeur {secret} fin")
    assert "[[SECRET:" in sortie
    for fragment in ("aB3dE5gH7j", "ABCDEFGH1234", "Zx9Qw3Er7", "correct-horse", "Kd82Lq0P", "S3cretPw"):
        assert fragment not in sortie


def test_les_empreintes_et_identifiants_hexadecimaux_ne_sont_pas_des_secrets(masqueur):
    texte = ("sha256:" + "ab" * 32 + " commit 9fceb02d0ae598e95dc970b74767f19372d61af8 "
             "id 3f2504e0-4f89-11d3-9a0c-0305e82c3301")
    assert _texte(masqueur, texte) == texte


def test_entropie_separe_un_secret_d_un_nom_de_fichier():
    assert entropie("Kd82Lq0PzX4mN7vB1cR6tY9wE3uA5sGh") > 4.0 > entropie("fichier_rapport_trimestriel_ventes_2026")


# -- jetons stables ---------------------------------------------------------------------------------------------------
def test_meme_valeur_meme_jeton_quel_que_soit_le_format(masqueur):
    a = masqueur.masquer(f"NAS {_g(NAS_1)}").remplacements[0].jeton
    b = masqueur.masquer(f"NAS {_g(NAS_1, '-')}").remplacements[0].jeton
    c = masqueur.masquer(f"NAS {_g(NAS_1, chr(0xa0))}").remplacements[0].jeton
    d = masqueur.masquer(f"NAS {_g(NAS_2)}").remplacements[0].jeton
    assert a == b == c and a != d


def test_le_jeton_depend_de_la_cle_et_de_la_categorie_et_ne_contient_pas_la_valeur():
    m1, m2 = MasqueurMotifs(CLE), MasqueurMotifs(b"z" * 32)
    t1, t2 = m1.masquer(f"NAS {NAS_1[:3]} {NAS_1[3:6]} {NAS_1[6:]}").texte, m2.masquer(
        f"NAS {NAS_1[:3]} {NAS_1[3:6]} {NAS_1[6:]}").texte
    assert t1 != t2
    assert NAS_1 not in t1 and NAS_1[:3] not in t1.split("[[")[1]
    assert m1.jeton("nas", "123456789") != m1.jeton("carte", "123456789")


def test_le_masquage_est_idempotent_et_un_jeton_n_est_pas_du_pii(masqueur):
    brut = f"M. Tremblay ({_g(NAS_1)}) — jean@example.test — (514) 555-0100"
    une = _texte(masqueur, brut)
    assert _texte(masqueur, une) == une
    assert not masqueur.contient_pii(une) and masqueur.contient_pii(brut)


def test_le_resultat_ne_porte_jamais_la_valeur_brute(masqueur):
    r = masqueur.masquer(f"NAS {_g(NAS_1)} et jean@example.test")
    assert isinstance(r, ResultatMasquage) and len(r.remplacements) == 2
    for pris in (repr(r), str(r.remplacements), repr(masqueur)):
        assert NAS_1 not in pris.replace(" ", "") and "jean@example.test" not in pris
    assert r.par_categorie == {"nas": 1, "courriel": 1}


def test_une_cle_invalide_est_refusee():
    for cle in (b"court", "texte" * 7, None):
        with pytest.raises(ErreurObservabilite) as exc:
            MasqueurMotifs(cle)  # type: ignore[arg-type]
        assert exc.value.code == "REJ-OBS-CLE-INVALIDE"
    with pytest.raises(ErreurObservabilite):
        MasqueurMotifs(CLE, categories=["inconnue"])


# -- modes irréversible / réversible ---------------------------------------------------------------------------------
def test_mode_irreversible_ne_garde_la_valeur_nulle_part():
    coffre_double = CoffrePIIMemoire()
    m = MasqueurMotifs(CLE, coffre=coffre_double)
    m.masquer(f"NAS {_g(NAS_1)}")
    assert coffre_double._valeurs == {}  # noqa: SLF001


def test_mode_reversible_depose_et_revele_mais_jamais_un_secret():
    coffre_double = CoffrePIIMemoire()
    m = MasqueurMotifs(CLE, coffre=coffre_double)
    r = m.masquer(f"NAS {_g(NAS_1)} clé ghp_{'aB3dE5gH7j' * 4}", mode=ModeMasquage.REVERSIBLE_COFFRE)
    par_cat = {x.categorie: x for x in r.remplacements}
    assert par_cat["nas"].reversible and not par_cat["secret"].reversible
    assert coffre_double.reveler(par_cat["nas"].jeton, acteur="admin-fictif") == _g(NAS_1)
    assert list(coffre_double._valeurs) == [par_cat["nas"].jeton]  # noqa: SLF001 — le secret n'y est pas
    assert coffre_double.acces == [("admin-fictif", par_cat["nas"].jeton)]
    with pytest.raises(ErreurObservabilite) as exc:
        coffre_double.reveler("[[NAS:000000000000]]", acteur="admin-fictif")
    assert exc.value.code == "REJ-OBS-COFFRE-PII-INCONNU"


def test_mode_reversible_sans_coffre_est_refuse():
    with pytest.raises(ErreurObservabilite) as exc:
        MasqueurMotifs(CLE).masquer("x", mode=ModeMasquage.REVERSIBLE_COFFRE)
    assert exc.value.code == "REJ-OBS-COFFRE-PII-REFUSE"


@pytest.fixture
def coffre_reel(session, tmp_path, monkeypatch):
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    chemin = dossier / "coffre.cle"
    cle_maitresse.generer_fichier(chemin)
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(chemin))
    monkeypatch.delenv(cle_maitresse.ENV_CLE, raising=False)
    with session() as cnx:
        identite.creer_personne(cnx, "admin_fictif", "Admin fictif", "mot-de-passe-pii-fictif-2026", ["admin"])
        identite.creer_personne(cnx, "employe_fictif", "Employé fictif", "mot-de-passe-pii-fictif-2026", ["employee"])
    return CoffrePIIDuCoffre(session, acteur_depot="admin_fictif")


def test_coffre_reel_depot_idempotent_revelation_reservee_a_l_admin_et_journalisee(coffre_reel, session, opsys_home):
    from opsys import stockage

    m = MasqueurMotifs(CLE, coffre=coffre_reel)
    jeton = m.masquer(f"NAS {_g(NAS_1)}", mode=ModeMasquage.REVERSIBLE_COFFRE).remplacements[0].jeton
    m.masquer(f"NAS {_g(NAS_1)}", mode=ModeMasquage.REVERSIBLE_COFFRE)  # redépôt : sans effet, sans erreur
    assert coffre_reel.reveler(jeton, acteur="admin_fictif") == _g(NAS_1)
    for refuse in ("employe_fictif", "inconnu", ""):
        with pytest.raises(ErreurObservabilite) as exc:
            coffre_reel.reveler(jeton, acteur=refuse)
        assert exc.value.code == "REJ-OBS-COFFRE-PII-REFUSE"
    with session() as cnx:
        actions = [(j["action"], j["resultat"]) for j in coffre.journal(cnx)]
    assert ("resolution", "ok") in actions  # la révélation laisse une trace dans le journal d'accès du coffre
    stockage.liberer()
    octets = b"".join(p.read_bytes() for p in opsys_home.rglob("*") if p.is_file())
    assert _g(NAS_1).encode() not in octets  # la base ne contient pas la valeur en clair
    masquage.oublier(_g(NAS_1))


def test_les_valeurs_actives_du_coffre_sont_masquees_avant_tout(masqueur):
    masquage.enregistrer("valeur-vive-fictive-xyz")
    try:
        assert "valeur-vive-fictive-xyz" not in _texte(masqueur, "la clé est valeur-vive-fictive-xyz ok")
    finally:
        masquage.oublier("valeur-vive-fictive-xyz")


# -- structures ----------------------------------------------------------------------------------------------------
def test_masquer_structure_traite_valeurs_et_cles_et_les_cles_secretes(masqueur):
    brut = {"client": "M. Tremblay", "jean@example.test": 3, "password": "hunter2-fictif", "n": 7, "ok": True,
            "x": None,
            "liste": [f"NAS {_g(NAS_1)}", {"tel": "(514) 555-0199"}], "token": "", "objet": object()}
    sortie = masqueur.masquer_structure(brut)
    texte = str(sortie)
    for fuite in ("Tremblay", "jean@example.test", "hunter2", NAS_1, "555-0199"):
        assert fuite not in texte.replace(" ", "")
    assert sortie["n"] == 7 and sortie["ok"] is True and sortie["x"] is None and sortie["token"] == ""
    assert sortie["objet"] == "<object>"  # jamais le repr d'un objet inconnu


def test_masquer_structure_borne_la_profondeur_et_la_taille(masqueur):
    imbrique: dict = {}
    courant = imbrique
    for _ in range(30):
        courant["a"] = {}
        courant = courant["a"]
    assert "[[TRONQUE]]" in str(masqueur.masquer_structure(imbrique))
    assert "[[TRONQUE]]" in str(masqueur.masquer_structure(list(range(5000))))
    assert _texte(masqueur, "x" * 250_000).endswith("[[TRONQUE]]")


# -- le port et la chaîne ---------------------------------------------------------------------------------------------
class _FauxNER:
    """Double d'un masqueur NER (Presidio) : masque les prénoms de sa liste."""

    identite = "double.ner/test"

    def masquer(self, texte, *, mode=ModeMasquage.IRREVERSIBLE):
        resultat = texte.replace("Hortense", "[[NOM:ner000000001]]")
        return ResultatMasquage(resultat, ())

    def contient_pii(self, texte):
        return "Hortense" in texte


def test_le_port_est_satisfait_par_les_motifs_et_par_un_double_ner(masqueur):
    assert isinstance(masqueur, MasqueurPII) and isinstance(_FauxNER(), MasqueurPII)
    assert isinstance(CoffrePIIMemoire(), CoffrePII)
    chaine = MasqueurEnChaine(masqueur, _FauxNER())
    sortie = chaine.masquer(f"Hortense a donné jean@example.test et {_g(NAS_1)} (NAS)").texte
    assert "Hortense" not in sortie and "jean@example.test" not in sortie and "COURRIEL" in sortie
    assert chaine.contient_pii("Hortense") and not chaine.contient_pii("rien")
    assert chaine.identite.startswith("chaine:opsys.motifs-quebec/v1+")
    with pytest.raises(ErreurObservabilite):
        MasqueurEnChaine()
    with pytest.raises(ErreurObservabilite):
        MasqueurEnChaine(object())  # type: ignore[arg-type]


def test_lexique_de_noms_connus_comble_les_noms_sans_civilite():
    m = MasqueurMotifs(CLE, lexique=["Hortense Fictive-Bouchard", "Steve"])
    sortie = m.masquer("Hortense Fictive-Bouchard et STEVE ont signé ; Stevenson non").texte
    assert "Hortense" not in sortie and "STEVE" not in sortie and "Stevenson" in sortie
    with pytest.raises(ValueError):
        MasqueurMotifs(CLE, lexique=[f"nom{i:05d}" for i in range(5001)])


# -- entrées hostiles -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("hostile", ["1 " * 60000, "a" * 100000, "a." * 50000 + "@", "a@" * 50000,
                                     "12 rue " + "de la " * 20000, "1" * 100000, "Ab1" * 30000,
                                     "M. " + "Aa " * 30000, "-----BEGIN PRIVATE KEY-----" + "x" * 100000,
                                     ("4111 " * 20000), "(" * 50000])
def test_entrees_hostiles_restent_en_temps_borne(masqueur, hostile):
    debut = time.perf_counter()
    masqueur.masquer(hostile)
    assert time.perf_counter() - debut < 2.0


def test_type_invalide_refuse(masqueur):
    for mauvais in (None, 12, b"octets"):
        with pytest.raises(ErreurObservabilite):
            masqueur.masquer(mauvais)  # type: ignore[arg-type]


# -- mesure sur le corpus fictif --------------------------------------------------------------------------------------
def test_mesure_sur_le_corpus_fictif_et_limites_nommees(masqueur):
    r = mesurer(masqueur)
    assert r["global"]["precision"] >= 0.95 and r["global"]["rappel"] >= 0.95
    assert r["negatifs"] >= 20 and r["taux_faux_positifs_negatifs"] == 0.0
    for categorie in ("nas", "carte", "telephone", "courriel", "code_postal", "adresse", "ramq", "neq", "secret",
                      "nom"):
        assert r["categories"][categorie]["rappel"] >= 0.95, categorie
    # Les limites sont VUES : si l'une est améliorée un jour, ce test force à le déclarer (et à mettre la doc à jour).
    assert r["limites_ameliorees"] == []
    assert {x["note"] for x in r["limites_confirmees"]} == {c.note for c in CORPUS if c.limite}
    assert len(r["limites_confirmees"]) >= 7
    assert r["faux_positifs_connus_corriges"] == [] and len(r["faux_positifs_connus_confirmes"]) >= 4


def test_la_mesure_voit_un_masqueur_qui_ne_masque_rien():
    class Aveugle:
        identite = "aveugle"

        def masquer(self, texte, *, mode=ModeMasquage.IRREVERSIBLE):
            return ResultatMasquage(texte, ())

        def contient_pii(self, texte):
            return False

    r = mesurer(Aveugle())
    assert r["global"]["rappel"] == 0.0 and r["global"]["manques"] > 40


def test_mesure_refuse_un_corpus_incoherent(masqueur):
    with pytest.raises(ValueError):
        mesurer(masqueur, [CasPII("texte", (("nas", "absent du texte"),))])


# -- clé locale ----------------------------------------------------------------------------------------------------
def test_cle_locale_creation_privee_stable_et_sous_cles_distinctes(tmp_path, verifier_acces_prive):
    chemin = tmp_path / "obs" / "cle-locale"
    with pytest.raises(ErreurObservabilite) as exc:
        cle_locale.charger(chemin)
    assert exc.value.code == "REJ-OBS-CLE-ABSENTE"
    graine = cle_locale.charger(chemin, creer=True)
    verifier_acces_prive(chemin)
    assert cle_locale.charger(chemin) == graine and len(graine) == 32
    sous = {u: cle_locale.deriver(graine, u) for u in cle_locale.USAGES}
    assert len(set(sous.values())) == 3 and graine not in sous.values()
    with pytest.raises(ErreurObservabilite):
        cle_locale.deriver(graine, "autre/usage")


def test_cle_locale_refuse_permissions_lien_et_contenu_invalide(tmp_path):
    graine = cle_locale.charger(tmp_path / "ok", creer=True)
    assert graine
    (tmp_path / "ok").chmod(0o644)
    with pytest.raises(ErreurObservabilite) as exc:
        cle_locale.charger(tmp_path / "ok")
    assert exc.value.code == "REJ-OBS-CLE-PERMISSIONS"
    (tmp_path / "lien").symlink_to(tmp_path / "ok")
    with pytest.raises(ErreurObservabilite) as exc:
        cle_locale.charger(tmp_path / "lien")
    assert exc.value.code == "REJ-OBS-CLE-INVALIDE"
    faux = tmp_path / "faux"
    faux.write_text("pas-du-base64\n")
    faux.chmod(0o600)
    with pytest.raises(ErreurObservabilite) as exc:
        cle_locale.charger(faux)
    assert exc.value.code == "REJ-OBS-CLE-INVALIDE"
