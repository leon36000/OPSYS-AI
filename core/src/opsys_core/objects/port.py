"""Port provider-neutre pour un magasin d'objets adressés par contenu
(CAS — Content-Addressable Storage). Sortie exacte de tasks/C05-005.md.

Vit dans `opsys_core/objects/`, un nouveau répertoire classé ADAPTER
dans core/dependency-rules.toml (revue d'architecture AVANT code)
plutôt que dans `opsys_core/ports/` (la couche « ports » système déjà
déclarée par C04-001, contrats de forme minimaux consommés par
plusieurs couches indépendantes du Core) : `ObjectStorePort` (ce
fichier) et son unique implémentation aujourd'hui (`local_cas.py`)
forment une seule unité conceptuelle — un magasin CAS avec un futur
adaptateur S3 documenté mais jamais activé (« préparer adapter S3 sans
l'activer », Implémentation strictement bornée de tasks/C05-005.md) —
pas un contrat générique partagé par kernel/domain au sens de
C04-001.

COLLISION DE NOM DÉLIBÉRÉMENT DOCUMENTÉE (revue d'architecture AVANT
code) : `opsys_core.authz.model.ObjectRef` existe déjà et désigne un
objet AUTORISÉ (object_type, object_id, object_id_tronque) — concept
sans aucun rapport avec le `ObjectRef` défini ici (sha256, size,
media_type), une référence de CONTENU adressée par hash. Même nom court,
deux formes incompatibles. Ne JAMAIS importer les deux sans alias dans
le même fichier (ex. `from authz.model import ObjectRef as
ObjectRefAutorisation`) — `ObjectRef` seul est ambigu dans ce dépôt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import BinaryIO, Protocol, runtime_checkable

_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")


class Sha256FormatInvalide(ValueError):
    """sha256 absent du format hexadécimal 64 caractères minuscules strict.

    Première ligne de défense du cas RED obligatoire « path traversal
    impossible » : un sha256 contenant '/', '..' ou une longueur/casse
    hors format est refusé ICI, avant même qu'un chemin disque ne soit
    construit à partir de lui (défense en profondeur — CasLocal
    re-vérifie indépendamment à chaque accès, cf. local_cas.py)."""


class TailleInvalide(ValueError):
    """size n'est pas un entier >= 0 (bool explicitement exclu)."""


class MediaTypeVide(ValueError):
    """media_type est une chaîne vide."""


@dataclass(frozen=True)
class ObjectRef:
    """Référence à un objet stocké par hash de contenu (SHA-256).

    Immuable (frozen) : une ObjectRef ne représente qu'une adresse de
    contenu, jamais un état mutable — l'état (vivant / supprimé
    logiquement / purgé) vit dans CasLocal, pas ici.
    """

    sha256: str
    size: int
    media_type: str

    def __post_init__(self) -> None:
        if not _SHA256_HEX_RE.fullmatch(self.sha256):
            raise Sha256FormatInvalide(
                "sha256 doit être exactement 64 caractères hexadécimaux "
                f"minuscules, reçu : {self.sha256!r}"
            )
        # bool est une sous-classe d'int en Python (isinstance(True, int)
        # est vrai) — piège du même GENRE que ReversibleNonBooleen en
        # C05-002 (opsys_core/persistence/migrations.py), sens inversé
        # ici : on EXCLUT le bool là où C05-002 l'EXIGEAIT. Sans ce garde
        # explicite, size=True passerait silencieusement
        # isinstance(size, int).
        if isinstance(self.size, bool) or not isinstance(self.size, int):
            raise TailleInvalide(
                "size doit être un int strict (bool explicitement exclu), "
                f"reçu : {self.size!r} ({type(self.size).__name__})"
            )
        if self.size < 0:
            raise TailleInvalide(f"size doit être >= 0, reçu : {self.size}")
        if not self.media_type:
            raise MediaTypeVide("media_type ne peut pas être une chaîne vide")


@runtime_checkable
class ObjectStorePort(Protocol):
    """Contrat provider-neutre d'un magasin d'objets adressés par contenu.

    Volontairement réduit à put/get (« Implémentation strictement
    bornée » de tasks/C05-005.md). `supprimer_logiquement`/`purger`
    (suppression logique vs définitive) sont des méthodes de `CasLocal`
    UNIQUEMENT — pas de ce contrat : décision de revue d'architecture
    AVANT code — un futur adaptateur S3 (préparé, non activé) pourrait
    implémenter la suppression logique/définitive tout autrement
    (versioning natif du bucket, lifecycle rules) ; figer ces deux
    méthodes ici imposerait une forme d'implémentation, pas seulement un
    contrat.

    `runtime_checkable` : permet `isinstance(x, ObjectStorePort)` sur un
    double structurel qui n'hérite PAS de ce Protocol — preuve mécanique
    que le contrat est de la FORME (typing structurel), pas de
    l'héritage ; un futur adaptateur S3 n'aura pas besoin d'hériter de
    cette classe.
    """

    def put(
        self, stream: BinaryIO, media_type: str = "application/octet-stream"
    ) -> ObjectRef:
        """Écrit le contenu de `stream` et retourne sa référence adressée."""
        ...

    def get(self, ref: ObjectRef) -> BinaryIO:
        """Retourne un flux binaire positionné en 0 sur le contenu de `ref`."""
        ...
