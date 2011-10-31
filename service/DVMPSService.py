import time
import subprocess
import shutil
import os
import uuid
import random
import DVMPSDAO
import libvirt
import xml.dom.minidom as minidom
import logging
import sys

class DVMPSService():
    def __init__(self, database=None):
        self.database = database
        self.logger = logging.getLogger('dvmps')

    def __cloned_disk_image_path(self, image_id):
        return '/var/lib/libvirt/images/active_dynamic/%s.img' % image_id

    def __cloned_xml_definition_path(self, image_id):
        return '/var/lib/libvirt/qemu/active_dynamic/%s.xml' % image_id

    def __base_disk_image_path(self, filename):
        return '/var/lib/libvirt/images/base/%s' % filename

    def __base_xml_template_path(self, filename):
        return '/var/lib/libvirt/qemu/templates/%s' % filename

    def __get_vnc_port(self, image_id):
        port = None
        try:
            connection = libvirt.openReadOnly(None)
            if connection is not None:
                domain = connection.lookupByName(image_id)
                if domain is not None:
                    xmlspec = domain.XMLDesc(0)
                    dom = minidom.parseString(xmlspec)
                    nodes = dom.getElementsByTagName('graphics')
                    for node in nodes:
                        port_candidate = node.getAttribute('port')
                        if port_candidate is not None and port_candidate != '':
                            port = str(port_candidate)
                else:
                    self.logger.error("__get_vnc_port(%s): no such domain" % (image_id,))
            else:
                self.logger.error("__get_vnc_port(%s): no libvirt connection" % (image_id,))
        except:
            self.logger.error("__get_vnc_port(%s) exception: %s" % (image_id, str(sys.exc_info()[1]))) 
        return port

    def __create_image(self, image_id):
        retval = False
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)
        bim = DVMPSDAO.BaseImages(dbc)
        mip = DVMPSDAO.MacIpPairs(dbc)

        allocated_image_conf = ali.get_configuration(image_id)
        if allocated_image_conf is not None and allocated_image_conf.has_key('base_image_id') and allocated_image_conf.has_key('mac_id'):
            full_path_base_image_file = None
            full_path_xml_template_file = None
            mac = None

            base_image_conf = bim.get_base_image_configuration(allocated_image_conf['base_image_id'])
            if base_image_conf is not None and base_image_conf.has_key('base_image_file') and base_image_conf.has_key('configuration_template'):
                full_path_base_image_file = self.__base_disk_image_path(base_image_conf['base_image_file'])
                full_path_xml_template_file = self.__base_xml_template_path(base_image_conf['configuration_template'])

            if allocated_image_conf.has_key('mac_id'):
                mac = mip.get_mac_for_mac_id(allocated_image_conf['mac_id'])

            if full_path_base_image_file is not None and full_path_xml_template_file is not None and mac is not None:
                if subprocess.call(['qemu-img', 'create', '-b', full_path_base_image_file, '-f', 'qcow2', self.__cloned_disk_image_path(image_id)]) == 0:
                    f = open(full_path_xml_template_file, 'r')
                    xmlspec = f.read()
                    f.close()
                    xmlspec = xmlspec.replace('$(VM_ID)', image_id)
                    xmlspec = xmlspec.replace('$(IMAGE_FILE)', self.__cloned_disk_image_path(image_id))
                    xmlspec = xmlspec.replace('$(MAC_ADDRESS)', mac)
                    f = open(self.__cloned_xml_definition_path(image_id), 'w')
                    f.write(xmlspec)
                    f.close()
                    retval = True
                    self.logger.info("__create_image(%s): image successfully created" % (image_id,))
                else:
                    self.logger.error("__create_image(%s): qemu-img failed to create new overlay image" % (image_id,))

        else:
            self.logger.warn("__create_image(%s): failed to look up image configuration" % (image_id,))

        return retval

    def __poweron_image(self, image_id):
        retval = False
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)

        allocated_image_conf = ali.get_configuration(image_id)
        if allocated_image_conf is not None:
            full_path_xml_def_file = self.__cloned_xml_definition_path(image_id)
            if subprocess.call(['virsh', 'create', full_path_xml_def_file]) == 0:
                self.logger.info("__poweron_image(%s): image successfully launched" % (image_id,))
                retval = True
            else:
                self.logger.error("__poweron_image(%s): virsh failed with create command" % (image_id,))
        else:
            self.logger.warn("__poweron_image(%s): failed to look up image configuration" % (image_id,))
        return retval

    def __poweroff_image(self, image_id):
        retval = False
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)

        allocated_image_conf = ali.get_configuration(image_id)
        if allocated_image_conf is not None:
            if subprocess.call(['virsh', 'destroy', image_id]) == 0:
                self.logger.info("__poweroff_image(%s): image successfully destroyed" % (image_id,))
                retval = True
            else:
                self.logger.error("__poweroff_image(%s): virsh failed with destroy command" % (image_id,))
        else:
            self.logger.warn("__poweroff_image(%s): failed to look up image configuration" % (image_id,))
        return retval

    def __destroy_image(self, image_id):
        retval = False
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)

        allocated_image_conf = ali.get_configuration(image_id)
        if allocated_image_conf is not None:
            retval = True
            try:
                os.remove(self.__cloned_disk_image_path(image_id))
            except:
                self.logger.warn("__destroy_image(%s): failed to remove disk image %s" % (image_id, self.__cloned_disk_image_path(image_id)))
                retval = False
                pass

            try:
                os.remove(self.__cloned_xml_definition_path(image_id))
            except:
                self.logger.warn("__destroy_image(%s): failed to remove xml definition %s" % (image_id, self.__cloned_xml_definition_path(image_id)))
                retval = False
                pass

            if retval == True:
                self.logger.info("__destroy_image(%s): image successfully destroyed" % (image_id,))
        else:
            self.logger.warn("__destroy_image(%s): failed to look up image configuration" % (image_id,))

    def __cleanup_expired_images(self):
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)
        bim = DVMPSDAO.BaseImages(dbc)
        mip = DVMPSDAO.MacIpPairs(dbc)
        timenow = int(time.time())

        image_ids = ali.get_images()
        for image_id in image_ids:
            image_record = ali.get_configuration(image_id)
            if image_record is not None and image_record.has_key('creation_time') and image_record.has_key('valid_for'):
                time_before_expiry = image_record['creation_time'] + image_record['valid_for'] - int(time.time())
                if time_before_expiry < 0:
                    self.logger.info("__cleanup_expired_images: found expired image %s" % (image_id,))
                    self.__poweroff_image(image_id)
                    self.__destroy_image(image_id)
                    if image_record.has_key('mac_id'):
                        mip.deallocate(image_record['mac_id'])
                    ali.deallocate(image_id)

    def allocate_image(self, base_image, valid_for, priority, comment):
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)
        bim = DVMPSDAO.BaseImages(dbc)
        mip = DVMPSDAO.MacIpPairs(dbc)

        image_id = str(uuid.uuid4())

        self.__cleanup_expired_images()

        self.logger.info("allocate_image: request to allocate image of type %s" % (base_image,))
        base_image_conf = bim.get_base_image_configuration_by_name(base_image)
        if base_image_conf is None or not base_image_conf.has_key('id') or not base_image_conf.has_key('base_image_file') or not base_image_conf.has_key('configuration_template'):
            self.logger.warn("allocate_image: no such base_image configured %s" % (base_image,))
            return { 'result': False, 'error': 'No such base image configured' }

        while True:
            mac_id = mip.allocate(valid_for=valid_for)
            if mac_id is not None:
                break
            else:
                lower_priority_images = ali.get_images_below_priority(priority)
                if len(lower_priority_images) == 0:
                    break
                else:
                    low_image_id = lower_priority_images[0]
                    low_image_conf = ali.get_configuration(low_image_id)
                    if low_image_conf is not None:
                        self.logger.info("allocate_image: destroying lower priority image %s" % (low_image_id,))
                        self.__poweroff_image(low_image_id)
                        self.__destroy_image(low_image_id)
                        if low_image_conf.has_key('mac_id'):
                            mip.deallocate(low_image_conf['mac_id'])
                        ali.deallocate(low_image_id)
                    else:
                        break

        if mac_id is None:
            self.logger.warn("allocate_image: no free MAC/IP pairs")
            return { 'result': False, 'error': 'Could not allocate a free MAC address' }

        if ali.allocate(image_id, mac_id, base_image_conf['id'], valid_for=valid_for, comment=comment, priority=priority) == False:
            self.logger.error("allocate_image: failed to allocate image (DAO)")
            mip.deallocate(mac_id)
            return { 'result': False, 'error': 'Failed to allocate image' }

        ip_addr = mip.get_ip_for_mac_id(mac_id)

        if self.__create_image(image_id) == True:
            if self.__poweron_image(image_id) == True:
                pass
            else:
                self.logger.error("allocate_image: failed to launch virtual machine")
                self.__destroy_image(image_id)
                ali.deallocate(image_id)
                mip.deallocate(mac_id)
                return { 'result': False, 'error': 'Failed to launch virtual machine' }
        else:
            self.logger.error("allocate_image: failed to setup virtual machine")
            ali.deallocate(image_id)
            mip.deallocate(mac_id)
            return { 'result': False, 'error': 'Failed to create backing image' }

        self.logger.info("allocate_image: successfully allocated image %s of type %s" % (image_id, base_image))
        ret_val = self.__image_status(image_id)
        return ret_val

    def deallocate_image(self, image_id):
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)
        mip = DVMPSDAO.MacIpPairs(dbc)

        self.__cleanup_expired_images()
        ret_val = { 'result': False, 'error': 'No such image' }

        allocated_image_conf = ali.get_configuration(image_id)
        if allocated_image_conf is not None:
            self.logger.info("deallocate_image(%s): deallocating" % (image_id,))
            self.__poweroff_image(image_id)
            self.__destroy_image(image_id)
            if allocated_image_conf.has_key('mac_id'):
                mip.deallocate(allocated_image_conf['mac_id'])
            ali.deallocate(image_id)
            ret_val = { 'result': True, 'image_id': image_id, 'status': 'not-allocated' }
        else:
            self.logger.warn("deallocate_image(%s): failed to look up image configuration" % (image_id,))

        return ret_val

    def revert_image(self, image_id):
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)

        self.__cleanup_expired_images()
        ret_val = { 'result': False, 'error': 'No such image' }

        allocated_image_conf = ali.get_configuration(image_id)
        if allocated_image_conf is not None:
            self.logger.info("revert_image(%s): reverting" % (image_id,))
            self.__poweroff_image(image_id)
            self.__destroy_image(image_id)
            self.__create_image(image_id)
            self.__poweron_image(image_id)
            ret_val = self.__image_status(image_id)
        else:
            self.logger.warn("revert_image(%s): failed to look up image configuration" % (image_id,))

        return ret_val

    def __image_status(self, image_id):
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)
        bim = DVMPSDAO.BaseImages(dbc)
        mip = DVMPSDAO.MacIpPairs(dbc)

        ret_val = None

        allocated_image_conf = ali.get_configuration(image_id)
        if allocated_image_conf is not None:
            valid_for = 0
            ip_addr = None
            base_image = None
            comment = None
            priority = 50

            if allocated_image_conf.has_key('creation_time') and allocated_image_conf.has_key('valid_for'):
                valid_for = allocated_image_conf['creation_time'] + allocated_image_conf['valid_for'] - int(time.time())
            if allocated_image_conf.has_key('mac_id'):
                ip_addr = mip.get_ip_for_mac_id(allocated_image_conf['mac_id'])
            if allocated_image_conf.has_key('base_image_id'):
                base_image_record = bim.get_base_image_configuration(allocated_image_conf['base_image_id'])
                if base_image_record is not None and base_image_record.has_key('base_image_name'):
                    base_image = base_image_record['base_image_name']
            if allocated_image_conf.has_key('comment'):
                comment = allocated_image_conf['comment']
            if allocated_image_conf.has_key('priority'):
                priority = allocated_image_conf['priority']
            ret_val = { 'result': True, 'image_id': image_id, 'status': 'allocated', 'ip_addr': ip_addr, 'base_image': base_image, 'valid_for': valid_for, 'priority': priority, 'comment': comment, 'vncport': self.__get_vnc_port(image_id) }
        else:
            self.logger.warn("__image_status(%s): failed to look up image configuration" % (image_id,))

        return ret_val

    def image_status(self, image_id):
        self.__cleanup_expired_images()
        ret_val = self.__image_status(image_id)
        if ret_val is None:
            ret_val = { 'result': True, 'image_id': image_id, 'status': 'not-allocated' }
        return ret_val

    def poweroff_image(self, image_id):
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)

        self.__cleanup_expired_images()
        ret_val = { 'result': False, 'error': 'no such image' }

        allocated_image_conf = ali.get_configuration(image_id)
        if allocated_image_conf is not None:
            self.__poweroff_image(image_id)
            ret_val = { 'result': True, 'image_id': image_id }
        else:
            self.logger.warn("poweroff_image(%s): failed to look up image configuration" % (image_id,))

        return ret_val

    def poweron_image(self, image_id):
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)

        self.__cleanup_expired_images()
        ret_val = { 'result': False, 'error': 'no such image' }

        allocated_image_conf = ali.get_configuration(image_id)
        if allocated_image_conf is not None:
            self.__poweron_image(image_id)
            ret_val = self.__image_status(image_id)
        else:
            self.logger.warn("poweron_image(%s): failed to look up image configuration" % (image_id,))

        return ret_val

    def status(self):
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)

        self.__cleanup_expired_images()
        images = ali.get_images()
        ret_val = { 'result': True, 'allocated_images': len(images) }
        return ret_val

    def running_images(self):
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        ali = DVMPSDAO.AllocatedImages(dbc)

        self.__cleanup_expired_images()
        images = ali.get_images()
        image_statuses = []
        for image in images:
            image_status = self.__image_status(image)
            if image_status != None:
                image_statuses.append(image_status)
        ret_val = { 'result': True, 'running_images': image_statuses }
        return ret_val

    def base_images(self):
        dbc = DVMPSDAO.DatabaseConnection(database=self.database)
        bim = DVMPSDAO.BaseImages(dbc)

        base_images = bim.get_base_images()
        return { 'result': True, 'base_images': base_images }
