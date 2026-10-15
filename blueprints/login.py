from flask import Blueprint, render_template, abort, Response, current_app, url_for, request, redirect, session, jsonify

from werkzeug.security import generate_password_hash
from common import app_root
from model import search_user
from model import dbmodel

login_bp = Blueprint('login', __name__, url_prefix='/')

def captcha_verify():
    user_input = request.form.get("captcha", "")
    stored = session.pop("captcha_text", "")
    if not stored or user_input != stored:
        print(f"{user_input} != {stored}")
        # return jsonify({"status": "failed", "msg":"captcha failed"})
        return False

    return True

@login_bp.route('/signin', methods=["GET", "POST"])
def signin():
    if request.method == "GET":
        return render_template('signin.html'), 200

    elif request.method == "POST":
        if not captcha_verify():
            abort(403)

        user_name = request.form.get("user_name") or ""
        pwd = request.form.get("password_hash") or ""
        user = None
        rt = dbmodel.search_user_getone(user_name=user_name)
        if rt:
            user = rt
            if dbmodel.verify_user_password(user, pwd):
                session["user_uuid"] = rt.uuid
                session["user_name"] = rt.user_name
                return redirect(url_for("main.index")), 302
                
        resp = Response(
            render_template("error_page/404.html", message="user not found"),
            404
        )
        abort(resp)

    else:
        abort(400)


@login_bp.route('/signup', methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template('signup.html'), 200

    elif request.method == "POST":
        user_name = (request.form.get("user_name") or "").strip()
        pwd = request.form.get("user_password") or ""

        if not user_name or not pwd:
            return (
                render_template(
                    "error_page/404.html",
                    message="user name and password are required",
                ),
                400,
            )

        if dbmodel.search_user_getone(user_name=user_name) is not None:
            return (
                render_template(
                    "error_page/404.html",
                    message="user name already taken",
                ),
                409,
            )

        pwd_hash = generate_password_hash(pwd)
        rt = dbmodel.create_user(
            user_name=user_name,
            password_hash=pwd_hash,
            role=dbmodel.UserRoleEnum.COMMON_USER.code,
        )
        if rt:
            session["user_uuid"] = rt.uuid
            session["user_name"] = rt.user_name
            return redirect(url_for("main.index")), 302

        return (
            render_template("error_page/404.html", message="cannot create user"),
            400,
        )

    else:
        abort(400)


@login_bp.route('/logout', methods=["POST"])
def logout():
    session.pop("user_uuid")
    session.pop("user_name")

    return render_template(url_for("main.index")), 200
