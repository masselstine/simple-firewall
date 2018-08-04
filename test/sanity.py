#!/usr/bin/python
#
# Test client must be started with
# docker run -it --network=none --privileged --name=debian debian /bin/bash
#

import os
import pexpect
import docker
from subprocess import call

PROMPT = "[0-9]+#"
SF_PROMPT = "bash-4.4#"
CLIENT_PROMPT = "root@.*:/#"
IMAGE_FILE = "tmp/deploy/images/genericx86-64/simple-firewall-genericx86-64.tar.bz2"
FNULL = open(os.devnull, 'w')

# pexpect connections
sf_conn = None
client_conn = None

# Test results
TOTAL_TEST = 3
num_skipped = TOTAL_TEST
num_passed = 0
num_failed = 0

# Connect to docker client
docker_client = docker.DockerClient(base_url='unix://var/run/docker.sock')

# Cleanup and exit
def exit_test():
    if num_passed == TOTAL_TEST:
        copy_to_registry()
    cleanup()
    print("INFO: Results")
    print("-------------------------------")
    print("Tests skipped: %d" % num_skipped)
    print("Tests passed: %d" % num_passed)
    print("Tests failed: %d" % num_failed)
    exit(0)

# Upload the new image to the local registry
def copy_to_registry():
    print("INFO: All tests passed.")
    response = raw_input("Push image to registry? y/n: ")
    if response == "y":
        try:
            image = docker_client.images.get("simple-firewall")
            image.tag("localhost:5000/simple-firewall")
            docker_client.images.push("localhost:5000/simple-firewall")
            docker_client.images.remove("localhost:5000/simple-firewall")
            print("INFO: Image pushed to the registry.")
        except:
            print("ERROR: Failed to push image to registry.")
    return


# Cleanup and exit. This an be after a successful run or after hitting a failure so
# be sure to check and cleanup anything which needs it.
def cleanup():
    global sf_conn
    global client_conn

    if sf_conn is not None:
        sf_conn.sendline("exit")
        sf_conn.close()
    if client_conn is not None:
        client_conn.sendline("exit")
        client_conn.close()
    stop_container("debian")
    stop_container("simple-firewall")
    cleanup_image()
    remove_veth_pair()
    FNULL.close()
    return

# Stop a container. Normally we will be handling this via pexpect
# and a proper "exit" but here we will force the issue, if needed
def stop_container(name):
    try:
        container = docker_client.containers.get(name)
        print("INFO: Stopping %s container." % name)
        container.stop()
        container.wait(timeout=10)
    except:
        # Either the container is not running or fails to
        # die, in either case we do nothing here.
        pass
    return

# Cleanup the simple-firewall container image
def cleanup_image():
    try:
        docker_client.images.remove("simple-firewall", force=True)
    except:
        print("INFO: Failed to delete image. Please manually cleanup")
        print("      the simple-firewall image before attempting to")
        print("      run the test again.")
    return

# Cleanup the veth pair. This will usually be done automatically
# by the containers shutting down but in some cases, for example if
# we fail to insert the veth into the containers, we need to do this
# explicitely.
def remove_veth_pair():
    # Test if the veth pair exists, do nothing if it doesn't
    cmd = "ip link show test-veth0"
    ret = call(cmd.split(), stdout=FNULL, stderr=FNULL)
    if ret != 0:
        return

    # The veth pair exists, remove it
    cmd = "ip link del test-veth0"
    ret = call(cmd.split(), stdout=FNULL, stderr=FNULL)
    if ret != 0:
        print("ERROR: Failed to remove veth pair. You may need to manually delete the")
        print("       veth pair with 'ip link del test-veth0' before attempting to run")
        print("       the test again.")
    return


# Import simple-firewall container into docker
def import_image():
    print("INFO: Importing simple-firewall into Docker")
    ret = call(["docker", "import", IMAGE_FILE, "simple-firewall"], stdout=FNULL)
    if ret != 0:
        print("ERROR: Failed to import image. Exiting.")
    return

# Start the simple-firewall container. We don't use the docker python
# bindings here since we want to interact with the container using
# pexpect to drive the test interactions.
def start_simple_firewall():
    global sf_conn

    # Start the image. Since Docker handles network devices differently
    # we can't just run /sbin/init so we use bash as our entrypoint and
    # then run /sbin/init after the network device is setup.
    print("INFO: Starting simple-firewall container.")
    try:
        sf_conn = pexpect.spawn('docker run -it --rm --entrypoint=/bin/bash --privileged --name=simple-firewall simple-firewall')
    except pexpect.ExceptionPexpect:
        print("ERROR: Unable to start simple-firewall container. Exiting.")
        exit_test()
        return
    try:
        sf_conn.expect(SF_PROMPT, 20)
        sf_conn.sendline("PS1='$?#'")
        sf_conn.expect(PROMPT, 5)
    except pexpect.TIMEOUT:
        print("ERROR: Issue with simple-firewall container. Exiting")
        exit_test()
        return
    return

# Restart the existing client container. This is a debian container
# with some additional tools installed such as dhclient.
def start_client():
    global client_conn

    print("INFO: Starting client container.")
    try:
        client_conn = pexpect.spawn('docker start -ia debian')
    except pexpect.ExceptionPexpect:
        print("ERROR: Unable to start client container. Exiting.")
        exit_test()
        return

    try:
        client_conn.expect(CLIENT_PROMPT, 10)
        client_conn.expect(CLIENT_PROMPT, 10)
        client_conn.sendline("PS1='$?#'")
        client_conn.expect(PROMPT, 5)
    except pexpect.TIMEOUT:
        print("ERROR: Issue with client container. Exiting")
        print(client_conn)
        exit_test()
        return
    return

# Return the container PID
def get_container_pid(name):
    pid = 0
    llclient = docker.APIClient(base_url='unix://var/run/docker.sock')
    try:
        container = llclient.containers(all=True, filters={"name": name})[0]
        details = llclient.inspect_container(container)
        pid = details['State']['Pid']
    except:
        pass
    return pid

# Link the two containers with a veth pair. We don't use
# a separate docker network as we don't want anything like
# a bridge in the host and only want a simple point to
# point connection as we get with OverC
def link_containers():
    print("INFO: Creating veth pair to connect our containers.")
    # create the veth pair in the root namespace
    cmd = "ip link add test-veth0 type veth peer name test-veth1"
    ret = call(cmd.split(), stdout=FNULL)
    if ret != 0:
        print("ERROR: Failed to create veth pair. Exiting.")
        exit_test()
        return

    # push one end of the veth pair into each of our container's namespaces
    pid = get_container_pid("debian")
    if pid == 0:
        print("ERROR: Unable to get client pid. Exiting.")
        exit_test()
        return

    cmd = "ip link set netns %d test-veth0" % pid
    ret = call(cmd.split(), stdout=FNULL)
    if ret != 0:
        print("ERROR: Failed to move veth into client container. Exiting.")
        exit_test()
        return

    pid = get_container_pid("simple-firewall")
    if pid == 0:
        print("ERROR: Unable to get simple-firewall pid. Exiting.")
        exit_test()
        return

    cmd = "ip link set netns %d test-veth1" % pid
    ret = call(cmd.split(), stdout=FNULL)
    if ret != 0:
        print("ERROR: Failed to move veth into simple-firewall container. Exiting.")
        exit_test()
    return

# Configure the simple-firewall container to match the environment when run
# in the OverC framework and execute /sbin/init.
def setup_simple_firewall():
    global sf_conn

    print("INFO: Setup simple-firewall and execute /sbin/init")
    try:
        sf_conn.sendline("ip link set dev test-veth1 name enp2s0")
        sf_conn.expect(PROMPT, 10)
        sf_conn.sendline("/sbin/init")
    except:
        print("ERROR: Failed to setup simple-firewall container. Exiting.")
        exit_test()
    return

# Configure the client container.
def setup_client():
    global client_conn

    print("INFO: Setting up client container.")
    try:
        client_conn.sendline("umount /etc/resolv.conf")
        client_conn.expect(PROMPT, 10)
        client_conn.sendline("dhclient -q test-veth0")
        client_conn.expect(PROMPT, 60)
    except:
        print("ERROR: Failed to setup client container. Exiting.")
        exit_test()
    return

# Adjust the totals for a passed or failed test
def test_result(name, passed):
    global num_skipped
    global num_passed
    global num_failed

    num_skipped -= 1
    if passed:
        num_passed += 1
        print("INFO: %s test PASSED" % name)
    else:
        num_failed += 1
        print("INFO: %s test FAILED" % name)
    return

# Test if the client container received an IP address. This will validate
# that dnsmasq is properly configured and running in the simple-firewall
def test_dhcp(conn):
    passed = False

    try:
        conn.sendline("ip address show test-veth0 | grep -q '192\.168\.10\.'")
        conn.expect(PROMPT, 10)
        if conn.after == "0#":
            passed = True
    except:
        pass
    
    test_result("DHCP", passed)
    return

# Test DNS
def test_dns(conn):
    passed = False

    try:
        conn.sendline("host yahoo.com")
        conn.expect(PROMPT, 10)
        if conn.after == "0#":
            passed = True
    except:
        pass

    test_result("DNS", passed)
    return

def test_ports(conn):
    passed = True

    # Get the allowed ports
    allow_file = "layers/simple-firewall/recipes-core/firewall-data/files/ports.allow"
    try:
        with open(allow_file) as f:
            ports = f.readlines()
        ports = [x.strip() for x in ports]
    except IOError as e:
        print("ERROR: unable to read ports.allow file. ({})".format(e.strerror))
        passed = False
        exit_test()

    # Test each allowed port
    for port in ports:
        try:
            # Create a server side nc instance (IP is the standard docker0 IP)
            nc = pexpect.spawn("/bin/netcat -l 172.17.0.1 {}".format(port))
            conn.sendline("netcat -z -w 3 172.17.0.1 {}".format(port))
            conn.expect(PROMPT, 10)
            if conn.after != "0#":
                print("INFO: Failed to access port {}".format(port))
                passed = False
        except:
            passed = False
            pass
        finally:
            if nc is not None:
                nc.close()

    test_result("PORTS", passed)        
    return


### main ###
# Import our simple-firewall container image into Docker
import_image()

# Start our client and simple-firewall containers
start_simple_firewall()
start_client()

# Link the containers with a virtual network connection
link_containers()

# Setup the simple-firewall
setup_simple_firewall()
setup_client()

# Run the tests from the client container
print("INFO: Running tests...")
test_dhcp(client_conn)
test_dns(client_conn)
test_ports(client_conn)

# Manually control the containers (for debugging)
#sf_conn.interact('\x1c')
#client_conn.interact('\x1c')

# Cleanup and print results
exit_test()
