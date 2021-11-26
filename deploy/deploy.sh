# Install apt dependencies

# Most of these are deps of vpnclient and hotspot and we install them to speed
# up the install process later

APT_DEPS="file jq sipcalc hostapd iptables iw dnsutils 
curl fake-hwclock
firmware-linux-free
python3-venv python3-setuptools python3-wheel"

apt install -o Dpkg::Options::='--force-confold' $APT_DEPS -y

# Initialize venv with pip dependencies

python3 -m venv venv
source venv/bin/activate
pip install wheel
pip install -r requirements.txt
deactivate

# Configure .local aliases

echo "clic" > /etc/yunohost/mdns.aliases

bash /usr/share/yunohost/hooks/conf_regen/??-mdns pre
[ -n "$YNH_BUILDER_INSTALL_CLIC" ] || systemctl daemon-reload
[ -n "$YNH_BUILDER_INSTALL_CLIC" ] || systemctl restart yunomdns

# Configure nginx + ssowat

cp deploy/nginx.conf /etc/nginx/conf.d/default.d/clic_install.conf
[ -n "$YNH_BUILDER_INSTALL_CLIC" ] || systemctl reload nginx

echo '{"redirected_urls": { "/": "/install" }}' > /etc/ssowat/conf.json.persistent

# Configure systemd service for flask app

cp deploy/clic.service /etc/systemd/system/
[ -n "$YNH_BUILDER_INSTALL_CLIC" ] || systemctl daemon-reload
systemctl enable clic
[ -n "$YNH_BUILDER_INSTALL_CLIC" ] || systemctl start clic

# Flag clic as "to be installed"

touch /etc/yunohost/clic_to_be_installed

