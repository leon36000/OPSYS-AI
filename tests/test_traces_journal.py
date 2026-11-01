"""Traces d'agents : masquage avant écriture, journal append-only à chaîne HMAC, rétention, tableaux, export.

Données fictives. Aucune connexion réseau : le transport de l'adaptateur Langfuse est un double qui enregistre la
requête.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from decimal import Decimal

import pytest

from opsys.observabilite import destinations, tableaux
from opsys.observabilite.corpus_pii import _nas
from opsys.observabilite.erreurs import ErreurObservabilite
from opsys.observabilite.pii import MasqueurMotifs
from opsys.observabilite.traces import (
    JournalTraces,
    Span,
    Tarif,
    Traceur,
    estimer_cout,
    instant_iso,
    lire_spans,
    traceur_local,
)

FICTIF = True
CLE_CHAINE, CLE_PII = b"c" * 32, b"p" * 32
NAS = _nas("13069254")
NAS_AFFICHE = f"{NAS[:3]} {NAS[3:6]} {NAS[6:]}"
DEP = "m01-front-office"


class Horloge:
    def __init__(self, debut: dt.datetime) -> None:
        self.t = debut

    def __call__(self) -> dt.datetime:
        return self.t


@pytest.fixture
def horloge() -> Horloge:
    return Horloge(dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC))


@pytest.fixture
def journal(tmp_path, horloge) -> JournalTraces:
    return JournalTraces(tmp_path / "traces", CLE_CHAINE, maintenant=horloge)


@pytest.fixture
def traceur(journal, horloge) -> Traceur:
    return Traceur(journal, MasqueurMotifs(CLE_PII), maintenant=horloge)


def _octets(journal: JournalTraces) -> bytes:
    return b"".join(p.read_bytes() for p in journal.dossier.rglob("*") if p.is_file())


def _span(**kw) -> Span:
    base = dict(trace_id="a" * 32, span_id="b" * 16, type="appel_outil", debut="2026-11-01T12:00:00.000Z", duree_ms=5,
                departement=DEP, agent="agent-m1", issue="ok", outil="m1_filtrer_provenance", niveau="N0")
    return Span(**{**base, **kw})


# -- masquage avant écriture -------------------------------------------------------------------------------------------
def test_aucun_renseignement_ni_secret_n_atteint_le_disque(traceur, journal):
    secret = "ghp_" + "aB3dE5gH7j" * 4
    with traceur.appel_outil(outil="m1_filtrer_provenance", departement=DEP, agent="agent-m1", niveau="N0") as s:
        s.attribut("note", f"écrire à jean.tremblay@example.test, NAS {NAS_AFFICHE}, clé {secret}")
        s.attribut("telephone", "(514) 555-0199")
        s.attribut("password", "hunter2-fictif")
        s.conclure("refus", code="REJ-M1-FICTIF")
    brut = _octets(journal)
    for fuite in (b"jean.tremblay", NAS_AFFICHE.encode(), NAS.encode(), secret.encode(), b"aB3dE5gH7j", b"555-0199",
                  b"hunter2"):
        assert fuite not in brut, fuite
    assert b"[[COURRIEL:" in brut and b"[[NAS:" in brut
    assert not MasqueurMotifs(CLE_PII).contient_pii(brut.decode())  # le fichier entier est propre au sens du masqueur


def test_les_cles_de_contenu_sont_refusees_meme_masquees(traceur, journal):
    with traceur.appel_outil(outil="m1_filtrer_provenance", departement=DEP, agent="agent-m1", niveau="N0") as s:
        for cle in ("corps", "contenu_courriel", "prompt", "sortie_outil", "message", "arguments", "result"):
            s.attribut(cle, "texte")
        s.attribut("etape", "reception")
    (spans,) = lire_spans(journal)
    assert dict(spans.attributs) == {"etape": "reception"} and traceur.ecartes >= 7


def test_attributs_bornes_et_types_stricts(traceur, journal):
    with traceur.appel_outil(outil="m1_filtrer_provenance", departement=DEP, agent="agent-m1", niveau="N0") as s:
        for i in range(40):
            s.attribut(f"cle{i}", "x" * 500)
        s.attribut("liste", [1, 2])
        s.attribut("Majuscule", "x")
    (span,) = lire_spans(journal)
    assert len(span.attributs) == 20 and all(len(v) <= 200 for v in span.attributs.values())


def test_un_identifiant_de_forme_inattendue_est_ecarte_pas_ecrit(traceur, journal):
    traceur.enregistrer(_span(outil="m1_x'; DROP TABLE", agent="Jean Tremblay", code_refus="a b c",
                              approbation_id="x y",
                              departement="m9-zzz", trace_id="pas hex", niveau="N9", jetons_entree=-5, duree_ms=-1))
    (span,) = lire_spans(journal)
    assert (span.outil, span.code_refus, span.approbation_id, span.niveau, span.jetons_entree) == (None,) * 5
    assert span.agent == "inconnu" and span.departement == "inconnu" and span.duree_ms == 0
    assert len(span.trace_id) == 32 and "pas hex" not in _octets(journal).decode()


def test_une_courriel_dans_un_identifiant_est_masque_puis_ecarte(traceur, journal):
    traceur.enregistrer(_span(approbation_id="jean@example.test"))
    assert b"jean@example.test" not in _octets(journal) and lire_spans(journal)[0].approbation_id is None


def test_type_ou_issue_inconnus_refuses_et_la_telemetrie_ne_casse_rien(traceur, journal):
    with pytest.raises(ErreurObservabilite):
        traceur.nettoyer(_span(type="autre"))
    assert traceur.enregistrer(_span(issue="reussi")) is None  # n'écrit rien et ne lève pas
    assert lire_spans(journal) == []


def test_une_panne_du_journal_ne_casse_pas_l_appel_d_outil(traceur, journal, monkeypatch):
    def casse(*_a, **_k):
        raise OSError("disque plein")

    monkeypatch.setattr(journal, "ajouter", casse)
    with traceur.appel_outil(outil="m1_filtrer_provenance", departement=DEP, agent="agent-m1", niveau="N0") as s:
        s.conclure("ok")
    # l'appel est allé au bout, sans exception


def test_une_panne_du_journal_ne_met_aucun_secret_dans_les_logs(traceur, journal, monkeypatch, caplog):
    secret = "ghp_" + "aB3dE5gH7j" * 4

    def casse(*_a, **_k):
        raise OSError(f"écriture refusée pour la clé {secret}")

    monkeypatch.setattr(journal, "ajouter", casse)
    with caplog.at_level("DEBUG"):
        traceur.enregistrer(_span(attributs={"note": f"jeton {secret}"}))
    assert secret not in caplog.text and "OSError" in caplog.text


def test_un_enregistrement_demesure_est_refuse_par_le_journal(journal):
    enorme = _span(attributs={f"cle{i}": "x" * 5000 for i in range(10)})
    with pytest.raises(ErreurObservabilite) as exc:
        journal.ajouter(enorme)  # le traceur borne les attributs ; le journal refuse ce qui dépasserait quand même
    assert exc.value.code == "REJ-OBS-TRACE-INVALIDE" and journal.segments() == []


def test_une_exception_de_l_outil_est_tracee_sans_son_message_puis_relancee(traceur, journal):
    with pytest.raises(ValueError), traceur.appel_outil(outil="m1_filtrer_provenance", departement=DEP,
                                                         agent="agent-m1", niveau="N0"):
        raise ValueError(f"le NAS {NAS_AFFICHE} est invalide")
    (span,) = lire_spans(journal)
    assert span.issue == "erreur" and span.code_refus == "exception_valueerror"
    assert NAS.encode() not in _octets(journal)


def test_le_traceur_exige_un_masqueur_conforme(journal):
    with pytest.raises(ErreurObservabilite) as exc:
        Traceur(journal, object())  # type: ignore[arg-type]
    assert exc.value.code == "REJ-OBS-MASQUEUR"


# -- modèle de trace ---------------------------------------------------------------------------------------------------
def test_chaque_appel_d_outil_porte_departement_agent_outil_niveau_duree_issue_et_lien(traceur, journal):
    ticks = iter([10.0, 10.25])
    t = Traceur(journal, MasqueurMotifs(CLE_PII), chrono=lambda: next(ticks))
    with t.appel_outil(outil="m5_envoyer_facture", departement="m05-financecore", agent="agent-m5", niveau="N4") as s:
        s.conclure("attente_approbation", approbation_id="demande-42")
    (span,) = lire_spans(journal)
    assert (span.type, span.departement, span.agent, span.outil, span.niveau) == (
        "appel_outil", "m05-financecore", "agent-m5", "m5_envoyer_facture", "N4")
    assert (span.duree_ms, span.issue, span.approbation_id) == (250, "attente_approbation", "demande-42")
    assert span.debut.endswith("Z") and len(span.trace_id) == 32 and len(span.span_id) == 16


def test_tour_d_agent_jetons_modele_et_cout_estime_en_decimal(traceur, journal):
    tarif = Tarif("palier-fictif", Decimal("3.00"), Decimal("15.00"))
    t = Traceur(journal, MasqueurMotifs(CLE_PII), tarifs={"palier-fictif": tarif})
    with t.tour_agent(departement=DEP, agent="agent-m1") as s:
        s.jetons(1_200, 350, modele="palier-fictif")
    with t.tour_agent(departement=DEP, agent="agent-m1") as s:
        s.jetons(100, 10, modele="modele-sans-tarif")
    premier, second = lire_spans(journal)
    assert premier.cout_estime_usd == "0.008850" and (premier.jetons_entree, premier.jetons_sortie) == (1200, 350)
    assert second.cout_estime_usd is None  # tarif inconnu : jamais un coût inventé
    assert estimer_cout(1000, 1000, None) is None and estimer_cout(None, 5, tarif) is None
    assert estimer_cout(1_000_000, 0, tarif) == Decimal("3.000000")


def test_un_refus_mcp_est_trace_avec_son_code(traceur, journal):
    traceur.refus(outil="m1_emettre_notification", departement=DEP, agent="agent-m1", niveau="N4",
                  code="REJ-MCP-RULE-OF-TWO", attributs={"moment": "appel"})
    (span,) = lire_spans(journal)
    assert (span.type, span.issue, span.code_refus) == ("refus_mcp", "refus", "REJ-MCP-RULE-OF-TWO")


# -- journal : append-only, chaîne, droits ----------------------------------------------------------------------------
def test_fichiers_prives_et_un_segment_par_jour(traceur, journal, horloge, verifier_acces_prive):
    traceur.enregistrer(_span())
    horloge.t += dt.timedelta(days=1)
    traceur.enregistrer(_span(span_id="c" * 16))
    segments = journal.segments()
    assert [p.name for p in segments] == ["traces-20261101.jsonl", "traces-20261102.jsonl"]
    verifier_acces_prive(journal.dossier)
    for p in segments:
        verifier_acces_prive(p)


def test_la_chaine_est_valide_apres_beaucoup_d_ecritures_concurrentes(traceur, journal):
    def ecrire(n):
        for i in range(25):
            traceur.enregistrer(_span(span_id=f"{n:02x}{i:02x}" + "0" * 12))

    fils = [threading.Thread(target=ecrire, args=(n,)) for n in range(8)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    rapport = journal.verifier()
    assert rapport.ok and rapport.enregistrements == 200 and rapport.problemes == ()
    assert len({e.seq for e in journal.lire()}) == 200


def _lignes(journal):
    chemin = journal.segments()[0]
    return chemin, chemin.read_text(encoding="utf-8").splitlines()


def test_toute_modification_suppression_ou_insertion_est_detectee(traceur, journal):
    for i in range(6):
        traceur.enregistrer(_span(span_id=f"{i:016x}"))
    assert journal.verifier().ok
    chemin, lignes = _lignes(journal)

    def reecrire(neuves):
        chemin.write_text("\n".join(neuves) + "\n", encoding="utf-8")
        return journal.verifier()

    modifie = list(lignes)
    modifie[2] = modifie[2].replace('"issue":"ok"', '"issue":"refus"')
    assert not reecrire(modifie).ok  # contenu modifié
    assert not reecrire(lignes[:2] + lignes[3:]).ok  # un maillon supprimé
    assert not reecrire([lignes[0], lignes[2], lignes[1], *lignes[3:]]).ok  # ordre changé
    assert not reecrire(lignes[:3] + [lignes[1]] + lignes[3:]).ok  # maillon dupliqué
    assert not reecrire([*lignes[:2], "{pas du json", *lignes[2:]]).ok  # ligne illisible
    assert reecrire(lignes).ok  # le fichier d'origine est de nouveau valide


def test_une_autre_cle_ne_valide_pas_la_chaine(traceur, journal):
    traceur.enregistrer(_span())
    autre = JournalTraces(journal.dossier, b"z" * 32)
    rapport = autre.verifier()
    assert not rapport.ok and "empreinte invalide" in rapport.problemes[0]


def test_ecriture_apres_une_ligne_tronquee_isole_la_ligne_sans_casser_la_suite(traceur, journal):
    traceur.enregistrer(_span())
    chemin = journal.segments()[0]
    with chemin.open("ab") as f:
        f.write(b'{"v":1,"seq":2,"prev":"abc"')  # écriture interrompue : pas de saut de ligne final
    traceur.enregistrer(_span(span_id="d" * 16))
    rapport = journal.verifier()
    assert not rapport.ok and any("tronquée" in p or "illisible" in p for p in rapport.problemes)
    assert len(lire_spans(journal)) == 2  # la lecture saute la ligne tronquée


def test_un_segment_du_milieu_supprime_rompt_la_chaine_mais_pas_le_premier_purge(traceur, journal, horloge):
    for jour in range(3):
        traceur.enregistrer(_span(span_id=f"{jour:016x}"))
        horloge.t += dt.timedelta(days=1)
    s1, s2, s3 = journal.segments()
    assert journal.verifier().ok
    s1.unlink()  # le plus ancien (purge) : accepté
    assert journal.verifier().ok
    s2.unlink()  # trou au milieu de ce qui reste : le troisième ne se rattache plus
    assert s3.exists() and journal.verifier().ok  # un seul segment restant : le trou n'est plus visible (limite)


def test_un_trou_au_milieu_est_detecte(traceur, journal, horloge):
    for jour in range(3):
        traceur.enregistrer(_span(span_id=f"{jour:016x}"))
        horloge.t += dt.timedelta(days=1)
    journal.segments()[1].unlink()
    rapport = journal.verifier()
    assert not rapport.ok and "maillon précédent rompu" in rapport.problemes[0]


def test_journal_en_lecture_seule_ne_peut_ni_ecrire_ni_purger_ni_verifier(tmp_path, traceur, journal):
    traceur.enregistrer(_span())
    ro = JournalTraces.lecture_seule(journal.dossier)
    assert len(lire_spans(ro)) == 1
    for action in (lambda: ro.ajouter(_span()), ro.appliquer_retention, ro.verifier):
        with pytest.raises(ErreurObservabilite):
            action()


def test_limites_de_construction_du_journal(tmp_path):
    for kw in ({"retention_jours": 0}, {"retention_jours": 5000}, {"taille_max_octets": 0}):
        with pytest.raises(ErreurObservabilite) as exc:
            JournalTraces(tmp_path / "x", CLE_CHAINE, **kw)
        assert exc.value.code == "REJ-OBS-JOURNAL-RETENTION"
    with pytest.raises(ErreurObservabilite):
        JournalTraces(tmp_path / "x", b"court")


# -- rétention --------------------------------------------------------------------------------------------------------
def test_retention_par_age_supprime_des_segments_entiers_et_consigne_la_purge(tmp_path, horloge):
    journal = JournalTraces(tmp_path / "t", CLE_CHAINE, retention_jours=3, maintenant=horloge)
    t = Traceur(journal, MasqueurMotifs(CLE_PII), maintenant=horloge)
    for jour in range(6):
        t.enregistrer(_span(span_id=f"{jour:016x}"))
        horloge.t += dt.timedelta(days=1)
    noms = [p.name for p in journal.segments()]
    assert noms == ["traces-20261103.jsonl", "traces-20261104.jsonl", "traces-20261105.jsonl", "traces-20261106.jsonl"]
    purges = journal.purges()
    assert purges and {r for p in purges for r in p["raisons"]} == {"age"} and purges[0]["dernier_maillon"]
    assert journal.verifier().ok  # le plus ancien segment restant commence après un segment purgé : accepté


def test_retention_par_taille_garde_toujours_le_segment_du_jour(tmp_path, horloge):
    journal = JournalTraces(tmp_path / "t", CLE_CHAINE, retention_jours=3650, taille_max_octets=1500,
                            maintenant=horloge)
    t = Traceur(journal, MasqueurMotifs(CLE_PII), maintenant=horloge)
    for jour in range(5):
        for i in range(4):
            t.enregistrer(_span(span_id=f"{jour}{i}".ljust(16, "0")))
        horloge.t += dt.timedelta(days=1)
    restants = journal.segments()
    assert 1 <= len(restants) < 5 and restants[-1].name == "traces-20261105.jsonl"
    assert any("taille" in p["raisons"] for p in journal.purges())


def test_retention_par_taille_ne_supprime_jamais_le_seul_segment_restant(tmp_path, horloge):
    journal = JournalTraces(tmp_path / "t", CLE_CHAINE, retention_jours=3650, taille_max_octets=100, maintenant=horloge)
    t = Traceur(journal, MasqueurMotifs(CLE_PII), maintenant=horloge)
    for jour in range(3):
        t.enregistrer(_span(span_id=f"{jour:016x}"))
        horloge.t += dt.timedelta(days=1)
    (reste,) = journal.segments()  # le segment du jour dépasse seul la limite : il reste, les anciens sont partis
    assert reste.name == "traces-20261103.jsonl" and len(lire_spans(journal)) == 1 and journal.verifier().ok


def test_retention_a_blanc_ne_supprime_rien(tmp_path, horloge):
    journal = JournalTraces(tmp_path / "t", CLE_CHAINE, retention_jours=3, maintenant=horloge)
    t = Traceur(journal, MasqueurMotifs(CLE_PII), maintenant=horloge)
    t.enregistrer(_span())
    horloge.t += dt.timedelta(days=30)
    avant = [p.name for p in journal.segments()]
    assert journal.appliquer_retention(a_blanc=True) == avant and [p.name for p in journal.segments()] == avant
    assert journal.appliquer_retention() == avant and journal.segments() == []
    assert journal.purges()[-1]["segments"] == avant


# -- tableaux de coût et de latence ------------------------------------------------------------------------------------
def test_tableaux_par_departement_percentiles_refus_et_cout_inconnu(traceur, journal):
    tarif = Tarif("m", Decimal("1.00"), Decimal("2.00"))
    t = Traceur(journal, MasqueurMotifs(CLE_PII), tarifs={"m": tarif})
    for ms in (10, 20, 30, 40, 1000):
        t.enregistrer(_span(duree_ms=ms, span_id=f"{ms:016x}"))
    t.enregistrer(_span(issue="refus", code_refus="REJ-MCP-RULE-OF-TWO", span_id="e" * 16, duree_ms=1))
    t.enregistrer(_span(issue="attente_approbation", span_id="f" * 16))
    with t.tour_agent(departement=DEP, agent="agent-m1") as s:
        s.jetons(1000, 500, modele="m")
    with t.tour_agent(departement=DEP, agent="agent-m1") as s:
        s.jetons(10, 10, modele="inconnu")
    t.enregistrer(_span(departement="m05-financecore", agent="agent-m5", duree_ms=7, span_id="9" * 16))
    spans = lire_spans(journal)
    m1, m5 = tableaux.agreger(spans)
    assert (m1.departement, m1.appels_outils, m1.tours_agent, m1.refus, m1.attentes_approbation) == (DEP, 7, 2, 1, 1)
    assert m1.latence_max_ms == 1000 and m1.latence_p50_ms == 10
    assert m1.cout_estime_usd == "0.002000" and m1.spans_sans_cout == 1  # le coût inconnu n'est pas compté comme zéro
    assert (m1.jetons_entree, m1.jetons_sortie) == (1010, 510)
    assert m5.departement == "m05-financecore" and m5.latence_p95_ms == 7 and m5.taux_refus == "0.0 %"
    assert tableaux.refus_par_code(spans) == [("REJ-MCP-RULE-OF-TWO", 1)]
    texte = tableaux.rendre_texte([m1, m5], tableaux.refus_par_code(spans))
    assert "m01-front-office" in texte and "REJ-MCP-RULE-OF-TWO" in texte and "pas la facture" in texte
    assert tableaux.vers_json([m1])["departements"][0]["taux_refus"] == "14.3 %"
    assert tableaux.rendre_texte([]) == "Aucune trace enregistrée sur la période."
    assert tableaux.percentile([], 50) is None and tableaux.percentile([5], 95) == 5


# -- export derrière le port ------------------------------------------------------------------------------------------
def test_export_incremental_par_lots_et_curseur(traceur, journal):
    for i in range(5):
        traceur.enregistrer(_span(span_id=f"{i:016x}"))
    cible = destinations.DestinationMemoire()
    assert isinstance(cible, destinations.DestinationTraces)
    r = destinations.exporter(journal, cible, MasqueurMotifs(CLE_PII), taille_lot=2)
    assert (r.envoyes, r.lots, r.refuses_pii, r.erreur) == (5, 3, 0, None) and len(cible.spans) == 5
    traceur.enregistrer(_span(span_id="9" * 16))
    r2 = destinations.exporter(journal, cible, MasqueurMotifs(CLE_PII))
    assert r2.envoyes == 1 and len(cible.spans) == 6  # rien n'est renvoyé deux fois
    assert destinations.exporter(journal, cible, MasqueurMotifs(CLE_PII)).envoyes == 0


def test_un_echec_d_export_n_avance_pas_le_curseur_et_se_rejoue(traceur, journal):
    for i in range(3):
        traceur.enregistrer(_span(span_id=f"{i:016x}"))
    cible = destinations.DestinationMemoire()
    cible.en_panne = True
    r = destinations.exporter(journal, cible, MasqueurMotifs(CLE_PII))
    assert r.erreur == "REJ-OBS-DESTINATION-REFUSEE" and r.envoyes == 0 and cible.spans == []
    cible.en_panne = False
    assert destinations.exporter(journal, cible, MasqueurMotifs(CLE_PII)).envoyes == 3  # aucun span perdu


def test_la_garde_de_sortie_retient_un_span_qui_contiendrait_encore_un_pii(traceur, journal):
    traceur.enregistrer(_span(span_id="1" * 16))
    # Un span écrit sans passer par le traceur (journal altéré, ancien format) : la garde de sortie le retient.
    journal.ajouter(_span(span_id="2" * 16, attributs={"note": f"NAS {NAS_AFFICHE} de jean@example.test"}))
    cible = destinations.DestinationMemoire()
    r = destinations.exporter(journal, cible, MasqueurMotifs(CLE_PII))
    assert (r.envoyes, r.refuses_pii) == (1, 1)
    assert all(NAS not in json.dumps(s.vers_dict()) for s in cible.spans)


def test_a_blanc_compte_sans_envoyer_ni_avancer_le_curseur(traceur, journal):
    traceur.enregistrer(_span())
    cible = destinations.DestinationMemoire()
    assert destinations.exporter(journal, cible, MasqueurMotifs(CLE_PII), a_blanc=True).envoyes == 1
    assert cible.spans == [] and destinations.exporter(journal, cible, MasqueurMotifs(CLE_PII)).envoyes == 1
    with pytest.raises(ErreurObservabilite):
        destinations.exporter(journal, cible, MasqueurMotifs(CLE_PII), taille_lot=0)


class _TransportEnregistreur:
    def __init__(self, statut=200):
        self.requetes, self.statut = [], statut

    def envoyer(self, requete):
        self.requetes.append(requete)
        return destinations.ReponseHTTP(self.statut)


def test_langfuse_construit_le_lot_sans_reseau_et_sans_fuite_de_cle(traceur, journal):
    tarif = Tarif("m", Decimal("1.00"), Decimal("2.00"))
    t = Traceur(journal, MasqueurMotifs(CLE_PII), tarifs={"m": tarif})
    with t.appel_outil(outil="m5_envoyer_facture", departement="m05-financecore", agent="agent-m5", niveau="N4") as s:
        s.conclure("attente_approbation", approbation_id="demande-7")
    with t.tour_agent(departement="m05-financecore", agent="agent-m5", trace_id="a" * 32) as s:
        s.jetons(100, 20, modele="m")
    transport = _TransportEnregistreur()
    cle_publique, cle_secrete = "pk-lf-fictive-0001", "sk-lf-fictive-secrete-9999"
    langfuse = destinations.DestinationLangfuse("http://langfuse.interne.example.test:3000/", lambda: (cle_publique,
                                                                                                       cle_secrete),
                                                transport)
    r = destinations.exporter(journal, langfuse, MasqueurMotifs(CLE_PII))
    assert r.erreur is None and r.envoyes == 2 and len(transport.requetes) == 1
    requete = transport.requetes[0]
    assert requete.url == "http://langfuse.interne.example.test:3000/api/public/ingestion" and requete.methode == "POST"
    lot = json.loads(requete.corps)
    types = [e["type"] for e in lot["batch"]]
    assert types.count("trace-create") == 2 and "span-create" in types and "generation-create" in types
    generation = next(e for e in lot["batch"] if e["type"] == "generation-create")["body"]
    assert generation["usage"] == {"input": 100, "output": 20, "unit": "TOKENS"} and generation["model"] == "m"
    span = next(e for e in lot["batch"] if e["type"] == "span-create")["body"]
    assert span["level"] == "WARNING" and span["metadata"]["approbation_id"] == "demande-7"
    assert requete.entetes["Authorization"].startswith("Basic ")
    # les clés ne fuient ni dans les repr ni dans le corps ; les identifiants d'événement sont déterministes (reprise)
    for visible in (repr(requete), repr(langfuse), requete.corps.decode()):
        assert cle_secrete not in visible and cle_publique not in visible
    rejoue = langfuse.construire_lot(list(lire_spans(journal)))
    assert [e["id"] for e in lot["batch"]] == [e["id"] for e in rejoue["batch"]]


def test_langfuse_sans_transport_refuse_et_un_statut_d_erreur_est_un_refus(traceur, journal):
    traceur.enregistrer(_span())
    sans = destinations.DestinationLangfuse("https://langfuse.example.test", lambda: ("a", "b"))
    with pytest.raises(ErreurObservabilite) as exc:
        sans.envoyer([])
    assert exc.value.code == "REJ-OBS-DESTINATION-NON-CONFIGUREE"
    echec = destinations.DestinationLangfuse("https://langfuse.example.test", lambda: ("a", "b"),
                                             _TransportEnregistreur(503))
    r = destinations.exporter(journal, echec, MasqueurMotifs(CLE_PII))
    assert r.erreur == "REJ-OBS-DESTINATION-REFUSEE" and r.envoyes == 0


@pytest.mark.parametrize("url", ["ftp://x.example.test", "http://u:p@x.example.test", "http://x.example.test/?k=v",
                                 "x.example.test", "http://", "https://x.example.test/#f"])
def test_langfuse_refuse_une_url_dangereuse(url):
    with pytest.raises(ErreurObservabilite) as exc:
        destinations.DestinationLangfuse(url, lambda: ("a", "b"))
    assert exc.value.code == "REJ-OBS-ARGUMENT-INVALIDE"


def test_traceur_local_cree_ses_cles_privees_et_ecrit_masque(opsys_home, verifier_acces_prive):
    t = traceur_local()
    with t.appel_outil(outil="m1_filtrer_provenance", departement=DEP, agent="agent-m1", niveau="N0") as s:
        s.attribut("note", "écrire à jean@example.test")
    assert t.journal.verifier().ok
    verifier_acces_prive(opsys_home / "observabilite" / "cle-locale")
    assert b"jean@example.test" not in _octets(t.journal)


def test_instant_iso_est_utc_a_la_milliseconde():
    assert instant_iso(dt.datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=dt.UTC)) == "2026-01-02T03:04:05.678Z"
