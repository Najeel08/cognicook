from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100, collation="NOCASE"), unique=True, nullable=False)
    email = db.Column(db.String(254, collation="NOCASE"), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    @property
    def username(self):
        return self.name

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        # A malformed hash should be handled as an invalid credential rather than
        # turning a login attempt into a server error (for example, after a
        # partially migrated legacy database).
        try:
            return check_password_hash(self.password_hash, password)
        except (TypeError, ValueError):
            return False


@login_manager.user_loader
def load_user(user_id):
    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    return db.session.get(User, normalized_user_id)
