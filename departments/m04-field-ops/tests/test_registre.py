import os
import subprocess
import sys
from pathlib import Path

import m4_field_ops.registre as registre_mod
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"


# Alias pour simplifier
Registre = registre_mod.Registre
VerificationError = registre_mod.VerificationError

# Types valides selon le contrat M4-S002
TYPE_VALIDES = {
    "intervention_inscrite",
    "transition_statut",
    "pointage",
    "demande_revue",
    "resolution_revue",
}

# Horodatage valide avec fuseau +00:00
H_VALIDE = "2025-04-14T12:00:00+00:00"

# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------
@pytest.fixture
def registre_vide():
    """Un registre fraîchement initialisé."""
    return Registre()

@pytest.fixture
def registre_avec_une_entree(registre_vide):
    """Registre contenant une entrée d'intervention valide."""
    reg = registre_vide
    entree = {
        "type_entree": "intervention_inscrite",
        "horodatage": H_VALIDE,
        "donnees": {"ref": "A001"},
    }
    reg.ajouter(entree)
    return reg

@pytest.fixture
def registre_avec_chainon(registre_vide):
    """Registre avec une petite chaîne de 3 entrées."""
    reg = registre_vide
    for i in range(3):
        reg.ajouter({
            "type_entree": "pointage",
            "horodatage": f"2025-04-14T1{i}:00:00+00:00",
            "valeur": i,
        })
    return reg

# -------------------------------------------------------------------
# Tests de création et propriétés de base
# -------------------------------------------------------------------
def test_initialisation_registre_vide():
    """Contrat du patron prouvé : un registre vide a taille 0, lire() vide, et
    tete() vaut None — l'ancre externe n'existe qu'à partir du premier maillon
    (c'est l'AJOUT qui crée la tête ; None distingue « jamais rien écrit » de
    toute vraie tête, qui est un hex non vide)."""
    r = Registre()
    assert r.taille() == 0, "un registre neuf est vide"
    assert r.lire() == [], "lire() d'un registre neuf retourne une liste vide"
    assert r.tete() is None, "tete() d'un registre neuf vaut None (aucune ancre encore)"


def test_lire_renvoie_copie_profonde(registre_avec_une_entree):
    """Modifier le résultat de lire() n'altère pas le registre."""
    reg = registre_avec_une_entree
    original = reg.lire()
    original[0]["donnees"]["ref"] = "MODIFIE"
    relu = reg.lire()
    assert relu[0]["donnees"]["ref"] != "MODIFIE", "La copie de lire() doit être indépendante"

# -------------------------------------------------------------------
# Tests d'ajout et validation d'entrée
# -------------------------------------------------------------------
class TestAjoutEntree:
    def test_ajout_entree_valide_retourne_ligne_id(self, registre_vide):
        """L'ajout d'une entrée valide retourne un identifiant de ligne non vide."""
        entree = {"type_entree": "intervention_inscrite", "horodatage": H_VALIDE}
        ligne_id = registre_vide.ajouter(entree)
        assert isinstance(ligne_id, str) and len(ligne_id) > 0, "ligne_id doit être une chaîne non vide"

    def test_type_entree_obligatoire(self, registre_vide):
        """L'absence de type_entree lève une ValueError."""
        with pytest.raises(ValueError, match="type_entree"):
            registre_vide.ajouter({"horodatage": H_VALIDE})

    @pytest.mark.parametrize("type_invalide", [
        "visite",                # minuscule
        "INTERVENTION_INSCRITE", # majuscule
        "inconnu",
        "",
        None,
        42,
    ], ids=["minuscule", "majuscule", "inconnu", "vide", "none", "entier"])
    def test_type_entree_hors_enumere_leve_valueerror(self, registre_vide, type_invalide):
        """Un type_entree non listé dans l'énuméré fermé provoque une ValueError nommant l'énuméré."""
        entree = {"type_entree": type_invalide, "horodatage": H_VALIDE}
        with pytest.raises(ValueError, match="type_entree"):
            registre_vide.ajouter(entree)

    @pytest.mark.parametrize("mauvais_horodatage", [
        "2025-04-14T12:00:00",       # sans fuseau
        "14/04/2025",
        "abcdef",
        "",
        None,
    ], ids=["sans_fuseau", "date_fr", "lettres", "vide", "none"])
    def test_horodatage_sans_fuseau_leve_valueerror(self, registre_vide, mauvais_horodatage):
        """Un horodatage absent du format ISO-8601 avec fuseau lève ValueError."""
        entree = {
            "type_entree": "intervention_inscrite",
            "horodatage": mauvais_horodatage,
        }
        with pytest.raises(ValueError, match="horodatage"):
            registre_vide.ajouter(entree)

    def test_ajout_entree_dict_non_modifiee_par_appelant(self, registre_vide):
        """La mutation du dictionnaire original après ajout n'affecte pas le registre (copie profonde)."""
        entree = {"type_entree": "pointage", "horodatage": H_VALIDE, "extra": "original"}
        reg = registre_vide
        reg.ajouter(entree)
        entree["extra"] = "modifie"
        entree["nouveau_champ"] = "injecte"
        stocke = reg.lire()[0]
        assert stocke.get("extra") == "original", "La copie doit conserver la valeur initiale"

    def test_mutation_imbriquee_de_l_original_n_affecte_pas_le_registre(self, registre_vide):
        """DISCRIMINANT du deepcopy : la construction du maillon par étalement
        ({**...}) protège déjà les clés de PREMIER niveau — muter une chaîne
        top-level ne prouve rien (mesuré : mutation deepcopy->rien non détectée
        avec ce seul cas). Seule une mutation IMBRIQUÉE distingue copie profonde
        et copie superficielle."""
        entree = {
            "type_entree": "pointage",
            "horodatage": H_VALIDE,
            "gps": {"lat": 45.5, "lon": -73.5},
        }
        registre_vide.ajouter(entree)
        entree["gps"]["lat"] = 99.9
        stocke = registre_vide.lire()[0]
        assert stocke["gps"]["lat"] == 45.5, (
            "la mutation imbriquée de l'original ne doit pas atteindre le registre "
            "(copie PROFONDE exigée, pas un étalement superficiel)"
        )
        assert "nouveau_champ" not in stocke, "Aucun champ ajouté après ajout ne doit apparaître"

    def test_ligne_id_et_precedent_ligne_id_fournis_par_appelant_sont_retires(self, registre_vide):
        """Les clés ligne_id et precedent_ligne_id, si présentes dans l'entrée soumise, sont ignorées."""
        entree = {
            "type_entree": "demande_revue",
            "horodatage": H_VALIDE,
            "ligne_id": "impose",
            "precedent_ligne_id": "forcer",
        }
        reg = registre_vide
        ligne_id = reg.ajouter(entree)
        stocke = reg.lire()[0]
        assert stocke["ligne_id"] != "impose", "ligne_id imposé doit être remplacé"
        assert stocke.get("precedent_ligne_id") != "forcer", "precedent_ligne_id imposé doit être ignoré"
        # Vérifier que le vrai ligne_id n'est pas celui imposé
        assert ligne_id != "impose", "Le ligne_id retourné ne doit pas être celui fourni"

# -------------------------------------------------------------------
# Tests de chaînage et intégrité
# -------------------------------------------------------------------
class TestChainage:
    def test_valider_chaine_vide_est_true(self, registre_vide):
        """La chaîne vide est valide."""
        assert registre_vide.valider_chaine() is True

    def test_valider_chaine_intacte_est_true(self, registre_avec_chainon):
        """Une chaîne non altérée passe la validation."""
        assert registre_avec_chainon.valider_chaine() is True

    def test_suppression_maillon_rechaine_naivement_fait_echouer_valider_chaine(self, registre_avec_chainon):
        """Supprimer un maillon du milieu et recoudre les suivants sans recalculer l'identifiant
        casse l'intégrité de la chaîne."""
        reg = registre_avec_chainon
        chaine = reg._chain
        # On supprime le deuxième élément (index 1)
        del chaine[1]
        # Maintenant on doit "recoudre" : le precedent_ligne_id de l'élément désormais en position 1
        # pointe vers l'élément 0. Si on ne fait rien, il pointe encore vers l'ancien prédécesseur ?
        # En fait, après suppression, le precedent_ligne_id n'est pas modifié, il peut encore pointer vers un
        # élément absent.
        # Selon le contrat, même une simple suppression sans recousure doit être détectée.
        # On ne fait rien de plus, le simple fait d'avoir supprimé un maillon casse la chaîne.
        assert reg.valider_chaine() is False, "La suppression d'un maillon doit invalider la chaîne"

    def test_falsification_valeur_maillon_invalide_chaine(self, registre_avec_chainon):
        """Altérer une valeur dans un maillon rend valider_chaine False."""
        reg = registre_avec_chainon
        # Modifier directement une donnée non protégée
        reg._chain[1]["valeur"] = 9999
        assert reg.valider_chaine() is False

    def test_reordonner_deux_maillons_invalide_chaine(self, registre_avec_chainon):
        """Échanger deux maillons consécutifs casse la chaîne."""
        reg = registre_avec_chainon
        chaine = reg._chain
        chaine[1], chaine[2] = chaine[2], chaine[1]
        assert reg.valider_chaine() is False

    def test_tronquer_dernier_maillon_detecte_par_ancre(self, registre_avec_chainon):
        """Retirer le dernier maillon d'une chaîne complète est détecté via une ancre externe."""
        reg = registre_avec_chainon
        ancre_originale = reg.tete()
        # On supprime le dernier élément
        reg._chain.pop()
        # La chaîne interne paraît localement cohérente (car tout est recalculé à partir de la tête du dernier restant)
        # mais l'ancre ne correspond plus à la tête actuelle.
        assert reg.valider_chaine(ancre=ancre_originale) is False, "L'ancre externe doit détecter la troncature"

    def test_ancre_fournie_differente_tete_detecte_reecriture_complete(self, registre_avec_chainon):
        """Lorsque l'ancre externe ne correspond pas à la tête, assert_chaine lève une exception
        signalant une possible réécriture complète."""
        reg = registre_avec_chainon
        # ancre totalement fausse
        fausse_ancre = "0123456789abcdef"
        # Alternance REGEX (revue M4-S002-r1, Grok-4.5) : `"a" or "b"` en Python
        # s'évalue en la seule chaîne "a" — le second littéral était mort.
        with pytest.raises(VerificationError, match="ancre|réécriture"):
            reg.assert_chaine(ancre=fausse_ancre)

    def test_corruption_interne_leve_verificationerror_pas_reecriture(self, registre_avec_chainon):
        """Une altération partielle de la chaîne est diagnostiquée comme corruption interne,
        pas comme une discordance d'ancre."""
        reg = registre_avec_chainon
        ancre_valide = reg.tete()
        # On modifie une valeur
        reg._chain[1]["valeur"] = -1
        with pytest.raises(VerificationError, match="invalide|altérée|incohérent"):
            reg.assert_chaine(ancre=ancre_valide)

# -------------------------------------------------------------------
# Tests de déterminisme inter-processus
# -------------------------------------------------------------------
def test_determinisme_tete_entre_processus():
    """Deux processus avec des PYTHONHASHSEED différentes produisent la même tête
    pour une séquence identique d'entrées."""
    # Script que chaque sous-processus exécutera
    script = """
import sys, json
from pathlib import Path
_SRC = Path(r'{src}')
sys.path.insert(0, str(_SRC))
from m4_field_ops.registre import Registre

entrees = [
    {{"type_entree": "intervention_inscrite", "horodatage": "2025-04-14T12:00:00+00:00", "id": 1}},
    {{"type_entree": "pointage", "horodatage": "2025-04-14T13:00:00+00:00", "quantite": 5}},
]
reg = Registre()
for e in entrees:
    reg.ajouter(e)
print(reg.tete())
"""
    script_formate = script.format(src=_SRC)

    seeds = ["123", "456"]
    sorties = []
    for seed in seeds:
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", script_formate],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        tete = result.stdout.strip()
        assert len(tete) > 0, f"Avec PYTHONHASHSEED={seed}, la tête ne doit pas être vide"
        sorties.append(tete)

    assert sorties[0] == sorties[1], (
        f"Les têtes doivent être identiques malgré un PYTHONHASHSEED différent : "
        f"seed 123 → {sorties[0]}, seed 456 → {sorties[1]}"
    )

def test_enumere_des_types_est_fige():
    """PROUVE que l'énuméré des type_entree est FIGÉ à l'ensemble ratifié —
    patron « catalogue gelé » (leçon du catalogue de verdicts M2, CA-M2-13) :
    les tests de rejet ne détectent pas un type AJOUTÉ en douce (mutation
    « type_pirate » mesurée non détectée sans ce test). Étendre l'énuméré doit
    être un acte conscient : mettre à jour CE test en même temps que la
    constante, avec revue."""
    attendu = {
        "intervention_inscrite",
        "transition_statut",
        "pointage",
        "demande_revue",
        "resolution_revue",
        "consentement_gps",     # PLAN T4.2 : §4 de POLITIQUE-geolocalisation.md
        "acces_position_gps",   # PLAN T4.2 : §6
        "purge_retention_gps",  # PLAN T4.2 : §5
        "variance_m6_recue",  # T1.3-b : outbox.enregistrer_signal_variance
        "assignation_technicien",  # PLAN T1.4-k : etats.assigner_technicien
        "localisation_chantier",  # PLAN T4.1-a : localisation.confirmer (coordonnées chiffrées)
        "cedule_proposee",  # PLAN T4.1-d : cedule_tournees.proposer (plan stocké, jamais une vérité)
        "cedule_appliquee",  # PLAN T4.1-d : cedule_tournees.appliquer (via etats.assigner_technicien)
    }
    assert set(registre_mod._TYPE_ENTREE_VALIDES) == attendu, (
        f"énuméré modifié sans ratification : {set(registre_mod._TYPE_ENTREE_VALIDES) ^ attendu}"
    )

def _entree(**extra):
    base = {"type_entree": "pointage", "horodatage": "2025-04-14T12:00:00+00:00"}
    base.update(extra)
    return base


def test_identifiants_fournis_par_l_appelant_sont_neutralises():
    """Un appelant qui FOURNIT ligne_id/precedent_ligne_id ne doit pas pouvoir
    influencer la dérivation ni corrompre la chaîne : sans le retrait explicite
    (mutation « pops retirés » mesurée non détectée), l'id forgé entre dans
    l'empreinte à l'ajout mais est exclu au recalcul de validation → registre
    invalide alors que l'appel a réussi."""
    reg = registre_mod.Registre()
    lid = reg.ajouter(_entree(ligne_id="forge", precedent_ligne_id="forge-prec"))
    assert lid != "forge", "le ligne_id doit être dérivé, jamais repris de l'appelant"
    stocke = reg.lire()[0]
    assert stocke["ligne_id"] == lid
    assert stocke["precedent_ligne_id"] is None
    assert reg.valider_chaine() is True, (
        "l'ajout d'une entrée portant des ids forgés doit laisser la chaîne valide "
        "(les ids fournis sont retirés AVANT dérivation)"
    )


def test_lire_depuis_retourne_une_copie_independante():
    """La branche lire(depuis=...) doit copier aussi profondément que lire() :
    muter le résultat ne corrompt pas le registre (mutation « retour direct sur
    la branche depuis » mesurée non détectée par le seul test sans argument)."""
    reg = registre_mod.Registre()
    lid1 = reg.ajouter(_entree(gps={"lat": 45.5, "lon": -73.5}))
    reg.ajouter(_entree(type_entree="transition_statut"))
    vue = reg.lire(depuis=lid1)
    vue[0]["gps"]["lat"] = 99.9
    vue[0]["type_entree"] = "pirate"
    assert reg.lire(depuis=lid1)[0]["gps"]["lat"] == 45.5
    assert reg.valider_chaine() is True, (
        "muter le résultat de lire(depuis) ne doit pas atteindre la chaîne interne"
    )


def test_troncature_de_queue_detectee_sans_ancre():
    """Supprimer le DERNIER maillon laisse une chaîne interne parfaitement
    cohérente (chaque maillon se recalcule) : seul le souvenir interne de
    l'empreinte globale la détecte sans ancre externe (contrôle mesuré comme
    unique détecteur — sa suppression n'était pas détectée)."""
    reg = registre_mod.Registre()
    reg.ajouter(_entree())
    reg.ajouter(_entree(type_entree="transition_statut"))
    del reg._chain[-1]  # falsification directe : troncature de la queue
    assert reg.valider_chaine() is False, (
        "la troncature de queue doit être détectée MÊME sans ancre "
        "(empreinte globale mémorisée au dernier ajout)"
    )
    with pytest.raises(VerificationError, match="empreinte globale"):
        reg.assert_chaine()


def test_falsification_du_seul_champ_precedent_detectee():
    """Falsifier precedent_ligne_id SANS toucher ligne_id n'altère ni la liste
    des ligne_id (contrôle d'empreinte globale aveugle) ni le recalcul depuis la
    marche (qui utilise le précédent ATTENDU, pas le champ) : le contrôle de
    cohérence du champ est l'unique détecteur (mesuré : sa suppression n'était
    pas détectée)."""
    reg = registre_mod.Registre()
    reg.ajouter(_entree())
    reg.ajouter(_entree(type_entree="transition_statut"))
    reg._chain[1]["precedent_ligne_id"] = "faux-precedent"
    assert reg.valider_chaine() is False
    with pytest.raises(VerificationError, match="precedent_ligne_id incohérent"):
        reg.assert_chaine()

