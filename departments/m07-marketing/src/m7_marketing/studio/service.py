"""Les gestes du studio, sur des journaux append-only et un dossier de fichiers : brief, fond, composition, contrôle,
revue, approbation, retrait, export vers un site, logo.

`Studio` rassemble les dépendances (journaux, fichiers, polices, sélection du modèle, verdict de licence, lecteurs OCR,
vectoriseur, horloge) ; les outils de M7 (`studio_outils.py`) n'en sont que des enveloppes minces qui établissent QUI
appelle. Rien ici n'appelle un modèle, un réseau ou un service de publication : la génération est une DEMANDE consignée
(`executeur.demander_generation`), l'approbation une écriture de journal, l'export un copier de fichier vers le dossier
d'actifs d'un site.

Les fichiers (fonds, artefacts, logos) vivent sous `$OPSYS_HOME/studio/` : noms construits par le code à partir
d'identifiants validés, écriture atomique, mode 0600, aucun lien symbolique suivi ; chaque lecture revérifie le SHA-256
du registre (un fichier remplacé sur le disque est refusé, jamais composé ni exporté).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import os
import re
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import actifs, briefs, composition, controle, executeur, logos, modeles, ocr, png, provenance
from . import portes as p
from .brief import Brief
from .gabarits import GabaritErreur
from .polices import PoliceErreur, RegistrePolices

REJ_FICHIER = "REJ-STUDIO-FICHIER"
REJ_FOND_OBSOLETE = "REJ-STUDIO-FOND-OBSOLETE"
REJ_FOND_ABSENT = "REJ-STUDIO-FOND-ABSENT"
REJ_LOGO_NON_APPROUVE = "REJ-STUDIO-LOGO-NON-APPROUVE"
REJ_COMPOSITION_DERIVEE = "REJ-STUDIO-COMPOSITION-DERIVEE"
REJ_BRIEF_REVISE = "REJ-STUDIO-BRIEF-REVISION-INTROUVABLE"
REJ_SITE = "REJ-STUDIO-EXPORT-SITE"
REJ_POLICES = "REJ-STUDIO-POLICES"
_ID = re.compile(r"^[a-z][a-z0-9-]{2,60}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_NOM_IMAGE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALT_MAX = 200
AVERTISSEMENT_IA_SITE = (
    "Le site ne porte aucun champ de divulgation d'IA : une image dont le fond est généré se signale dans le contenu "
    "de la "
    "page ; le sas social, lui, exige la divulgation (À valider auprès d'un professionnel qualifié)."
)


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


class FichiersStudio:
    def __init__(self, racine: Path) -> None:
        self.racine = racine

    def _chemin(self, relatif: str) -> Path:
        morceaux = relatif.split("/")
        if (
            len(morceaux) not in (2, 3)
            or morceaux[0] not in ("fonds", "visuels", "logos")
            or any(not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,80}", m) for m in morceaux)
        ):
            raise OSError("chemin de fichier du studio invalide")
        return self.racine.joinpath(*morceaux)

    def ecrire(self, relatif: str, octets: bytes) -> None:
        chemin = self._chemin(relatif)
        chemin.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temporaire = chemin.with_name(chemin.name + ".tmp")
        descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descripteur, "wb") as flux:
            flux.write(octets)
        os.replace(temporaire, chemin)

    def lire(self, relatif: str, sha256: str | None = None) -> bytes:
        chemin = self._chemin(relatif)
        meta = chemin.lstat()
        if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode) or meta.st_size > 64 * 1024 * 1024:
            raise OSError("fichier du studio : fichier ordinaire de 64 Mio au plus exigé")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(chemin, flags), "rb") as flux:
            donnees = flux.read()
        if sha256 is not None and hashlib.sha256(donnees).hexdigest() != sha256:
            raise OSError("le fichier ne correspond plus à l'empreinte du registre")
        return donnees


@dataclasses.dataclass(frozen=True)
class Journaux:
    briefs: Any
    jobs: Any
    provenance: Any
    actifs: Any


@dataclasses.dataclass(frozen=True)
class Studio:
    journaux: Journaux
    fichiers: FichiersStudio
    polices: Callable[[bool], RegistrePolices]
    selection: Callable[[str], modeles.SelectionModele]
    verdict_licence: Callable[[str], Mapping[str, Any] | None]
    lecteurs: Callable[[RegistrePolices], Mapping[str, ocr.LecteurOCR]]
    vectoriseur: logos.Vectoriseur
    maintenant: Callable[[], dt.datetime]
    par: str

    # -- outils internes -------------------------------------------------------------------------------------
    def _horodatage(self) -> str:
        return self.maintenant().astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _registre_polices(self, production: bool) -> RegistrePolices | dict[str, Any]:
        try:
            return self.polices(production)
        except PoliceErreur as exc:
            return _refus(exc.code, "$.polices", exc.detail)

    # -- brief -------------------------------------------------------------------------------------------------
    def preparer_brief(self, donnees: Any, cle_idempotence: str, brief_id: str | None = None) -> dict[str, Any]:
        return briefs.composer(self.journaux.briefs, donnees, cle_idempotence, self.par, self._horodatage(), brief_id)

    # -- fond généré (demande seulement) ---------------------------------------------------------------------------
    def demander_fond(self, brief_id: str, genre: str = "image", variante: int = 0) -> dict[str, Any]:
        etat = briefs.obtenir(self.journaux.briefs, brief_id)
        if isinstance(etat, dict):
            return etat
        if genre not in modeles.CAPACITES:
            return _refus(modeles.REJ_CAPACITE, "$.genre", f"genre parmi {list(modeles.CAPACITES)}")
        if type(variante) is not int or not 0 <= variante <= 99:
            return _refus("REJ-STUDIO-VARIANTE", "$.variante", "entier de 0 à 99")
        try:
            selection = self.selection(genre)
        except modeles.ModeleRefuse as exc:
            return {
                "accepte": False,
                "refus": [{"code": exc.code, "chemin": "$.modele", "detail": exc.detail}],
                "codes_politique": list(exc.refus),
            }
        return executeur.demander_generation(
            self.journaux.jobs,
            brief_id,
            etat.brief,
            selection,
            par=self.par,
            horodatage=self._horodatage(),
            maintenant=self.maintenant(),
            variante=variante,
        )

    # -- composition ---------------------------------------------------------------------------------------------------
    def _logo_pour_gabarit(self, logo_actif_id: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if logo_actif_id is None:
            return None, None
        etats, refus = actifs.charger(self.journaux.actifs)
        if refus is not None:
            return None, refus
        logo = etats.get(logo_actif_id)
        if logo is None or logo.kind != p.KIND_LOGO:
            return None, _refus(actifs.REJ_ACTIF_INCONNU, "$.logo_actif_id", f"logo inconnu : {logo_actif_id!r}")
        if not logo.approuve:
            return None, _refus(
                REJ_LOGO_NON_APPROUVE,
                "$.logo_actif_id",
                f"le logo {logo_actif_id} est « {logo.etat} » : un logo se pose seulement une fois "
                "approuvé par une personne (N3)",
            )
        d = logo.donnees
        return {"id": logo.actif_id, "chemins": d["chemins"], "vb_w": d["vb_w"], "vb_h": d["vb_h"]}, None

    def _fond_pour_brief(self, brief: Brief, fond_actif_id: str | None):
        """(octets du fond, maillon de provenance, état du fond, refus)."""
        if not brief.genere:
            if fond_actif_id is not None:
                return (
                    None,
                    None,
                    None,
                    _refus(composition.REJ_FOND_NON_DEMANDE, "$.fond_actif_id", "ce brief n'a pas de fond généré"),
                )
            return None, None, None, None
        if fond_actif_id is None:
            return (
                None,
                None,
                None,
                _refus(
                    REJ_FOND_ABSENT, "$.fond_actif_id", "ce brief demande un fond généré : indiquer l'actif de fond"
                ),
            )
        etats, refus = actifs.charger(self.journaux.actifs)
        if refus is not None:
            return None, None, None, refus
        fond = etats.get(fond_actif_id)
        if fond is None or fond.kind != p.KIND_FOND:
            return (
                None,
                None,
                None,
                _refus(actifs.REJ_ACTIF_INCONNU, "$.fond_actif_id", f"fond inconnu : {fond_actif_id!r}"),
            )
        if fond.donnees["fond_spec_empreinte"] != brief.empreinte_fond():
            return (
                None,
                None,
                None,
                _refus(
                    REJ_FOND_OBSOLETE,
                    "$.fond_actif_id",
                    "le brief a changé (description, format ou palette du fond) depuis la "
                    "génération de ce fond : refaire la demande de fond",
                ),
            )
        maillon = provenance.trouver(self.journaux.provenance, fond.donnees["provenance_chaine"])
        if maillon is None:
            return (
                None,
                None,
                None,
                _refus(
                    composition.REJ_FOND_SANS_PROVENANCE,
                    "$.fond_actif_id",
                    "provenance introuvable ou journal altéré : aucun fond sans provenance",
                ),
            )
        try:
            octets = self.fichiers.lire(f"fonds/{fond.actif_id}.{fond.donnees['format']}", fond.donnees["sha256"])
        except OSError as exc:
            return None, None, None, _refus(REJ_FICHIER, "$.fond_actif_id", str(exc))
        return octets, maillon, fond, None

    def composer(
        self,
        brief_id: str,
        fond_actif_id: str | None = None,
        logo_actif_id: str | None = None,
        police_id: str | None = None,
        ppp: int | None = None,
    ) -> dict[str, Any]:
        etat = briefs.obtenir(self.journaux.briefs, brief_id)
        if isinstance(etat, dict):
            return etat
        brief = etat.brief
        polices = self._registre_polices(production=not brief.fictif)
        if isinstance(polices, dict):
            return polices
        police_id = police_id or polices.ids()[0]
        fond_octets, maillon, _fond, refus = self._fond_pour_brief(brief, fond_actif_id)
        if refus is not None:
            return refus
        if maillon is not None:
            verdict = self.verdict_licence(maillon["fournisseur_id"])
            if verdict is None or not verdict.get("conforme"):
                return _refus(
                    actifs.REJ_LICENCE,
                    "$.licence",
                    "la licence du modèle qui a produit ce fond n'est plus conforme au profil du client : "
                    f"{(verdict or {}).get('codes') or 'aucun verdict'}",
                )
        logo, refus = self._logo_pour_gabarit(logo_actif_id)
        if refus is not None:
            return refus
        try:
            comp = composition.composer_visuel(
                brief,
                polices,
                police_id,
                fond_png=fond_octets,
                provenance=provenance.vers_provenance_de_composition(maillon) if maillon else None,
                logo=logo,
                ppp=ppp,
            )
        except (composition.CompositionRefusee, GabaritErreur) as exc:
            return _refus(exc.code, "$", exc.detail)
        except PoliceErreur as exc:
            return _refus(exc.code, "$.police", exc.detail)
        alt = f"{brief.marque['nom']} : {brief.textes['titre']['fr']}"[:ALT_MAX]
        resultat = actifs.enregistrer_composition(
            self.journaux.actifs,
            comp,
            brief_id=brief_id,
            alt=alt,
            par=self.par,
            horodatage=self._horodatage(),
            fond_actif_id=fond_actif_id,
            logo_actif_id=logo_actif_id,
            nature_generateur=maillon["nature_generateur"] if maillon else None,
            fournisseur_id=maillon["fournisseur_id"] if maillon else None,
            mention_licence=(maillon["licence"].get("mention_obligatoire") if maillon else None),
        )
        if not resultat.get("accepte"):
            return resultat
        try:
            for fmt, octets in comp.artefacts.items():
                self.fichiers.ecrire(f"visuels/{resultat['actif_id']}/visuel.{fmt}", octets)
        except OSError as exc:
            return _refus(REJ_FICHIER, "$", f"artefact non écrit : {type(exc).__name__}")
        return {
            **resultat,
            "artefacts": comp.empreintes(),
            "ia_generee": comp.ia_generee,
            "mention_licence_requise": maillon["licence"].get("mention_obligatoire") if maillon else None,
            "prochaine_etape": "contrôler le visuel (m7_controler_visuel_studio)",
        }

    # -- contrôle --------------------------------------------------------------------------------------------------
    def controler(self, actif_id: str) -> dict[str, Any]:
        etats, refus = actifs.charger(self.journaux.actifs)
        if refus is not None:
            return refus
        courant = etats.get(actif_id)
        if courant is None:
            return _refus(actifs.REJ_ACTIF_INCONNU, "$.actif_id", f"actif inconnu : {actif_id!r}")
        if courant.kind == p.KIND_LOGO:
            return self._controler_logo(courant)
        if courant.kind != p.KIND_VISUEL:
            return _refus(actifs.REJ_ETAT, "$.actif_id", "un fond brut ne se contrôle pas : il se compose d'abord")
        d = courant.donnees
        brief = briefs.par_empreinte(self.journaux.briefs, d["brief_empreinte"])
        if brief is None:
            return _refus(
                REJ_BRIEF_REVISE, "$.actif_id", "la révision du brief qui a produit ce visuel est introuvable"
            )
        polices = self._registre_polices(production=not brief.fictif)
        if isinstance(polices, dict):
            return polices
        fond_octets, maillon, _fond, refus = self._fond_pour_brief(brief, d.get("fond_actif_id"))
        if refus is not None:
            return refus
        logo, refus = self._logo_pour_gabarit(d.get("logo_actif_id"))
        if refus is not None:
            return refus
        try:
            refaite = composition.composer_visuel(
                brief,
                polices,
                d["police_id"],
                fond_png=fond_octets,
                provenance=provenance.vers_provenance_de_composition(maillon) if maillon else None,
                logo=logo,
                ppp=d["ppp"],
            )
        except (composition.CompositionRefusee, GabaritErreur, PoliceErreur) as exc:
            return _refus(exc.code, "$", exc.detail)
        if refaite.empreinte() != d["composition_empreinte"]:
            return _refus(
                REJ_COMPOSITION_DERIVEE,
                "$.actif_id",
                "la composition refaite des mêmes entrées n'a plus l'empreinte du registre (police, fond ou "
                "logo changé) : recomposer",
            )
        stockes: dict[str, bytes] = {}
        for fmt in d["artefacts"]:
            try:
                stockes[fmt] = self.fichiers.lire(f"visuels/{actif_id}/visuel.{fmt}")
            except OSError:
                stockes[fmt] = b""  # absent : le contrôle de reproductibilité le dira
        sur_disque = dataclasses.replace(refaite, artefacts=stockes)
        verdict = (lambda: self.verdict_licence(maillon["fournisseur_id"])) if maillon else None
        rapport = controle.controler(
            sur_disque,
            polices,
            self.lecteurs(polices),
            maintenant=self.maintenant(),
            verdict_licence=verdict,
            mention_licence_requise=d.get("mention_licence"),
            composition_enregistree=d["composition_empreinte"],
        )
        resultat = actifs.enregistrer_controle(
            self.journaux.actifs, actif_id, rapport.donnees, self.par, self._horodatage()
        )
        if resultat.get("accepte"):
            resultat = {
                **resultat,
                "conforme": rapport.conforme,
                "constats_en_echec": [
                    {"code": c["code"], "detail": c["detail"]} for c in rapport.constats if not c["ok"]
                ],
                "lecteurs": rapport.donnees["lecteurs"],
            }
        return resultat

    def _controler_logo(self, courant: actifs.EtatActif) -> dict[str, Any]:
        d = courant.donnees
        try:
            svg = self.fichiers.lire(f"logos/{courant.actif_id}.svg", d["svg_sha256"])
            logo = logos.LogoVectoriel(tuple(d["chemins"]), d["vb_w"], d["vb_h"])
        except (OSError, ValueError) as exc:
            return _refus(REJ_FICHIER, "$.actif_id", str(exc))
        rapport = logos.rapport_controle(logo, svg, maintenant=self.maintenant(), source=d["source"], outil=d["outil"])
        resultat = actifs.enregistrer_controle(
            self.journaux.actifs, courant.actif_id, rapport, self.par, self._horodatage()
        )
        if not resultat.get("accepte"):
            return resultat
        return {
            **resultat,
            "conforme": rapport["conforme"],
            "avertissement": actifs.AVERTISSEMENT_LOGO,
            "constats_en_echec": [
                {"code": c["code"], "detail": c["detail"]} for c in rapport["constats"] if not c["ok"]
            ],
        }

    # -- revue ---------------------------------------------------------------------------------------------------------
    def demander_revue(self, actif_id: str) -> dict[str, Any]:
        return actifs.demander_revue(self.journaux.actifs, actif_id, self.par, self._horodatage())

    def approuver(
        self,
        actif_id: str,
        composition_empreinte: str,
        rapport_empreinte: str,
        approbateur: Mapping[str, str] | None,
        attestations: Any,
    ) -> dict[str, Any]:
        etats, refus = actifs.charger(self.journaux.actifs)
        if refus is not None:
            return refus
        courant = etats.get(actif_id)
        verdict = None
        if courant is not None and courant.donnees.get("fournisseur_id"):
            fournisseur_id = courant.donnees["fournisseur_id"]
            verdict = lambda: self.verdict_licence(fournisseur_id)  # noqa: E731
        resultat = actifs.approuver(
            self.journaux.actifs,
            actif_id,
            composition_empreinte,
            rapport_empreinte,
            approbateur,
            attestations,
            self._horodatage(),
            verdict_licence=verdict,
        )
        if resultat.get("accepte") and courant is not None and courant.kind == p.KIND_LOGO:
            resultat = {**resultat, "avertissement": actifs.AVERTISSEMENT_LOGO}
        return resultat

    def rejeter(self, actif_id: str, motif: str) -> dict[str, Any]:
        return actifs.rejeter(self.journaux.actifs, actif_id, self.par, motif, self._horodatage())

    def revoquer(self, actif_id: str, motif: str) -> dict[str, Any]:
        return actifs.revoquer(self.journaux.actifs, actif_id, self.par, motif, self._horodatage())

    # -- logos ---------------------------------------------------------------------------------------------------------
    def vectoriser_logo(
        self,
        fictif: bool,
        fond_actif_id: str | None = None,
        chemins: list[str] | None = None,
        vb_w: float | None = None,
        vb_h: float | None = None,
        seuil: int = 128,
    ) -> dict[str, Any]:
        if (fond_actif_id is None) == (chemins is None):
            return _refus(logos.REJ_LOGO, "$", "fournir exactement un de fond_actif_id (concept raster) ou chemins")
        try:
            if fond_actif_id is not None:
                etats, refus = actifs.charger(self.journaux.actifs)
                if refus is not None:
                    return refus
                fond = etats.get(fond_actif_id)
                if fond is None or fond.kind != p.KIND_FOND or fond.donnees["format"] != "png":
                    return _refus(actifs.REJ_ACTIF_INCONNU, "$.fond_actif_id", "concept raster (fond PNG) inconnu")
                raster = png.decoder(self.fichiers.lire(f"fonds/{fond.actif_id}.png", fond.donnees["sha256"]))
                logo = self.vectoriseur.vectoriser(raster, seuil)
                source = f"vectorisation de {fond_actif_id}"
                raster_sha = fond.donnees["sha256"]
            else:
                if vb_w is None or vb_h is None:
                    return _refus(logos.REJ_LOGO, "$.vb_w", "boîte de vue (vb_w, vb_h) exigée avec les chemins")
                logo = logos.logo_depuis_chemins(chemins, vb_w, vb_h)
                source, raster_sha = "chemins fournis", None
        except (ValueError, OSError, png.PngInvalide) as exc:
            code = getattr(exc, "code", logos.REJ_LOGO)
            return _refus(code, "$", getattr(exc, "detail", str(exc)))
        svg = logos.svg_du_logo(logo)
        outil = {
            "nom": self.vectoriseur.nom if fond_actif_id else "chemins-agent",
            "version": self.vectoriseur.version,
            "nature": self.vectoriseur.nature if fond_actif_id else "double",
        }
        enregistre = actifs.enregistrer_logo(
            self.journaux.actifs,
            sha256=logo.empreinte(),
            chemins=list(logo.chemins),
            vb_w=logo.vb_w,
            vb_h=logo.vb_h,
            svg_sha256=hashlib.sha256(svg).hexdigest(),
            source=source,
            outil=outil,
            fictif=fictif,
            par=self.par,
            horodatage=self._horodatage(),
            raster_sha256=raster_sha,
        )
        if not enregistre.get("accepte"):
            return enregistre
        try:
            self.fichiers.ecrire(f"logos/{enregistre['actif_id']}.svg", svg)
            for nom, octets in logos.declinaisons(logo).items():
                self.fichiers.ecrire(f"logos/{enregistre['actif_id']}-{nom}.svg", octets)
        except OSError as exc:
            return _refus(REJ_FICHIER, "$", f"logo non écrit : {type(exc).__name__}")
        return {
            **enregistre,
            "declinaisons": ["monochrome", "negatif"],
            "avertissement": actifs.AVERTISSEMENT_LOGO,
            "prochaine_etape": "contrôler le logo, puis demander la revue : aucune protection juridique n'est promise",
        }

    # -- export vers un site ------------------------------------------------------------------------------------------
    def exporter_vers_site(
        self, actif_id: str, site_id: str, nom: str, format_: str, dossier_actifs_site: Callable[[str], Path]
    ) -> dict[str, Any]:
        if not _ID.fullmatch(site_id) or not _NOM_IMAGE.fullmatch(nom) or format_ not in ("png", "svg"):
            return _refus(REJ_SITE, "$", "site_id, nom d'image (a-z0-9-) et format (png|svg) valides exigés")
        etats, refus = actifs.charger(self.journaux.actifs)
        if refus is not None:
            return refus
        courant = etats.get(actif_id)
        if courant is None or courant.kind != p.KIND_VISUEL:
            return _refus(actifs.REJ_ACTIF_INCONNU, "$.actif_id", f"visuel inconnu : {actif_id!r}")
        if not courant.approuve:
            return _refus(
                actifs.REJ_ETAT,
                "$.actif_id",
                f"le visuel est « {courant.etat} » : seul un visuel approuvé (N3) s'exporte vers un site",
            )
        infos = courant.donnees["artefacts"].get(format_)
        if infos is None:
            return _refus(REJ_SITE, "$.format", f"ce visuel n'a pas d'artefact {format_}")
        try:
            octets = self.fichiers.lire(f"visuels/{actif_id}/visuel.{format_}", infos["sha256"])
            cible = dossier_actifs_site(site_id) / "images"
            cible.mkdir(parents=True, mode=0o700, exist_ok=True)
            destination = cible / f"{nom}.{format_}"
            temporaire = destination.with_name(destination.name + ".tmp")
            descripteur = os.open(
                temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600
            )
            with os.fdopen(descripteur, "wb") as flux:
                flux.write(octets)
            os.replace(temporaire, destination)
        except OSError as exc:
            return _refus(REJ_SITE, "$", f"export impossible : {type(exc).__name__}")
        entree = {
            "id": nom,
            "fichier": f"images/{nom}.{format_}",
            "largeur": infos["largeur"],
            "hauteur": infos["hauteur"],
            "alt": {"fr": courant.donnees["alt"][:ALT_MAX]},
        }
        resultat = {
            "accepte": True,
            "actif_id": actif_id,
            "fichier": entree["fichier"],
            "sha256": infos["sha256"],
            "entree_images": entree,
            "execute": False,
        }
        if courant.donnees.get("ia_generee"):
            resultat["avertissement_ia"] = AVERTISSEMENT_IA_SITE
        return resultat

    # -- lecture -------------------------------------------------------------------------------------------------------
    def lire(self, actif_id: str | None = None, brief_id: str | None = None, limite: int = 20) -> dict[str, Any]:
        if brief_id is not None:
            return briefs.lire(self.journaux.briefs, brief_id)
        resultat = actifs.lire(self.journaux.actifs, actif_id, limite)
        if actif_id is not None or not resultat.get("accepte"):
            return resultat
        return {
            **resultat,
            "briefs": briefs.lire(self.journaux.briefs, None, 5).get("briefs", []),
            "integrite": {"actifs": actifs.charger(self.journaux.actifs)[1] is None},
        }
