import json
import subprocess
from requests.utils import requote_uri

steps = []
current_step = None

def step(func):
    steps.append(func)
    return func

@step
def upgrade(install_params):

    apt = "DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none LC_ALL=C" \
          "apt-get -o=Acquire::Retries=3 -o=Dpkg::Use-Pty=0 --quiet --assume-yes "

    run_cmd(apt + "udate")
    run_cmd(apt + "dist-upgrade -o Dpkg::Options::='--force-confold' --fix-broken --show-upgraded ")
    run_cmd(apt + "autoremove")


@step
def postinstall(install_params):

    run_cmd("yunohost tools postinstall -d {main_domain} -p {password}".format(**install_params))

@step
def firstuser(install_params):

    if " " in install_params["fullname"]:
        install_params["firstname"], install_params["lastname"] = install_params["fullname"].split(" ", 1)
    else:
        install_params["firstname"], install_params["lastname"] = install_params["fullname"]

    run_cmd("yunohost user create {username} -q 0 "
            "-f {firstname} "
            "-l {lastname} "
            "-m {username}@{main_domain} "
            "-p {password}"
            .format(**install_params))

@step
def vpnclient(install_params):
    if not install_params["enable_vpnclient"]:
        return "skipped"

    main_domain_esc = requote_uri(install_params["main_domain"])
    run_cmd("yunohost app install vpnclient --force --args \"domain=%s&path=/vpnadmin\"" % main_domain_esc)
    run_cmd("yunohost app addaccess vpnclient -u {username}".format(**install_params))
    run_cmd("yunohost app setting vpnclient service_enabled -v 1")

    open("/tmp/config.cube", "w").write(json.dumps(install_params["cubefile"]))
    os.system("chown root:root /tmp/config.cube")
    os.system("chmod 600 /tmp/config.cube")

    run_cmd("ynh-vpnclient-loadcubefile.sh -u {username} -p {password} -c /tmp/config.cube".format(**install_params))


@step
def hotspot():
    if not install_params["enable_hotspot"]:
        return "skipped"

    main_domain_esc = requote_uri(install_params["main_domain"])
    wifi_ssid_esc = requote_uri(install_params["wifi_ssid"])
    wifi_password_esc = requote_uri(install_params["wifi_password"])

    run_cmd("yunohost app install hotspot --force --args \""
            "domain={main_domain_esc}"
            "&path=/wifiadmin"
            "&wifi_ssid={wifi_ssid_esc}"
            "&wifi_passphrase={wifi_password_esc}"
            "&firmware_nonfree=no\""
            .format(main_domain_esc=main_domain_esc,
                    wifi_ssid_esc=wifi_ssid_esc,
                    wifi_password_esc=wifi_password_esc))
# TODO:
#
#  yunohost app addaccess hotspot -u "${settings[yunohost,user]}" &>> $log_file
#
#  yunohost app setting hotspot ip6_dns0 -v "${settings[hotspot,ip6_dns0]}" &>> $log_file
#  yunohost app setting hotspot ip6_dns1 -v "${settings[hotspot,ip6_dns1]}" &>> $log_file
#  yunohost app setting hotspot ip4_dns0 -v "${settings[hotspot,ip4_dns0]}" &>> $log_file
#  yunohost app setting hotspot ip4_dns1 -v "${settings[hotspot,ip4_dns1]}" &>> $log_file
#  yunohost app setting hotspot ip4_nat_prefix -v "${settings[hotspot,ip4_nat_prefix]}" &>> $log_file
#
#  ynh_wifi_device=$(yunohost app setting hotspot wifi_device 2> /dev/null)
#
#  if [ "${ynh_wifi_device}" == none ]; then
#    yunohost app setting hotspot service_enabled -v 1 &>> $log_file
#  fi

@step
def customscript():
    return "skipped"

@step
def reboot():
    return "skipped"

# ===============================================================
# ===============================================================
# ===============================================================

def run_cmd(cmd):

    append_step_log("Running: " + cmd)
    subprocess.check_call(cmd + " &>> ./data/%s.logs" % current_step.__name__, shell=True)

def append_step_log(message):
    open("./data/%s.logs" % current_step.__name__, "a").write(message + "\n")

def set_step_status(status):
    open("./data/%s.status" % current_step.__name__, "w").write(status)

if __name__ == "__main__":

    install_params = json.loads(open("./data/install_params.json").read())

    for step in steps:

        current_step = step
        set_step_status("ongoing")
        try:
            ret = step(install_params)
            assert ret in [None, "success", "skipped"]
        except Exception as e:
            set_step_status("failed")
            import traceback
            append_step_log(traceback.format_exc())
            append_step_log(str(e))
            break
        else:
            set_step_status(ret if ret else "success")
