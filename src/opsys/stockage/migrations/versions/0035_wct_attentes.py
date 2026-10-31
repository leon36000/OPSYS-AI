"""File WCT privée ; succède à 0034, non activée."""

from alembic import op

from opsys.stockage.schema import WCT_ATTENTES, WCT_ATTENTES_AUDIT

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    cnx = op.get_bind()
    if cnx.dialect.name not in {"sqlite", "postgresql"}:
        raise RuntimeError("backend attente WCT non pris en charge")
    WCT_ATTENTES.create(cnx)
    WCT_ATTENTES_AUDIT.create(cnx)
    if cnx.dialect.name == "postgresql":
        _upgrade_postgresql()
        return
    op.execute("""CREATE TRIGGER wct_attentes_insert_guard BEFORE INSERT ON wct_attentes
        WHEN NEW.etat != 'attente' OR NEW.consommateur != 'm05-financecore'
          OR length(NEW.evenement_id) != 64 OR NEW.evenement_id GLOB '*[^0-9a-f]*'
          OR length(NEW.instance_id) NOT BETWEEN 1 AND 36 OR length(NEW.devis_id) NOT BETWEEN 1 AND 100
          OR length(NEW.lead_id) NOT BETWEEN 1 AND 128 OR NEW.cree_epoch < 0
          OR length(NEW.recu_sha256) != 64 OR NEW.recu_sha256 GLOB '*[^0-9a-f]*'
          OR typeof(NEW.cree_epoch) != 'integer' OR typeof(NEW.expire_epoch) != 'integer'
          OR typeof(NEW.revision_politique) != 'integer' OR NEW.expire_epoch - NEW.cree_epoch != 604800
          OR NEW.source_m3 IS NOT NULL OR NEW.source_m5 IS NOT NULL
          OR NOT EXISTS (SELECT 1 FROM opsys_instance i WHERE i.id=1 AND i.instance_id=NEW.instance_id)
          OR NOT EXISTS (SELECT 1 FROM evenements_sortants e WHERE e.evenement_id=NEW.evenement_id
              AND e.type_evenement='m4.travaux_termines' AND e.producteur='m04-field-ops')
          OR NOT EXISTS (SELECT 1 FROM evenements_recus r WHERE r.evenement_id=NEW.evenement_id
              AND r.consommateur=NEW.consommateur AND r.statut='echec')
        BEGIN SELECT RAISE(ABORT,'attente initiale invalide'); END""")
    op.execute("""CREATE TRIGGER wct_attentes_update_guard BEFORE UPDATE ON wct_attentes
        WHEN NEW.evenement_id IS NOT OLD.evenement_id OR NEW.consommateur IS NOT OLD.consommateur
          OR NEW.instance_id IS NOT OLD.instance_id OR NEW.devis_id IS NOT OLD.devis_id
          OR NEW.lead_id IS NOT OLD.lead_id OR NEW.recu_sha256 IS NOT OLD.recu_sha256
          OR NEW.cree_epoch IS NOT OLD.cree_epoch
          OR NEW.expire_epoch IS NOT OLD.expire_epoch
          OR NOT ((OLD.etat='attente' AND NEW.etat IN ('prete','expiree','refusee'))
               OR (OLD.etat='prete' AND NEW.etat IN ('terminee','expiree','refusee')))
          OR (OLD.etat='attente' AND NEW.etat='prete' AND (
              typeof(NEW.revision_politique) != 'integer' OR NEW.revision_politique <= 0
              OR length(NEW.source_m3) != 64 OR length(NEW.source_m5) != 64
              OR NEW.source_m3 GLOB '*[^0-9a-f]*' OR NEW.source_m5 GLOB '*[^0-9a-f]*'
              OR NEW.source_m3 IS NULL OR NEW.source_m5 IS NULL))
          OR (OLD.etat='attente' AND NEW.etat != 'prete' AND (
              NEW.revision_politique IS NOT OLD.revision_politique OR NEW.source_m3 IS NOT OLD.source_m3
              OR NEW.source_m5 IS NOT OLD.source_m5))
          OR (OLD.etat='prete' AND (NEW.revision_politique IS NOT OLD.revision_politique
              OR NEW.source_m3 IS NOT OLD.source_m3 OR NEW.source_m5 IS NOT OLD.source_m5))
        BEGIN SELECT RAISE(ABORT,'transition attente invalide'); END""")
    op.execute(
        "CREATE TRIGGER wct_attentes_no_delete BEFORE DELETE ON wct_attentes "
        "BEGIN SELECT RAISE(ABORT,'attente immuable'); END"
    )
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER wct_attentes_audit_no_{action.lower()} BEFORE {action} ON wct_attentes_audit "
            "BEGIN SELECT RAISE(ABORT,'audit immuable'); END"
        )


def _upgrade_postgresql():
    op.execute("""CREATE FUNCTION wct_attentes_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'attente immuable' USING ERRCODE = '23514';
        ELSIF TG_OP = 'INSERT' THEN
            IF NEW.etat <> 'attente' OR NEW.consommateur <> 'm05-financecore'
                OR NEW.evenement_id !~ '^[0-9a-f]{64}$' OR length(NEW.instance_id) NOT BETWEEN 1 AND 36
                OR length(NEW.devis_id) NOT BETWEEN 1 AND 100 OR length(NEW.lead_id) NOT BETWEEN 1 AND 128
                OR NEW.cree_epoch < 0 OR NEW.recu_sha256 !~ '^[0-9a-f]{64}$'
                OR NEW.expire_epoch - NEW.cree_epoch <> 604800
                OR NEW.source_m3 IS NOT NULL OR NEW.source_m5 IS NOT NULL
                OR NOT EXISTS (SELECT 1 FROM opsys_instance i WHERE i.id=1 AND i.instance_id=NEW.instance_id)
                OR NOT EXISTS (SELECT 1 FROM evenements_sortants e WHERE e.evenement_id=NEW.evenement_id
                    AND e.type_evenement='m4.travaux_termines' AND e.producteur='m04-field-ops')
                OR NOT EXISTS (SELECT 1 FROM evenements_recus r WHERE r.evenement_id=NEW.evenement_id
                    AND r.consommateur=NEW.consommateur AND r.statut='echec') THEN
                RAISE EXCEPTION 'attente initiale invalide' USING ERRCODE = '23514';
            END IF;
        ELSE
            IF NEW.evenement_id IS DISTINCT FROM OLD.evenement_id
                OR NEW.consommateur IS DISTINCT FROM OLD.consommateur
                OR NEW.instance_id IS DISTINCT FROM OLD.instance_id OR NEW.devis_id IS DISTINCT FROM OLD.devis_id
                OR NEW.lead_id IS DISTINCT FROM OLD.lead_id OR NEW.recu_sha256 IS DISTINCT FROM OLD.recu_sha256
                OR NEW.cree_epoch IS DISTINCT FROM OLD.cree_epoch OR NEW.expire_epoch IS DISTINCT FROM OLD.expire_epoch
                OR NOT ((OLD.etat='attente' AND NEW.etat IN ('prete','expiree','refusee'))
                    OR (OLD.etat='prete' AND NEW.etat IN ('terminee','expiree','refusee')))
                OR (OLD.etat='attente' AND NEW.etat='prete' AND (
                    NEW.revision_politique <= 0 OR NEW.source_m3 IS NULL OR NEW.source_m5 IS NULL
                    OR NEW.source_m3 !~ '^[0-9a-f]{64}$' OR NEW.source_m5 !~ '^[0-9a-f]{64}$'))
                OR (OLD.etat='attente' AND NEW.etat <> 'prete' AND (
                    NEW.revision_politique IS DISTINCT FROM OLD.revision_politique
                    OR NEW.source_m3 IS DISTINCT FROM OLD.source_m3 OR NEW.source_m5 IS DISTINCT FROM OLD.source_m5))
                OR (OLD.etat='prete' AND (NEW.revision_politique IS DISTINCT FROM OLD.revision_politique
                    OR NEW.source_m3 IS DISTINCT FROM OLD.source_m3
                    OR NEW.source_m5 IS DISTINCT FROM OLD.source_m5)) THEN
                RAISE EXCEPTION 'transition attente invalide' USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER wct_attentes_guard_trigger BEFORE INSERT OR UPDATE OR DELETE ON wct_attentes
        FOR EACH ROW EXECUTE FUNCTION wct_attentes_guard()""")
    op.execute("""CREATE FUNCTION wct_attentes_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'audit immuable' USING ERRCODE = '23514'; END $$""")
    op.execute("""CREATE TRIGGER wct_attentes_audit_immutable_trigger BEFORE UPDATE OR DELETE ON wct_attentes_audit
        FOR EACH ROW EXECUTE FUNCTION wct_attentes_audit_immutable()""")


def downgrade():
    cnx = op.get_bind()
    if cnx.dialect.name == "postgresql":
        op.execute("LOCK TABLE wct_attentes, wct_attentes_audit IN ACCESS EXCLUSIVE MODE")
    elif cnx.dialect.name != "sqlite":
        raise RuntimeError("backend attente WCT non pris en charge")
    if cnx.execute(WCT_ATTENTES.select().limit(1)).first():
        raise RuntimeError("attentes présentes")
    if cnx.execute(WCT_ATTENTES_AUDIT.select().limit(1)).first():
        raise RuntimeError("audit attente présent")
    if cnx.dialect.name == "postgresql":
        op.execute("DROP TRIGGER wct_attentes_audit_immutable_trigger ON wct_attentes_audit")
        op.execute("DROP TRIGGER wct_attentes_guard_trigger ON wct_attentes")
    else:
        for action in ("update", "delete"):
            op.execute("DROP TRIGGER wct_attentes_audit_no_" + action)
        for suffix in ("insert_guard", "update_guard", "no_delete"):
            op.execute("DROP TRIGGER wct_attentes_" + suffix)
    WCT_ATTENTES_AUDIT.drop(cnx)
    WCT_ATTENTES.drop(cnx)
    if cnx.dialect.name == "postgresql":
        op.execute("DROP FUNCTION wct_attentes_guard()")
        op.execute("DROP FUNCTION wct_attentes_audit_immutable()")
