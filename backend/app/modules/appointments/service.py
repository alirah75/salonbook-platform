from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError
from app.db.enums import AppointmentStatus
from app.modules.access.service import Principal
from app.modules.appointments import domain, idempotency
from app.modules.appointments.models import Appointment, AppointmentHistory, AppointmentItem
from app.modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentResponse,
    CancelInput,
    HistoryResponse,
    ItemResponse,
    ReasonInput,
    RescheduleInput,
    VersionInput,
)
from app.modules.billing.service import invoice
from app.modules.catalog import common
from app.modules.catalog.schemas import Page
from app.modules.identity.context import AuthContext
from app.modules.identity.models import CustomerProfile, User
from app.modules.identity.sessions import SessionService
from app.modules.scheduling import engine
from app.modules.scheduling.intervals import Package
from app.modules.scheduling.schemas import AvailabilityQuery
from app.modules.workforce.models import EmployeeProfile


def allowed(
    principal: Principal, permission: str, row: Appointment, *, owner: UUID | None = None
) -> bool:
    try:
        principal.require(permission, line_id=row.line_id, owner_id=owner)
    except AppError:
        return False
    return True


def assigned(session: Session, principal: Principal, row: Appointment) -> bool:
    return (
        session.scalar(
            select(EmployeeProfile.id).where(
                EmployeeProfile.id == row.employee_id,
                EmployeeProfile.user_id == principal.user_id,
                EmployeeProfile.is_active.is_(True),
                EmployeeProfile.deleted_at.is_(None),
            )
        )
        is not None
    )


def authorize(
    session: Session, principal: Principal, row: Appointment, customer: CustomerProfile, action: str
) -> None:
    if action in {"complete", "no_show"}:
        permitted = allowed(principal, "appointment.manage", row) or (
            allowed(principal, "appointment.finish_assigned", row)
            and assigned(session, principal, row)
        )
    else:
        own = (
            "appointment.cancel_own"
            if action == "cancel"
            else "appointment.reschedule_own"
            if action == "reschedule"
            else "appointment.read_own"
        )
        permitted = allowed(principal, "appointment.manage", row) or allowed(
            principal, own, row, owner=customer.user_id
        )
    if not permitted:
        raise AppError("forbidden", "Access denied.", 403)


def visibility(session: Session, principal: Principal) -> ColumnElement[bool]:
    clauses: list[ColumnElement[bool]] = []
    for grant in principal.grants:
        if grant.permission not in {
            "appointment.read",
            "appointment.read_own",
            "appointment.read_assigned",
        }:
            continue
        scope = (
            Appointment.tenant_id == principal.tenant_id
            if grant.scope == "TENANT"
            else Appointment.line_id == UUID(grant.line_id)
            if grant.scope == "LINE"
            else false()
        )
        if grant.permission == "appointment.read_own":
            scope &= Appointment.customer_id.in_(
                select(CustomerProfile.id).where(CustomerProfile.user_id == principal.user_id)
            )
        elif grant.permission == "appointment.read_assigned":
            scope &= Appointment.employee_id.in_(
                select(EmployeeProfile.id).where(
                    EmployeeProfile.user_id == principal.user_id,
                    EmployeeProfile.is_active.is_(True),
                    EmployeeProfile.deleted_at.is_(None),
                )
            )
        clauses.append(scope)
    if not clauses:
        raise AppError("forbidden", "Access denied.", 403)
    return or_(*clauses)


def view(session: Session, principal: Principal, row: Appointment) -> AppointmentResponse:
    customer = session.execute(
        select(CustomerProfile, User.display_name)
        .join(
            User,
            (User.id == CustomerProfile.user_id) & (User.tenant_id == CustomerProfile.tenant_id),
        )
        .where(CustomerProfile.id == row.customer_id)
    ).one()
    name = session.scalar(
        select(EmployeeProfile.public_name).where(EmployeeProfile.id == row.employee_id)
    )
    full = (
        allowed(principal, "appointment.read", row)
        or allowed(principal, "appointment.manage", row)
        or allowed(principal, "appointment.read_own", row, owner=customer[0].user_id)
    )
    items = [
        ItemResponse.model_validate(item)
        for item in session.scalars(
            select(AppointmentItem)
            .where(AppointmentItem.appointment_id == row.id)
            .order_by(AppointmentItem.position)
        )
    ]
    if not full:
        for item in items:
            item.amount = None
    return AppointmentResponse(
        id=row.id,
        customer_id=row.customer_id,
        customer_name=customer[1],
        employee_id=row.employee_id,
        employee_name=name or "",
        line_id=row.line_id,
        status=row.status,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        occupied_starts_at=row.occupied_starts_at,
        occupied_ends_at=row.occupied_ends_at,
        duration_minutes=row.duration_minutes,
        buffer_before_minutes=row.buffer_before_minutes,
        buffer_after_minutes=row.buffer_after_minutes,
        total_amount=row.total_amount if full else None,
        currency="IRR",
        is_test=row.is_test,
        hold_expires_at=row.hold_expires_at,
        confirmed_at=row.confirmed_at,
        cancelled_at=row.cancelled_at,
        cancellation_reason=row.cancellation_reason,
        version=row.version,
        items=items,
    )


def ensure_version(row: Appointment, expected: int) -> None:
    if row.version != expected:
        raise AppError("stale_appointment", "The booking changed. Refresh it before retrying.", 409)


def policy_cutoff(principal: Principal, row: Appointment, override: bool, now: datetime) -> None:
    if override:
        principal.require("appointment.override", line_id=row.line_id)
        return
    minutes = row.policy_snapshot.get("cancel_before_minutes")
    if not isinstance(minutes, int):
        raise AppError("policy_unavailable", "This booking requires a manager policy review.", 409)
    if now > row.starts_at - timedelta(minutes=minutes):
        raise AppError(
            "cancellation_cutoff", "The cancellation or rescheduling deadline has passed.", 409
        )


class AppointmentService:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions

    def list(
        self,
        context: AuthContext,
        raw: str,
        starts_from: datetime,
        starts_until: datetime,
        limit: int,
        offset: int,
        *,
        status: AppointmentStatus | None = None,
        line_id: UUID | None = None,
        employee_id: UUID | None = None,
        mine: bool = False,
    ) -> Page[AppointmentResponse]:
        if not timedelta(0) < starts_until - starts_from <= timedelta(days=366):
            raise AppError("date_range", "Select a time range of at most 366 days.", 422)
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            query = select(Appointment).where(
                visibility(session, identity.principal),
                Appointment.starts_at >= starts_from,
                Appointment.starts_at < starts_until,
            )
            if status:
                query = query.where(Appointment.status == status)
            if mine:
                query = query.where(
                    Appointment.customer_id.in_(
                        select(CustomerProfile.id).where(
                            CustomerProfile.user_id == identity.principal.user_id
                        )
                    )
                )
            if line_id:
                query = query.where(Appointment.line_id == line_id)
            if employee_id:
                query = query.where(Appointment.employee_id == employee_id)
            rows = session.scalars(
                query.order_by(Appointment.starts_at, Appointment.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page(
                [view(session, identity.principal, row) for row in rows], limit, offset
            )
        return result

    def get(self, context: AuthContext, raw: str, identifier: UUID) -> AppointmentResponse:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            row = session.scalar(
                select(Appointment).where(
                    Appointment.id == identifier, visibility(session, identity.principal)
                )
            )
            if row is None:
                raise common.missing()
            result = view(session, identity.principal, row)
        return result

    def history(
        self, context: AuthContext, raw: str, identifier: UUID, limit: int, offset: int
    ) -> Page[HistoryResponse]:
        with self.sessions.authorized(context, raw, calendar_read=True) as (session, identity):
            if (
                session.scalar(
                    select(Appointment.id).where(
                        Appointment.id == identifier, visibility(session, identity.principal)
                    )
                )
                is None
            ):
                raise common.missing()
            rows = session.scalars(
                select(AppointmentHistory)
                .where(AppointmentHistory.appointment_id == identifier)
                .order_by(AppointmentHistory.created_at, AppointmentHistory.id)
                .offset(offset)
                .limit(limit + 1)
            ).all()
            result = common.page(
                [HistoryResponse.model_validate(row) for row in rows], limit, offset
            )
        return result

    def create(
        self, context: AuthContext, raw: str, csrf: str, key: str, payload: AppointmentCreate
    ) -> idempotency.Outcome:
        def transaction() -> idempotency.Outcome:
            with self.sessions.authorized(context, raw, csrf, calendar_read=True) as (
                session,
                identity,
            ):
                identity.principal.require("appointment.create", line_id=payload.line_id)
                customer = session.scalar(
                    select(CustomerProfile).where(CustomerProfile.user_id == identity.user.id)
                )
                if customer is None:
                    raise common.missing()
                domain.customer_lock(session, customer.id)

                def reserve() -> AppointmentResponse:
                    ids = domain.candidate_ids(session, payload.line_id, payload.employee_id)
                    # Include this customer's previous hold before sorted employee locking.
                    ids.update(
                        session.scalars(
                            select(Appointment.employee_id).where(
                                Appointment.customer_id == customer.id,
                                Appointment.status == AppointmentStatus.AWAITING_PAYMENT,
                            )
                        )
                    )
                    domain.employee_locks(session, ids)
                    now = datetime.now(UTC)
                    domain.expire_related(session, customer.id, ids, now)
                    salon, policy, _ = engine.settings(session)
                    day = payload.starts_at.astimezone(ZoneInfo(salon.timezone)).date()
                    available = engine.availability(
                        session,
                        AvailabilityQuery(
                            line_id=payload.line_id,
                            service_ids=payload.service_ids,
                            date_from=day,
                            date_until=day + timedelta(days=1),
                            employee_id=payload.employee_id,
                            assignment="auto",
                            limit=100,
                        ),
                        now=now,
                        at=payload.starts_at,
                    )
                    if not available.items:
                        raise AppError(
                            "slot_unavailable", "The requested time is no longer available.", 409
                        )
                    slot = available.items[0]
                    now = datetime.now(UTC)
                    if slot.occupied_starts_at <= now:
                        raise AppError(
                            "slot_unavailable", "The requested time has already started.", 409
                        )
                    free = available.total_amount == 0
                    if (
                        not free
                        and session.scalar(
                            select(Appointment.id).where(
                                Appointment.customer_id == customer.id,
                                Appointment.status == AppointmentStatus.AWAITING_PAYMENT,
                            )
                        )
                        is not None
                    ):
                        raise AppError(
                            "active_hold", "Finish or cancel your existing hold first.", 409
                        )
                    row = Appointment(
                        tenant_id=context.tenant_id,
                        customer_id=customer.id,
                        employee_id=slot.employee_id,
                        line_id=payload.line_id,
                        status=AppointmentStatus.CONFIRMED
                        if free
                        else AppointmentStatus.AWAITING_PAYMENT,
                        starts_at=slot.starts_at,
                        ends_at=slot.ends_at,
                        occupied_starts_at=slot.occupied_starts_at,
                        occupied_ends_at=slot.occupied_ends_at,
                        duration_minutes=available.duration_minutes,
                        buffer_before_minutes=available.buffer_before_minutes,
                        buffer_after_minutes=available.buffer_after_minutes,
                        total_amount=available.total_amount,
                        currency="IRR",
                        is_test=self.sessions.settings.payments_mode == "test",
                        version=1,
                        confirmed_at=now if free else None,
                        hold_expires_at=None
                        if free
                        else min(
                            now + timedelta(minutes=policy.hold_minutes), slot.occupied_starts_at
                        ),
                        policy_snapshot={
                            "version": policy.policy_version,
                            "hold_minutes": policy.hold_minutes,
                            "cancel_before_minutes": policy.cancel_before_minutes,
                            "no_show_grace_minutes": policy.no_show_grace_minutes,
                            "timezone": salon.timezone,
                            "slot_step_minutes": policy.slot_step_minutes,
                            "identity_mode": "mobile_password",
                        },
                    )
                    session.add(row)
                    session.flush()
                    parent = common.line(session, payload.line_id)
                    for position, service_id in enumerate(payload.service_ids, 1):
                        offer, product = (
                            common.offer(session, payload.line_id, service_id),
                            common.service(session, service_id),
                        )
                        session.add(
                            AppointmentItem(
                                tenant_id=context.tenant_id,
                                appointment_id=row.id,
                                original_employee_id=row.employee_id,
                                line_id=row.line_id,
                                service_id=service_id,
                                position=position,
                                service_name=product.name,
                                line_name=parent.name,
                                employee_name=slot.employee_name,
                                duration_minutes=offer.duration_minutes,
                                buffer_before_minutes=offer.buffer_before_minutes,
                                buffer_after_minutes=offer.buffer_after_minutes,
                                amount=offer.price_amount,
                            )
                        )
                    domain.event(
                        session,
                        row,
                        "confirmed_free" if free else "held",
                        identity.user.id,
                        request_id=context.request_id,
                    )
                    session.flush()
                    if free:
                        invoice(session, row)
                    return view(session, identity.principal, row)

                result = idempotency.execute(
                    session,
                    context,
                    identity.user.id,
                    "appointment.create",
                    key,
                    payload.model_dump(mode="json"),
                    reserve,
                    status=201,
                )
            return result

        return domain.retry(transaction)

    def change(
        self,
        context: AuthContext,
        raw: str,
        csrf: str,
        key: str,
        identifier: UUID,
        action: str,
        payload: VersionInput,
    ) -> idempotency.Outcome:
        def transaction() -> idempotency.Outcome:
            with self.sessions.authorized(context, raw, csrf, calendar_read=True) as (
                session,
                identity,
            ):
                row = session.scalar(select(Appointment).where(Appointment.id == identifier))
                if row is None:
                    raise common.missing()
                customer = domain.customer_lock(session, row.customer_id)
                session.refresh(row)
                authorize(session, identity.principal, row, customer, action)

                def mutate() -> AppointmentResponse:
                    ids = {row.employee_id}
                    if isinstance(payload, RescheduleInput):
                        ids.update(domain.candidate_ids(session, row.line_id, payload.employee_id))
                        ids.update(
                            session.scalars(
                                select(Appointment.employee_id).where(
                                    Appointment.customer_id == customer.id,
                                    Appointment.status == AppointmentStatus.AWAITING_PAYMENT,
                                )
                            )
                        )
                    domain.employee_locks(session, ids)
                    session.refresh(row, with_for_update=True)
                    now = datetime.now(UTC)
                    if domain.expire(session, row, now):
                        raise domain.ExpiredHold()
                    ensure_version(row, payload.expected_version)
                    if action == "confirm":
                        domain.confirm_verified(
                            session, row, identity.user.id, request_id=context.request_id
                        )
                    elif action == "cancel" and isinstance(payload, CancelInput):
                        if row.status not in {
                            AppointmentStatus.CONFIRMED,
                            AppointmentStatus.AWAITING_PAYMENT,
                        }:
                            raise AppError(
                                "invalid_transition", "This booking cannot be cancelled.", 409
                            )
                        if row.status == AppointmentStatus.CONFIRMED:
                            policy_cutoff(identity.principal, row, payload.override_policy, now)
                        elif payload.override_policy:
                            identity.principal.require("appointment.override", line_id=row.line_id)
                        row.status, row.cancelled_at, row.cancellation_reason = (
                            AppointmentStatus.CANCELLED,
                            now,
                            payload.reason,
                        )
                        row.version += 1
                        domain.event(
                            session,
                            row,
                            "cancelled",
                            identity.user.id,
                            payload.reason,
                            data={"policy_override": payload.override_policy},
                            request_id=context.request_id,
                        )
                        domain.payment_review(session, row)
                    elif action == "reschedule" and isinstance(payload, RescheduleInput):
                        if (
                            row.status != AppointmentStatus.CONFIRMED
                            or row.occupied_starts_at <= now
                        ):
                            raise AppError(
                                "invalid_transition",
                                "Only an unstarted confirmed booking can be rescheduled.",
                                409,
                            )
                        policy_cutoff(identity.principal, row, payload.override_policy, now)
                        domain.expire_related(session, customer.id, ids, now)
                        items = session.scalars(
                            select(AppointmentItem)
                            .where(AppointmentItem.appointment_id == row.id)
                            .order_by(AppointmentItem.position)
                        ).all()
                        if not items:
                            raise AppError(
                                "snapshot_unavailable", "This booking has no service snapshot.", 409
                            )
                        salon, _, _ = engine.settings(session)
                        day = payload.starts_at.astimezone(ZoneInfo(salon.timezone)).date()
                        available = engine.availability(
                            session,
                            AvailabilityQuery(
                                line_id=row.line_id,
                                service_ids=[item.service_id for item in items],
                                date_from=day,
                                date_until=day + timedelta(days=1),
                                employee_id=payload.employee_id,
                                assignment="auto",
                                limit=100,
                            ),
                            now=now,
                            at=payload.starts_at,
                            reserved_package=Package(
                                row.duration_minutes,
                                row.buffer_before_minutes,
                                row.buffer_after_minutes,
                            ),
                            exclude_appointment_id=row.id,
                        )
                        if not available.items:
                            raise AppError(
                                "slot_unavailable",
                                "The destination time is unavailable. The original booking is unchanged.",
                                409,
                            )
                        slot = available.items[0]
                        before = {
                            "starts_at": row.starts_at.isoformat(),
                            "employee_id": str(row.employee_id),
                        }
                        row.starts_at, row.ends_at = slot.starts_at, slot.ends_at
                        row.occupied_starts_at, row.occupied_ends_at = (
                            slot.occupied_starts_at,
                            slot.occupied_ends_at,
                        )
                        row.employee_id = slot.employee_id
                        row.version += 1
                        domain.event(
                            session,
                            row,
                            "rescheduled",
                            identity.user.id,
                            payload.reason,
                            data={
                                "before": before,
                                "after": {
                                    "starts_at": row.starts_at.isoformat(),
                                    "employee_id": str(row.employee_id),
                                },
                                "policy_override": payload.override_policy,
                            },
                            request_id=context.request_id,
                        )
                    elif action in {"complete", "no_show"} and isinstance(payload, ReasonInput):
                        if row.status != AppointmentStatus.CONFIRMED:
                            raise AppError(
                                "invalid_transition",
                                "Only a confirmed booking can be finished.",
                                409,
                            )
                        grace = row.policy_snapshot.get("no_show_grace_minutes", 15)
                        if not isinstance(grace, int):
                            raise AppError(
                                "policy_unavailable", "This booking needs policy review.", 409
                            )
                        cutoff = (
                            row.ends_at
                            if action == "complete"
                            else row.starts_at + timedelta(minutes=grace)
                        )
                        if now < cutoff:
                            raise AppError(
                                "too_early", "The booking has not reached the required time.", 409
                            )
                        row.status = (
                            AppointmentStatus.COMPLETED
                            if action == "complete"
                            else AppointmentStatus.NO_SHOW
                        )
                        row.version += 1
                        domain.event(
                            session,
                            row,
                            action,
                            identity.user.id,
                            payload.reason,
                            request_id=context.request_id,
                        )
                    else:
                        raise AppError("invalid_transition", "Unsupported booking operation.", 409)
                    session.flush()
                    return view(session, identity.principal, row)

                result = idempotency.execute(
                    session,
                    context,
                    identity.user.id,
                    f"appointment.{action}:{identifier}",
                    key,
                    payload.model_dump(mode="json"),
                    mutate,
                )
            return result

        return domain.retry(transaction)
