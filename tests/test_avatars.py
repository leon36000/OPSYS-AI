"""Avatars des départements (chantier « avatars », étape 1) : bloc `avatar` des manifestes, contrôle de
`opsys-metier verifier`, surcharges du client dans le profil d'entreprise et résolution de l'identité effective.

Noms de personnes et surcharges : données FICTIVES."""

from __future__ import annotations

import dataclasses
import shutil

import pytest
import yaml

from opsys import avatars, cli, taxonomie
from opsys.avatars import AvatarInvalide, Surcharge
from opsys.departements import charger_departements, lire_manifeste

# La décision d'architecte : nom par défaut de chaque département.
NOMS_PAR_DEFAUT = {
    "m01-front-office": "Léa",
    "m02-revenue-crm": "Victor",
    "m03-estimation": "Mathis",
    "m04-field-ops": "Gabriel",
    "m05-financecore": "Sophie",
    "m06-material-control": "Rosalie",
    "m07-marketing": "Chloé",
    "m08-analytics": "Olivier",
    "m09-strategic-intelligence": "Athéna",
    "m10-memoire": "Mnémo",
}

AVATAR_VALIDE = {
    "nom": "Démo",
    "role": "Avatar fictif",
    "voix": "voix.demo.defaut",
    "visage": "visage.demo.defaut",
    "canaux": {"messagerie": "disponible", "voix": "prevu"},
}


@pytest.fixture(scope="module")
def reels():
    return charger_departements()


def _copie_demo(racine_demo, tmp_path, avatar):
    cible = tmp_path / "departements"
    shutil.copytree(racine_demo, cible)
    chemin = cible / "m09-demo" / "department.yaml"
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    if avatar is None:
        donnees.pop("avatar", None)
    else:
        donnees["avatar"] = avatar
    chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    return cible


def _profil(contenu: dict):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(yaml.safe_dump(contenu, allow_unicode=True), encoding="utf-8")
    return fichier


# --- Manifestes réels ---


def test_chaque_departement_reel_porte_son_avatar_par_defaut(reels):
    assert {ident: dep.avatar.nom for ident, dep in reels.items()} == NOMS_PAR_DEFAUT
    for dep in reels.values():
        assert dep.avatar.role and len(dep.avatar.role) <= avatars.ROLE_MAX
        assert dep.avatar.voix.startswith("voix.") and dep.avatar.visage.startswith("visage.")
        # Seule la messagerie existe aujourd'hui ; voix et audiovisuel sont annoncés, jamais affirmés.
        assert dep.avatar.canaux == {"messagerie": "disponible", "voix": "prevu", "audiovisuel": "prevu"}
    assert avatars.verifier_declarations(reels) == []


def test_opsys_verifier_accepte_les_avatars_reels(opsys_home, capsys):
    assert cli.main(["verifier"]) == 0
    assert "10 avatars aux noms distincts" in capsys.readouterr().out


# --- Bloc `avatar` d'un manifeste ---


def test_bloc_avatar_valide_normalise(racine_demo, tmp_path):
    canaux_desordre = {"voix": "prevu", "messagerie": "disponible"}
    cible = _copie_demo(racine_demo, tmp_path, {**AVATAR_VALIDE, "canaux": canaux_desordre})
    dep = lire_manifeste(cible / "m09-demo")
    assert dep.avatar == avatars.Avatar(
        nom="Démo", role="Avatar fictif", voix="voix.demo.defaut", visage="visage.demo.defaut",
        canaux={"messagerie": "disponible", "voix": "prevu"},
    )
    assert list(dep.avatar.canaux) == ["messagerie", "voix"]  # ordre stable, pas celui du YAML


def test_bloc_avatar_absent_reste_lisible_mais_le_verificateur_le_refuse(racine_demo, tmp_path, monkeypatch, capsys):
    cible = _copie_demo(racine_demo, tmp_path, None)
    assert lire_manifeste(cible / "m09-demo").avatar is None
    assert avatars.verifier_declarations(charger_departements(cible)) == [
        "m09-demo : department.yaml ne déclare pas de bloc avatar (nom, role, voix, visage, canaux)"
    ]
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(cible))
    assert cli.main(["verifier"]) == 1
    assert "avatars des départements invalides" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("changement", "message"),
    [
        ({"nom": None}, "champ\\(s\\) obligatoire\\(s\\) manquant\\(s\\) \\['nom'\\]"),
        ({"role": None}, "manquant\\(s\\) \\['role'\\]"),
        ({"voix": None}, "manquant\\(s\\) \\['voix'\\]"),
        ({"visage": None}, "manquant\\(s\\) \\['visage'\\]"),
        ({"canaux": None}, "manquant\\(s\\) \\['canaux'\\]"),
        ({"pronom": "elle"}, "clé\\(s\\) inconnue\\(s\\) \\['pronom'\\]"),
        ({"nom": ""}, "nom requis"),
        ({"nom": "R2D2"}, "refusé : des lettres seulement"),
        ({"nom": "Léa <b>"}, "refusé"),
        ({"nom": "A" * 41}, "au plus 40"),
        ({"role": "x" * 81}, "au plus 80"),
        ({"role": "<script>"}, "chevron refusé"),
        ({"voix": "elevenlabs:rachel"}, "voix 'elevenlabs:rachel' mal formé"),
        ({"voix": "visage.demo.defaut"}, "voix 'visage.demo.defaut' mal formé"),
        ({"voix": "voix.demo"}, "mal formé"),
        ({"visage": "https://exemple.invalid/visage.glb"}, "visage .* mal formé"),
        ({"visage": "visage.Demo.defaut"}, "mal formé"),
        ({"canaux": {}}, "objet non vide"),
        ({"canaux": ["messagerie"]}, "objet non vide"),
        ({"canaux": {"telepathie": "prevu"}}, "canal inconnu 'telepathie'"),
        ({"canaux": {"messagerie": "actif"}}, "état 'actif'"),
        ({"canaux": {"voix": "disponible"}}, "canaux.voix déclaré disponible, mais aucun runtime"),
        ({"canaux": {"audiovisuel": "disponible"}}, "canaux.audiovisuel déclaré disponible"),
    ],
)
def test_bloc_avatar_invalide_refuse(racine_demo, tmp_path, changement, message):
    avatar = {**AVATAR_VALIDE, **changement}
    avatar = {cle: valeur for cle, valeur in avatar.items() if valeur is not None}
    cible = _copie_demo(racine_demo, tmp_path, avatar)
    with pytest.raises(ValueError, match=message):
        lire_manifeste(cible / "m09-demo")


def test_bloc_avatar_qui_n_est_pas_un_objet_refuse(racine_demo, tmp_path):
    cible = _copie_demo(racine_demo, tmp_path, "Léa")
    with pytest.raises(ValueError, match="avatar doit être un objet"):
        lire_manifeste(cible / "m09-demo")


def test_noms_acceptes_accents_trait_d_union_apostrophe():
    for nom in ("Léa", "Marie-Ève", "O’Neil", "D'Arcy", "Jean Philippe", "Mnémo"):
        assert avatars.valider_nom(nom, "test") == nom
    assert avatars.valider_nom("  Léa  ", "test") == "Léa"


def test_deux_manifestes_au_meme_nom_casse_et_accents_ignores(reels):
    m1, m2 = reels["m01-front-office"], reels["m02-revenue-crm"]
    jumeau = dataclasses.replace(m2, avatar=dataclasses.replace(m2.avatar, nom="LEA"))
    problemes = avatars.verifier_declarations({m1.id: m1, m2.id: jumeau})
    assert problemes == [
        "manifestes : nom d'avatar 'Léa' partagé par m01-front-office, m02-revenue-crm (casse et accents ignorés)"
    ]


# --- Surcharges du client et résolution ---


def test_sans_surcharge_l_identite_effective_est_le_defaut(reels):
    identites = avatars.resoudre_identites(reels)
    assert list(identites) == list(NOMS_PAR_DEFAUT)
    lea = identites["m01-front-office"]
    assert (lea.nom, lea.voix, lea.visage) == ("Léa", "voix.lea.defaut", "visage.lea.defaut")
    assert lea.code == "M1" and lea.role == reels["m01-front-office"].avatar.role
    assert lea.sources == {"nom": "manifeste", "voix": "manifeste", "visage": "manifeste"}


def test_le_client_renomme_et_change_voix_et_visage(reels):
    surcharges = avatars.normaliser_surcharges({
        "m01-front-office": {"nom": "Julie", "voix": "voix.julie.chaleureuse", "visage": "visage.julie.defaut"},
        "m05-financecore": {"voix": "voix.sophie.posee"},
    })
    identites = avatars.resoudre_identites(reels, surcharges)
    julie = identites["m01-front-office"]
    assert (julie.nom, julie.voix, julie.visage) == ("Julie", "voix.julie.chaleureuse", "visage.julie.defaut")
    assert julie.sources == {"nom": "entreprise", "voix": "entreprise", "visage": "entreprise"}
    # Le rôle et les canaux restent ceux du manifeste : le client ne déclare pas ce que le département sait faire.
    assert julie.role == reels["m01-front-office"].avatar.role
    assert julie.canaux == reels["m01-front-office"].avatar.canaux
    sophie = identites["m05-financecore"]
    assert (sophie.nom, sophie.voix) == ("Sophie", "voix.sophie.posee")
    assert sophie.sources == {"nom": "manifeste", "voix": "entreprise", "visage": "manifeste"}
    assert identites["m02-revenue-crm"].nom == "Victor"


def test_deux_avatars_peuvent_echanger_leurs_noms(reels):
    surcharges = {"m01-front-office": Surcharge(nom="Victor"), "m02-revenue-crm": Surcharge(nom="Léa")}
    identites = avatars.resoudre_identites(reels, surcharges)
    assert (identites["m01-front-office"].nom, identites["m02-revenue-crm"].nom) == ("Victor", "Léa")


@pytest.mark.parametrize(
    ("surcharges", "message"),
    [
        ({"m02-revenue-crm": Surcharge(nom="Léa")},
         "nom d'avatar 'Léa' partagé par m01-front-office, m02-revenue-crm"),
        ({"m02-revenue-crm": Surcharge(nom="lea")}, "partagé par m01-front-office, m02-revenue-crm"),
        ({"m02-revenue-crm": Surcharge(nom="Julie"), "m03-estimation": Surcharge(nom="Julie")},
         "partagé par m02-revenue-crm, m03-estimation"),
        ({"m11-inexistant": Surcharge(nom="Julie")}, "département\\(s\\) inconnu\\(s\\) \\['m11-inexistant'\\]"),
    ],
)
def test_resolution_refuse_doublon_et_departement_inconnu(reels, surcharges, message):
    with pytest.raises(AvatarInvalide, match=message):
        avatars.resoudre_identites(reels, surcharges)


def test_resolution_refuse_un_departement_sans_avatar(reels):
    m1 = reels["m01-front-office"]
    with pytest.raises(AvatarInvalide, match="sans avatar"):
        avatars.resoudre_identites({m1.id: dataclasses.replace(m1, avatar=None)})


@pytest.mark.parametrize(
    ("brut", "message"),
    [
        (["m01-front-office"], "doit être un objet"),
        ({"m01-front-office": {}}, "objet non vide"),
        ({"m01-front-office": "Julie"}, "objet non vide"),
        ({"m01-front-office": {"role": "Patronne"}}, "non personnalisable\\(s\\) \\['role'\\]"),
        ({"m01-front-office": {"canaux": {"voix": "disponible"}}}, "non personnalisable\\(s\\) \\['canaux'\\]"),
        ({"m01-front-office": {"nom": "J" * 41}}, "au plus 40"),
        ({"m01-front-office": {"nom": "Julie 2"}}, "lettres seulement"),
        ({"m01-front-office": {"nom": "Julie\n"}}, None),  # espaces de bord retirés : accepté
        ({"m01-front-office": {"nom": "Ju\x00lie"}}, "lettres seulement"),
        ({"m01-front-office": {"nom": "🙂"}}, "lettres seulement"),
        ({"m01-front-office": {"nom": 12}}, "nom requis"),
        ({"m01-front-office": {"voix": "openai/alloy"}}, "mal formé"),
        ({"m01-front-office": {"visage": "visage..defaut"}}, "mal formé"),
        ({1: {"nom": "Julie"}}, "identifiant de département attendu"),
    ],
)
def test_surcharges_mal_formees(brut, message):
    if message is None:
        assert avatars.normaliser_surcharges(brut)["m01-front-office"].nom == "Julie"
        return
    with pytest.raises(AvatarInvalide, match=message):
        avatars.normaliser_surcharges(brut)


# --- Profil d'entreprise ($OPSYS_HOME/entreprise.yaml) ---


def test_profil_absent_ou_sans_cle_garde_les_defauts(opsys_home, reels):
    assert avatars.lire_surcharges() == {}
    _profil({"zone_desservie": ["Québec"]})
    assert avatars.lire_surcharges() == {}
    assert avatars.identites_effectives(reels)["m01-front-office"].nom == "Léa"


def test_profil_avec_surcharge_resolue(opsys_home, reels):
    _profil({"avatars": {"m10-memoire": {"nom": "Mémoire Vive"}}})
    assert avatars.identites_effectives(reels)["m10-memoire"].nom == "Mémoire Vive"
    assert avatars.verifier_profil(reels) == []


def test_profil_casse_n_est_jamais_lu_comme_absent(opsys_home, reels):
    fichier = _profil({"avatars": {"m01-front-office": {"nom": "Julie 2"}}})
    with pytest.raises(taxonomie.ProfilInvalide, match="lettres seulement"):
        avatars.lire_surcharges()
    fichier.write_text("avatars: [\n", encoding="utf-8")
    with pytest.raises(taxonomie.ProfilInvalide, match="illisible"):
        avatars.lire_surcharges()


def test_opsys_verifier_refuse_une_surcharge_en_doublon(opsys_home, capsys):
    _profil({"avatars": {"m03-estimation": {"nom": "Gabriel"}}})
    assert cli.main(["verifier"]) == 1
    erreur = capsys.readouterr().err
    assert "avatars personnalisés invalides" in erreur
    assert "partagé par m03-estimation, m04-field-ops" in erreur


def test_opsys_verifier_refuse_une_surcharge_d_un_departement_inconnu(opsys_home, capsys):
    _profil({"avatars": {"m11-inexistant": {"nom": "Julie"}}})
    assert cli.main(["verifier"]) == 1
    assert "département(s) inconnu(s) ['m11-inexistant']" in capsys.readouterr().err


def test_opsys_verifier_accepte_une_surcharge_valide(opsys_home, capsys):
    _profil({"avatars": {"m01-front-office": {"nom": "Julie", "voix": "voix.julie.defaut"}}})
    assert cli.main(["verifier"]) == 0
    assert "10 avatars aux noms distincts" in capsys.readouterr().out
