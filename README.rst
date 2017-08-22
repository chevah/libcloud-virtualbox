libcloud-virtualbox
###################

LibCloud driver for managing VirtualBox via the web service.

For now this is experimental code.

Unicode names and paths are not yet supported.

Tested only with VirtualBox 5.

Driver registration
===================


Prior to using this driver you will have to call::


    # Add the libcloud 3rd party driver for VirtualBox.
    set_driver(
        'virtualbox',
        'libcloud_virtualbox.virtualbox_driver',
        'VirtualBoxNodeDriver',
        )


Implementation details
======================

It is assumes that libcloud is the only tool used to manage the VMs.

For now, using the VirtualBox SDK there is no way to add meta-data to a
medium.


Nodes
-----

Nodes are created with a single SATA attached HDD.

The need the following data attached to them as extra data:

* libcloud_size: ID of the size with which they were created.

When a node is created from an image, the disk size and the initial credentials
are set via DMI.
In this way it should be possible to get them from any OS.
The other option is to pass them via guest properties, but the guest would
need the guest addition installed in order to retrieve them. 
In the future this might be implemented by passing an URL and then cloud-init
could to the rest.


Images
------

Images are simple HDD medium files.
They are not crated as appliances, since there is no way to register and list
available appliances.

Image should be create with the following informations in the name:

 * os-type - as listed in `vboxmanage list ostypes`
 * min-mem - minimum memory size in MB
 * min-disk - minimum disk size in GB
 * min-cpu - minimum cpu size

Ex: IMAGE-NAME-OS_TYPE-CPU-MEM-DISK

To register a new image you can run this command.
I could not found any other way to add a new medium.::

    vboxmanage showmediuminfo /PATH/TO/VOBX/images/IMAGE-FILE.vdi

When creating an image from an existing node, is up to the creator to encode
the required minimum CPU, DISK and MEM in the new image name.


Volumes
-------

Volumes are created with fixed size inside the 'volumes/' directory.


Node sizes
----------

It provides a fix set of VM sizes, based on the host's size.

There is an extra size with the ID as emptry string which is a placeholder
for VM which don't have a size attached.


TODO
====

* Add support for setting port forwarding for NAT.
* Add support for volume snapshots. In VirtualBox snapshots are directly
  associated to a machine and not to a volume.
  The VirtualBox Python SDK seems broken for getting the snapshots for an
  hard disk.


Testing
=======

Tests are designed to be run with a VirtualBox web service listening.

You will need:

* vbox web service on the same host on port 10083 with `null` authentication.
* vbox web service to run **as the same user** running the tests, so that
  the test can have access to the actual files.
* `vboxmanage` command to be available.
* A lot of disk space as the tests will create some images.

On Ubuntu you can run these commands, assuming that vboxweb.service runs
as `root`:

    VBoxManage setproperty websrvauthlibrary null
    sudo systemctl restart vboxweb.service

You can also set the `default` authentication method and update the username
and password inside the tests.

When running the test, the test medium and machines are created inside the
`test-tmp` folder.
When test are failing it is possible that the 

You can run all test via tox::

    tox -e py27-tests

Or some tests::

    tox -e py27-tests  -- --with-id 19


License
=======

The goal is to have the code under Apache-2.0, same license as apache-libcloud.
The current code uses the Oracle Virtualbox SDK which is under CDDL.
See COPYING.CDDL
