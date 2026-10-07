"""Only fixed, application-owned SQL fragments; all request values are bound.

Each report query uses one PostgreSQL statement snapshot. Refund attribution is
monotone: consume original appointment items in position order. The difference
between cumulative refunds before/after an entry reconciles every partial refund
without floating point, even when an earlier refund is outside the report range.
"""

SCOPED = """
WITH scoped AS (
    SELECT a.id, a.line_id FROM appointments a
    WHERE a.tenant_id = :tenant AND a.is_test = :is_test
      AND (:all_lines OR a.line_id = ANY(CAST(:lines AS uuid[])))
      AND (CAST(:line AS uuid) IS NULL OR a.line_id = CAST(:line AS uuid))
), ledger AS (
    SELECT e.*, p.appointment_id, s.line_id, al.id IS NOT NULL AS allocated
    FROM financial_entries e
    JOIN payment_transactions t ON (t.tenant_id, t.id) = (e.tenant_id, e.transaction_id)
    JOIN payment_intents p ON (p.tenant_id, p.id) = (t.tenant_id, t.intent_id)
    JOIN scoped s ON s.id = p.appointment_id
    LEFT JOIN payment_allocations al
      ON (al.tenant_id, al.transaction_id) = (e.tenant_id, e.transaction_id)
    WHERE e.tenant_id = :tenant AND e.is_test = :is_test AND e.booked_at < :until
)
"""

DAILY = (
    SCOPED
    + """
SELECT (booked_at AT TIME ZONE :zone)::date AS day,
       COALESCE(sum(amount) FILTER (WHERE kind = 'CAPTURE'), 0) AS received,
       COALESCE(sum(amount) FILTER (WHERE kind = 'REFUND'), 0) AS refunded,
       COALESCE(sum(amount) FILTER (WHERE kind = 'CAPTURE' AND allocated), 0) AS allocated_received,
       COALESCE(sum(amount) FILTER (WHERE kind = 'REFUND' AND allocated), 0) AS allocated_refunded
FROM ledger WHERE booked_at >= :since GROUP BY day ORDER BY day
"""
)

ATTRIBUTED = (
    SCOPED
    + """
, running AS (
    SELECT *, COALESCE(sum(amount) FILTER (WHERE kind = 'REFUND') OVER (
        PARTITION BY transaction_id ORDER BY booked_at, id ROWS UNBOUNDED PRECEDING
    ), 0) AS refunded_to_date FROM ledger WHERE allocated
), items AS (
    SELECT i.*, COALESCE(sum(i.amount) OVER (
        PARTITION BY i.appointment_id ORDER BY i.position
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ), 0) AS preceding_amount
    FROM appointment_items i JOIN scoped s ON s.id = i.appointment_id
    WHERE i.tenant_id = :tenant
), attributed AS (
    SELECT i.*, CASE WHEN e.kind = 'CAPTURE' THEN i.amount ELSE 0 END AS received,
        CASE WHEN e.kind = 'REFUND' THEN
          LEAST(i.amount, GREATEST(0, e.refunded_to_date - i.preceding_amount)) -
          LEAST(i.amount, GREATEST(0, e.refunded_to_date - e.amount - i.preceding_amount))
        ELSE 0 END AS refunded
    FROM running e JOIN items i ON i.appointment_id = e.appointment_id
    WHERE e.booked_at >= :since
)
"""
)

# These expressions are never populated from user input.
DIMENSIONS = {
    "line": ("line_id", "line_name"),
    "employee": ("original_employee_id", "employee_name"),
    "service": ("service_id", "service_name"),
}

DOCUMENTS = {
    "payments": """
        SELECT t.id, s.id AS appointment_id, s.line_id, r.number, t.verified_at AS at,
               t.amount, 'SUCCEEDED' AS status, al.id IS NOT NULL AS allocated,
               t.amount - COALESCE((SELECT sum(f.amount) FROM refunds f
                 WHERE (f.tenant_id, f.transaction_id) = (t.tenant_id, t.id)
                 AND f.status NOT IN ('FAILED', 'CANCELLED')), 0) AS refundable,
               NULL AS reason
        FROM payment_transactions t
        JOIN payment_intents p ON (p.tenant_id, p.id) = (t.tenant_id, t.intent_id)
        JOIN scoped s ON s.id = p.appointment_id
        JOIN receipts r ON (r.tenant_id, r.transaction_id) = (t.tenant_id, t.id)
        LEFT JOIN payment_allocations al ON (al.tenant_id, al.transaction_id) = (t.tenant_id, t.id)
        WHERE t.tenant_id = :tenant AND t.verified_at >= :since AND t.verified_at < :until
    """,
    "refunds": """
        SELECT f.id, s.id AS appointment_id, s.line_id, c.number, f.created_at AS at,
               f.amount, f.status::text AS status, NULL AS allocated, NULL AS refundable, f.reason
        FROM refunds f
        JOIN payment_transactions t ON (t.tenant_id, t.id) = (f.tenant_id, f.transaction_id)
        JOIN payment_intents p ON (p.tenant_id, p.id) = (t.tenant_id, t.intent_id)
        JOIN scoped s ON s.id = p.appointment_id
        LEFT JOIN credit_notes c ON (c.tenant_id, c.refund_id) = (f.tenant_id, f.id)
        WHERE f.tenant_id = :tenant AND f.created_at >= :since AND f.created_at < :until
    """,
    "invoices": """
        SELECT v.id, s.id AS appointment_id, s.line_id, v.number, v.issued_at AS at,
               v.total_amount AS amount, 'ISSUED' AS status,
               NULL AS allocated, NULL AS refundable, NULL AS reason
        FROM invoices v JOIN scoped s ON s.id = v.appointment_id
        WHERE v.tenant_id = :tenant AND v.issued_at >= :since AND v.issued_at < :until
    """,
}
