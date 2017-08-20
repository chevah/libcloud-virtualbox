libcloud-virtualbox
###################

LibCloud driver for VirtualBox.

For not this is experimental code.

Unicode names and paths are not yet supported.

Tested only with VirtualBox 5.

It is assumes that libcloud is the only tool used to manage the VMs.

The target is to use it together with mist.io.

To keep the creation date for each VM, it will create a snapshot soon after
the VM is created.

Images are normal hard disk, stored in the 'images/' directory.
For now, using the VirtualBox SDK there is no way to add meta-data to a
medium.

Volumes are created with fixed size.

It provides a fix set of VM sizes, based on the host's size.


TODO
====

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

    tox -e py27-tests  -- \
        libcloud_virtualbox.test_virtualbox_driver:VirtualBoxNodeDriverTests


License
=======

The goal is to have the code under Apache-2.0, same license as apache-libcloud.
The current code uses the Oracle Virtualbox SDK which is under CDDL.
See COPYING.CDDL
