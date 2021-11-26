from flask import Flask, render_template, request, jsonify
from flask_babel import Babel
from flask_babel import gettext as _

import json
import requests
import subprocess
import os

from time import sleep
from install_procedure import steps

DYNDNS_DOMAINS = ["nohost.me", "noho.st", "ynh.fr"]
AVAILABLE_LANGUAGES = ["en"] + os.listdir("translations")

# Copypasta from https://stackoverflow.com/a/36033627
class PrefixMiddleware(object):
    def __init__(self, app, prefix=""):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):

        if environ["PATH_INFO"].startswith(self.prefix):
            environ["PATH_INFO"] = environ["PATH_INFO"][len(self.prefix):]
            environ["SCRIPT_NAME"] = self.prefix
            return self.app(environ, start_response)
        else:
            start_response("404", [("Content-Type", "text/plain")])
            return ["This url does not belong to the app.".encode()]


app = Flask(__name__, static_folder="assets")
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix="/install")

babel = Babel(app)

print(steps)
steps = [(s.__name__, description) for s, description in steps]

@babel.localeselector
def get_locale():
    # try to guess the language from the user accept
    # header the browser transmits.  We support de/fr/en in this
    # example.  The best match wins.
    return request.accept_languages.best_match(AVAILABLE_LANGUAGES)


@app.route("/", methods=["POST", "GET"])
def main():

    if not os.path.exists("/etc/yunohost/clic_to_be_installed"):
        return "Clic is already installed"

    # We need this here because gettext (_) gotta be called when user makes the
    # request to know their language ... (or at least not sure how to do this
    # another way ... we can have a loop but that will probably hide what
    # strings are needed and therefore we won't be able to easily collect them
    # for translation generation)
    # But the consequence is : this gotta be kept in sync with the step list

    # FIXME: i18n
    print(steps)
    steps_with_i18n = [(s, _(description)) for s, description in steps]

    print(steps_with_i18n)
    translated_steps = [step for step, _ in steps_with_i18n]
    assert set(translated_steps)

    if request.method == "GET":
        if not os.path.exists("./data/install_params.json"):
            return render_template("form.html")
        else:
            install_params = json.loads(open("./data/install_params.json").read())
            return render_template(
                "status.html", steps=steps_with_i18n, install_params=install_params
            )

    if request.method == "POST":
        form_data = {k: v for k, v in request.form.items()}
        try:
            validate(form_data)
        except Exception as e:
            return str(e), 400

        return start_install(form_data)


@app.route("/retry", methods=["POST"])
def retry():
    return start_install(json.loads(open("./data/install_params.json").read()))


@app.route("/fullreset", methods=["POST"])
def fullreset():
    cwd = os.path.dirname(os.path.realpath(__file__))
    return os.system("bash %s/deploy/fullreset.sh" % cwd) == 0


def start_install(form_data={}):

    form_data["use_dyndns_domain"] = any(
        form_data.get("main_domain").endswith("." + dyndns_domain)
        for dyndns_domain in DYNDNS_DOMAINS
    )
    form_data["request_host"] = request.host

    os.system("mkdir -p ./data/")
    os.system("chown root:root ./data/")
    os.system("chmod o-rwx ./data/")
    if form_data:
        with open("./data/install_params.json", "w") as f:
            f.write(json.dumps(form_data))

    os.system(
        "systemctl reset-failed clic_install.service &>/dev/null || true "
    )
    cwd = os.path.dirname(os.path.realpath(__file__))
    start_status = os.system(
        "systemd-run --unit=clic_install %s/venv/bin/python3 %s/install_procedure.py"
        % (cwd, cwd)
    )

    sleep(3)

    status = (
        subprocess.check_output(
            "systemctl is-active clic_install.service || true", shell=True
        )
        .strip()
        .decode("utf-8")
    )
    if status == "active":
        return "", 200
    elif start_status != 0:
        return (
            "Failed to start the install script ... maybe the app ain't started as root ?",
            500,
        )
    else:
        status = (
            subprocess.check_output(
                "journalctl --no-pager --no-hostname -n 20 -u clic_install.service || true",
                shell=True,
            )
            .strip()
            .decode("utf-8")
        )
        return (
            "The install script was started but is still not active ... \n<pre style='text-align:left;'>"
            + status
            + "</pre>",
            500,
        )


def validate(form):

    # Connected to the internet ?
    try:
        requests.get("https://wikipedia.org", timeout=15)
    except Exception as e:
        raise Exception(
            _("It looks like the board is not connected to the internet !?")
        )

    # Dyndns domain is available ?
    if any(
        form["main_domain"].endswith("." + dyndns_domain)
        for dyndns_domain in DYNDNS_DOMAINS
    ):
        try:
            r = requests.get(
                "https://dyndns.yunohost.org/test/" + form["main_domain"], timeout=15
            )
            assert "is available" in r.text.strip()
        except Exception as e:
            raise Exception(
                _(
                    "It looks like domain %(domain)s is not available.",
                    domain=form["main_domain"],
                )
            )

    # .toml format ?
    if form.get("custom_appbundle") in ["true", True]:
        pass
        #try:
        #    json.loads(form["bundlefile"])
        #except Exception as e:
        #    raise Exception(
        #        _(
        #            "Could not load this file as json ... Is it a valid .toml file ?"
        #            + str(form["enable_vpn"])
        #        )
        #    )
        #
        # FIXME : validate expected data structure

    return True


@app.route("/status", methods=["GET"])
def status():
    def most_recent_info(log_path):

        cmd = (
            f"tac {log_path} | tail -n 50 | grep -m 1 ' INFO \\| SUCCESS ' | cut -d ' ' -f 5-"
        )
        message = subprocess.check_output(cmd, shell=True).strip().decode("utf-8")

        if not message:
            message = (
                subprocess.check_output("tail -n 1 %s" % log_path, shell=True)
                .strip()
                .decode("utf-8")
            )

        return redact_passwords(message)

    update_info_to_redact()

    data = []
    for step, _ in steps:
        status_path = "./data/%s.status" % step
        logs_path = "./data/%s.logs" % step
        data.append(
            {
                "id": step,
                "status": open(status_path).read().strip()
                if os.path.exists(status_path)
                else "pending",
                "message": most_recent_info(logs_path)
                if os.path.exists(logs_path)
                else None,
            }
        )

    status = (
        subprocess.check_output(
            "systemctl is-active clic_install.service || true", shell=True
        )
        .strip()
        .decode("utf-8")
    )

    return jsonify({"active": status == "active", "steps": data})


@app.route("/debug", methods=["GET"])
def debug():

    update_info_to_redact()
    data = []
    for step, _ in steps:
        logs_path = "./data/%s.logs" % step
        data.append(
            {
                "id": step,
                "logs": redact_passwords(open(logs_path).read().strip())
                if os.path.exists(logs_path)
                else [],
            }
        )
    return jsonify(data)


to_redact = []


def update_info_to_redact():

    if not os.path.exists("./data/install_params.json"):
        return

    data = json.loads(open("./data/install_params.json").read())

    global to_redact
    to_redact = []
    for key, value in data.items():
        if value and "pass" in key:
            to_redact.append(value)


def redact_passwords(content):

    for value in to_redact:
        content = content.replace(value, "[REDACTED]")

    return content
