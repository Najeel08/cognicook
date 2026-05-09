from extensions import db


class AuthAttempt(db.Model):
    __table_args__ = (
        db.Index("ix_auth_attempt_key_attempted_at", "key", "attempted_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), nullable=False)
    attempted_at = db.Column(db.Float, nullable=False)
