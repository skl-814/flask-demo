from flask import session, Response, Blueprint
from captcha.image import ImageCaptcha
import random

from common import limiter

captcha_bp = Blueprint("captcha", __name__, url_prefix='/captcha')

@captcha_bp.route('/get')
@limiter.limit("20 per minute")
def get_captcha():
    img = ImageCaptcha()
    code = ''.join(random.choices("1234567890abcdefghijklmnopqrstuvwxyz",k=6))
    session['captcha_text'] = code.lower()

    data = img.generate(code).read()
    resp = Response(data)
    resp.headers["Content-Type"] = 'image/png'
    resp.headers["Cache-Control"] = "no-store, no-cache, no-revalidate, max-age=0"
    
    return resp

