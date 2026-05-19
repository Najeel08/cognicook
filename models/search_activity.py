from extensions import db


class SearchActivity(db.Model):
    __table_args__ = (
        db.Index("ix_search_activity_user_created_at", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    ingredients = db.Column(db.Text, nullable=False)
    normalized_ingredients = db.Column(db.Text, nullable=False)
    result_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.Float, nullable=False)
