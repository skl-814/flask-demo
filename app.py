from flask import Flask, Response, render_template, abort
import pathlib
import dotenv

from common import app_root

# config
dotenv.load_dotenv(app_root / '.env')

app = Flask(__name__)

from blueprints.main import main_bp
app.register_blueprint(main_bp)

@app.route("/hello")
def hello():
  return "hello world", 200


if __name__ == "__main__":
  app.run()
