from extensions import db


class Favorite(db.Model):
    __table_args__ = (
        db.UniqueConstraint("user_id", "recipe_id", name="uq_favorite_user_recipe"),
    )

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe.id", ondelete="CASCADE"), nullable=False)

    user = db.relationship("User", back_populates="favorites")
    recipe = db.relationship("Recipe", back_populates="favorites")
