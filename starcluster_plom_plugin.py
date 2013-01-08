from starcluster import clustersetup
from starcluster.logger import log

plom_install_sh = '''
#!/bin/bash

#dep
apt-get install -y build-essential libgsl0-dev libjansson-dev python-sympy python-django libssl-dev curl python-software-properties

#zeroMQ (latest stable)
wget http://download.zeromq.org/zeromq-3.2.2.tar.gz
tar -zxvf zeromq-3.2.2.tar.gz
cd zeromq-3.2.2
./configure
make
make install
ldconfig
cd ..

#node (latest stable)

##from source
##wget http://nodejs.org/dist/v0.8.16/node-v0.8.16.tar.gz
##tar -zxvf node-v0.8.16.tar.gz
##cd node-v0.8.16
##./configure
##make
##make install
cd ..

#from PPA (faster)
add-apt-repository -y ppa:chris-lea/node.js
apt-get update
apt-get install -y nodejs npm

#plom-sfi
git clone https://github.com/plom/plom-sfi.git
cd plom-sfi

sed -ie "s/gcc-4.7/gcc/" install.sh
cd model_builder/C/core
sed -ie \"s/#define FLAG_VERBOSE \([0-9]*\)/#define FLAG_VERBOSE 0/\" plom.h
sed -ie \"s/#define FLAG_WARNING \([0-9]*\)/#define FLAG_WARNING 0/\" plom.h
cd ../../../

./install.sh
cd ../


#plom-fit
npm install -g plom-fit
'''

class PlomPlugin(clustersetup.DefaultClusterSetup):

    """
    Install PLoM and its dependencies in every node in parallel

    To use in .starcluster/config (assuming this file is called plom.py):
    [plugin plom_plugin]
    SETUP_CLASS = plom.PlomPlugin
    """

    def __init__(self):
        super(PlomPlugin, self).__init__()

    def run(self, nodes, master, user, user_shell, volumes):
        for node in nodes:
            self.pool.simple_job(node.ssh.execute, ("echo '%s' > plom_install.sh && chmod +x plom_install.sh && ./plom_install.sh" % plom_install_sh), jobid=node.alias)
            log.info("Installing plom on %s" % node.alias)

        self.pool.wait(len(nodes))
