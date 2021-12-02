import time
import os
import json
import subprocess
import toml
from requests.utils import requote_uri
from flask_babel import gettext as _

steps = []
current_step = None


def step(description):
    def decorator(func):
        steps.append((func, description))
        return func
    return decorator

@step("System upgrade")
def upgrade(install_params):

    apt = (
        "DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none LC_ALL=C "
        "apt-get -o=Acquire::Retries=3 -o=Dpkg::Use-Pty=0 --quiet --assume-yes "
    )

    run_cmd(apt + "update")
    run_cmd(
        apt
        + "dist-upgrade -o Dpkg::Options::='--force-confold' --fix-broken --show-upgraded"
    )
    run_cmd(apt + "autoremove")


@step("System initialization")
def postinstall(install_params):

    run_cmd(
        "yunohost tools postinstall -d '{main_domain}' -p '{password}'".format(
            **install_params
        )
    )


@step("First user creation")
def firstuser(install_params):

    if " " in install_params["fullname"].strip():
        install_params["firstname"], install_params["lastname"] = (
            install_params["fullname"].strip().split(" ", 1)
        )
    else:
        install_params["firstname"] = install_params["fullname"]
        install_params["lastname"] = "FIXMEFIXME"  # FIXME

    run_cmd(
        "yunohost user create '{username}' -q 0 "
        "-f '{firstname}' "
        "-l '{lastname}' "
        "-d '{main_domain}' "
        "-p '{password}'".format(**install_params)
    )


def install_app_function(app_id):
    def install_app(install_params):

        # These are the default values
        args = {
            "admin": install_params["username"],
            "domain": ".",
            "language": "fr",
            "is_public": "yes",
        }

        args.update(appbundle[app_id].get("arguments", {}))

        args["domain"] = (args["domain"] + install_params["main_domain"]).strip(".")

        serialized_args = '&'.join(arg + "=" + requote_uri(args[arg]) for arg in args)

        src = appbundle[app_id].get("src", app_id)

        if os.system(f'yunohost domain list --output-as json | jq -r ".domains[]" | grep -q "^{args["domain"]}$"') != 0:
            run_cmd(f'yunohost domain add {args["domain"]}')
        run_cmd(f"yunohost app install {src} --force --args '{serialized_args}'")

        if appbundle[app_id].get("default") and args.get("path", "/") != "/":
            run_cmd(f"yunohost app makedefault {app_id}")

    install_app.__name__ = f"install_{app_id}"

    return install_app


appbundle_path = os.path.dirname(__file__) + "/appbundle.toml"
appbundle = toml.load(appbundle_path)
for app in appbundle.keys():
    step(f"Install {app}")(install_app_function(app))


@step("Cleaning")
def cleanup(install_params):

    # Update diagnosis results
    run_cmd("yunohost diagnosis run")
    run_cmd("yunohost diagnosis show --issues")
    run_cmd("rm /etc/yunohost/clic_to_be_installed")

    cmds = [
        "sleep 15",
        "echo '{}' > /etc/ssowat/conf.json.persistent",
        "rm /etc/nginx/conf.d/default.d/clic_install.conf",
        "systemctl reload nginx",
        "rm /etc/systemd/system/clic.service",
        "systemctl daemon-reload",
        "systemctl disable --now clic",
    ]

    open("/tmp/clic-cleanup", "w").write(
        "rm /tmp/clic-cleanup;\n" + "\n".join(cmds)
    )
    os.system("systemd-run --scope bash /tmp/clic-cleanup &")

    time.sleep(5)


# ===============================================================
# ===============================================================
# ===============================================================


def run_cmd(cmd):

    append_step_log("Running: " + cmd)
    subprocess.check_call(
        cmd + " &>> ./data/%s.logs" % current_step.__name__,
        shell=True,
        executable="/bin/bash",
    )


def append_step_log(message):
    open("./data/%s.logs" % current_step.__name__, "a").write(message + "\n")


def set_step_status(status):
    open("./data/%s.status" % current_step.__name__, "w").write(status)


def get_step_status():
    f = "./data/%s.status" % current_step.__name__
    return open(f, "r").read().strip() if os.path.exists(f) else None


if __name__ == "__main__":

    cwd = os.path.dirname(os.path.realpath(__file__))
    os.chdir(cwd)
    install_params = json.loads(open("./data/install_params.json").read())

    for step, description in steps:

        current_step = step

        # When re-running the whole thing multiple time,
        # skip test that were already succesfull / skipped...
        if get_step_status() in ["success", "skipped"]:
            continue

        set_step_status("ongoing")
        try:
            append_step_log("============================")
            ret = step(install_params)
            assert ret in [None, "success", "skipped"]
        except subprocess.CalledProcessError as e:
            set_step_status("failed")
            append_step_log(str(e))
            break
        except Exception as e:
            set_step_status("failed")
            import traceback

            append_step_log(traceback.format_exc())
            append_step_log(str(e))
            break

        set_step_status(ret if ret else "success")
