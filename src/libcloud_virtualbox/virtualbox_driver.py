"""
LibCloud compute driver for VirtualBox.
"""
from __future__ import unicode_literals

from contextlib import contextmanager
import ntpath
import posixpath

from libcloud.compute.base import (
    Node,
    NodeDriver,
    NodeImage,
    NodeLocation,
    NodeSize,
    StorageVolume,
    )
from libcloud.compute.providers import set_driver
from libcloud.compute.types import NodeState, StorageVolumeState
from ZSI import FaultException

from virtualbox_sdk import VirtualBoxManager


@contextmanager
def _session(vbox_manager, machine_id, lock_type=None):
    """
    A context manager which will lock the target machine and make sure the
    lock is released at the end.
    """
    if lock_type is None:
        lock_type = vbox_manager.constants.LockType_Shared

    target = vbox_manager.vbox.findMachine(machine_id)
    session = vbox_manager.platform.getSessionObject(vbox_manager.vbox)
    try:
        target.lockMachine(session, lock_type)
    except FaultException as error:
        if error.fault.string:
            raise RuntimeError(
                'Machine is already locked. '
                'If you are sure that nobody else is using it, '
                'you will need to break the lock by restarting the VirtualBox '
                'web service.'
                )
        else:
            raise error
    try:
        yield session
    finally:
        session.unlockMachine()


class VirtualBoxNodeDriver(NodeDriver):
    """
    Driver for VirtualBox via the web service API.
    """

    def __init__(self, host, port=18083, username='', password=''):
        options = {
            'url': 'http://%s:%s/' % (host, port),
            'user': username,
            'password': password,
            }

        self._vbox = VirtualBoxManager(
            sStyle='WEBSERVICE', dPlatformParams=options)

        # For remote connections vboxapi does the stupid thing of just
        # printing the exception without raising it.
        if self._vbox.vbox is None:
            raise RuntimeError(
                'Failed to connect to the web service. See logs.')

        self._host_cpu_count = int(
            self._vbox.vbox.getHost().getProcessorCount())
        self._host_memory_size = int(
            self._vbox.vbox.getHost().getMemorySize())

        self._vm_base_path = str(
            self._vbox.vbox.systemProperties.defaultMachineFolder)
        # Images are stored in the 'VBOX_DEFALT/images' directory.
        self._images_path = self._joinPath(self._vm_base_path, 'images')
        self._volumes_path = self._joinPath(self._vm_base_path, 'volumes')

    def _waitForProgress(self, progress):
        """
        Wait for `progress` to finalize.

        Return `True` if operation was successful.
        """
        while not progress.completed:
            progress.waitForCompletion(1000)
            self._vbox.waitForEvents(0)

        if int(progress.resultCode) != 0:
            error = progress.errorInfo
            if error:
                raise RuntimeError(
                    'Error in %s: %s' % (error.component, error.text))
            return False
        else:
            return True

    @contextmanager
    def _getMutableMachine(self, node):
        """
        A context manager for changing the settings of a machine.
        """
        if node.state != NodeState.STOPPED:
            raise RuntimeError('Only stopped machines can be reconfigured.')

        lock_type = self._vbox.constants.LockType_Write
        with _session(self._vbox, node.id, lock_type) as session:
            mutable = session.getMachine()
            yield mutable
            mutable.saveSettings()

    @contextmanager
    def _getConsole(self, node):
        """
        A context manager for getting the console of a machine.
        """
        with _session(self._vbox, node.id) as session:
            console = session.getConsole()
            yield console

    def _joinPath(self, *args):
        """
        Join the arguments as a path.
        """
        if '/' in args[0]:
            # NT don't usually contain '/', while Linux/Unix can have '\'.
            return posixpath.join(*args)
        else:  # pragma: no cover
            return ntpath.join(*args)

    def _getHardDisk(self, disk_id, read_only=False):
        """
        Return an IMedium for the hard disk with `disk_id`.
        """
        access_mode = self._vbox.constants.AccessMode_ReadWrite
        if read_only:
            access_mode = self._vbox.constants.AccessMode_ReadOnly

        return self._vbox.vbox.openMedium(
            disk_id,
            self._vbox.constants.DeviceType_HardDisk,
            access_mode,
            False,
            )

    def _deleteHardDisk(self, disk_id):
        """
        Delete the hard disk at location `medium_id`, which can be an ID or
        an path.
        """
        hdd = self._getHardDisk(disk_id)
        progress = hdd.deleteStorage()
        return self._waitForProgress(progress)

    #
    # Node management
    #

    def list_nodes(self):
        """
        List all nodes.

        :return:  list of node objects
        :rtype: ``list`` of :class:`.Node`
        """
        result = []
        for node in self._vbox.getArray(self._vbox.vbox, 'machines'):
            vbox_state = str(node.state)
            state = _get_libcloud_state(vbox_state)
            result.append(Node(
                id=str(node.id),
                name=str(node.name),
                state=state,
                public_ips=[],
                private_ips=[],
                driver=self,
                image=None,
                created_at=None,
                extra={'virtualbox_stat': vbox_state},
                ))
        return result

    def list_sizes(self, location=None):
        """
        List sizes on a provider

        :param location: The location at which to list sizes
        :type location: :class:`.NodeLocation`

        :return: list of node size objects
        :rtype: ``list`` of :class:`.NodeSize`
        """
        result = []
        for cpu_size in range(1, self._host_cpu_count + 1):
            for ram_size in range(256, self._host_memory_size, 256):
                for disk_size in [10, 30, 50, 100]:
                    name = '%s_cpu-%s_ram-%s_disk' % (
                        cpu_size, ram_size, disk_size)
                    result.append(NodeSize(
                        id=name,
                        name=name,
                        ram=ram_size,
                        disk=disk_size,
                        bandwidth=0,
                        price=0,
                        driver=self,
                        extra={'cpu': cpu_size}
                        ))
        return result

    def list_locations(self):
        """
        List data centers for a provider

        :return: list of node location objects
        :rtype: ``list`` of :class:`.NodeLocation`
        """
        # Virtualbox has no locations, so we return a single location which
        # represents the VirtualBox host.
        return [NodeLocation(
            id='virtualbox-location',
            name='VirtualBox Location',
            country='UN',
            driver=self,
            )]

    def create_node(self, **kwargs):
        """
        Create a new node instance. This instance will be started
        automatically.

        :return: The newly created node.
        :rtype: :class:`.Node`
        """

    def reboot_node(self, node):
        """
        Reboot a node.

        :param node: The node to be rebooted
        :type node: :class:`.Node`

        :return: True if the reboot was successful, otherwise False
        :rtype: ``bool``
        """
        with self._getConsole(node) as console:
            console.reset()
        return True

    def destroy_node(self, node):
        """
        Destroy a node.

        Depending upon the provider, this may destroy all data associated with
        the node, including backups.

        :param node: The node to be destroyed
        :type node: :class:`.Node`

        :return: True if the destroy was successful, False otherwise.
        :rtype: ``bool``
        """
        target = self._vbox.vbox.findMachine(node.id)
        try:
            disks = target.unregister(
                self._vbox.constants.CleanupMode_DetachAllReturnHardDisksOnly)
            progress = target.deleteConfig(list(disks))
            return self._waitForProgress(progress)
        except Exception as error:
            raise RuntimeError('Failed to destroy node. %s' % (error,))

    def ex_start_node(self, node):
        """
        Start the VM.

        It does not check that the node can be started.
        """
        target = self._vbox.vbox.findMachine(node.id)
        session = self._vbox.platform.getSessionObject(self._vbox.vbox)
        try:
            progress = target.launchVMProcess(session, 'headless', '')
            return self._waitForProgress(progress)
        finally:
            self._vbox.closeMachineSession(session)

    def ex_stop_node(self, node):
        """
        Stop the VM with a brute forced power down.
        """
        with self._getConsole(node) as console:
            console.powerDown()
        return True

    def ex_resize_node(self, node, plan_id):
        """
        Resize the node.
        """
        raise RuntimeError('Resize is not yet supported.')

    def ex_rename_node(self, node, name):
        """
        Rename the `node` to `name`.
        """
        with self._getMutableMachine(node) as mutable:
            mutable.setName(name.encode('utf-8'))
        return True

    ##
    # Volume and snapshot management methods
    ##

    def list_volumes(self):
        """
        List storage volumes.

        :rtype: ``list`` of :class:`.StorageVolume`
        """
        result = []
        for disk in self._vbox.getArray(self._vbox.vbox, 'hardDisks'):
            if str(disk.location).startswith(self._images_path):
                # This is an image, so we ignore it.
                continue

            # Size for libcloud is in GB.
            size = long(disk.logicalSize) / (1024 * 1000 * 1000)

            result.append(StorageVolume(
                id=str(disk.id),
                name=str(disk.name),
                size=int(size),
                state=StorageVolumeState.AVAILABLE,
                driver=self,
                extra={
                    'location': str(disk.location),
                    'actual_size': long(disk.size)
                    },
                ))
        return result

    def list_volume_snapshots(self, volume):
        """
        List snapshots for a storage volume.

        :rtype: ``list`` of :class:`VolumeSnapshot`
        """
        raise NotImplementedError(
            'list_volume_snapshots not implemented for this driver')

    def create_volume(self, size, name, location=None, snapshot=None):
        """
        Create a new volume.

        :param size: Size of volume in gigabytes (required)
        :type size: ``int``

        :param name: Name of the volume to be created
        :type name: ``str``

        :param location: Which data center to create a volume in. If
                               empty, undefined behavior will be selected.
                               (optional)
        :type location: :class:`.NodeLocation`

        :param snapshot:  Snapshot from which to create the new
                          volume.  (optional)
        :type snapshot: :class:`.VolumeSnapshot`

        :return: The newly created volume.
        :rtype: :class:`StorageVolume`
        """
        if snapshot is not None:
            raise NotImplementedError(
                'create_volume from a snapshot is not supported.')

        path = self._joinPath(self._volumes_path, name + '.vdi')
        disk = self._vbox.vbox.createMedium(
            'VDI',
            path,
            self._vbox.constants.AccessMode_ReadWrite,
            self._vbox.constants.DeviceType_HardDisk,
            )

        vbox_size = size * 1040.0 * 1000 * 1000
        progress = disk.createBaseStorage(
            vbox_size, (self._vbox.constants.MediumVariant_Fixed,))
        self._waitForProgress(progress)

        return StorageVolume(
            id=str(disk.id),
            name=str(disk.name),
            size=size,
            state=StorageVolumeState.AVAILABLE,
            driver=self,
            extra={
                'location': str(disk.location),
                'actual_size': long(disk.size)
                },
            )

    def create_volume_snapshot(self, volume, name=None):
        """
        Creates a snapshot of the storage volume.

        :param volume: The StorageVolume to create a VolumeSnapshot from
        :type volume: :class:`.VolumeSnapshot`

        :param name: Name of created snapshot (optional)
        :type name: `str`

        :rtype: :class:`VolumeSnapshot`
        """
        raise NotImplementedError(
            'create_volume_snapshot not implemented for this driver')

    def attach_volume(self, node, volume, device=None):
        """
        Attaches volume to node.

        :param node: Node to attach volume to.
        :type node: :class:`.Node`

        :param volume: Volume to attach.
        :type volume: :class:`.StorageVolume`

        :param device: Where the device is exposed, e.g. '/dev/sdb'
        :type device: ``str``

        :rytpe: ``bool``
        """
        target = self._vbox.vbox.findMachine(node.id)

        # Find the next free slot and the active controller.
        last_port = 0
        have_sata = False
        for attachment in target.getMediumAttachmentsOfController('IDE'):
            last_port = max(last_port, int(attachment.port))

        if last_port > 0:
            # This is an machine with an IDE controller, and it looks like
            # the controller is full.
            raise RuntimeError('IDE controller already full.')

        for attachment in target.getMediumAttachmentsOfController('SATA'):
            have_sata = True
            last_port = max(last_port, int(attachment.port))

        controller_name = 'IDE'
        if have_sata:
            controller_name = 'SATA'

        hdd = self._getHardDisk(volume.id)

        with self._getMutableMachine(node) as mutable:
            mutable.attachDevice(
                controller_name,
                last_port + 1,
                0,
                self._vbox.constants.DeviceType_HardDisk,
                hdd,
                )
        return True

    def detach_volume(self, volume):
        """
        Detaches a volume from a node.

        :param volume: Volume to be detached
        :type volume: :class:`.StorageVolume`

        :rtype: ``bool``
        """
        # To detach the volume, we search for the machine on which this
        # volume is attached, then search the medium attachments on that
        # machine to know the controller, port and device on which this
        # volume is attached.

        hdd = self._getHardDisk(volume.id)

        # There is a bug in VirtualBox SDK and instead of returning a list,
        # it return the string representation of the list.
        # We asssume that only a single machine is attached to this volume.
        node_id = str(hdd.getMachineIds()).strip("[']")
        target = self._vbox.vbox.findMachine(node_id)

        # Find the libcloude node.
        node = None
        for candidate_node in self.list_nodes():
            if candidate_node.id == node_id:
                node = candidate_node
                break

        all_attachments = (
            list(target.getMediumAttachmentsOfController('IDE')) +
            list(target.getMediumAttachmentsOfController('SATA'))
            )

        to_remove_attachment = None
        for attachment in all_attachments:
            if str(attachment.medium.id) == volume.id:
                to_remove_attachment = attachment
                break

        with self._getMutableMachine(node) as mutable:
            mutable.detachDevice(
                str(to_remove_attachment.controller),
                int(to_remove_attachment.port),
                int(to_remove_attachment.device),
                )
        return True

    def destroy_volume(self, volume):
        """
        Destroys a storage volume.

        :param volume: Volume to be destroyed
        :type volume: :class:`StorageVolume`

        :rtype: ``bool``
        """
        return self._deleteHardDisk(volume.id)

    def destroy_volume_snapshot(self, snapshot):
        """
        Destroys a snapshot.

        :param snapshot: The snapshot to delete
        :type snapshot: :class:`VolumeSnapshot`

        :rtype: :class:`bool`
        """
        raise NotImplementedError(
            'destroy_volume_snapshot not implemented for this driver')

    ##
    # Image management methods
    ##

    def list_images(self, location=None):
        """
        List images on a provider.

        :param location: The location at which to list images.
        :type location: :class:`.NodeLocation`

        :return: list of node image objects.
        :rtype: ``list`` of :class:`.NodeImage`
        """
        result = []
        for disk in self._vbox.getArray(self._vbox.vbox, 'hardDisks'):
            if not str(disk.location).startswith(self._images_path):
                continue

            result.append(NodeImage(
                id=str(disk.getId()),
                name=str(disk.getName()),
                driver=self,
                extra={'location': str(disk.location)},
                ))
        return result

    def create_image(self, node, name, description=None):
        """
        Creates an image from a node object.

        :param node: Node to run the task on.
        :type node: :class:`.Node`

        :param name: name for new image.
        :type name: ``str``

        :param description: description for new image.
        :type name: ``description``

        :rtype: :class:`.NodeImage`:
        :return: NodeImage instance on success.
        """
        target = self._vbox.vbox.findMachine(node.id)
        medium = None
        for attachment in target.getMediumAttachments():
            medium = attachment.getMedium()
            if not medium.isValid():
                continue
            if str(medium.format) != 'VDI':
                continue
            # We stop at the first valid HDD.
            break

        if not medium:
            raise RuntimeError('Node has no attached disk.')

        path = self._joinPath(self._images_path, name + '.vdi')
        target = self._vbox.vbox.createMedium(
            'VDI',
            path,
            self._vbox.constants.AccessMode_ReadWrite,
            self._vbox.constants.DeviceType_HardDisk,
            )

        variant = (self._vbox.constants.MediumVariant_Standard,)
        progress = medium.cloneToBase(target, variant)
        self._waitForProgress(progress)

        return NodeImage(
            id=str(target.id),
            name=str(target.name),
            driver=self,
            extra={'location': str(target.location)},
            )

    def delete_image(self, node_image):
        """
        Deletes a node image from a provider.

        :param node_image: Node image object.
        :type node_image: :class:`.NodeImage`

        :return: ``True`` if delete_image was successful, ``False`` otherwise.
        :rtype: ``bool``
        """
        return self._deleteHardDisk(node_image.id)

    def get_image(self, image_id):
        """
        Returns a single node image from a provider.

        :param image_id: ID of the image to be retrieved.
        :type image_id: ``str``

        :rtype :class:`.NodeImage`:
        :return: NodeImage instance on success.
        """
        disk = self._getHardDisk(image_id, read_only=True)
        return NodeImage(
            id=str(disk.id),
            name=str(disk.name),
            driver=self,
            extra={'location': str(disk.location)},
            )

    def copy_image(self, source_region, node_image, name, description=None):
        """
        Copies an image from a source region to the current region.
        """
        # VirtualBox has no regions, so there is no need to copy images.
        raise NotImplementedError(
            'copy_image not implemented for this driver.')


def _get_libcloud_state(vbox_state):
    """
    Convert from VirtualBox state to LibCloud state.

    See SDK -> 6.63 MachineState.

    VirtualBox states:
        PoweredOff
        Starting
        Aborted
        Running
        Paused
        Saved
        Restoring
        OnlineSnapshotting
        Saving
        Stopping

    LibCloud states:
        RUNNING: Node is running.
        STARTING: Node is starting up.
        REBOOTING: Node is rebooting.
        TERMINATED: Node is terminated. This node can't be started later on.
        STOPPING: Node is currently trying to stop.
        STOPPED: Node is stopped. This node can be started later on.
        PENDING: Node is pending.
        SUSPENDED: Node is suspended.
        ERROR: Node is an error state. Usually no operations can be performed
                     on the node once it ends up in the error state.
        PAUSED: Node is paused.
        RECONFIGURING: Node is being reconfigured.
        UNKNOWN: Node state is unknown.
    """
    mapping = {
        'poweredoff': NodeState.STOPPED,
        'starting': NodeState.STARTING,
        'aborted': NodeState.ERROR,
        'stuck': NodeState.ERROR,
        'running': NodeState.RUNNING,
        'paused': NodeState.PAUSED,
        'saved': NodeState.PAUSED,
        'restoring': NodeState.RECONFIGURING,
        'settingup': NodeState.RECONFIGURING,
        'onlinesnapshotting': NodeState.RECONFIGURING,
        'saving': NodeState.RECONFIGURING,
        'stopping': NodeState.STOPPING,
        'firstonline': NodeState.RUNNING,
        'lastonline': NodeState.RUNNING,
        'teleported': NodeState.STOPPED,
        }
    return mapping.get(vbox_state.lower(), NodeState.UNKNOWN)


# Add the libcloud 3rd party driver for VirtualBox.
set_driver(
    'virtualbox',
    'libcloud_virtualbox.virtualbox_driver',
    'VirtualBoxNodeDriver',
    )
