SUMMARY = "A simple firewall implemented with iptables"
DESCRIPTION = "A simple firewall implemented with iptables \
               allowing for per port rules."

HOMEPAGE = "http://www.windriver.com"

require recipes-core/images/c3-app-container.inc

IMAGE_INSTALL += " \
    iptables \
    dnsmasq \
    bash \
    firewall-data \
    iproute2 \
    base-passwd \
"
