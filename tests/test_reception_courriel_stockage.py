"""fictif: true — propriétaire privé SQLite, aucune connexion fournisseur ou clé réelle."""
import importlib
import importlib.util
from dataclasses import dataclass, field

import pytest
from alembic import command
from sqlalchemy import event, func, select, update

from opsys import identite, stockage
from opsys.stockage.schema import JOURNAL, OPSYS_INSTANCE, REGISTRES

RAW = b"From: client-fictif@example.test\r\nSubject: PLAN-FICTIF-PRIVE\r\n\r\nCONTENU-FICTIF-SECRET\xff"
KEY = b"k" * 32
KEY_ID = "a" * 32
ACTOR = "admin.courriel.fictif"
SOURCE_KEYS = ("instance_id", "source_id", "compte_id", "boite", "uid_validity", "uid")


def port():
    assert importlib.util.find_spec("opsys.reception_courriel_stockage") is not None, "propriétaire absent"
    return importlib.import_module("opsys.reception_courriel_stockage")


@dataclass
class Case:
    args: dict
    calls: list = field(default_factory=list)
    after_key: object = None
    policy: str = "b" * 64

    def autoriser(self, cnx, coords, operation):
        assert dict(coords) == {k: self.args[k] for k in SOURCE_KEYS}
        assert operation in {"recevoir", "lire"}
        self.calls.append(operation)
        person = identite.personne_active(cnx, ACTOR)
        if person is None or "admin" not in person.roles:
            return None
        return ACTOR, self.policy

    def cle(self, reference):
        assert reference in {None, KEY_ID}
        if self.after_key:
            self.after_key()
        return KEY_ID, KEY

    def recevoir(self, **changes):
        return port().recevoir(dict(self.args, **changes), source=RAW,
                               autoriser=self.autoriser, obtenir_cle=self.cle)

    def lire(self):
        return port().lire({k: self.args[k] for k in SOURCE_KEYS},
                           autoriser=self.autoriser, obtenir_cle=self.cle)


@pytest.fixture
def case(opsys_home):
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ACTOR, "Admin courriel FICTIF", "mot-de-passe-fictif-123456", ["admin"])
        instance_id = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
    args = dict(version=1, instance_id=instance_id, source_id="c" * 64, compte_id="inbox-fictif",
                boite="INBOX", uid_validity="17", uid=42, taille_annoncee=len(RAW),
                recu_le="2026-10-28T04:00:00.000Z", date_interne=None, message_id="<message-fictif@example.test>")
    yield Case(args)
    stockage.liberer()


def test_stockage_original_survit_reouverture_et_ne_cree_pas_fait_M1(case):
    p = port()
    assert len(KEY) == 32
    receipt = case.recevoir()
    assert receipt["statut"] == "ORIGINAL_STOCKE_INTERNE"
    assert "client-fictif" not in repr(receipt) and "INBOX" not in repr(receipt)
    stockage.liberer()
    same, original = case.lire()
    assert same == receipt and original.source == RAW and dict(original.arguments) == case.args
    with stockage.transaction() as cnx:
        rows = cnx.execute(select(p.RECEPTIONS)).mappings().all()
        assert len(rows) == 1
        dump = repr(rows).encode()
        for private in [RAW, KEY, b"PLAN-FICTIF", b"INBOX", b"client-fictif", b"message-fictif"]:
            assert private not in dump
        assert cnx.execute(select(func.count()).select_from(REGISTRES)).scalar_one() == 0
        audit = cnx.execute(select(JOURNAL).where(JOURNAL.c.action.like("m1.original_courriel.%"))).mappings().all()
        assert [r["action"] for r in audit] == ["m1.original_courriel.stocker", "m1.original_courriel.lire"]
        assert "INBOX" not in repr(audit) and "CONTENU-FICTIF" not in repr(audit)


def test_rejeu_exact_historique_sans_nouvel_audit(case):
    first = case.recevoir()
    second = case.recevoir(recu_le="2026-10-28T05:00:00.000Z", message_id=None)
    assert first == second
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(port().RECEPTIONS)).scalar_one() == 1
        assert cnx.execute(select(func.count()).select_from(JOURNAL)
                           .where(JOURNAL.c.action == "m1.original_courriel.stocker")).scalar_one() == 1
    assert case.calls == ["recevoir"] * 4


def test_meme_identite_autres_octets_est_conflit(case):
    first = case.recevoir()
    with pytest.raises(port().Refus, match="CONFLIT"):
        port().recevoir(case.args, source=b"x" * len(RAW), autoriser=case.autoriser, obtenir_cle=case.cle)
    assert case.lire()[0] == first


def test_autorite_avant_select_recu_et_rejeu(case):
    case.recevoir()
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ACTOR, "admin")
    statements = []
    def spy(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    engine = stockage.moteur()
    event.listen(engine, "before_cursor_execute", spy)
    try:
        with pytest.raises(PermissionError):
            case.recevoir()
        with pytest.raises(PermissionError):
            case.lire()
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert not any("receptions_courriel" in statement for statement in statements)


def test_revocation_apres_insert_annule_original_et_audit(case, monkeypatch):
    p = port()
    original_audit = p.etat.journaliser
    def revoke(cnx, *args, **kwargs):
        original_audit(cnx, *args, **kwargs)
        identite.retirer_role(cnx, ACTOR, "admin")
    monkeypatch.setattr(p.etat, "journaliser", revoke)
    with pytest.raises(PermissionError):
        case.recevoir()
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(p.RECEPTIONS)).scalar_one() == 0
        assert cnx.execute(select(func.count()).select_from(JOURNAL)
                           .where(JOURNAL.c.action == "m1.original_courriel.stocker")).scalar_one() == 0


def test_politique_changee_pendant_crypto_refuse(case):
    case.after_key = lambda: setattr(case, "policy", "d" * 64)
    with pytest.raises(PermissionError):
        case.recevoir()
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(port().RECEPTIONS)).scalar_one() == 0


@pytest.mark.parametrize("change", [dict(chiffre=b"x" * 32), dict(nonce=b"x" * 12),
    dict(source_sha256="0" * 64), dict(taille_octets=1), dict(recu_id="e" * 32),
    dict(enregistre_le="2026-10-29T00:00:00.000Z")])
def test_corruption_chiffre_ou_AAD_refuse_lecture_et_rejeu(case, change):
    case.recevoir()
    p = port()
    with stockage.transaction() as cnx:
        cnx.execute(update(p.RECEPTIONS).values(**change))
    for action in [case.lire, case.recevoir]:
        with pytest.raises(p.Refus, match="CORROMPU"):
            action()


@pytest.mark.parametrize("cle", [None, (KEY_ID, b"court"), ("b" * 32, KEY), (KEY_ID, bytearray(KEY))])
def test_rejeu_sans_bonne_cle_ne_rend_pas_ACK(case, cle):
    case.recevoir()
    with pytest.raises(port().Refus, match="CLE|CORROMPU"):
        port().recevoir(case.args, source=RAW, autoriser=case.autoriser, obtenir_cle=lambda _: cle)


def test_transaction_ambiante_refusee_avant_reponse(case):
    with stockage.transaction(), pytest.raises(port().Refus, match="TRANSACTION"):
        case.recevoir()


def test_commit_exterieur_en_panne_ne_renvoie_pas_recu(case):
    p = port()
    engine = stockage.moteur()
    def fail_commit(conn):
        raise RuntimeError("commit fictif échoué")
    event.listen(engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit fictif"):
            case.recevoir()
    finally:
        event.remove(engine, "commit", fail_commit)
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(p.RECEPTIONS)).scalar_one() == 0


def test_cle_ou_autorite_absente_refusee(case):
    p = port()
    for authority, key in [(None, case.cle), (case.autoriser, None)]:
        with pytest.raises((PermissionError, p.Refus)):
            p.recevoir(case.args, source=RAW, autoriser=authority, obtenir_cle=key)


def test_quota_refuse_sans_evicter(case, monkeypatch):
    p = port()
    first = case.recevoir()
    monkeypatch.setattr(p, "MAX_LIGNES", 1)
    case.args["uid"] = 43
    with pytest.raises(p.Refus, match="QUOTA"):
        case.recevoir()
    case.args["uid"] = 42
    assert case.recevoir() == first


def test_instance_etrangere_refusee(case):
    case.args["instance_id"] = "00000000-0000-4000-8000-000000000001"
    with pytest.raises(port().Refus, match="INSTANCE"):
        case.recevoir()


@pytest.mark.parametrize("operation", ["stocker", "lire"])
def test_trigger_modifie_original_avant_commit_aucun_recu(case, operation):
    p = port()
    if operation == "lire":
        case.recevoir()
    with stockage.transaction() as cnx:
        before = cnx.execute(select(p.RECEPTIONS)).mappings().all()
        if operation == "stocker":
            cnx.exec_driver_sql("CREATE TRIGGER corruption_fictive AFTER INSERT ON receptions_courriel "
                               "BEGIN UPDATE receptions_courriel SET nonce=zeroblob(12); END")
        else:
            cnx.exec_driver_sql("CREATE TRIGGER corruption_fictive AFTER INSERT ON journal "
                               "WHEN NEW.action='m1.original_courriel.lire' "
                               "BEGIN UPDATE receptions_courriel SET nonce=zeroblob(12); END")
    with pytest.raises(p.Refus, match="CORROMPU"):
        (case.recevoir if operation == "stocker" else case.lire)()
    with stockage.transaction() as cnx:
        assert cnx.execute(select(p.RECEPTIONS)).mappings().all() == before


def test_migration_vide_retour_0029_et_remontee_preservent_instance(case):
    port()
    with stockage.transaction() as cnx:
        config = stockage._config()
        config.attributes["connection"] = cnx
        command.downgrade(config, "0029")
        assert cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one() == case.args["instance_id"]
        assert identite.personne_active(cnx, ACTOR).identifiant == ACTOR
    assert stockage.migrer() == "0030"
    assert case.recevoir()["statut"] == "ORIGINAL_STOCKE_INTERNE"


@pytest.mark.parametrize("operation", ["nouveau", "rejeu", "lire"])
@pytest.mark.parametrize("changed", [None, ("e" * 32, b"z" * 32)])
def test_cle_revoquee_ou_tournee_entre_crypto_et_commit_refuse(case, operation, changed):
    p = port()
    if operation != "nouveau":
        case.recevoir()
    seen = []
    def provider(reference):
        seen.append(reference)
        return (KEY_ID, KEY) if len(seen) == 1 else changed
    with pytest.raises(p.Refus, match="CLE"):
        if operation == "lire":
            p.lire({k: case.args[k] for k in SOURCE_KEYS}, autoriser=case.autoriser, obtenir_cle=provider)
        else:
            p.recevoir(case.args, source=RAW, autoriser=case.autoriser, obtenir_cle=provider)
    assert seen == ([None, None] if operation == "nouveau" else [KEY_ID, KEY_ID])
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(p.RECEPTIONS)).scalar_one() == (operation != "nouveau")


def test_migration_preserve_autres_tables_et_downgrade_occupe_refuse(case):
    port()
    case.recevoir()
    before = stockage.revision_courante()
    assert before == "0030"
    config = stockage._config()
    with pytest.raises(RuntimeError, match="rétrogradation refusée"), stockage.transaction() as cnx:
        config.attributes["connection"] = cnx
        command.downgrade(config, "0029")
    assert stockage.revision_courante() == before
    assert case.lire()[1].source == RAW
