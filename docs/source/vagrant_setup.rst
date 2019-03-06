Vagrant Installation
====================

Install the Vagrant virtual machine management system from `Hashicorp
<https://www.vagrantup.com/docs/installation/>`__ and the `VirtualBox
<https://www.virtualbox.org/>`__ virtualization software.

Once you've installed Vagrant, install the `vbguest` plugin using the command:

::

    vagrant plugin install vagrant-vbguest

If you already use a different Virtual Machine provider, it may be compatible
with Vagrant, in which case you may need to modify the ``Vagrantfile``. This
method is not recommended.

Starting Dallinger
------------------

The first time you start the virtual machine, Vagrant will download an Ubuntu Linux image and run installation steps. This will take some time and downloads a large amount of data through the internet connection.


In your terminal/command prompt, navigate to the directory that contains the ``Vagrantfile`` and begin the process with the following command:

::

    vagrant up

You can then connect to the vagrant machine over ssh and interact with Dallinger. This is done through:

::

    vagrant ssh

You will be in the ``/vagrant`` directory which is shared with the host machine. You can use Dallinger and run tests as usual from this prompt. When running an experiment, you should specify port 5000 as the experiment's port, which will then be made available to the host on port 5000.

When you're finished, shut the Vagrant machine down by running:

::

    vagrant halt

New experiments created using the `cookiecutter` template described in
:doc:`Creating an Experiment <creating_an_experiment>`
include a ``Vagrantfile`` which will setup a virtual machine configured to run
your new Dallinger experiment. The Dallinger demos package also includes a
``Vagrantfile``.
