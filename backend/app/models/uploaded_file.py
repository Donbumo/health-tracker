from datetime import datetime, timezone

from app.extensions import db


class UploadedFile(db.Model):
    __tablename__ = "uploaded_files"
    __table_args__ = (
        db.UniqueConstraint("user_id", "sha256", name="uq_uploaded_files_user_sha256"),
        db.Index("ix_uploaded_files_user_created", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(64), nullable=False)
    storage_path = db.Column(db.String(512), nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    mime_type = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )

    user = db.relationship("User", back_populates="uploaded_files")
