from __future__ import annotations

import csv
import hashlib
import io
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import custody

SOURCE_CSV: Path = Path(__file__).resolve().parent / "sources" / "RF01-W11-AUTHORITY-MAP-M1-M10.csv"
SOURCE_SHA256_ATTENDU: str = "867969610e9d8a442aeb9879818b9165877952f2ca3cede7d8236d44bb8c3648"

_CARACTERES_HEX = set("0123456789abcdefABCDEF")


class SourceSha256Divergente(Exception):
    """Le fichier source a été altéré ou remplacé depuis la dernière validation de référence.

    Poursuivre produirait une carte d'autorité fondée sur des données non contrôlées,
    ce qui invaliderait la traçabilité exigée par la ligne de base.
    """


class ReversibiliteRefusee(Exception):
    """La normalisation des tokens ne permet pas de reconstituer la cellule originale.

    Cela révèle une ambiguïté de parsing (espaces multiples, virgules internes, etc.)
    qui doit être résolue à la source avant de générer la carte, sans quoi deux
    modules pourraient interpréter différemment la même liste d'agrégats.
    """


class AgregatDuplique(Exception):
    """Un même agrégat métier est revendiqué par deux modules différents.

    Cela brise l'invariant d'autorité unique : chaque agrégat ne peut avoir qu'un
    seul propriétaire dans la ligne de base. Le conflit doit être arbitré.
    """


@dataclass(frozen=True)
class BusinessAuthorityRecord:
    """Enregistrement d'une autorité métier : un module propriétaire d'un agrégat."""

    aggregate: str
    owner: str
    source_row: int
    source_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.aggregate, str) or self.aggregate.strip() == "":
            raise ValueError("aggregate doit être une chaîne non vide après strip().")

        if not isinstance(self.owner, str) or self.owner.strip() == "":
            raise ValueError("owner doit être une chaîne non vide après strip().")

        # True/False passent isinstance(..., int) mais ne sont jamais des numéros de ligne valides.
        if isinstance(self.source_row, bool):
            raise ValueError("source_row ne peut pas être un booléen.")
        if not isinstance(self.source_row, int) or self.source_row < 1:
            raise ValueError("source_row doit être un entier supérieur ou égal à 1.")

        if (
            not isinstance(self.source_sha256, str)
            or len(self.source_sha256) != 64
            or not all(caractere in _CARACTERES_HEX for caractere in self.source_sha256)
        ):
            raise ValueError("source_sha256 doit être une empreinte hexadécimale de 64 caractères.")


def construire_carte_autorite_metier(
    chemin_source: Path = SOURCE_CSV,
    sha256_attendu: str = SOURCE_SHA256_ATTENDU,
) -> tuple[BusinessAuthorityRecord, ...]:
    """Construit la carte d'autorité métier à partir du CSV source.

    Vérifie l'intégrité du fichier par SHA-256, contrôle la réversibilité de
    chaque cellule d'agrégats, puis garantit qu'un agrégat n'est détenu que par
    un seul module.
    """
    sha256_reel = hashlib.sha256(chemin_source.read_bytes()).hexdigest()
    if sha256_reel != sha256_attendu:
        raise SourceSha256Divergente(
            f"Empreinte SHA-256 du source divergente : attendue={sha256_attendu}, obtenue={sha256_reel}"
        )

    records: list[BusinessAuthorityRecord] = []
    proprietaires_par_agregat: dict[str, str] = {}

    with chemin_source.open(newline="", encoding="utf-8") as fichier:
        lecteur = csv.DictReader(fichier)
        for source_row, ligne in enumerate(lecteur, start=1):
            owner = ligne["module"]
            cellule = ligne["authoritative_for"]
            tokens = [token.strip() for token in cellule.split(",")]

            reconstitution = ", ".join(tokens)
            if reconstitution != cellule:
                raise ReversibiliteRefusee(
                    f"Réversibilité refusée ligne {source_row} ({owner}) : "
                    f"tokens={tokens}, reconstitution={reconstitution!r}, originale={cellule!r}"
                )

            for token in tokens:
                proprietaire_existant = proprietaires_par_agregat.get(token)
                if proprietaire_existant is not None and proprietaire_existant != owner:
                    raise AgregatDuplique(
                        f"L'agrégat {token!r} est déjà détenu par {proprietaire_existant!r} ; "
                        f"{owner!r} tente également d'en être l'autorité."
                    )

                if proprietaire_existant is None:
                    proprietaires_par_agregat[token] = owner

                records.append(
                    BusinessAuthorityRecord(
                        aggregate=token,
                        owner=owner,
                        source_row=source_row,
                        source_sha256=sha256_reel,
                    )
                )

    return tuple(records)


def produire_sortie(sortie_dir: Path, worktree: Path) -> Path:
    """Produit le fichier CSV de sortie de la carte d'autorité métier.

    La sérialisation utilise le module csv pour garantir un échappement correct,
    et l'écriture passe obligatoirement par `custody.ecrire_sans_suivre_symlink`
    afin de ne pas suivre de lien symbolique malveillant.
    """
    records = construire_carte_autorite_metier()
    sortie_dir.mkdir(parents=True, exist_ok=True)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["aggregate", "owner", "source_row", "source_sha256"])
    for record in records:
        writer.writerow(
            [record.aggregate, record.owner, record.source_row, record.source_sha256]
        )

    chemin_sortie = sortie_dir / "BUSINESS-AUTHORITY-MAP-M1-M10.csv"
    custody.ecrire_sans_suivre_symlink(chemin_sortie, buffer.getvalue(), worktree)
    return chemin_sortie


if __name__ == "__main__":
    worktree = Path(__file__).resolve().parents[2]
    sortie_dir = Path(__file__).resolve().parent
    chemin_ecrit = produire_sortie(sortie_dir, worktree)
    print(chemin_ecrit)
