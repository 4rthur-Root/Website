"""
app.py 
logique centrale du backend
contient toute la logique partagée du frontend
"""

import os
import mimetypes
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify, abort,
                   Response, stream_with_context)
from flask_session import Session as FlaskSession
from dotenv import load_dotenv

load_dotenv()

from . import samba_client as smb
from . import admin_logic  as adm
#import ueba_hook

app = Flask(__name__, template_folder="../frontend/templates", static_folder="../frontend/static")
app.secret_key                  = os.getenv("FLASK_SECRET_KEY", "dev_key_change_me")
app.config["SESSION_TYPE"]      = "filesystem"
app.config["SESSION_FILE_DIR"]  = "/tmp/flask_sessions_samba"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"]= True
app.config["MAX_CONTENT_LENGTH"]= 500 * 1024 * 1024  # 500 Mo max
os.makedirs("/tmp/flask_sessions_samba", exist_ok=True)
FlaskSession(app)
#app.register_blueprint(ueba_hook.ueba_bp)

GROUP_META = {
    "direction":    {"label": "Direction",       "color": "#3b82f6", "icon": "🏛️"},
    "comptabilite": {"label": "Accounting",      "color": "#06b6d4", "icon": "📊"},
    "rh":           {"label": "Human Resources", "color": "#8b5cf6", "icon": "👥"},
    "technique":    {"label": "Technical",       "color": "#f59e0b", "icon": "⚙️"},
    "commun":       {"label": "Shared",          "color": "#22c55e", "icon": "🤝"},
}

GROUP_ACCESS = {
    "direction":    ["direction", "commun"],
    "comptabilite": ["comptabilite", "commun"],
    "rh":           ["rh", "commun"],
    "technique":    ["technique", "commun"],
}

# HTTP errors
@app.errorhandler(413)
def too_large(e):
    flash("⛔ File too large - limit: 500 MB. Compress the file before uploading.", "error")
    share = request.view_args.get("share", "commun") if request.view_args else "commun"
    return redirect(url_for("portal", share=share)), 303

@app.errorhandler(500)
def server_error(e):
    flash("⛔ Something went wrong on the server. Please try again.", "error")
    return redirect(url_for("portal")), 303

@app.errorhandler(403)
def forbidden(e):
    flash("⛔ Access denied.", "error")
    return redirect(url_for("portal")), 303

# Decorators
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            flash("Please sign in.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Administrator access required.", "error")
            return redirect(url_for("portal"))
        return f(*args, **kwargs)
    return decorated

# Health check
@app.route('/health')
def health():
    return {'status': 'ok'}, 200   

# Authentication
@app.route("/", methods=["GET", "POST"])
def login():
    if "username" in session:
        return redirect(url_for("admin_dashboard") if session.get("role") == "admin" else url_for("portal"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not password:
            error = "Please fill in all fields."
        elif username == "admin":
            result = adm.test_ssh_auth()
            if result.get("ok"):
                session.update({"username": "admin", "password": password,
                                "group": "admin", "role": "admin"})
                adm.audit("admin", "LOGIN", "admin", f"from {request.remote_addr}")
                return redirect(url_for("admin_dashboard"))
            else:
                error = result.get("error", "Administrator authentication failed.")
        else:
            result = smb.test_auth(username, password)
            if result["ok"]:
                session.update({"username": username, "password": password,
                                "group": result["group"], "role": "employee"})
                return redirect(url_for("portal"))
            else:
                error = result["error"]

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    username = session.get("username", "?")
    if session.get("role") == "admin":
        adm.audit(username, "LOGOUT", username)
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# Employee portal
@app.route("/portal")
@login_required
def portal():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))

    group   = session["group"]
    allowed = GROUP_ACCESS.get(group, [])
    share   = request.args.get("share", allowed[0] if allowed else "commun")

    if share not in allowed:
        return redirect(url_for("portal", share=allowed[0] if allowed else "commun"))

    files_data = None
    smb_error  = None
    result = smb.list_files(share, session["username"], session["password"])
    if result["ok"]:
        files_data = result["files"]
    else:
        smb_error = result["error"]

    return render_template("portal.html",
        username   = session["username"],
        group      = group,
        allowed    = allowed,
        share      = share,
        files      = files_data,
        smb_error  = smb_error,
        group_meta = GROUP_META,
        server_ip  = os.getenv("SAMBA_SERVER", "10.0.1.10"),
    )


@app.route("/upload/<share>", methods=["POST"])
@login_required
def upload(share):
    allowed = GROUP_ACCESS.get(session["group"], [])
    if share not in allowed:
        flash("⛔ You don't have permission to upload to this share.", "error")
        return redirect(url_for("portal"))

    file = request.files.get("file")
    if not file or file.filename == "":
        flash("No file selected.", "warning")
        return redirect(url_for("portal", share=share))

    try:
        data = file.read()
        if len(data) == 0:
            flash("⛔ The file is empty.", "error")
            return redirect(url_for("portal", share=share))

        result = smb.upload_file(share, file.filename, data,
                                 session["username"], session["password"])
        if result["ok"]:
            flash(f"✅ '{file.filename}' uploaded to /{share}", "success")
        else:
            flash(f"⛔ {result['error']}", "error")
    except Exception as e:
        flash("⛔ Upload failed. Please try again.", "error")

    return redirect(url_for("portal", share=share))


@app.route("/stream/<share>/<path:filename>")
@login_required
##@ueba_hook.lf2r("download")
def stream_download(share, filename):
    if share not in GROUP_ACCESS.get(session["group"], []):
        abort(403)

    try:
        mime      = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        file_size = smb.get_file_size(share, filename,
                                      session["username"], session["password"])
        generator = smb.stream_file(share, filename,
                                    session["username"], session["password"])

        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        if file_size:
            headers["Content-Length"] = str(file_size)

        return Response(stream_with_context(generator), mimetype=mime, headers=headers)
    except Exception:
        flash("⛔ Download failed. Please try again.", "error")
        return redirect(url_for("portal", share=share))


@app.route("/preview/<share>/<path:filename>")
@login_required
##@ueba_hook.lf2r("preview")
def preview(share, filename):
    if share not in GROUP_ACCESS.get(session["group"], []):
        abort(403)

    ext = os.path.splitext(filename)[1].lower()
    try:
        if ext in smb.PREVIEW_TEXT:
            result = smb.read_text_file(share, filename,
                                        session["username"], session["password"])
            if not result["ok"]:
                flash(f"⛔ {result['error']}", "error")
                return redirect(url_for("portal", share=share))
            return render_template("preview_text.html",
                filename=filename, share=share, content=result["content"],
                group_meta=GROUP_META, group=session["group"])

        mime      = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        generator = smb.stream_file(share, filename,
                                    session["username"], session["password"])
        return Response(stream_with_context(generator), mimetype=mime,
                        headers={"Content-Disposition": f'inline; filename="{filename}"'})
    except Exception:
        flash("⛔ Preview failed. Please try again.", "error")
        return redirect(url_for("portal", share=share))


@app.route("/delete/<share>/<path:filename>", methods=["POST"])
@login_required
#@ueba_hook.lf2r("delete")
def delete(share, filename):
    if share not in GROUP_ACCESS.get(session["group"], []):
        flash("⛔ Access denied.", "error")
        return redirect(url_for("portal"))

    result = smb.delete_file(share, filename,
                             session["username"], session["password"])
    flash(f"🗑️ '{filename}' deleted." if result["ok"] else f"⛔ {result['error']}",
          "success" if result["ok"] else "error")
    return redirect(url_for("portal", share=share))


# Employee password change
@app.route("/change-password", methods=["POST"])
@login_required
def change_own_password():
    if session.get("role") == "admin":
        return redirect(url_for("admin_dashboard"))

    current = request.form.get("current_password", "")
    new_pwd = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    group   = session.get("group", "commun")
    allowed = GROUP_ACCESS.get(group, ["commun"])

    if new_pwd != confirm:
        flash("⛔ Passwords do not match.", "error")
        return redirect(url_for("portal", share=allowed[0]))

    result = adm.change_own_password(session["username"], current, new_pwd)
    if result["ok"]:
        session["password"] = new_pwd
        flash("✅ Password changed successfully.", "success")
    else:
        flash(f"⛔ {result['error']}", "error")

    return redirect(url_for("portal", share=allowed[0]))


# Admin dashboard
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    data = adm.get_dashboard_data()
    return render_template("admin.html",
        username   = session["username"],
        data       = data,
        group_meta = GROUP_META,
        server_ip  = os.getenv("SAMBA_SERVER", "10.0.1.10"),
    )


@app.route("/admin/refresh")
@login_required
@admin_required
def admin_refresh():
    data = adm.get_dashboard_data()
    return jsonify({
        "ok":        data.get("ok"),
        "load_1m":   data.get("load_1m"),
        "memory":    data.get("memory"),
        "disk":      data.get("disk"),
        "smb_count": data.get("smb_count"),
        "fail2ban":  data.get("fail2ban"),
    })


@app.route("/admin/fail2ban/unban", methods=["POST"])
@login_required
@admin_required
def unban_ip():
    ip = request.form.get("ip", "").strip()
    if not ip:
        flash("IP address is required.", "error")
        return redirect(url_for("admin_dashboard"))
    result = adm.unban_ip(ip, actor=session["username"])
    flash(f"✅ IP {ip} unbanned." if result["ok"] else f"⛔ {result['error']}",
          "success" if result["ok"] else "error")
    return redirect(url_for("admin_dashboard") + "#fail2ban")


@app.route("/admin/users/add", methods=["POST"])
@login_required
@admin_required
def add_user():
    username = request.form.get("username", "").strip().lower()
    group    = request.form.get("group", "").strip()
    password = request.form.get("password", "")
    confirm  = request.form.get("confirm", "")

    if password != confirm:
        flash("⛔ The passwords you entered don't match", "error")
        return redirect(url_for("admin_dashboard") + "#users")

    result = adm.add_user(username, group, password, actor=session["username"])
    flash(f"✅ User '{username}' created in '{group}'." if result["ok"] else f"⛔ {result['error']}",
          "success" if result["ok"] else "error")
    return redirect(url_for("admin_dashboard") + "#users")


@app.route("/admin/users/delete", methods=["POST"])
@login_required
@admin_required
def delete_user():
    username = request.form.get("username", "").strip()
    confirm  = request.form.get("confirm_username", "").strip()

    if username != confirm:
        flash("⛔ Confirmation does not match.", "error")
        return redirect(url_for("admin_dashboard") + "#users")

    result = adm.delete_user(username, actor=session["username"])
    flash(f"✅ '{username}' deleted." if result["ok"] else f"⛔ {result['error']}",
          "success" if result["ok"] else "error")
    return redirect(url_for("admin_dashboard") + "#users")


@app.route("/admin/users/change-password", methods=["POST"])
@login_required
@admin_required
def admin_change_password():
    username = request.form.get("username", "").strip()
    new_pwd  = request.form.get("new_password", "")
    confirm  = request.form.get("confirm_password", "")

    if new_pwd != confirm:
        flash("⛔ The passwords do not match", "error")
        return redirect(url_for("admin_dashboard") + "#users")

    result = adm.change_user_password(username, new_pwd, actor=session["username"])
    flash(f"✅ Password of user '{username}' modified" if result["ok"] else f"⛔ {result['error']}",
          "success" if result["ok"] else "error")
    return redirect(url_for("admin_dashboard") + "#users")


@app.route("/admin/users/logs/<username>")
@login_required
@admin_required
def user_logs(username):
    return jsonify(adm.get_user_logs(username))


@app.route("/admin/audit")
@login_required
@admin_required
def get_audit():
    return jsonify({"ok": True, "entries": adm.get_audit_log(100)})


@app.route("/admin/backup/status")
@login_required
@admin_required
def backup_status():
    return jsonify(adm.get_backup_status())


@app.route("/admin/backup/run", methods=["POST"])
@login_required
@admin_required
def run_backup():
    result = adm.run_backup_now(actor=session["username"])
    flash("✅ Backup started." if result["ok"] else f"⛔ {result['error']}",
          "success" if result["ok"] else "error")
    return redirect(url_for("admin_dashboard") + "#backup")

"""
if __name__ == "__main__":
    print("\n" + "="*55)
    print("  Samba Portal")
    print(f"  Serveur : {os.getenv('SAMBA_SERVER','10.0.1.10')}")
    print(f"  Admin   : {os.getenv('SSH_USER','?')}@{os.getenv('SSH_HOST','?')}")
    print("  URL     : http://localhost:5000")
    print("="*55 + "\n")
    app.run(host="0.0.0.0", port=5000,
            debug=os.getenv("FLASK_DEBUG", "False") == "True")
"""