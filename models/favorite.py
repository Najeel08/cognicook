from extensions import db

class Favorite(db.Model):
    __table_args__ = (
        db.UniqueConstraint("user_id", "recipe_id", name="uq_favorite_user_recipe"),
    )

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe.id"), nullable=False)
