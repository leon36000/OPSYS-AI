"""Tests pour core/src/opsys_core/objects/{port,local_cas}.py (C05-005) —
ObjectStorePort (contrat provider-neutre) et CasLocal (magasin adressé
par contenu, stockage disque local), DEUXIÈME tâche de la phase C05
après C05-001 (config/connexion PostgreSQL) et à la suite de C05-002
(moteur de migrations, phase C05 non séquentielle par dépendances).

Couvre les 4 cas RED obligatoires de tasks/C05-005.md :
  1. octets différents ne partagent pas le même ref
  2. hash mismatch bloque
  3. path traversal impossible
  4. delete logique distinct de purge

Conception revue par architecture AVANT code (subagent `architecte`,
Claude Opus 5 natif) — verdict complet dans l'Evidence Bundle. Points
notables de la revue, chacun couvert par un test dédié ci-dessous :
  - piège bool/int sur ObjectRef.size (bool est une sous-classe d'int en
    Python — isinstance(True, int) est vrai — sens inverse du piège déjà
    rencontré sur `reversible` en C05-002, ici on EXCLUT le bool)
  - ObjectRef re-validée par CasLocal à CHAQUE accès, pas seulement à la
    construction (anticipe une désérialisation future qui contournerait
    __post_init__, ex. C05-006 manifeste de sauvegarde)
  - vérification hash à la lecture sur un SEUL descripteur de fichier
    (jamais ouvrir/fermer/rouvrir — fenêtre TOCTOU), isolée du contrôle
    de taille par une corruption à longueur CONSTANTE
  - résurrection : put() du même contenu qu'un objet supprimé
    logiquement le fait revivre (tombstone retiré)
  - collision de nom délibérée avec opsys_core.authz.model.ObjectRef
    (objet AUTORISÉ, forme différente) — documentée dans port.py, jamais
    importée sans alias dans ce fichier
  - S3-ready sans code S3 : double structurel (duck-typing) satisfait
    isinstance(x, ObjectStorePort) sans hériter du Protocol ; zéro
    occurrence de boto3 dans opsys_core/objects/

Aucun conftest.py (convention déjà mesurée sur ce dépôt, cf.
test_postgres_configuration.py) — chaque fichier insère core/src
lui-même.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import sys
from io import BytesIO
from pathlib import Path
from threading import Barrier
from typing import BinaryIO

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from opsys_core.objects.local_cas import (
    CasLocal,
    CheminHorsRacineRefuse,
    HashMismatch,
    ObjetIntrouvable,
    ObjetSupprimeLogiquement,
)
from opsys_core.objects.port import (
    MediaTypeVide,
    ObjectRef,
    ObjectStorePort,
    Sha256FormatInvalide,
    TailleInvalide,
)

# SHA-256 de la chaîne vide — valeur connue et stable (RFC/NIST), utilisée
# pour prouver que le hachage lui-même est correct, pas seulement "un"
# hash quelconque.
_SHA256_CHAINE_VIDE = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ------------------------------------------------------------------
# Cas RED obligatoire #1 : octets différents ne partagent pas le même ref
# ------------------------------------------------------------------


def test_cr_er_l_objectstoreport_et_le_cas_local_1(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref_a = cas.put(BytesIO(b"contenu A"))
    ref_b = cas.put(BytesIO(b"contenu B, longueur totalement differente"))
    assert ref_a.sha256 != ref_b.sha256
    # Contenu récupéré distinctement, sans collision de stockage.
    assert cas.get(ref_a).read() == b"contenu A"
    assert cas.get(ref_b).read() == b"contenu B, longueur totalement differente"


def test_meme_contenu_meme_ref_idempotent(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref_1 = cas.put(BytesIO(b"identique"))
    ref_2 = cas.put(BytesIO(b"identique"))
    assert ref_1 == ref_2


def test_contenu_vide_hash_connu_et_stable(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(b""))
    assert ref.size == 0
    assert ref.sha256 == _SHA256_CHAINE_VIDE


def test_ecriture_atomique_pas_de_fichier_temporaire_residuel(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    cas.put(BytesIO(b"contenu quelconque"))
    fichiers_racine = [p for p in tmp_path.iterdir() if p.is_file()]
    assert fichiers_racine == [], (
        f"fichier(s) temporaire(s) résiduel(s) à la racine du CAS : {fichiers_racine}"
    )


def test_gros_flux_traverse_plusieurs_blocs_de_lecture(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    gros_contenu = b"x" * 200_000  # > taille d'un seul bloc de lecture interne
    ref = cas.put(BytesIO(gros_contenu))
    assert ref.size == 200_000
    assert cas.get(ref).read() == gros_contenu


def test_media_type_par_defaut_application_octet_stream(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(b"sans media_type explicite"))
    assert ref.media_type == "application/octet-stream"


def test_media_type_explicite_conserve(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(b"{}"), media_type="application/json")
    assert ref.media_type == "application/json"


# ------------------------------------------------------------------
# Cas RED obligatoire #2 : hash mismatch bloque
# ------------------------------------------------------------------


def test_cr_er_l_objectstoreport_et_le_cas_local_2(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(b"contenu original de longueur fixe"))
    # Corruption sur disque à longueur CONSTANTE (isole le contrôle de
    # hash du contrôle de taille — un test qui tronquerait masquerait un
    # défaut de contrôle de hash derrière un contrôle de taille qui
    # suffirait seul à détecter l'écart).
    chemin = tmp_path / ref.sha256[:2] / ref.sha256[2:]
    octets = bytearray(chemin.read_bytes())
    octets[0] ^= 0xFF
    chemin.write_bytes(bytes(octets))
    with pytest.raises(HashMismatch):
        cas.get(ref)


def test_hash_mismatch_repete_jamais_de_descripteur_traineur(tmp_path: Path) -> None:
    # Un défaut ici laisserait un descripteur de fichier ouvert (fuite) à
    # chaque corruption détectée — vérifié en confirmant que plusieurs
    # get() successifs sur le même chemin échouent identiquement, sans
    # blocage ni comportement différent au fil des appels.
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(b"a" * 100))
    chemin = tmp_path / ref.sha256[:2] / ref.sha256[2:]
    octets = bytearray(chemin.read_bytes())
    octets[0] ^= 0xFF
    chemin.write_bytes(bytes(octets))
    for _ in range(3):
        with pytest.raises(HashMismatch):
            cas.get(ref)


def test_contenu_intact_ne_leve_jamais_hash_mismatch(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(b"contenu jamais corrompu"))
    assert cas.get(ref).read() == b"contenu jamais corrompu"


# ------------------------------------------------------------------
# Cas RED obligatoire #3 : path traversal impossible
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    "sha256_malveillant",
    [
        "../../../../etc/passwd",
        "..",
        "/etc/passwd",
        "a" * 63,  # 63 caractères, pas 64
        "a" * 65,  # 65 caractères
        "A" * 64,  # majuscules refusées (format strict minuscule)
        ("a" * 62) + "..",
        "0" * 62 + "/x",
        "",
    ],
)
def test_cr_er_l_objectstoreport_et_le_cas_local_3(sha256_malveillant: str) -> None:
    with pytest.raises(Sha256FormatInvalide):
        ObjectRef(sha256=sha256_malveillant, size=1, media_type="text/plain")


def test_path_traversal_re_verifie_par_caslocal_pas_seulement_a_la_construction(
    tmp_path: Path,
) -> None:
    # Simule une ObjectRef reconstruite en contournant __post_init__ (ex.
    # future désérialisation d'un manifeste, C05-006) — CasLocal ne doit
    # JAMAIS faire confiance à la seule provenance Python de l'objet.
    ref_forgee = object.__new__(ObjectRef)
    object.__setattr__(ref_forgee, "sha256", "../../../../etc/passwd")
    object.__setattr__(ref_forgee, "size", 1)
    object.__setattr__(ref_forgee, "media_type", "text/plain")
    cas = CasLocal(tmp_path)
    with pytest.raises(CheminHorsRacineRefuse):
        cas.get(ref_forgee)
    with pytest.raises(CheminHorsRacineRefuse):
        cas.supprimer_logiquement(ref_forgee)
    with pytest.raises(CheminHorsRacineRefuse):
        cas.purger(ref_forgee)


def test_path_traversal_format_invalide_sans_symboles_de_navigation_refuse(
    tmp_path: Path,
) -> None:
    # Isole la re-validation de FORMAT (CasLocal._valider_sha256) du
    # contrôle de CONTENTION de chemin (resolve()+relative_to() dans
    # _chemin_shard) : cette entrée forgée reste géométriquement DANS la
    # racine (aucun "/" ni ".." — resolve()+relative_to() seul ne la
    # détecterait PAS puisqu'elle ne sort jamais de la racine), donc SEULE
    # la re-validation de format peut la refuser ici. Sans ce test isolé,
    # une mutation qui retirerait _valider_sha256 resterait invisible
    # pour la plupart des entrées malveillantes (rattrapées par l'autre
    # garde) — piège déjà rencontré sur ce dépôt (C05-002, mutation
    # invisible si la source est déjà triée par une garde voisine).
    ref_forgee = object.__new__(ObjectRef)
    object.__setattr__(ref_forgee, "sha256", "A" * 64)  # majuscules : format invalide, mais reste dans la racine
    object.__setattr__(ref_forgee, "size", 1)
    object.__setattr__(ref_forgee, "media_type", "text/plain")
    cas = CasLocal(tmp_path)
    with pytest.raises(CheminHorsRacineRefuse):
        cas.get(ref_forgee)


def test_shard_symlinke_hors_racine_refuse(tmp_path: Path) -> None:
    # Défense en profondeur : même un shard nommé avec 2 hex valides mais
    # symlinké hors de la racine du CAS doit être refusé — protège contre
    # une racine partiellement compromise, au-delà du seul filtrage de
    # format sur sha256.
    racine = tmp_path / "racine_cas"
    racine.mkdir()
    hors_racine = tmp_path / "hors_racine"
    hors_racine.mkdir()
    (racine / "ab").symlink_to(hors_racine, target_is_directory=True)
    cas = CasLocal(racine)
    ref = ObjectRef(sha256="ab" + "0" * 62, size=1, media_type="text/plain")
    with pytest.raises(CheminHorsRacineRefuse):
        cas.get(ref)


# ------------------------------------------------------------------
# Cas RED obligatoire #4 : delete logique distinct de purge
# ------------------------------------------------------------------


def test_cr_er_l_objectstoreport_et_le_cas_local_4(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(b"objet a supprimer"))

    # Suppression logique : get() refuse avec une exception DISTINCTE de
    # "introuvable" — l'objet existe toujours (tombstone), juste caché.
    cas.supprimer_logiquement(ref)
    with pytest.raises(ObjetSupprimeLogiquement):
        cas.get(ref)

    # Un objet JAMAIS écrit lève une exception DIFFÉRENTE — distinction
    # sémantique observable, pas seulement nominale.
    ref_jamais_ecrit = ObjectRef(sha256="f" * 64, size=1, media_type="text/plain")
    with pytest.raises(ObjetIntrouvable):
        cas.get(ref_jamais_ecrit)

    # La purge retire réellement l'objet — get() lève ensuite
    # ObjetIntrouvable (plus jamais ObjetSupprimeLogiquement : l'état
    # "supprimé logiquement" lui-même a disparu, pas seulement caché).
    cas.purger(ref)
    with pytest.raises(ObjetIntrouvable):
        cas.get(ref)


def test_purger_sans_suppression_logique_prealable_fonctionne(tmp_path: Path) -> None:
    # purger() ne doit PAS exiger un supprimer_logiquement() préalable —
    # retrait définitif indépendant, pas la deuxième étape obligatoire
    # d'un protocole en 2 phases.
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(b"objet vivant, jamais soft-delete"))
    cas.purger(ref)
    with pytest.raises(ObjetIntrouvable):
        cas.get(ref)


def test_supprimer_logiquement_deux_fois_refuse(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(b"objet"))
    cas.supprimer_logiquement(ref)
    with pytest.raises(ObjetSupprimeLogiquement):
        cas.supprimer_logiquement(ref)


def test_supprimer_logiquement_objet_inexistant_refuse(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref = ObjectRef(sha256="c" * 64, size=1, media_type="text/plain")
    with pytest.raises(ObjetIntrouvable):
        cas.supprimer_logiquement(ref)


def test_purger_objet_inexistant_refuse(tmp_path: Path) -> None:
    cas = CasLocal(tmp_path)
    ref = ObjectRef(sha256="d" * 64, size=1, media_type="text/plain")
    with pytest.raises(ObjetIntrouvable):
        cas.purger(ref)


def test_put_du_meme_contenu_resurrecte_un_objet_supprime_logiquement(
    tmp_path: Path,
) -> None:
    # Piège de conception identifié en revue d'architecture AVANT code :
    # un put() du même contenu qu'un objet tombstoné doit le faire
    # revivre (retirer le tombstone), jamais rester silencieusement
    # supprimé alors que le contenu est de nouveau présent.
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(b"contenu resurrectable"))
    cas.supprimer_logiquement(ref)
    with pytest.raises(ObjetSupprimeLogiquement):
        cas.get(ref)
    ref_2 = cas.put(BytesIO(b"contenu resurrectable"))
    assert ref_2 == ref
    assert cas.get(ref).read() == b"contenu resurrectable"


def test_deux_put_concurrents_resurrectent_le_meme_tombstone_sans_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le CAS reste idempotent quand deux résurrections se chevauchent.

    La barrière force les deux appels à arriver exactement avant le retrait
    du même tombstone. Sans retrait tolérant à l'absence, l'un des deux
    threads reçoit FileNotFoundError après que l'autre l'a supprimé.
    """
    contenu = b"contenu resurrectable concurrent"
    cas = CasLocal(tmp_path)
    ref = cas.put(BytesIO(contenu))
    cas.supprimer_logiquement(ref)
    tombstone = tmp_path / ref.sha256[:2] / f"{ref.sha256[2:]}.supprime"
    assert tombstone.exists()

    barriere_unlink = Barrier(2)
    unlink_original = Path.unlink

    def unlink_synchronise(path: Path, missing_ok: bool = False) -> None:
        if path == tombstone:
            barriere_unlink.wait(timeout=5)
        unlink_original(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_synchronise)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(cas.put, BytesIO(contenu)) for _ in range(2)]
        resultats = []
        erreurs = []
        for future in futures:
            try:
                resultats.append(future.result())
            except BaseException as exc:  # la preuve vérifie l'absence de toute exception brute
                erreurs.append(exc)

    assert erreurs == []
    assert resultats == [ref, ref]
    assert not tombstone.exists()
    assert cas.get(ref).read() == contenu


# ------------------------------------------------------------------
# ObjectRef — validations supplémentaires (revue d'architecture)
# ------------------------------------------------------------------


def test_size_bool_explicitement_refuse() -> None:
    # bool est une sous-classe d'int en Python (isinstance(True, int) est
    # vrai) — sans garde explicite, size=True passerait silencieusement
    # isinstance(size, int).
    with pytest.raises(TailleInvalide):
        ObjectRef(sha256="0" * 64, size=True, media_type="text/plain")  # type: ignore[arg-type]
    with pytest.raises(TailleInvalide):
        ObjectRef(sha256="0" * 64, size=False, media_type="text/plain")  # type: ignore[arg-type]


def test_size_negatif_refuse() -> None:
    with pytest.raises(TailleInvalide):
        ObjectRef(sha256="0" * 64, size=-1, media_type="text/plain")


def test_media_type_vide_refuse() -> None:
    with pytest.raises(MediaTypeVide):
        ObjectRef(sha256="0" * 64, size=1, media_type="")


def test_objectref_est_immuable() -> None:
    ref = ObjectRef(sha256="0" * 64, size=1, media_type="text/plain")
    with pytest.raises(AttributeError):
        ref.size = 2  # type: ignore[misc]


# ------------------------------------------------------------------
# ObjectStorePort — forme du contrat (revue d'architecture)
# ------------------------------------------------------------------


def test_objectstoreport_declare_put_et_get() -> None:
    assert hasattr(ObjectStorePort, "put")
    assert hasattr(ObjectStorePort, "get")


def test_objectstoreport_ne_declare_pas_supprimer_ou_purger() -> None:
    # Décision de revue d'architecture AVANT code : supprimer_logiquement/
    # purger sont des méthodes de CasLocal SEULEMENT, jamais du contrat
    # provider-neutre (un futur adaptateur S3 pourrait les implémenter
    # tout autrement — versioning natif du bucket, lifecycle rules).
    assert not hasattr(ObjectStorePort, "supprimer_logiquement")
    assert not hasattr(ObjectStorePort, "purger")


def test_double_structurel_satisfait_isinstance_sans_heriter(tmp_path: Path) -> None:
    # Preuve mécanique que ObjectStorePort est un contrat DE FORME
    # (typing structurel), pas d'héritage — un futur adaptateur S3
    # (préparé, non activé, "Implémentation strictement bornée" de
    # tasks/C05-005.md) n'aura pas besoin d'hériter de CasLocal ni du
    # Protocol. Double RÉELLEMENT fonctionnel (dict en mémoire), pas un
    # stub qui ne ferait que satisfaire isinstance() sans jamais
    # fonctionner si on l'appelait vraiment.
    class DoubleEnMemoire:
        def __init__(self) -> None:
            self._magasin: dict[str, tuple[bytes, str]] = {}

        def put(
            self, stream: BinaryIO, media_type: str = "application/octet-stream"
        ) -> ObjectRef:
            contenu = stream.read()
            sha256 = hashlib.sha256(contenu).hexdigest()
            self._magasin[sha256] = (contenu, media_type)
            return ObjectRef(sha256=sha256, size=len(contenu), media_type=media_type)

        def get(self, ref: ObjectRef) -> BinaryIO:
            contenu, _ = self._magasin[ref.sha256]
            return BytesIO(contenu)

    double = DoubleEnMemoire()
    assert isinstance(double, ObjectStorePort)
    assert isinstance(CasLocal(tmp_path), ObjectStorePort)
    # Le double n'est pas seulement structurellement conforme, il
    # fonctionne réellement — preuve que le contrat put()->ref, get(ref)
    # ->flux est respecté par une implémentation indépendante minimale.
    ref = double.put(BytesIO(b"preuve de fonctionnement reel"))
    assert double.get(ref).read() == b"preuve de fonctionnement reel"


def test_aucune_reference_boto3_dans_le_code_source() -> None:
    # "préparer adapter S3 sans l'activer" (Implémentation strictement
    # bornée) : zéro occurrence de boto3 — la préparation est le Protocol
    # structurel lui-même, pas du code mort en attente d'activation.
    racine = Path(__file__).resolve().parents[2] / "src" / "opsys_core" / "objects"
    fichiers = list(racine.glob("*.py"))
    assert fichiers, f"aucun fichier trouvé sous {racine}"
    for fichier in fichiers:
        contenu = fichier.read_text(encoding="utf-8").lower()
        assert "boto3" not in contenu, f"{fichier} référence boto3"
