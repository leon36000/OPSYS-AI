"""Le fournisseur météo que la configuration de l'entreprise OUVRE (PLAN T4.13, M4.10).

Fermé par défaut : sans clé ``fournisseur`` dans le profil météo (`opsys-metier meteo declarer`), aucun adaptateur
réseau n'est créé et aucune requête ne part jamais ; la prévision se saisit à la main (``meteo_manuelle``). Ce module
est le seul lien entre le profil (`opsys.meteo`, un dict que l'adaptateur d'outils a lu et validé) et les adaptateurs
réseau :

    * ``msc_geomet``  -> ``meteo_geomet.creer_fournisseur_geomet`` (licence ECCC v2.1.1, usage commercial permis) ;
    * ``open_meteo``  -> ``meteo_open_meteo.creer_fournisseur_open_meteo``, seulement avec le forfait COMMERCIAL
    déclaré et
      la clé d'API dans la variable d'environnement que le profil nomme (décision du propriétaire, GATE NATHAN).

Il ne lit ni fichier ni horloge ; l'environnement est un argument (``environ``), jamais ``os.environ`` en dur, pour que
les tests n'en dépendent pas.
"""

from __future__ import annotations

from . import meteo, meteo_geomet, meteo_open_meteo

__all__ = ["fournisseur_depuis_le_profil"]


def fournisseur_depuis_le_profil(profil, environ, transport=None):
    """``(fournisseur, None)``, ``(None, verdict)`` ou ``(None, None)`` : le fournisseur que le profil ouvre.

    ``(None, None)`` : aucun fournisseur n'est ouvert (profil absent ou sans clé ``fournisseur``) : ce n'est pas une
    erreur, c'est l'état par défaut, et l'appelant le dit (« aucun fournisseur ouvert »). ``(None, verdict)`` : le
    profil en ouvre un qui ne peut pas l'être (forfait non commercial, clé d'API absente de l'environnement, fuseau
    inconnu) : ``REJ-METEO-FOURNISSEUR-FERME`` dit pourquoi. ``environ`` : le mapping des variables d'environnement ;
    ``transport`` : voir ``meteo_http`` (``None`` pour le vrai réseau)."""
    if not isinstance(profil, dict) or profil.get("fournisseur") is None:
        return None, None
    nom = profil["fournisseur"]
    fuseau = profil.get("fuseau")
    if nom == meteo_geomet.FOURNISSEUR:
        return meteo_geomet.creer_fournisseur_geomet(fuseau, transport=transport)
    if nom == meteo_open_meteo.FOURNISSEUR:
        reglage = profil.get("open_meteo") or {}
        cle_env = reglage.get("cle_env")
        cle_api = None if not isinstance(cle_env, str) else environ.get(cle_env)
        if not cle_api:
            return None, meteo.verdict_meteo(
                meteo.CODE_FOURNISSEUR_FERME,
                f"Open-Meteo fermé : la variable d'environnement {cle_env!r} (clé d'API du forfait commercial) est "
                "absente ou vide ; la clé n'entre jamais dans le profil",
            )
        return meteo_open_meteo.creer_fournisseur_open_meteo(
            reglage.get("forfait"),
            cle_api,
            fuseau,
            transport=transport,
        )
    return None, meteo.verdict_meteo(
        meteo.CODE_FOURNISSEUR_FERME,
        f"fournisseur météo inconnu : {nom!r} (attendu : msc_geomet ou open_meteo)",
    )
