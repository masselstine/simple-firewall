SUMMARY = "Configuration and init script for the simple-firewall"
LICENSE = "MIT"

S = "${WORKDIR}"

SRC_URI = " \
    file://init \
    file://simple-firewall.conf \
"

RDEPENDS_${PN} += " \
    bash \
    coreutils \
"

do_install() {
    install -d ${D}/sbin
    install -m 755 ${S}/init ${D}/sbin/init

    install -d ${D}/${sysconfdir}
    install -d ${D}/${sysconfdir}/dnsmasq.d
    install -m 644 ${S}/simple-firewall.conf ${D}/${sysconfdir}/dnsmasq.d
}
