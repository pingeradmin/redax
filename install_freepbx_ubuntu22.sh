#!/bin/bash
###############################################################################
# FreePBX 17 + Asterisk 21 on Ubuntu 22.04 (Jammy)
# Target: 149.56.33.86
#
# NOTE: FreePBX has no official Ubuntu support (only Debian 11/12 or their
# own SNG7/SNGRHEL distro). This script replicates what the official
# installer does on Debian, adapted for Ubuntu package names/repos.
# Run as root. Tested approach for Asterisk 21 + FreePBX 17.
###############################################################################

set -e

echo "### 1. Base system update ###"
apt update && apt -y upgrade
apt -y install sudo wget curl git vim gnupg2 lsb-release ca-certificates \
  software-properties-common unzip build-essential

echo "### 2. Hostname / hosts sanity (FreePBX is picky about FQDN) ###"
# Adjust hostname as needed before running, e.g.:
# hostnamectl set-hostname pbx.triangle.local
hostnamectl set-hostname pbx.local || true
grep -q "$(hostname)" /etc/hosts || echo "127.0.1.1 $(hostname)" >> /etc/hosts

echo "### 3. Install MariaDB ###"
apt -y install mariadb-server mariadb-client
systemctl enable mariadb --now

# Secure it (non-interactive)
mysql -e "UPDATE mysql.user SET Password=PASSWORD('ChangeMe_DBRoot!') WHERE User='root';" || true
mysql -e "DELETE FROM mysql.user WHERE User='';"
mysql -e "DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';"
mysql -e "FLUSH PRIVILEGES;"

echo "### 4. Install Apache + PHP 8.1 (FreePBX 17 supports 8.1/8.2) ###"
apt -y install apache2
apt -y install php8.1 php8.1-cli php8.1-common php8.1-mysql php8.1-gd \
  php8.1-mbstring php8.1-intl php8.1-xml php8.1-bcmath php8.1-curl \
  php8.1-zip php8.1-soap php8.1-ldap libapache2-mod-php8.1

a2enmod rewrite ssl
systemctl enable apache2 --now

echo "### 5. Node.js (required by FreePBX 17 GUI) ###"
curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
apt -y install nodejs

echo "### 6. Asterisk build dependencies ###"
apt -y install \
  subversion libnewt-dev libxml2-dev linux-headers-$(uname -r) \
  libsqlite3-dev uuid-dev libjansson-dev libedit-dev \
  sqlite3 pkg-config automake libtool autoconf \
  libssl-dev libsrtp2-dev libspeex-dev libspeexdsp-dev \
  libogg-dev libvorbis-dev libcurl4-openssl-dev unixodbc-dev \
  binutils-dev libcfg-dev

echo "### 7. Download and build Asterisk 21 ###"
cd /usr/src
wget -q http://downloads.asterisk.org/pub/telephony/asterisk/asterisk-21-current.tar.gz
tar xzf asterisk-21-current.tar.gz
cd asterisk-21*/

contrib/scripts/install_prereq install
./configure --with-jansson-bundled --with-pjproject-bundled
make menuselect.makeopts
menuselect/menuselect --enable app_macro --enable format_mp3 menuselect.makeopts || true

make -j"$(nproc)"
make install
make samples
make config
ldconfig

echo "### 8. Create asterisk user & fix permissions ###"
useradd -m -r -d /var/lib/asterisk asterisk || true
usermod -aG audio,dialout asterisk || true

for d in /etc/asterisk /var/{lib,log,spool,run}/asterisk /usr/lib/asterisk; do
  chown -R asterisk:asterisk "$d"
done

sed -i 's/^;\?AST_USER=.*/AST_USER="asterisk"/' /etc/default/asterisk 2>/dev/null || true
sed -i 's/^;\?AST_GROUP=.*/AST_GROUP="asterisk"/' /etc/default/asterisk 2>/dev/null || true

systemctl enable asterisk --now

echo "### 9. FreePBX database + user ###"
mysql -e "CREATE DATABASE asterisk;"
mysql -e "CREATE DATABASE asteriskcdrdb;"
mysql -e "CREATE USER 'asteriskuser'@'localhost' IDENTIFIED BY 'ChangeMe_FPBX!';"
mysql -e "GRANT ALL PRIVILEGES ON asterisk.* TO 'asteriskuser'@'localhost';"
mysql -e "GRANT ALL PRIVILEGES ON asteriskcdrdb.* TO 'asteriskuser'@'localhost';"
mysql -e "FLUSH PRIVILEGES;"

echo "### 10. Download FreePBX 17 ###"
cd /usr/src
git clone -b release/17.0 https://github.com/FreePBX/framework.git freepbx
cd freepbx

echo "### 11. Run FreePBX installer ###"
./start_asterisk start || true
./install -n --webroot=/var/www/html

echo "### 12. Apache/PHP tuning for FreePBX ###"
a2dissite 000-default.conf || true
cat > /etc/apache2/sites-available/freepbx.conf <<'EOF'
<VirtualHost *:80>
    DocumentRoot /var/www/html
    <Directory /var/www/html>
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
EOF
a2ensite freepbx.conf
systemctl restart apache2

echo "### 13. Firewall (adjust as needed for your SIP trunks) ###"
apt -y install ufw
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 5060/udp
ufw allow 5061/tcp
ufw allow 10000:20000/udp
ufw --force enable

echo "### DONE ###"
echo "Visit http://149.56.33.86/admin to complete FreePBX GUI setup."
echo "Remember to change: MySQL root pw, asteriskuser pw (used above as placeholders)."
