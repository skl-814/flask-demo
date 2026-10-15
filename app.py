from flask import Flask, Response, render_template, abort, request, session
import pathlib
import os
import dotenv

from common import app_root

# config
dotenv.load_dotenv(app_root / '.env')

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///data.db"

# Required for signed session cookies. Without it Flask raises
# `RuntimeError: The session is unavailable because no secret key was set.`
# on the first session write (e.g. login).
# Prefer SECRET_KEY from the environment / .env; fall back to a dev-only value.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "dev-only-insecure-secret-key"

from common import db, migrate, babel, limiter

db.init_app(app)
migrate.init_app(app, db)

limiter.init_app(app)

def select_locale():
    lang = request.args.get("lang") or session.get("lang")
    return lang if lang in ("zh_CN", "en_US") else "zh_CN"

babel.init_app(app)


from blueprints.main import main_bp
from blueprints.login import login_bp
from blueprints.captcha import captcha_bp
app.register_blueprint(main_bp)
app.register_blueprint(login_bp)
app.register_blueprint(captcha_bp)

@app.route("/hello")
def hello():
    return "hello world", 200


if __name__ == "__main__":
    app.run(debug=True)
