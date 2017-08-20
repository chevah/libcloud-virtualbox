"""
Tests for the libcloud VirtualBox driver.

It uses the external `vboxmanage` command to arrange the testing environment.

When things are breaking check the VirtualBox state using an external tool,
and make sure you don't have any VM or mediums starting with 'test-' name.
"""
from __future__ import unicode_literals
import os
import subprocess
import time

import unittest

from libcloud.compute.base import (
    Node,
    NodeImage,
    NodeLocation,
    NodeSize,
    StorageVolume,
    )
from libcloud.compute.types import NodeState, StorageVolumeState

from libcloud_virtualbox.virtualbox_driver import VirtualBoxNodeDriver

USERNAME = ''
PASSWORD = ''


def _create_disk(path, size=1):
    """
    Create a disk medium and return it's UUID.
    """
    target_path = os.path.join(*path)
    try:
        output = subprocess.check_output([
            'vboxmanage', 'createmedium', 'disk',
            '--size', str(size),
            '--filename', target_path,
            ],
            stderr=subprocess.STDOUT,
            )
    except subprocess.CalledProcessError as error:  # pragma: no cover
        if 'VERR_ALREADY_EXISTS' in error.output:
            _delete_disk(*path)
        raise AssertionError(
            'Failed to create medium. %s' % (error.output))

    parts = output.strip().split('Medium created. UUID: ', 1)
    return parts[1]


def _delete_disk(*path):
    """
    Delete a disk medium from `path`.
    """
    target_path = os.path.join(*path)
    try:
        subprocess.check_output([
            'vboxmanage', 'closemedium', 'disk', target_path, '--delete'],
            stderr=subprocess.STDOUT,
            )
    except subprocess.CalledProcessError as error:  # pragma: no cover
        raise AssertionError(
            'Failed to delete medium. %s' % (error.output))


def _create_machine(name, medium_id):
    """
    Create a new VM attacehd to storage `medium_id`.
    """
    base_folder = os.path.abspath(os.path.join('test-tmp', 'vm'))
    output = subprocess.check_output([
        'vboxmanage', 'createvm', '--register',
        '--name', name,
        '--basefolder', base_folder,
        ])
    uuid = output.splitlines()[1].strip('UUID: ')

    subprocess.check_output([
        'vboxmanage', 'storagectl', uuid, '--name', 'SATA',
        '--add', 'sata', '--controller', 'IntelAHCI',
        ])

    if medium_id is not None:
        subprocess.check_output([
            'vboxmanage', 'storageattach', uuid, '--storagectl', 'SATA',
            '--port', '0', '--device', '0', '--type', 'hdd',
            '--medium', medium_id,
            ])
    return uuid


def _delete_machine(uuid):
    """
    Unregister and delete a VM, without deleting the attached storage.
    """

    # Force stopping the VM, and ignore if already stoped.
    try:
        subprocess.check_output([
            'vboxmanage', 'controlvm', uuid, 'poweroff'],
            stderr=subprocess.STDOUT,
            )
    except subprocess.CalledProcessError as error:  # pragma: no cover
        output = error.output
        if 'is not currently running' not in output:
            raise AssertionError('Failed to stop the machine: %s' % (output,))

    try:
        subprocess.check_output([
            'vboxmanage', 'unregistervm', uuid, '--delete'],
            stderr=subprocess.STDOUT,
            )
    except subprocess.CalledProcessError as error:  # pragma: no cover
        output = error.output
        if 'is being powered down' in output:
            time.sleep(2)
            _delete_machine(uuid)
            return
        raise AssertionError('Failed to delete machine. %s' % (output,))


class VirtualBoxNodeDriverTests(unittest.TestCase):
    """
    Tests for VirtualBoxNodeDriver.
    """

    @classmethod
    def setUpClass(cls):
        cls.sut = VirtualBoxNodeDriver('localhost', 18083, USERNAME, PASSWORD)
        # Inject testing paths.
        cls.sut._images_path = os.path.abspath(os.path.join(
            'test-tmp', 'images'))
        cls.sut._volumes_path = os.path.abspath(os.path.join(
            'test-tmp', 'volumes'))

    @classmethod
    def tearDownClass(cls):
        leftover_files = []
        for root, dirs, files in os.walk('test-tmp', topdown=False):
            for name in files:  # pragma: no cover
                target = os.path.join(root, name)
                leftover_files.append(target)
                os.remove(target)
            for name in dirs:  # pragma: no cover
                target = os.path.join(root, name)
                os.rmdir(target)

        if leftover_files:  # pragma: no cover
            raise AssertionError(
                'Leftover files found: %s' % (leftover_files,))

    def addImage(self, name, cleanup=True):
        """
        Add a testing image and register for cleanup.
        """
        uuid = _create_disk(['test-tmp', 'images', name])
        if cleanup:
            self.addCleanup(_delete_disk, uuid)
        return uuid

    def addVolume(self, name, size=1, cleanup=True):
        """
        Add a testing volume and register for cleanup.
        """
        uuid = _create_disk(['test-tmp', 'volumes', name], size=size)
        if cleanup:
            self.addCleanup(_delete_disk, uuid)
        return uuid

    def addMachine(self, name, no_volume=False, cleanup=True):
        """
        Add a new virtual machine and register it for cleanup.
        """
        # Removing the machine will also remove the disk, so we don't
        # clean it.
        if no_volume:
            medium_id = None
        else:
            medium_id = self.addVolume(
                'test-hdd-for-%s' % (name,), cleanup=False)
        uuid = _create_machine(name, medium_id)

        if cleanup:
            self.addCleanup(_delete_machine, uuid)
        return uuid

    def getNode(self, node_id):
        """
        Return an existing Node by id or None if not found.
        """
        try:
            return next(  # pragma: no cover
                n for n in self.sut.list_nodes() if n.id == node_id)
        except StopIteration:
            return None

    def getVolume(self, volume_id):
        """
        Return an existing volume by id.
        """
        return next(  # pragma: no cover
            v for v in self.sut.list_volumes() if v.id == volume_id)

    def test_init_bad_connection(self):
        """
        It will raise an exception when the connection failed.
        """
        with self.assertRaises(RuntimeError) as context:
            VirtualBoxNodeDriver('127.0.0.1', 12345, '', '')

        self.assertEqual(
            'Failed to connect to the web service. See logs.',
            context.exception.args[0])

    def test_list_sizes(self):
        """
        Returns a list of `NodeSize`.
        """
        sizes = self.sut.list_sizes()

        self.assertIsInstance(sizes[0], NodeSize)
        self.assertIs(self.sut, sizes[0].driver)
        # Do a simple check for a size which can be found on any host.
        names = [size.name for size in sizes]
        self.assertIn('1_cpu-256_ram-30_disk', names)

    def test_list_locations(self):
        """
        Return a list with a single `NodeLocation`.
        """
        locations = self.sut.list_locations()

        self.assertEqual(1, len(locations))
        self.assertIsInstance(locations[0], NodeLocation)
        self.assertIs(self.sut, locations[0].driver)
        self.assertEqual('virtualbox-location', locations[0].id)
        self.assertEqual('VirtualBox Location', locations[0].name)

    def test_list_images(self):
        """
        It return a list of `NodeImage`.
        """
        # Create some testing images and volumes.
        uuid1 = self.addImage('libcloud_virtualbox_test-img1.vdi')
        uuid2 = self.addImage('libcloud_virtualbox_test-img2.vdi')

        images = self.sut.list_images()
        self.assertEqual(2, len(images))

        self.assertIsInstance(images[0], NodeImage)
        self.assertIs(self.sut, images[0].driver)
        actual_ids = [image.id for image in images]
        self.assertItemsEqual([uuid1, uuid2], actual_ids)
        actual_names = [image.name for image in images]
        self.assertItemsEqual([
            'libcloud_virtualbox_test-img1.vdi',
            'libcloud_virtualbox_test-img2.vdi',
            ], actual_names)
        self.assertTrue(os.path.exists(images[0].extra['location']))

    def test_get_image(self):
        """
        Return a NodeImage for a requested ID.
        """
        uuid = self.addImage('test-get-image')

        result = self.sut.get_image(uuid)

        self.assertIsInstance(result, NodeImage)
        self.assertIs(self.sut, result.driver)
        self.assertEqual(uuid, result.id)
        self.assertEqual('test-get-image.vdi', result.name)
        self.assertTrue(os.path.exists(result.extra['location']))

    def test_delete_image(self):
        """
        It will unregister and remove the image from disk.
        """
        uuid = self.addImage('test-delete-image', cleanup=False)
        image = self.sut.get_image(uuid)

        try:
            result = self.sut.delete_image(image)
        except:  # pragma: no cover
            # If there are any errors, do a desperate cleanup.
            _delete_disk(uuid)
            raise

        self.assertTrue(result)
        self.assertFalse(os.path.exists(image.extra['location']))

    def test_create_image(self):
        """
        It creates an image from an existing node.
        """
        # First create the target machine.
        new_name = 'test-create-image'
        node_id = self.addMachine('test-create-image-vm')
        existing_node = self.getNode(node_id)

        result = self.sut.create_image(existing_node, new_name)

        self.assertIsInstance(result, NodeImage)
        self.assertIs(self.sut, result.driver)
        self.assertEqual('test-create-image.vdi', result.name)
        image_ids = [i.id for i in self.sut.list_images()]
        self.assertIn(result.id, image_ids)
        self.assertTrue(os.path.exists(result.extra['location']))
        # Cleaunp the image.
        self.sut.delete_image(result)

    def test_create_image_node_without_volume(self):
        """
        It fails to create an image when node has no attached volumes.
        """
        node_id = self.addMachine(
            'test-create_image_node_without_volume', no_volume=True)
        existing_node = self.getNode(node_id)

        with self.assertRaises(RuntimeError) as context:
            self.sut.create_image(existing_node, 'some-name')

        self.assertEqual(
            'Node has no attached disk.', context.exception.args[0])

    def test_copy_image(self):
        """
        It doesn't support copying an image.
        """
        with self.assertRaises(NotImplementedError) as context:
            self.sut.copy_image(
                source_region='some-mock-region',
                node_image='some-mock-image',
                name='test_copy_image',
                )

        self.assertEqual(
            'copy_image not implemented for this driver.',
            context.exception.args[0])

    def test_list_volumes(self):
        """
        It return a list of `StorageVolume`, ignoring images.
        """
        self.addImage('test-list_volumes-image.vdi')
        uuid1 = self.addVolume('libcloud_virtualbox_test-vol1.vdi', size=2000)
        uuid2 = self.addVolume('libcloud_virtualbox_test-vol2.vdi')
        uuid3 = self.addVolume('libcloud_virtualbox_test-vol3.vdi')

        volumes = self.sut.list_volumes()

        self.assertIsInstance(volumes[0], StorageVolume)
        actual_uuids = [v.id for v in volumes]
        self.assertIn(uuid1, actual_uuids)
        self.assertIn(uuid2, actual_uuids)
        self.assertIn(uuid3, actual_uuids)
        volume_1 = self.getVolume(uuid1)
        self.assertEqual(2, volume_1.size)
        self.assertEqual(StorageVolumeState.AVAILABLE, volume_1.state)

    def test_create_volume(self):
        """
        It created a volume and returns it as `StorageVolume`.
        """
        volume = self.sut.create_volume(size=1, name='test-create-volume')
        self.addCleanup(_delete_disk, volume.id)

        self.assertIsInstance(volume, StorageVolume)
        self.assertEqual('test-create-volume.vdi', volume.name)
        self.assertEqual(1, volume.size)
        # It is available in the list of volumes.
        volumes = self.sut.list_volumes()
        uuids = [v.id for v in volumes]
        self.assertIn(volume.id, uuids)

    def test_create_volume_with_snapshot(self):
        """
        It doesn't support creating a volume from an snapshot.
        """
        with self.assertRaises(NotImplementedError) as context:
            self.sut.create_volume(
                size=1,
                name='test-create_volume_with_snapshot',
                snapshot='some-mocked-snapshot',
                )

        self.assertEqual(
            'create_volume from a snapshot is not supported.',
            context.exception.args[0])

    def test_destroy_volume(self):
        """
        It unregister and removes a volume.
        """
        volume = self.sut.create_volume(size=1, name='test-destroy-volume')
        self.assertTrue(os.path.exists(volume.extra['location']))

        result = self.sut.destroy_volume(volume)

        self.assertTrue(result)
        # Is is no longer in the list.
        volumes = self.sut.list_volumes()
        uuids = [v.id for v in volumes]
        self.assertNotIn(volume.id, uuids)
        # File was removed.
        self.assertFalse(os.path.exists(volume.extra['location']))

    def test_attach_volume_detach_volume(self):
        """
        It can attach and detach an volume to an existing node.
        """
        node_id = self.addMachine('test-attach-volume')
        node = self.getNode(node_id)
        volume_id = self.addVolume('test-attach-volume-target')
        volume = self.getVolume(volume_id)

        result = self.sut.attach_volume(node, volume)

        self.assertTrue(result)

        result = self.sut.detach_volume(volume)

        self.assertTrue(result)

    def test_list_nodes(self):
        """
        It returns a list of `Node`.
        """
        node_id = self.addMachine('test-list_nodes')

        result = self.sut.list_nodes()

        self.assertIsInstance(result[0], Node)
        self.assertIs(self.sut, result[0].driver)
        actual_uuids = [n.id for n in result]
        self.assertIn(node_id, actual_uuids)
        node = self.getNode(node_id)
        self.assertEqual('test-list_nodes', node.name)
        self.assertEqual(NodeState.STOPPED, node.state)

    def test_destroy_node(self):
        """
        It will remove the node together with its volumes.
        """
        node_id = self.addMachine('test-destroy_node', cleanup=False)
        node = self.getNode(node_id)

        result = self.sut.destroy_node(node)

        self.assertTrue(result)
        # We check that node is removed. The actual file removal checks are
        # done by the teardown.
        node = self.getNode(node_id)
        self.assertIsNone(node)

    def test_ex_rename_node(self):
        """
        It can rename a stopped node.
        """
        node_id = self.addMachine('test-ex_rename_node')
        node = self.getNode(node_id)
        self.assertEqual('test-ex_rename_node', node.name)
        self.assertEqual(NodeState.STOPPED, node.state)

        result = self.sut.ex_rename_node(node, 'test-ex_rename_node-renamed')

        self.assertTrue(result)
        node = self.getNode(node_id)
        self.assertEqual('test-ex_rename_node-renamed', node.name)

    def test_ex_rename_node_running(self):
        """
        It can't rename a running node.
        """
        node_id = self.addMachine('test-ex_rename_node_running')
        node = self.getNode(node_id)
        self.sut.ex_start_node(node)
        node = self.getNode(node_id)
        self.assertEqual(NodeState.RUNNING, node.state)

        with self.assertRaises(RuntimeError) as context:
            self.sut.ex_rename_node(
                node, 'test-ex_rename_node_running-renamed')

        self.assertEqual('', context.exception.arg[0])

    def test_ex_start_node_ex_stop_node_reboot_node(self):
        """
        It will start and stop a node.
        """
        node_id = self.addMachine('test-ex_start_node_ex_stop_node')
        node = self.getNode(node_id)
        self.assertEqual(NodeState.STOPPED, node.state)

        # Start it.
        result = self.sut.ex_start_node(node)

        self.assertTrue(result)
        node = self.getNode(node_id)
        self.assertEqual(NodeState.RUNNING, node.state)

        # Reboot it.
        result = self.sut.reboot_node(node)
        self.assertTrue(result)
        # Reboot is instant
        node = self.getNode(node_id)
        self.assertEqual(NodeState.RUNNING, node.state)

        # Stop it.
        result = self.sut.ex_stop_node(node)

        self.assertTrue(result)
        node = self.getNode(node_id)
        self.assertEqual(NodeState.STOPPING, node.state)
        # Wait for it to stop.
        time.sleep(2)
        node = self.getNode(node_id)
        self.assertEqual(NodeState.STOPPED, node.state)
