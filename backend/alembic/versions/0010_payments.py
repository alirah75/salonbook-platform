"""Durable test gateway and refund reconciliation schedule. Frozen schema DDL."""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE mock_orders (\n\taccount_id UUID NOT NULL, \n\trequest_key VARCHAR(128) NOT NULL, \n\tmerchant VARCHAR(160) NOT NULL, \n\tamount BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tstatus VARCHAR(16) DEFAULT 'PENDING' NOT NULL, \n\tscenario VARCHAR(32), \n\tunknown_reads INTEGER DEFAULT '0' NOT NULL, \n\treceived_at TIMESTAMP WITH TIME ZONE, \n\ttenant_id UUID NOT NULL, \n\tid UUID DEFAULT gen_random_uuid() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_mock_orders PRIMARY KEY (tenant_id, id), \n\tCONSTRAINT fk_mock_orders_tenant_id_account_id_payment_accounts FOREIGN KEY(tenant_id, account_id) REFERENCES payment_accounts (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_mock_orders_tenant_id_account_id_request_key UNIQUE (tenant_id, account_id, request_key), \n\tCONSTRAINT ck_mock_orders_amount_currency CHECK (amount > 0 AND currency = 'IRR'), \n\tCONSTRAINT ck_mock_orders_unknown_reads CHECK (unknown_reads >= 0), \n\tCONSTRAINT ck_mock_orders_status CHECK (status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'CANCELLED')), \n\tCONSTRAINT fk_mock_orders_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute("ALTER TABLE mock_orders ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mock_orders FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON mock_orders USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TRIGGER guard_identity BEFORE UPDATE ON mock_orders FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity()"
    )
    op.execute(
        "\nCREATE TABLE mock_refunds (\n\torder_id UUID NOT NULL, \n\trequest_key VARCHAR(128) NOT NULL, \n\tamount BIGINT NOT NULL, \n\ttenant_id UUID NOT NULL, \n\tid UUID DEFAULT gen_random_uuid() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_mock_refunds PRIMARY KEY (tenant_id, id), \n\tCONSTRAINT fk_mock_refunds_tenant_id_order_id_mock_orders FOREIGN KEY(tenant_id, order_id) REFERENCES mock_orders (tenant_id, id) ON DELETE RESTRICT, \n\tCONSTRAINT uq_mock_refunds_tenant_id_order_id_request_key UNIQUE (tenant_id, order_id, request_key), \n\tCONSTRAINT ck_mock_refunds_amount CHECK (amount > 0), \n\tCONSTRAINT fk_mock_refunds_tenant_id_salons FOREIGN KEY(tenant_id) REFERENCES salons (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute("ALTER TABLE mock_refunds ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mock_refunds FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON mock_refunds USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TRIGGER guard_identity BEFORE UPDATE ON mock_refunds FOR EACH ROW EXECUTE FUNCTION app_private.guard_tenant_identity()"
    )
    op.execute(
        "CREATE TRIGGER touch_timestamp BEFORE UPDATE ON mock_orders FOR EACH ROW EXECUTE FUNCTION app_private.touch_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER immutable_evidence BEFORE UPDATE OR DELETE ON mock_refunds FOR EACH ROW EXECUTE FUNCTION app_private.reject_evidence_mutation()"
    )
    op.execute("ALTER TABLE refunds ADD COLUMN next_check_at timestamptz")
    op.execute(
        "CREATE INDEX ix_refunds_reconcile ON refunds (tenant_id, next_check_at) WHERE status IN ('APPROVED', 'PROCESSING', 'RECONCILIATION_REQUIRED')"
    )
    op.execute("DROP INDEX ix_payment_attempts_reconcile")
    op.execute(
        "CREATE INDEX ix_payment_attempts_reconcile ON payment_attempts (tenant_id, next_check_at) WHERE status <> 'SUCCEEDED'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_payment_attempts_reconcile")
    op.execute(
        "CREATE INDEX ix_payment_attempts_reconcile ON payment_attempts (tenant_id, next_check_at) WHERE status IN ('PENDING', 'VERIFYING', 'RECONCILIATION_REQUIRED')"
    )
    op.execute("DROP INDEX ix_refunds_reconcile")
    op.execute("ALTER TABLE refunds DROP COLUMN next_check_at")
    op.drop_table("mock_refunds")
    op.drop_table("mock_orders")
