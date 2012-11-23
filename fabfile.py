import sys
import time
import boto
import os
from fabric.api import *
from fabric.contrib.console import confirm
import fabric.contrib.files

env.user = 'ubuntu'
env.key_filename = os.getenv("HOME") + '/test_key.pem'

DNS_PATH = os.getenv("HOME") + "/my_ec2_cluster.txt"
RETRIEVE_PATH = os.getenv("HOME") + '/'


##################################################
##starting instances
##################################################

def update_instances(reservation_id):
    """return an updated list of instances for a given reservation_id"""

    ec2 = boto.connect_ec2()

    for r in ec2.get_all_instances():
        if r.id == reservation_id:
            reservation = r
            return reservation.instances

    return []


def start(N, path=DNS_PATH, append=False, instance_type='cc2.8xlarge', image_id='ami-98fa58f1'):
#def start(N, path=DNS_PATH, append=False, instance_type='t1.micro', image_id='ami-a29943cb'):
    """start a cluster of N nodes and write public dns in path
    if append=True, N nodes will be added to the current cluster
    """

    N = int(N) #N from fabric is a string...

    placement_group = 'sfi_high_io' if 'cc' in instance_type else None

    ec2 = boto.connect_ec2()
    reservation = ec2.run_instances(image_id=image_id,
                                    key_name='test_key',
                                    min_count=N,
                                    max_count=N,
                                    instance_type=instance_type,
                                    security_groups=['test_zmq'],
                                    placement_group=placement_group,
                                    user_data = """#!/bin/bash
                                    apt-get update
                                    apt-get install -y build-essential libgsl0-dev libjansson-dev libzmq-dev emacs htop
                                    """)

    print('reservation id: ' + reservation.id)
    time.sleep(10)

    ##reservation only contain the id. we wait that the instances fire up...
    while len(update_instances(reservation.id)) != N:
        print('waiting for the {0} instances (currently {1})'.format(N, ','.join([i.id for i in reservation.instances])))
        time.sleep(10)

    while not all(map(lambda x: x.update()=='running', reservation.instances)):
        print('waiting for all instances to be in a "running" state'.format(N))
        print('\n'.join(['{0}: {1}'.format(i.id, i.state) for i in reservation.instances]))
        time.sleep(10)

    print('All instances are running!\n writing public dns in file: {0}'.format(path))

    with open(path, 'a' if append else 'w') as f:
        for i in reservation.instances:
            env.hosts.append(i.public_dns_name)
            f.write(i.public_dns_name + '\n')


##################################################
####cluster, workers, new and master are used to set env.hosts variable
##################################################

def cluster(path=DNS_PATH):
    """update the env dict with the public dns contained in DNS_PATH"""
    env.hosts = [line.strip() for line in open(path)]


def workers(path=DNS_PATH):
    """update the env dict with the public dns of the workers contained in DNS_PATH"""

    dns = [line.strip() for line in open(path)]
    if len(dns) ==1 :
        print('your cluster only have a master node, add nodes for workers')
    else:
        env.hosts = dns[1:]

def new(path=DNS_PATH, N=1):
    """update the env dict with the public dns of N workers recently added (N last lines of DNS_PATH)"""

    N = int(N)
    dns = [line.strip() for line in open(path)]
    if len(dns) < (N+1) :
        print('wrong N!')
    else:
        env.hosts = dns[-N:]



def master(path=DNS_PATH):
    """update the env dict with the public dns of the master node contained in DNS_PATH"""
    dns = [line.strip() for line in open(path)]
    env.hosts = [ dns[0] ]



##################################################
##doing work...
##################################################


@parallel
def deploy(path_tar_gz):
    """
    install plom (get the sources and compile...)
    usage: fab cluster deploy or fab new deploy. fab cluster or new fill the env.hosts list
    """

    mytargz = os.path.split(path_tar_gz)[1]
    mydir = mytargz.split('.')[0]

    if fabric.contrib.files.exists('/home/ubuntu/'+mydir+'/'):
        run('rm -rf /home/ubuntu/'+mydir+'/')

    with cd('/home/ubuntu/'):
        put(path_tar_gz, '.')
        run('tar -zxvf {0}'.format(mytargz))

    with cd('/home/ubuntu/{0}/src/sh/'.format(mydir)):
        run('chmod +x compile.sh')
        run('./compile.sh')



@parallel
def run_cmd(cmd, remote_dir):
    """run a cmd on the remote dir remote_dir. This function has to be called
    after worker or master depending on which nodes it has to be
    executed.
    usage: fab master run_cmd... (e.g fab master run_cmd:'./smc_zmq -J 10 -C 1 -P 1 < ../settings.json',hfmdJ)
    or
    fab workers run_cmd... (e.g fab workers run_cmd:'./sfi_worker_deter -J 1 -P 1 -I ec2-23-20-44-111.compute-1.amazonaws.com < ../settings.json',hfmdJ)"""

    with cd('/home/ubuntu/{0}/bin/'.format(remote_dir)):
        ##we wrap cmd within a bash script sfiprog to avoid issues with io redirection
        run('echo -e "#!/bin/bash\ncd /home/ubuntu/{0}/bin/\n{1}\n" > sfiprog ; chmod +x sfiprog'.format(remote_dir, cmd))
        run('screen -d -m -S sfi "./sfiprog"; sleep 5') ##the secret is to slep
        ##the sleep can be fragile. Another solution is to start the instance with a screen session and write command to it with:
        ##screen -S <session-name> -p 0 -X stuff <command> ##note that stuff is a keyword
        ##The keys there are "stuff" and the -p 0 part. The latter selectes the window in which to write the command. If you don't specify it, it doesn't work unless you have already connected to the screen session.



@parallel
def reboot():
    """reboot now!"""

    sudo('reboot')


@parallel
def ps():
    """report the status of workers
    usage: fab workers ps
    """

    with settings(warn_only=True):
        with hide('running', 'warnings'):
            run('ps -A | grep -i sfi_worker | grep -v grep')

@parallel
def killall(cmd='sfi_worker_*'):
    """killall
    usage: fab workers killall
    """

    with settings(warn_only=True):
        with hide('running', 'warnings'):
            run('killall '+ cmd)



def retrieve(model_dir, local_path=RETRIEVE_PATH):
    """usage: fab master retrieve..."""

    with cd('/home/ubuntu/'):
        run('tar -zcvf {0}.tar.gz {0}'.format(model_dir))

    get('/home/ubuntu/{0}.tar.gz'.format(model_dir), local_path)




##################################################
##terminating instances
##################################################


def terminate(path=DNS_PATH):
    """terminate instances whose public dns are in path"""

    ec2 = boto.connect_ec2()
    dns = [line.strip() for line in open(path)]

    ids = []
    ##create list of our instances whose public dns are in dns
    for reservation in ec2.get_all_instances():
        for i in reservation.instances:
            if i.public_dns_name in dns:
                ids.append(i.id)

    ##terminate the instance listed in ids
    ec2.terminate_instances(instance_ids=ids)



##################################################
#global control of the plom AWS account
##################################################

def terminate_all():
    """terminate **all** the plom AWS account instances"""

    ec2 = boto.connect_ec2()
    ids = []
    for reservation in ec2.get_all_instances():
        for i in reservation.instances:
            ids.append(i.id)

    ec2.terminate_instances(instance_ids=ids)


def get_all_state():
    """get the state of **all** the plom AWS account instances"""
    ec2 = boto.connect_ec2()
    for reservation in ec2.get_all_instances():
        print('instances of reservation ' + reservation.id + ':')
        for i in reservation.instances:
            print(i.id + ' :' + i.state)


def get_all_dns():
    """get the public dns of **all** the plom AWS account instances"""
    env.hosts = []
    ec2 = boto.connect_ec2()

    for reservation in ec2.get_all_instances():
        for i in reservation.instances:
            if i.public_dns_name:
                print i.id + ' :' + i.public_dns_name
                env.hosts.append(i.public_dns_name)
