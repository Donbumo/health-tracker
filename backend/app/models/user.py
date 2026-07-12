from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(254), nullable=False, unique=True, index=True)
    email = db.Column(db.String(254), nullable=True, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.String(20),
        nullable=False,
        default="user",
        server_default="user",
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.current_timestamp(),
    )

    uploaded_files = db.relationship(
        "UploadedFile",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    training_plans = db.relationship(
        "TrainingPlan",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    training_sessions = db.relationship(
        "TrainingSession",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    exercises = db.relationship(
        "Exercise",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    exercise_aliases = db.relationship(
        "ExerciseAlias",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    daily_energy_records = db.relationship(
        "DailyEnergy",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    daily_nutrition_records = db.relationship(
        "DailyNutrition",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    weigh_ins = db.relationship(
        "WeighIn",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    medical_lab_reports = db.relationship(
        "MedicalLabReport",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    food_products = db.relationship(
        "FoodProduct",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    recipes = db.relationship(
        "Recipe",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    import_runs = db.relationship(
        "ImportRun",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    activities = db.relationship(
        "Activity",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    routes = db.relationship(
        "Route",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
