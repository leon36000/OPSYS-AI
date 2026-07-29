import sys
from pathlib import Path
import yaml
import inspect
import pytest

_RACINE = Path(__file__).resolve().parents[1]
_SRC = _RACINE / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
import garde_fou  # noqa: E402
import verdicts  # noqa: E402
from registre import Registre  # noqa: E402

_FIXTURES = _RACINE / "fixtures" / "interdits"


def _charger(nom: str):
    """Charge une fixture YAML et refuse fail-closed si le marqueur fictif est absent."""
    chemin = _FIXTURES / nom
    with open(chemin, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data.get("fictif") is not True:
        raise ValueError(
            f"Fixture {nom} non marquée fictive — collecte interrompue"
        )
    return data["cas"]


_ADVERSARIAUX = _charger("adversariaux.v1.yaml")
_LEGITIMES = _charger("legitimes.v1.yaml")

# Garde-fou de non-vacuité – la collecte échoue si les fixtures sont vides
assert _ADVERSARIAUX, "Fixture adversariale vide — collecte interrompue"
assert _LEGITIMES, "Fixture légitime vide — collecte interrompue"


@pytest.fixture(scope="module")
def adversariaux():
    with open(_FIXTURES / "adversariaux.v1.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["fictif"] is True, "Fixture adversariale non marquée fictive — refusée"
    return data["cas"]


@pytest.fixture(scope="module")
def legitimes():
    with open(_FIXTURES / "legitimes.v1.yaml", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["fictif"] is True, "Fixture légitime non marquée fictive — refusée"
    return data["cas"]


# Test 1 – Fixture adversariale : chaque cas bloqué ; stats globales
@pytest.mark.parametrize(
    "cas",
    [
        pytest.param(c, id=f"{c['famille']}-{c['texte'][:30]}")
        for c in _ADVERSARIAUX
    ],
)
def test_adversarial_each(cas):
    verdict = garde_fou.verifier_sortie(cas["texte"])
    assert verdict["code"].startswith(
        "REJ-INTERDIT-"
    ), f"Attendu blocage pour {cas['texte']!r}"


def test_adversarial_stats(adversariaux):
    bloques = 0
    famille_correcte = 0
    total = len(adversariaux)
    for cas in adversariaux:
        verdict = garde_fou.verifier_sortie(cas["texte"])
        if verdict["code"].startswith("REJ-INTERDIT-"):
            bloques += 1
            if verdict["code"] == f"REJ-INTERDIT-{cas['famille'].upper()}":
                famille_correcte += 1
    assert bloques == total, f"Doit bloquer 100% : bloqués {bloques}/{total}"
    assert famille_correcte / total >= 0.90, (
        f"Famille exacte correcte pour {famille_correcte}/{total} (< 90%)"
    )


# Test 2 – Fixture légitime : aucun faux positif
@pytest.mark.parametrize(
    "cas",
    [
        pytest.param(c, id=f"ok-{c['texte'][:30]}")
        for c in _LEGITIMES
    ],
)
def test_legitime_each(cas):
    verdict = garde_fou.verifier_sortie(cas["texte"])
    assert verdict["code"] == "OK", f"Faux positif sur {cas['texte']!r}"


def test_piege_rappel():
    assert garde_fou.verifier_sortie("Nous vous rappelons demain")["code"] == "OK", (
        "Le rappel téléphonique n'est pas un engagement chantier"
    )


def test_piege_finir_travaux_demain():
    assert garde_fou.verifier_sortie("Les travaux seront finis demain")["code"] == "REJ-INTERDIT-DATE", (
        "Annonce de fin de travaux = date interdite"
    )


# Test 4 – Une famille = un test dédié minimal (positif + négatif)
def test_prix_bloque():
    assert garde_fou.verifier_sortie("12 500 $")["code"] == "REJ-INTERDIT-PRIX"


def test_prix_ok():
    assert garde_fou.verifier_sortie("votre demande est enregistrée")["code"] == "OK"


def test_date_bloque():
    # exemple de date interdite
    assert garde_fou.verifier_sortie("Intervention programmée le 2025-04-10")["code"] == "REJ-INTERDIT-DATE"


def test_date_ok():
    assert garde_fou.verifier_sortie("Nous avons bien reçu votre message")["code"] == "OK"


def test_engagement_bloque():
    assert garde_fou.verifier_sortie("Nous nous engageons à terminer")["code"] == "REJ-INTERDIT-ENGAGEMENT"


def test_engagement_ok():
    assert garde_fou.verifier_sortie("Nous étudions votre projet avec attention")["code"] == "OK"


def test_aveu_bloque():
    assert garde_fou.verifier_sortie("C'est notre faute, nous sommes responsables")["code"] == "REJ-INTERDIT-AVEU"


def test_aveu_ok():
    assert garde_fou.verifier_sortie("Merci pour votre retour constructif")["code"] == "OK"


# Test 5 – Registre d'alerte
def test_registre_alerte_ajout():
    reg = Registre()
    texte_incorrect = "C'est garanti, nous remboursons"
    horodatage = "2026-07-26T12:00:00Z"
    verdict = garde_fou.verifier_sortie(texte_incorrect, registre=reg, horodatage=horodatage)
    assert reg.taille() == 1, "Une alerte doit être enregistrée"
    entree = reg.lire()[0]
    assert entree["type_entree"] == "alerte"
    assert entree["payload"]["code_verdict"] == verdict["code"]
    assert reg.valider_chaine(), "La chaîne d'audit doit rester intègre après l'ajout"



def test_registre_texte_legitime_n_ecrit_rien():
    reg = Registre()
    nb_avant = reg.taille()
    horodatage = "2026-07-26T12:00:00Z"
    garde_fou.verifier_sortie("Merci de nous avoir contactés", registre=reg, horodatage=horodatage)
    assert reg.taille() == nb_avant, "Aucune entrée pour un texte légitime"



def test_casse_insensibilite():
    assert garde_fou.verifier_sortie("GARANTI")["code"] == "REJ-INTERDIT-ENGAGEMENT"
    assert garde_fou.verifier_sortie("Garanti")["code"] == "REJ-INTERDIT-ENGAGEMENT"
    assert garde_fou.verifier_sortie("garanti")["code"] == "REJ-INTERDIT-ENGAGEMENT"


def test_apostrophes_identiques():
    assert garde_fou.verifier_sortie("c'est notre faute")["code"] == "REJ-INTERDIT-AVEU"
    assert garde_fou.verifier_sortie("c’est notre faute")["code"] == "REJ-INTERDIT-AVEU"  # U+2019


# Test 7 – Texte vide / non-string
def test_texte_vide_ok():
    assert garde_fou.verifier_sortie("")["code"] == "OK"


def test_None_leve_TypeError():
    with pytest.raises(TypeError):
        garde_fou.verifier_sortie(None)


def test_int_leve_TypeError():
    with pytest.raises(TypeError):
        garde_fou.verifier_sortie(42)


# Test 8 – Déterminisme
def test_determinisme():
    texte = "Nous nous engageons à une finition soignée"
    v1 = garde_fou.verifier_sortie(texte)
    v2 = garde_fou.verifier_sortie(texte)
    assert v1 == v2, "Les verdicts doivent être identiques d'un appel à l'autre"


# Test 9 – Zéro réseau / zéro horloge
def test_zero_reseau_zero_horloge():
    source = inspect.getsource(garde_fou)
    interdits = ["urllib", "socket", "http.client", "datetime.now", "time.time"]
    for mot in interdits:
        assert mot not in source, f"'{mot}' trouvé dans le source de garde_fou"


# Test 10 – Zéro LLM
def test_zero_llm():
    source = inspect.getsource(garde_fou)
    interdits = ["openai", "litellm", "requests", "completion"]
    for mot in interdits:
        assert mot not in source, f"'{mot}' trouvé dans le source de garde_fou"
