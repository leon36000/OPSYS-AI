"""Réglages de direction (CFG-1) : le magasin chaîné des valeurs adoptées, sans le sas (le geste humain est prouvé
ailleurs).

Prouve : une adoption écrit UN maillon (qui, quand, ancienne et nouvelle valeur, raison, version, approbation) lié au
précédent par empreinte ; une double adoption de la même valeur est idempotente ; la valeur hors bornes ou de mauvais
type est refusée sans maillon ; la version attendue protège contre une adoption sur une valeur qui a changé ; le
retour arrière dépile (adoption A, B, retour : A, retour : aucune) en une opération ; une raison contenant un
renseignement personnel est refusée ; la chaîne falsifiée (valeur changée, maillon retiré, ordre échangé, empreinte
refaite) ne se rejoue pas et n'est servie à personne ; l'écriture concurrente est refusée ; hors transaction, rien
n'est écrit. Données fictives.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import select, update

from opsys import stockage
from opsys.reglages import lecture, magasin
from opsys.reglages.declaration import ReglageRefuse
from opsys.stockage.schema import REGISTRES

_spec = importlib.util.spec_from_file_location("reglages_aide", Path(__file__).with_name("reglages_aide.py"))
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)

FICTIF = True
QUAND = "2026-11-02T15:00:00+00:00"
CLE = "m2.jours_entre_relances"
BORNES_M8 = "m8.bornes_taux_acceptation_pct"


@pytest.fixture
def deps(tmp_path, monkeypatch):
    yield aide.installer(tmp_path, monkeypatch)
    stockage.liberer()


def _reglage(deps, cle):
    return next(r for d in deps.values() for r in d.reglages if r.cle == cle)


def _geste(deps, cle=CLE, valeur=7, **plus):
    parametres = {"par": aide.PROPRIETAIRE, "role": "nathan_owner", "approbation_id": "demande-1",
                  "raison": "Décision de départ", "quand": QUAND, **plus}
    return magasin.adopter(stockage.connexion_courante(), _reglage(deps, cle), valeur, **parametres)


def _retour(deps, cle=CLE, **plus):
    parametres = {"par": aide.PROPRIETAIRE, "role": "nathan_owner", "approbation_id": "demande-2",
                  "raison": "Retour au départ", "quand": QUAND, **plus}
    return magasin.revenir(stockage.connexion_courante(), _reglage(deps, cle), **parametres)


def test_une_adoption_ecrit_un_maillon_complet_lie_au_vide(deps):
    with stockage.transaction():
        resultat = _geste(deps)
        (maillon,) = magasin.lire_chaine()
    assert resultat["statut"] == "adopte" and resultat["version"] == 1 and resultat["origine"] == "proposition"
    assert set(maillon) == magasin.CHAMPS_MAILLON
    assert maillon["rang"] == 0 and maillon["precedent"] == "" and maillon["type"] == "adoption"
    assert maillon["cle"] == CLE and maillon["departement"] == "m02-revenue-crm"
    assert maillon["ancienne_valeur"] is None and maillon["nouvelle_valeur"] == 7
    assert (maillon["par"], maillon["role"]) == (aide.PROPRIETAIRE, "nathan_owner")
    assert maillon["approbation_id"] == "demande-1"
    assert maillon["raison"] == "Décision de départ" and maillon["quand"] == QUAND
    assert maillon["empreinte"] == magasin.empreinte(maillon) == resultat["empreinte"]


def test_la_valeur_proposee_est_marquee_proposition_et_une_autre_valeur_saisie(deps):
    with stockage.transaction():
        assert _geste(deps, valeur=7)["origine"] == "proposition"
        assert _geste(deps, valeur=10)["origine"] == "saisie"


def test_les_maillons_se_chainent_et_l_ancienne_valeur_est_celle_en_vigueur(deps):
    with stockage.transaction():
        _geste(deps, valeur=7)
        second = _geste(deps, valeur=10)
        chaine = magasin.lire_chaine()
    assert second["version"] == 2 and second["ancienne_valeur"] == 7
    assert chaine[1]["precedent"] == chaine[0]["empreinte"] and chaine[1]["rang"] == 1
    assert magasin.rejouer(chaine)[CLE]["pile"] == [7, 10]


def test_adopter_deux_fois_la_meme_valeur_est_idempotent_sans_nouveau_maillon(deps):
    with stockage.transaction():
        premier = _geste(deps, valeur=7)
        deuxieme = _geste(deps, valeur=7, approbation_id="demande-9", raison="Double clic de l'écran")
        assert len(magasin.lire_chaine()) == 1
    assert premier["statut"] == "adopte" and deuxieme["statut"] == "deja_adopte" and deuxieme["version"] == 1


def test_une_valeur_hors_bornes_ou_de_mauvais_type_est_refusee_sans_maillon(deps):
    with stockage.transaction():
        for mauvais, code in ((0, "REJ-REGLAGE-HORS-BORNES"), (3651, "REJ-REGLAGE-HORS-BORNES"),
                              ("7", "REJ-REGLAGE-TYPE"), (7.5, "REJ-REGLAGE-TYPE"), (True, "REJ-REGLAGE-TYPE"),
                              (None, "REJ-REGLAGE-TYPE"), ([7], "REJ-REGLAGE-TYPE")):
            with pytest.raises(ReglageRefuse) as exc:
                _geste(deps, valeur=mauvais)
            assert exc.value.code == code, mauvais
        assert magasin.lire_chaine() == []


def test_la_version_attendue_protege_d_une_valeur_qui_a_change_depuis_la_lecture(deps):
    with stockage.transaction():
        _geste(deps, valeur=7, version_attendue=0)
        _geste(deps, valeur=10, version_attendue=1)
        with pytest.raises(ReglageRefuse) as exc:
            _geste(deps, valeur=14, version_attendue=1)
        assert exc.value.code == "REJ-REGLAGE-VERSION"
        with pytest.raises(ReglageRefuse):
            _geste(deps, valeur=14, version_attendue=-1)
        with pytest.raises(ReglageRefuse):
            _geste(deps, valeur=14, version_attendue="2")
        assert len(magasin.lire_chaine()) == 2


def test_la_version_attendue_n_empeche_pas_la_reprise_idempotente_d_une_valeur_deja_en_vigueur(deps):
    with stockage.transaction():
        _geste(deps, valeur=7, version_attendue=0)
        assert _geste(deps, valeur=7, version_attendue=0)["statut"] == "deja_adopte"


def test_le_retour_arriere_depile_en_une_operation_jusqu_a_l_absence(deps):
    with stockage.transaction():
        _geste(deps, valeur=7)
        _geste(deps, valeur=10)
        premier = _retour(deps)
        assert premier["statut"] == "retour_arriere" and premier["valeur"] == 7 and premier["ancienne_valeur"] == 10
        second = _retour(deps)
        assert second["valeur"] is None and second["ancienne_valeur"] == 7 and second["version"] == 4
        with pytest.raises(ReglageRefuse) as exc:
            _retour(deps)
        assert exc.value.code == "REJ-REGLAGE-RIEN-A-ANNULER"
        chaine = magasin.lire_chaine()
        assert [m["type"] for m in chaine] == ["adoption", "adoption", "retour_arriere", "retour_arriere"]
        assert magasin.valeur_en_vigueur(magasin.rejouer(chaine), CLE) is None


def test_adopter_apres_un_retour_arriere_repart_de_l_absence(deps):
    with stockage.transaction():
        _geste(deps, valeur=7)
        _retour(deps)
        suite = _geste(deps, valeur=7, approbation_id="demande-3")
        assert suite["statut"] == "adopte" and suite["version"] == 3 and suite["ancienne_valeur"] is None


def test_un_retour_arriere_sans_adoption_est_refuse_et_ne_touche_pas_un_autre_reglage(deps):
    with stockage.transaction():
        _geste(deps, valeur=7)
        with pytest.raises(ReglageRefuse) as exc:
            _retour(deps, cle="m2.jours_soumission_perimee")
        assert exc.value.code == "REJ-REGLAGE-RIEN-A-ANNULER"
        assert magasin.valeur_en_vigueur(magasin.chaine_verifiee()[1], CLE) == 7


def test_le_retour_arriere_respecte_la_version_attendue(deps):
    with stockage.transaction():
        _geste(deps, valeur=7)
        with pytest.raises(ReglageRefuse) as exc:
            _retour(deps, version_attendue=0)
        assert exc.value.code == "REJ-REGLAGE-VERSION"
        assert _retour(deps, version_attendue=1)["statut"] == "retour_arriere"


def test_les_reglages_sont_independants_les_uns_des_autres(deps):
    with stockage.transaction():
        _geste(deps, valeur=7)
        _geste(deps, cle="m2.jours_soumission_perimee", valeur=14)
        _geste(deps, cle=BORNES_M8, valeur={"pire": "20", "cible": 60})
        rejeu = magasin.chaine_verifiee()[1]
        assert magasin.valeur_en_vigueur(rejeu, CLE) == 7
        assert magasin.valeur_en_vigueur(rejeu, "m2.jours_soumission_perimee") == 14
        assert magasin.valeur_en_vigueur(rejeu, BORNES_M8) == {"pire": "20", "cible": "60"}
        assert magasin.version_de(rejeu, CLE) == 1 and magasin.version_de(rejeu, "m2.inconnu") == 0


@pytest.mark.parametrize("raison", ["", "ab", "x" * 301, 12, None, "contient\x00nul"])
def test_une_raison_absente_trop_courte_trop_longue_ou_non_imprimable_est_refusee(deps, raison):
    with stockage.transaction():
        with pytest.raises(ReglageRefuse) as exc:
            _geste(deps, raison=raison)
        assert exc.value.code == "REJ-REGLAGE-RAISON"
        assert magasin.lire_chaine() == []


@pytest.mark.parametrize("raison", [
    "Écrire à marie.tremblay@example.test pour confirmer",
    "Appeler le 418-555-0142 avant de décider",
    "NAS 046 454 286 de l'employé concerné",
    "Après l'entretien avec M. Tremblay",
])
def test_une_raison_qui_contient_un_renseignement_personnel_est_refusee(deps, raison):
    with stockage.transaction():
        with pytest.raises(ReglageRefuse) as exc:
            _geste(deps, raison=raison)
        assert exc.value.code == "REJ-REGLAGE-RAISON-PII"
        assert magasin.lire_chaine() == []
        assert _geste(deps, valeur=7)["statut"] == "adopte"  # une raison saine passe


def test_la_raison_est_nettoyee_des_espaces_multiples(deps):
    with stockage.transaction():
        _geste(deps, raison="  Décision   discutée\nen   comité  ")
        assert magasin.lire_chaine()[0]["raison"] == "Décision discutée en comité"


@pytest.mark.parametrize(("champ", "valeur"), [("par", ""), ("par", "x" * 65), ("role", ""), ("approbation_id", ""),
                                               ("approbation_id", 12), ("quand", "2026-11-02T15:00:00"),
                                               ("quand", "pas une date"), ("quand", None)])
def test_signataire_demande_et_instant_sont_exiges_avec_fuseau(deps, champ, valeur):
    with stockage.transaction():
        with pytest.raises(ReglageRefuse):
            _geste(deps, **{champ: valeur})
        assert magasin.lire_chaine() == []


def test_hors_transaction_rien_n_est_ecrit(deps):
    with stockage.transaction() as cnx:
        reglage = _reglage(deps, CLE)
    with pytest.raises(ReglageRefuse) as exc:
        magasin.adopter(cnx, reglage, 7, par="x", role="nathan_owner", approbation_id="d", raison="Raison valide",
                        quand=QUAND)
    assert exc.value.code == "REJ-REGLAGE-TRANSACTION"
    with pytest.raises(ReglageRefuse):
        magasin.adopter(None, reglage, 7, par="x", role="nathan_owner", approbation_id="d", raison="Raison valide",
                        quand=QUAND)
    assert aide.chaine() == []


def test_l_empreinte_est_deterministe_et_ne_depend_pas_de_l_ordre_des_cles(deps):
    corps = {"schema": magasin.SCHEMA_MAILLON, "rang": 0, "cle": CLE, "nouvelle_valeur": 7, "raison": "é"}
    inverse = dict(reversed(list(corps.items())))
    assert magasin.empreinte(corps) == magasin.empreinte(inverse) == magasin.empreinte({**corps, "empreinte": "x"})
    assert magasin.empreinte(corps) != magasin.empreinte({**corps, "nouvelle_valeur": 8})


# -- l'intégrité de la chaîne ------------------------------------------------------------------------------------
def _remplir(deps):
    with stockage.transaction():
        _geste(deps, valeur=7)
        _geste(deps, valeur=10)
        _geste(deps, cle=BORNES_M8, valeur={"pire": "20", "cible": 60})


def _maillons_sql(cnx):
    return cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.maillon).where(
        (REGISTRES.c.departement == magasin.DEPARTEMENT_STOCKAGE) & (REGISTRES.c.registre == magasin.REGISTRE)
    ).order_by(REGISTRES.c.rang)).all()


def _remplacer(cnx, rang, maillon):
    cnx.execute(update(REGISTRES).where(
        (REGISTRES.c.departement == magasin.DEPARTEMENT_STOCKAGE) & (REGISTRES.c.registre == magasin.REGISTRE)
        & (REGISTRES.c.rang == rang)).values(maillon=json.dumps(maillon, ensure_ascii=False, separators=(",", ":"))))


def _refaire_empreinte(maillon):
    maillon = dict(maillon)
    maillon["empreinte"] = magasin.empreinte(maillon)
    return maillon


def test_une_valeur_changee_a_la_main_casse_la_chaine_et_n_est_plus_servie(deps):
    _remplir(deps)
    with stockage.transaction() as cnx:
        (_, texte), *_ = _maillons_sql(cnx)
        maillon = json.loads(texte)
        maillon["nouvelle_valeur"] = 1
        _remplacer(cnx, 0, maillon)  # empreinte non refaite
        with pytest.raises(magasin.ChaineInvalide):
            magasin.chaine_verifiee()
        lues = lecture.adoptees()
        assert lues.chaine_valide is False and lues.valeurs == {} and "maillon 0" in lues.detail


def test_une_valeur_changee_avec_l_empreinte_refaite_casse_le_lien_suivant(deps):
    _remplir(deps)
    with stockage.transaction() as cnx:
        (_, texte), *_ = _maillons_sql(cnx)
        maillon = json.loads(texte)
        maillon["nouvelle_valeur"] = 1
        _remplacer(cnx, 0, _refaire_empreinte(maillon))
        with pytest.raises(magasin.ChaineInvalide, match="maillon 1"):
            magasin.chaine_verifiee()


def test_un_maillon_rehache_dont_seule_la_raison_change_rompt_le_lien_du_suivant(deps):
    """Aucune valeur n'a bougé (le rejeu des valeurs est cohérent) : seul le chaînage par empreinte peut le voir."""
    _remplir(deps)
    with stockage.transaction() as cnx:
        (_, texte), *_ = _maillons_sql(cnx)
        maillon = json.loads(texte)
        maillon["raison"] = "Raison réécrite après coup"
        _remplacer(cnx, 0, _refaire_empreinte(maillon))
        with pytest.raises(magasin.ChaineInvalide, match="maillon 1 : lien avec le maillon précédent rompu"):
            magasin.chaine_verifiee()


def test_un_maillon_retire_ou_deux_maillons_echanges_cassent_la_chaine(deps):
    _remplir(deps)
    with stockage.transaction() as cnx:
        lignes = _maillons_sql(cnx)
        un, deux = json.loads(lignes[1][1]), json.loads(lignes[2][1])
        _remplacer(cnx, 1, deux)
        _remplacer(cnx, 2, un)
        with pytest.raises(magasin.ChaineInvalide):
            magasin.chaine_verifiee()


def test_un_maillon_avec_un_champ_de_plus_ou_de_moins_casse_la_chaine(deps):
    _remplir(deps)
    with stockage.transaction() as cnx:
        (_, texte), *_ = _maillons_sql(cnx)
        maillon = json.loads(texte)
        _remplacer(cnx, 0, _refaire_empreinte({**maillon, "supplement": "x"}))
        with pytest.raises(magasin.ChaineInvalide, match="champs inattendus"):
            magasin.chaine_verifiee()
        maillon.pop("raison")
        _remplacer(cnx, 0, _refaire_empreinte(maillon))
        with pytest.raises(magasin.ChaineInvalide):
            magasin.chaine_verifiee()


@pytest.mark.parametrize(("champ", "valeur", "fragment"), [
    ("ancienne_valeur", 3, "ancienne valeur différente"),
    ("version", 5, "version"),
    ("version", 0, "version"),
    ("type", "retour_arriere", "retour arrière"),
    ("rang", 7, "schéma ou rang"),
    ("schema", "autre/v9", "schéma ou rang"),
    ("quand", "hier", "instant"),
])
def test_un_dernier_maillon_incoherent_meme_rehache_casse_la_chaine(deps, champ, valeur, fragment):
    """Le DERNIER maillon n'a pas de suivant dont le lien trahirait la retouche : seuls ses contrôles la voient."""
    _remplir(deps)
    with stockage.transaction() as cnx:
        lignes = _maillons_sql(cnx)
        dernier = json.loads(lignes[-1][1])
        dernier[champ] = valeur
        _remplacer(cnx, len(lignes) - 1, _refaire_empreinte(dernier))
        with pytest.raises(magasin.ChaineInvalide, match=fragment):
            magasin.chaine_verifiee()


@pytest.mark.parametrize("texte", ["pas du json", "[1, 2]", "null", '{"__opsys__": "inconnu", "v": 1}', "{"])
def test_un_maillon_illisible_est_une_chaine_invalide_jamais_une_panne(deps, texte):
    _remplir(deps)
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == magasin.DEPARTEMENT_STOCKAGE) & (REGISTRES.c.rang == 1)).values(maillon=texte))
        with pytest.raises(magasin.ChaineInvalide, match="illisible"):
            magasin.chaine_verifiee()
        lues = lecture.adoptees()
        assert lues.chaine_valide is False and lues.valeurs == {} and "illisible" in lues.detail
        assert lecture.journal() == []


def test_une_chaine_cassee_refuse_tout_nouveau_geste(deps):
    _remplir(deps)
    with stockage.transaction() as cnx:
        (_, texte), *_ = _maillons_sql(cnx)
        maillon = json.loads(texte)
        maillon["par"] = "usurpateur"
        _remplacer(cnx, 0, maillon)
        with pytest.raises(ReglageRefuse) as exc:
            _geste(deps, valeur=14)
        assert exc.value.code == "REJ-REGLAGE-CHAINE-INVALIDE"
        with pytest.raises(ReglageRefuse) as exc:
            _retour(deps)
        assert exc.value.code == "REJ-REGLAGE-CHAINE-INVALIDE"


def test_un_retour_arriere_forge_vers_une_autre_valeur_ne_se_rejoue_pas():
    base = {"schema": magasin.SCHEMA_MAILLON, "cle": "m2.x", "departement": "m02-revenue-crm", "par": "p",
            "role": "r", "approbation_id": "a", "raison": "raison", "quand": QUAND}

    def maillon(rang, precedent, **plus):
        m = {**base, "rang": rang, "precedent": precedent, **plus}
        m["empreinte"] = magasin.empreinte(m)
        return m

    a = maillon(0, "", type="adoption", version=1, ancienne_valeur=None, nouvelle_valeur=7, origine="saisie")
    b = maillon(1, a["empreinte"], type="adoption", version=2, ancienne_valeur=7, nouvelle_valeur=10, origine="saisie")
    bon = maillon(2, b["empreinte"], type="retour_arriere", version=3, ancienne_valeur=10, nouvelle_valeur=7,
                  origine="retour_arriere")
    assert magasin.rejouer([a, b, bon])["m2.x"]["pile"] == [7]
    forge = maillon(2, b["empreinte"], type="retour_arriere", version=3, ancienne_valeur=10, nouvelle_valeur=99,
                    origine="retour_arriere")
    with pytest.raises(magasin.ChaineInvalide, match="autre valeur"):
        magasin.rejouer([a, b, forge])
    sans_changement = maillon(2, b["empreinte"], type="adoption", version=3, ancienne_valeur=10, nouvelle_valeur=10,
                              origine="saisie")
    with pytest.raises(magasin.ChaineInvalide, match="sans changement"):
        magasin.rejouer([a, b, sans_changement])
    sans_rien = maillon(0, "", type="retour_arriere", version=1, ancienne_valeur=None, nouvelle_valeur=None,
                        origine="retour_arriere")
    with pytest.raises(magasin.ChaineInvalide, match="sans adoption"):
        magasin.rejouer([sans_rien])


def test_une_ecriture_concurrente_au_meme_rang_est_refusee_sans_ecraser_le_gagnant(deps):
    with stockage.transaction():
        _geste(deps, valeur=7)
        ancienne_chaine = magasin.lire_chaine()
        _geste(deps, valeur=10)  # le « gagnant » écrit le rang 1
        with pytest.raises(ReglageRefuse) as exc:
            magasin._ajouter(ancienne_chaine, {
                "type": "adoption", "cle": CLE, "departement": "m02-revenue-crm", "version": 2, "ancienne_valeur": 7,
                "nouvelle_valeur": 14, "origine": "saisie", "par": "p", "role": "nathan_owner",
                "approbation_id": "a", "raison": "perdant", "quand": QUAND})
        assert exc.value.code == "REJ-REGLAGE-CONCURRENCE"
        assert magasin.valeur_en_vigueur(magasin.chaine_verifiee()[1], CLE) == 10


def test_deux_adoptions_simultanees_de_la_meme_valeur_n_ecrivent_qu_un_maillon(deps):
    """Deux transactions concurrentes (deux fils) : SQLite les sérialise, la seconde relit l'état de la première."""
    import threading

    reglage = _reglage(deps, CLE)
    barriere = threading.Barrier(2)
    resultats, erreurs = [], []

    def adopter(numero):
        try:
            barriere.wait(timeout=10)
            with stockage.transaction() as cnx:
                resultats.append(magasin.adopter(
                    cnx, reglage, 7, par=aide.PROPRIETAIRE, role="nathan_owner", approbation_id=f"demande-{numero}",
                    raison="Décision simultanée", quand=QUAND)["statut"])
        except Exception as exc:  # noqa: BLE001 - consigné puis vérifié ci-dessous
            erreurs.append(exc)

    fils = [threading.Thread(target=adopter, args=(n,)) for n in (1, 2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)
    assert not erreurs, erreurs
    assert sorted(resultats) == ["adopte", "deja_adopte"]
    assert len(aide.chaine()) == 1


def test_la_chaine_survit_a_la_fermeture_de_la_base_et_se_rejoue_identique(deps):
    _remplir(deps)
    avant = aide.chaine()
    stockage.liberer()  # « panne » : plus aucune connexion ni cache
    apres = aide.chaine()
    assert avant == apres and len(apres) == 3
    with stockage.transaction():
        assert magasin.chaine_verifiee()[1][CLE]["pile"] == [7, 10]
