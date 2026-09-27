from flask import Blueprint, render_template, abort, Response, current_app, url_for

from common import app_root

main_bp = Blueprint('main', __name__, url_prefix='/')

@main_bp.route('/')
def index():

  return render_template('index.html'), 200
