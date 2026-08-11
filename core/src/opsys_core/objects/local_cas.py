"""CasLocal — implémentation locale (disque) de ObjectStorePort (C05-005).

Adressage par contenu façon git : `<root>/<sha256[:2]>/<sha256[2:]>`.

Écriture atomique : fichier temporaire créé DANS la racine du CAS (jamais
`/tmp` — évite un `os.replace()` inter-système-de-fichiers, EXDEV),
haché en un seul passage pendant l'écriture (le flux source n'est pas
supposé « seekable »), `fsync()` avant `os.replace()` dans le shard
final. LIMITATION CONNUE ET ACCEPTÉE (non testable ici) : la durabilité
de l'ENTRÉE DE RÉPERTOIRE après un crash exigerait aussi un `fsync()` du
descripteur du répertoire parent — hors périmètre de cette tâche (même
patron que les limitations déjà nommées en C05-002, ex. dollar-quoting
PostgreSQL non géré).

Vérification à la lecture : un SEUL descripteur de fichier ouvert par
`get()`, jamais réouverture après vérification (fenêtre TOCTOU) — cf.
cas RED obligatoire « hash mismatch bloque ».

Suppression logique (`supprimer_logiquement`) distincte de la purge
(`purger`, cas RED obligatoire) : deux méthodes, deux exceptions,
absentes du Protocol `ObjectStorePort` (décision de revue d'architecture
AVANT code, cf. port.py). Un tombstone est un fichier sidecar
`<hash>.supprime` — les noms d'objets réels sont TOUJOURS exactement 64
caractères hexadécimaux sans point, donc aucune collision possible avec
ce suffixe.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import BinaryIO

from opsys_core.objects.port import ObjectRef

_TAILLE_LOT = 65536  # 64 KiB par lecture — un seul passage, jamais tout le flux en mémoire d'un coup
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")
_SUFFIXE_TOMBSTONE = ".supprime"


class CheminHorsRacineRefuse(ValueError):
    """Le chemin résolu sort de la racine du CAS (path traversal / shard symlink).

    Levée à DEUX niveaux indépendants : format sha256 invalide (avant
    toute construction de chemin) ET résolution finale hors racine
    (défense en profondeur contre un shard symlinké) — cas RED
    obligatoire « path traversal impossible »."""


class HashMismatch(ValueError):
    """Le contenu relu ne correspond pas au sha256/size déclarés par la référence."""


class ObjetIntrouvable(LookupError):
    """Aucun objet (ni vivant ni supprimé logiquement) à cette référence."""


class ObjetSupprimeLogiquement(LookupError):
    """L'objet existe mais a été supprimé logiquement (tombstone).

    Exception DISTINCTE de ObjetIntrouvable — cas RED obligatoire
    « delete logique distinct de purge » : l'objet n'est pas absent, il
    est caché ; get() sur un objet jamais écrit lève ObjetIntrouvable,
    get() sur un objet tombstoné lève CETTE exception."""


class CasLocal:
    """Magasin d'objets adressés par contenu, stockage local sur disque."""

    def __init__(self, root: "Path | str") -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _valider_sha256(self, sha256: str) -> None:
        # Re-validation DÉLIBÉRÉE même si ObjectRef.__post_init__ l'a déjà
        # faite à la construction (revue d'architecture AVANT code) : une
        # ObjectRef peut être reconstruite en contournant __post_init__
        # (ex. désérialisation future d'un manifeste de sauvegarde,
        # C05-006) — CasLocal ne fait jamais confiance à la seule
        # provenance Python de l'objet qu'on lui passe.
        if not _SHA256_HEX_RE.fullmatch(sha256):
            raise CheminHorsRacineRefuse(
                f"sha256 hors format, refusé avant toute résolution de chemin : {sha256!r}"
            )

    def _chemin_shard(self, sha256: str) -> Path:
        self._valider_sha256(sha256)
        chemin = self._root / sha256[:2] / sha256[2:]
        # Défense en profondeur contre un shard symlinké hors racine :
        # résoudre puis vérifier l'inclusion réelle, jamais faire
        # confiance à la seule construction textuelle du chemin.
        resolu = chemin.resolve()
        try:
            resolu.relative_to(self._root)
        except ValueError:
            raise CheminHorsRacineRefuse(
                f"chemin résolu {resolu} hors de la racine CAS {self._root}"
            ) from None
        return chemin

    def put(
        self, stream: BinaryIO, media_type: str = "application/octet-stream"
    ) -> ObjectRef:
        hasheur = hashlib.sha256()
        taille = 0
        self._root.mkdir(parents=True, exist_ok=True)
        # Fichier temporaire à la racine du CAS (même système de fichiers
        # que la destination finale — le shard exact n'est connu qu'APRÈS
        # lecture complète du flux, donc impossible de créer directement
        # dans le shard cible) : os.replace() final ne traverse jamais de
        # frontière de montage (EXDEV).
        fd, chemin_tmp_str = tempfile.mkstemp(dir=str(self._root))
        chemin_tmp = Path(chemin_tmp_str)
        try:
            with os.fdopen(fd, "wb") as f:
                while True:
                    bloc = stream.read(_TAILLE_LOT)
                    if not bloc:
                        break
                    hasheur.update(bloc)
                    taille += len(bloc)
                    f.write(bloc)
                f.flush()
                os.fsync(f.fileno())

            sha256 = hasheur.hexdigest()
            ref = ObjectRef(sha256=sha256, size=taille, media_type=media_type)
            chemin_final = self._chemin_shard(sha256)
            chemin_final.parent.mkdir(parents=True, exist_ok=True)
            chemin_tombstone = chemin_final.with_name(
                chemin_final.name + _SUFFIXE_TOMBSTONE
            )

            if chemin_final.exists():
                # CAS : contenu déjà présent et identique par construction
                # (adressé par son propre hash) — idempotent, rien à
                # réécrire.
                chemin_tmp.unlink(missing_ok=True)
            else:
                os.replace(chemin_tmp, chemin_final)

            if chemin_tombstone.exists():
                # Résurrection (revue d'architecture AVANT code, testée
                # explicitement) : un put() du même contenu qu'un objet
                # supprimé logiquement le fait revivre — le tombstone n'a
                # plus lieu d'être dès que le contenu réel est
                # présent/reconfirmé. Vérifié APRÈS la branche
                # exists()/replace() ci-dessus, jamais court-circuité par
                # elle : le cas typique de résurrection est précisément
                # celui où chemin_final existe déjà (soft-delete ne
                # retire jamais les octets réels).
                chemin_tombstone.unlink()

            return ref
        finally:
            chemin_tmp.unlink(missing_ok=True)

    def get(self, ref: ObjectRef) -> BinaryIO:
        chemin = self._chemin_shard(ref.sha256)
        chemin_tombstone = chemin.with_name(chemin.name + _SUFFIXE_TOMBSTONE)
        if chemin_tombstone.exists():
            raise ObjetSupprimeLogiquement(f"objet {ref.sha256} supprimé logiquement")
        try:
            f = open(chemin, "rb")
        except FileNotFoundError:
            raise ObjetIntrouvable(f"objet {ref.sha256} introuvable") from None

        # Vérification à la lecture sur un SEUL descripteur (cas RED
        # obligatoire « hash mismatch bloque ») : jamais ouvrir, fermer,
        # puis rouvrir pour retourner le flux (fenêtre TOCTOU) — on lit,
        # on hache, puis on retourne le MÊME descripteur repositionné en 0.
        try:
            hasheur = hashlib.sha256()
            taille = 0
            while True:
                bloc = f.read(_TAILLE_LOT)
                if not bloc:
                    break
                hasheur.update(bloc)
                taille += len(bloc)
            if hasheur.hexdigest() != ref.sha256 or taille != ref.size:
                raise HashMismatch(
                    f"contenu sur disque ne correspond pas à la référence "
                    f"{ref.sha256} (relu : {hasheur.hexdigest()}, {taille} octets, "
                    f"attendu {ref.size} octets)"
                )
            f.seek(0)
            return f
        except BaseException:
            f.close()
            raise

    def supprimer_logiquement(self, ref: ObjectRef) -> None:
        chemin = self._chemin_shard(ref.sha256)
        chemin_tombstone = chemin.with_name(chemin.name + _SUFFIXE_TOMBSTONE)
        if chemin_tombstone.exists():
            raise ObjetSupprimeLogiquement(
                f"objet {ref.sha256} déjà supprimé logiquement"
            )
        if not chemin.exists():
            raise ObjetIntrouvable(f"objet {ref.sha256} introuvable")
        chemin_tombstone.touch()

    def purger(self, ref: ObjectRef) -> None:
        chemin = self._chemin_shard(ref.sha256)
        chemin_tombstone = chemin.with_name(chemin.name + _SUFFIXE_TOMBSTONE)
        existe_reel = chemin.exists()
        existe_tombstone = chemin_tombstone.exists()
        if not existe_reel and not existe_tombstone:
            raise ObjetIntrouvable(f"objet {ref.sha256} introuvable, rien à purger")
        if existe_reel:
            chemin.unlink()
        if existe_tombstone:
            chemin_tombstone.unlink()
