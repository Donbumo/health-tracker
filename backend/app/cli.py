import click
from datetime import datetime, timedelta, timezone
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db
from app.models import (
    ApiDevice,
    ApiRefreshToken,
    ApiSession,
    DeviceSyncState,
    IdempotencyRecord,
    PlannedWorkout,
    SyncChange,
    CompanionDeviceProfile,
    CompanionProgressEvent,
    CompanionWorkoutDelivery,
    User,
)
from app.services.demo_seed import (
    DEMO_EMAIL,
    DEMO_PASSWORD,
    DemoSeedError,
    seed_demo_data,
)
from app.services.backup_reconcile import BackupReconciliationService
from app.services.mobile_sync import canonical_hash
from app.services.workout_drafts import cleanup_report as workout_draft_cleanup_report


@click.command("seed-admin")
@with_appcontext
def seed_admin_command() -> None:
    """Create the initial administrator if it does not exist."""
    username = (current_app.config.get("ADMIN_USERNAME") or "").strip()
    password = current_app.config.get("ADMIN_PASSWORD") or ""

    if not username:
        raise click.ClickException("ADMIN_USERNAME is required")
    if len(username) > 80:
        raise click.ClickException("ADMIN_USERNAME must be at most 80 characters")
    if len(password) < 12 or password == "replace-with-a-long-random-password":
        raise click.ClickException("ADMIN_PASSWORD must contain at least 12 characters")

    existing = db.session.execute(
        db.select(User).where(User.username == username)
    ).scalar_one_or_none()
    if existing:
        if not existing.is_admin:
            raise click.ClickException(
                "ADMIN_USERNAME already belongs to a non-admin user"
            )
        click.echo(f"Admin user '{username}' already exists; no changes made.")
        return

    admin = User(username=username, role="admin")
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    click.echo(f"Admin user '{username}' created.")


@click.group("seed")
def seed_group() -> None:
    """Populate explicit development and QA fixtures."""


@seed_group.command("demo")
@with_appcontext
def seed_demo_command() -> None:
    """Create idempotent fictional data for manual browser QA."""
    try:
        _user, created = seed_demo_data()
    except DemoSeedError as error:
        raise click.ClickException(str(error)) from error

    total_created = sum(created.values())
    click.echo("Demo QA listo; todos los registros son ficticios.")
    click.echo(f"Email: {DEMO_EMAIL}")
    click.echo(f"Password: {DEMO_PASSWORD}")
    click.echo(f"Registros creados en esta ejecución: {total_created}")


@click.group("backup")
def backup_group() -> None:
    """Operate and reconcile full account backups."""


@backup_group.command("reconcile")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Apply safe status/staging repairs. Default is dry-run.",
)
@click.option(
    "--stale-after-hours",
    type=click.IntRange(min=1, max=24 * 365),
    default=24,
    show_default=True,
)
@with_appcontext
def backup_reconcile_command(apply_changes: bool, stale_after_hours: int) -> None:
    """Report storage drift without exposing filenames or health data."""
    report = BackupReconciliationService().reconcile(
        apply=apply_changes,
        stale_after_hours=stale_after_hours,
    )
    click.echo(f"mode={report['mode']}")
    for key in (
        "missing_uploads",
        "corrupt_uploads",
        "missing_exports",
        "corrupt_exports",
        "orphan_files",
        "stale_staging",
        "abandoned_runs",
        "records_updated",
        "staging_removed",
        "suspicious_symlinks",
    ):
        click.echo(f"{key}={report[key]}")

    # In dry-run, print per-orphan metadata block (allowlisted, no content/paths).
    orphan_details = report.get("orphan_details", [])
    for index, detail in enumerate(orphan_details):
        click.echo(f"orphan[{index}]:")
        click.echo(f"  storage_kind={detail['storage_kind']}")
        if "relative_path" in detail:
            click.echo(f"  relative_path={detail['relative_path']}")
        else:
            click.echo(f"  path_fingerprint={detail['path_fingerprint']}")
        click.echo(f"  size_bytes={detail['size_bytes']}")
        click.echo(f"  sha256={detail['sha256']}")
        click.echo(f"  modified_at={detail['modified_at']}")
        click.echo(f"  probable_category={detail['probable_category']}")
        click.echo(f"  matching_database_record={str(detail['matching_database_record']).lower()}")

    suspicious_symlinks = report.get("suspicious_symlink_details", [])
    for index, detail in enumerate(suspicious_symlinks):
        click.echo(f"symlink[{index}]:")
        click.echo(f"  storage_kind={detail['storage_kind']}")
        click.echo(f"  path_fingerprint={detail['path_fingerprint']}")
        click.echo(f"  reason={detail['reason']}")


@click.group("api-auth")
def api_auth_group() -> None:
    """Maintain API device sessions without exposing token material."""


@api_auth_group.command("cleanup")
@click.option("--apply", "apply_changes", is_flag=True, help="Revoke expired records; default is dry-run.")
@with_appcontext
def api_auth_cleanup_command(apply_changes: bool) -> None:
    """Report or revoke expired API sessions and refresh tokens."""
    now = datetime.now(timezone.utc)
    expired_sessions = db.session.execute(
        db.select(ApiSession).where(ApiSession.expires_at < now, ApiSession.revoked_at.is_(None))
    ).scalars().all()
    expired_tokens = db.session.execute(
        db.select(ApiRefreshToken).where(ApiRefreshToken.expires_at < now, ApiRefreshToken.revoked_at.is_(None))
    ).scalars().all()
    reuse_families = db.session.execute(
        db.select(ApiRefreshToken).where(ApiRefreshToken.reuse_detected_at.is_not(None))
    ).scalars().all()
    revoked_devices = db.session.execute(
        db.select(ApiDevice).where(ApiDevice.revoked_at.is_not(None))
    ).scalars().all()
    if apply_changes:
        for record in expired_sessions:
            record.revoked_at = now
            record.revoke_reason = "expired_cleanup"
        for record in expired_tokens:
            record.revoked_at = now
        db.session.commit()
    click.echo(f"mode={'apply' if apply_changes else 'dry-run'}")
    click.echo(f"expired_sessions={len(expired_sessions)}")
    click.echo(f"expired_refresh_tokens={len(expired_tokens)}")
    click.echo(f"reuse_detected_tokens={len(reuse_families)}")
    click.echo(f"revoked_devices={len(revoked_devices)}")


@click.group("mobile-sync")
def mobile_sync_group() -> None:
    """Inspect and clean retained mobile synchronization metadata."""


@mobile_sync_group.command("cleanup")
@click.option("--apply", "apply_changes", is_flag=True, help="Delete only safely expired metadata; default is dry-run.")
@with_appcontext
def mobile_sync_cleanup_command(apply_changes: bool) -> None:
    """Clean expired idempotency rows without invalidating an active cursor."""
    now = datetime.now(timezone.utc)
    idempotency = db.session.execute(
        db.select(IdempotencyRecord).where(IdempotencyRecord.expires_at < now)
    ).scalars().all()
    stale_cutoff = now - timedelta(
        days=current_app.config["SYNC_CHANGE_RETENTION_DAYS"]
    )
    states = db.session.execute(db.select(DeviceSyncState)).scalars().all()
    minimum_cursor = min((item.last_pull_sequence for item in states), default=None)
    change_statement = db.select(SyncChange).where(SyncChange.changed_at < stale_cutoff)
    if minimum_cursor is None:
        changes = []
    else:
        changes = db.session.execute(
            change_statement.where(SyncChange.sequence <= minimum_cursor)
        ).scalars().all()
    tombstone_cutoff = now - timedelta(
        days=current_app.config["SYNC_TOMBSTONE_RETENTION_DAYS"]
    )
    tombstones = db.session.execute(
        db.select(PlannedWorkout).where(
            PlannedWorkout.deleted_at.is_not(None),
            PlannedWorkout.deleted_at < tombstone_cutoff,
        )
    ).scalars().all()
    stale_devices = db.session.execute(
        db.select(DeviceSyncState).where(DeviceSyncState.updated_at < stale_cutoff)
    ).scalars().all()
    if apply_changes:
        for item in idempotency:
            db.session.delete(item)
        for item in changes:
            db.session.delete(item)
        # Tombstones and device cursor rows are reported only. Removing either can
        # make an offline client miss a deletion, so physical cleanup is deferred.
        db.session.commit()
    click.echo(f"mode={'apply' if apply_changes else 'dry-run'}")
    click.echo(f"expired_idempotency_records={len(idempotency)}")
    click.echo(f"safe_expired_changes={len(changes)}")
    click.echo(f"expired_tombstones_report_only={len(tombstones)}")
    click.echo(f"stale_device_cursors_report_only={len(stale_devices)}")


@click.group("companion")
def companion_group() -> None:
    """Inspect retained companion delivery metadata safely."""


@companion_group.command("cleanup")
@click.option("--apply", "apply_changes", is_flag=True, help="Expire deliveries and remove old checkpoints; default is dry-run.")
@with_appcontext
def companion_cleanup_command(apply_changes: bool) -> None:
    """Report companion drift without deleting workouts or sessions."""
    now = datetime.now(timezone.utc)
    progress_cutoff = now - timedelta(days=current_app.config["COMPANION_PROGRESS_RETENTION_DAYS"])
    terminal_cutoff = now - timedelta(days=current_app.config["COMPANION_TERMINAL_RETENTION_DAYS"])
    terminal = {"completed", "aborted", "failed", "expired", "cancelled"}
    expired = db.session.execute(
        db.select(CompanionWorkoutDelivery).where(
            CompanionWorkoutDelivery.expires_at.is_not(None),
            CompanionWorkoutDelivery.expires_at < now,
            CompanionWorkoutDelivery.status.not_in(terminal),
        )
    ).scalars().all()
    old_terminal = db.session.execute(
        db.select(CompanionWorkoutDelivery).where(
            CompanionWorkoutDelivery.status.in_(terminal),
            CompanionWorkoutDelivery.updated_at < terminal_cutoff,
        )
    ).scalars().all()
    old_progress = db.session.execute(
        db.select(CompanionProgressEvent).where(CompanionProgressEvent.created_at < progress_cutoff)
    ).scalars().all()
    old_profiles = db.session.execute(
        db.select(CompanionDeviceProfile).where(
            CompanionDeviceProfile.revoked_at.is_not(None),
            CompanionDeviceProfile.revoked_at < terminal_cutoff,
        )
    ).scalars().all()
    deliveries = db.session.execute(db.select(CompanionWorkoutDelivery)).scalars().all()
    orphaned = [item for item in deliveries if item.planned_workout is None or item.profile is None or item.api_device is None]
    mismatched = [item for item in deliveries if item.profile.api_device_id != item.api_device_id or item.profile.user_id != item.user_id]
    bad_hash = []
    for item in deliveries:
        package = dict(item.payload_snapshot_json or {})
        stored = package.pop("package_hash", None)
        if stored != item.package_hash or canonical_hash(package) != item.package_hash:
            bad_hash.append(item)
    if apply_changes:
        for item in expired:
            item.status = "expired"
            item.updated_at = now
            item.revision += 1
        for item in old_progress:
            if item.delivery.status in terminal:
                db.session.delete(item)
        db.session.commit()
    click.echo(f"mode={'apply' if apply_changes else 'dry-run'}")
    click.echo(f"expired_nonterminal={len(expired)}")
    click.echo(f"old_terminal_report_only={len(old_terminal)}")
    click.echo(f"old_progress={len(old_progress)}")
    click.echo(f"old_revoked_profiles_report_only={len(old_profiles)}")
    click.echo(f"orphaned_deliveries={len(orphaned)}")
    click.echo(f"package_hash_mismatch={len(bad_hash)}")
    click.echo(f"profile_device_mismatch={len(mismatched)}")


@click.group("workout-drafts")
def workout_drafts_group() -> None:
    """Inspect and safely clean recoverable workout drafts."""


@workout_drafts_group.command("cleanup")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="Delete only invalid, expired or completed drafts; default is dry-run.",
)
@with_appcontext
def workout_drafts_cleanup_command(apply_changes: bool) -> None:
    """Report draft health without printing workout content."""
    report = workout_draft_cleanup_report(apply=apply_changes)
    for key in (
        "mode",
        "expired_drafts",
        "orphaned_drafts",
        "oversized_drafts",
        "hash_mismatches",
        "completed_session_drafts",
        "old_active_drafts_report_only",
        "records_updated",
        "records_deleted",
    ):
        click.echo(f"{key}={report[key]}")


def register_commands(app) -> None:
    app.cli.add_command(seed_admin_command)
    app.cli.add_command(seed_group)
    app.cli.add_command(backup_group)
    app.cli.add_command(api_auth_group)
    app.cli.add_command(mobile_sync_group)
    app.cli.add_command(companion_group)
    app.cli.add_command(workout_drafts_group)
