"""Fabriques communes des tests de la veille concurrentielle. Données FICTIVES (domaines en `.example`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from m7_marketing.veille import collecte, doubles, registre

from opsys.observabilite.pii import MasqueurMotifs

MAINTENANT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
DOMAINE = "horizon.example"
HOTE = "www.horizon.example"
ACCUEIL = f"https://{HOTE}/"
SERVICES = f"https://{HOTE}/services"
PLAN = f"https://{HOTE}/sitemap.xml"
AUTRE_HOTE = "communiques.horizon-presse.example"
COMMUNIQUE = f"https://{AUTRE_HOTE}/nouvelles"


class Horloge:
    def __init__(self, depart: datetime = MAINTENANT) -> None:
        self.t = depart

    def __call__(self) -> datetime:
        return self.t

    def avancer(self, **kw) -> None:
        self.t += timedelta(**kw)


def masqueur() -> MasqueurMotifs:
    return MasqueurMotifs(b"\x09" * 32)


def sources_horizon():
    return [{"url": ACCUEIL, "nature": "site_officiel"}, {"url": SERVICES, "nature": "site_officiel"},
            {"url": PLAN, "nature": "plan_de_site"}]


def declarer_horizon(journal, *, concurrent_id="horizon", nom="Revêtements Horizon", sources=None, additionnels=None):
    ack = registre.declarer(journal, concurrent_id, nom, DOMAINE, sources or sources_horizon(), additionnels, "nathan",
                            "2026-10-01T00:00:00Z")
    assert ack["accepte"], ack
    return registre.actifs(journal)


def site_horizon() -> doubles.DoubleSitePublic:
    d = doubles.DoubleSitePublic()
    d.robots(HOTE, "User-agent: *\nDisallow: /prive\nCrawl-delay: 0\n")
    d.ajouter(ACCUEIL, doubles.page_html(description="Revêtement et gouttières à Laval, soumission gratuite.",
                                         ld=['{"@context":"https://schema.org","@type":"LocalBusiness"}'],
                                         liens=["/services", "/contact", f"https://{HOTE}/a-propos",
                                             "https://autre.example/x"],
                                         corps="mot " * 100))
    d.ajouter(SERVICES, doubles.page_html(titre="Nos services", h1=("Services", "Autres"), corps="texte " * 30))
    d.ajouter(PLAN, doubles.plan_de_site([ACCUEIL, SERVICES, f"https://{HOTE}/contact"]), type_contenu=doubles.XML)
    return d


def collecteur(double, concurrents, horloge=None, **options):
    horloge = horloge or Horloge()
    return collecte.Collecteur(double, concurrents=concurrents, maintenant=horloge, masqueur=masqueur(),
                               **options), horloge
