Using EC2 for Docker Based Deployments
======================================

The ``dallinger`` commandline tool has some helpers for managing EC2 instances
to help facilitate using Docker to deploy experiments on those instances (see
:doc:`docker_support`).


Initial Setup
-------------

Required AWS Permissions
~~~~~~~~~~~~~~~~~~~~~~~~


In order to run the ``dallinger ec2`` commands, your AWS user or role needs to
have the following permissions:

- ``AmazonEC2FullAccess``
- ``AmazonRoute53FullAccess``

See :doc:`aws_etc_keys` for more details.


Route53 DNS
~~~~~~~~~~~


If your lab is doing this for the first time, you probably need to acquire a
domain name for your experiment server. This is the parent URL that will be used
to host your experiments. If your lab already has a domain name, you can skip
this step. On the AWS online console, navigate to the Route 53 service. On the
Dashboard you can register a domain name. Note that different domain names come
with different costs, and that registering a domain name can take from a few
minutes to several hours. Before proceeding with the next steps, please wait
until the AWS console tells you that the registration is complete.

The examples below assume that you have setup a domain ``my-experiments.org`` in
Route53.

EC2 Security Group
~~~~~~~~~~~~~~~~~~

By default the ``dallinger ec2`` commands will provision instances with the
security group ``dallinger``. If that group does not exist, one will be created
with ingress rules (firewall rules for incoming traffic) that allow access to:

    * Port 22 (SSH) - for connecting to the server
    * Port 80 (HTTP) - for web traffic
    * Port 443 (HTTPS) - for secure web traffic
    * Port 5000 - for direct access to the Dallinger application

You can use an existing security group by setting the ``ec2_default_security_group``
value in your `~/.dallingerconfig` file.

EC2 SSH Key Pair (PEM File)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default the ``dallinger ec2`` commands will use an SSH key pair named
``dallinger`` to create instances. If that key pair does not exist you will need
to create one on AWS, download it, place it in your home folder and make it read only.

You need to configure **two** PEM-related settings for EC2 deployments:

1. **ec2_default_pem** - The name of the EC2 key pair (without the .pem extension)
2. **server_pem** - The full path to the local PEM file for SSH authentication

Example configuration in `~/.dallingerconfig`::

    [PEM files]
    ec2_default_pem = my-ec2-key
    server_pem = ~/.ssh/my-ec2-key.pem

The ``ec2_default_pem`` value specifies which EC2 key pair to associate with the instance
when provisioning. Dallinger will look for this key in ``~/.ssh/`` first (recommended),
then fall back to ``~/`` for backwards compatibility.

The ``server_pem`` value specifies the local private key file that will
be used for SSH authentication when connecting to the instance. It's recommended to
store this in ``~/.ssh/`` following standard SSH key management practices.

**Both configuration values are required** for EC2-based deployments. If either is missing
or if the PEM file doesn't exist at the specified path, the deployment will fail with an error message.

For more information, see the `AWS EC2 documentation on creating key pairs
<https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/create-key-pairs.html>`__.

**Supported SSH Key Types:**

AWS EC2 and Dallinger support the following key types:

* **RSA** (2048-bit or higher) - Most common and compatible. Generate with: ``ssh-keygen -t rsa -b 4096 -f ~/.ssh/my-key.pem``
* **Ed25519** - Modern and secure (recommended). Generate with: ``ssh-keygen -t ed25519 -f ~/.ssh/my-key.pem``
* **ECDSA** (256-bit or higher) - Modern and secure. Generate with: ``ssh-keygen -t ecdsa -b 521 -f ~/.ssh/my-key.pem``

Both PEM and OpenSSH private key formats are supported.

.. note::

    DSS/DSA keys are NOT supported. They have been deprecated industry-wide since 2015
    due to security weaknesses (limited to 1024-bit). AWS EC2 does not generate DSS keys.

AWS Region
----------

Except where noted, when ``--region`` is not specified then the
config value set in ``aws_region`` in e.g. ``~/.dallingerconfig`` will be used.


Provisioning an EC2 server instance
-----------------------------------

**Note**: If you decide to deploy to an EC2 instance, you need to "hire" the server
(Provisioning). Once you do that -- the clock is ticking and you will be charged
hourly until you release it (Teardown).

To provision an on-demand EC2 instance::

    dallinger ec2 provision --name <server_name> --region <region> --dns-host <subdomain>.my-experiments.org --type <type> --security_group_name <security_group>

Pick an instance name which is easy to recognize, for example
`tapping-deployment-batch-2` is good but `melody123` would be bad::

    dallinger ec2 provision --name tapping-deployment-batch-2 --region <region> --dns-host <subdomain>.my-experiments.org --type <type>

For example, if you want to collect data in Paris your command will include the
region name for Paris, like this::

    dallinger ec2 provision --name tapping-deployment-batch-2 --region eu-west-3 --dns-host <subdomain>.my-experiments.org --type <type>

Subdomain name should target your identity so it could be your own name. For
example::

    dallinger ec2 provision --name tapping-deployment-batch-2 --region eu-west-3 --dns-host elif.my-experiments.org --type <type>

You should use a different instance type according to your need. m7i.large is
recommended for debugging and m7i.xlarge is for deploying. For example::

    dallinger ec2 provision --name tapping_deployment_batch_2 --region eu-west-3 --dns-host elif.my-experiments.org --type m7i.large

You can configure different amounts of storage or different instance types::

    dallinger ec2 provision --name <server_name> --region <region> --storage 100 --type m5.2xlarge


Increasing Storage on An Instance
---------------------------------

You can increase the storage on a running instance by server name::

    dallinger ec2 increase-storage --name <server_name> --region <region> --storage 200

Or by DNS name::

    dallinger ec2 increase-storage --dns <subdomain>.my-experiments.org --region <region> --storage 200


Stopping and Starting
---------------------

You can temporarily stop a running instance to prevent it from incurring hourly
costs (while retaining its stored data)::

    dallinger ec2 stop --name <server_name> --region <region>
    dallinger ec2 stop --dns <subdomain>.my-experiments.org --region <region>

Similarly you can start a stopped instance::

    dallinger ec2 start --name <server_name> --region <region>
    dallinger ec2 start --dns <subdomain>.my-experiments.org --region <region>

Or restart a running instance::

    dallinger ec2 restart --name <server_name> --region <region>
    dallinger ec2 restart --dns <subdomain>.my-experiments.org --region <region>


Teardown an EC2 Instance
------------------------

**Important**: don't forget to export your data before you tear down the server.
If you don't all data is lost and there is NO way to retrieve them. Before you
teardown the instance make sure:

    * The experiment is stopped on the recruiter, e.g. in Prolific the experiment should be STOPPED and thus not active
    * Make sure you exported your data and run export.py to make sure your data is not faulty

To teardown an on-demand EC2 instance ny server name::

    dallinger ec2 teardown --name <server_name> --region <region>

Or by DNS name::

    dallinger ec2 teardown --dns <subdomain>.my-experiments.org --region <region>


Listing Available Regions and Instance Types
--------------------------------------------

You can list the available EC2 regions using::

    dallinger ec2 list regions

Different instance types may be available in different regions, you can list the
available instance types for a region using::

    dallinger ec2 list instance_types --region <region>


Listing Existing Instances
--------------------------

Dallinger provides some tools for introspecting your current EC2 resources. You can list all instances::

    dallinger ec2 list instances --region <region>

Or filter based on instance state::

    dallinger ec2 list instances --region <region> --running
    dallinger ec2 list instances --region <region> --stopped --terminated

The results will be filtered to show only instances using the key pair specified by
``ec2_default_pem`` (defaults to "dallinger" if not configured).

**Note**: If ``--region`` is not explicitly specified instances in all regions will be listed.


Connecting to a Container Running an Experiment
-----------------------------------------------

You can make an SSH connection to the docker container running the a specific
experiment using the server DNS name and the experiment app name with the
following command::

    dallinger ec2 ssh web --dns ubuntu@<subdomain>.my-experiments.org --app <subdomain>.my-experiments.org
