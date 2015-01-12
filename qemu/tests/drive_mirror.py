import os
import logging
from autotest.client.shared import error, utils
from virttest import utils_misc, storage, qemu_storage, nfs
from qemu.tests import block_copy


class DriveMirror(block_copy.BlockCopy):

    """
    base class for block mirror tests;
    """

    def __init__(self, test, params, env, tag):
        super(DriveMirror, self).__init__(test, params, env, tag)
        self.target_image = self.get_target_image()

    def parser_test_args(self):
        """
        paraser test args and set default value;
        """
        default_params = {"create_mode": "absolute-path",
                          "reopen_timeout": 60,
                          "full_copy": "full",
                          "check_event": "no"}
        self.default_params.update(default_params)
        params = super(DriveMirror, self).parser_test_args()
        if params["block_mirror_cmd"].startswith("__"):
            params["full_copy"] = (params["full_copy"] == "full")
        params = params.object_params(params["target_image"])
        if params.get("image_type") == "iscsi":
            params.setdefault("host_setup_flag", 2)
            params["host_setup_flag"] = int(params["host_setup_flag"])
        return params

    def get_target_image(self):
        params = self.parser_test_args()
        target_image = storage.get_image_filename(params, self.data_dir)
        if params.get("image_type") == "nfs":
            image = nfs.Nfs(params)
            image.setup()
            utils_misc.wait_for(lambda: os.path.ismount(image.mount_dir),
                                timeout=30)
        elif params.get("image_type") == "iscsi":
            image = qemu_storage.Iscsidev(params, self.data_dir,
                                          params["target_image"])
            return image.setup()

        if (params["create_mode"] == "existing" and
                not os.path.exists(target_image)):
            image = qemu_storage.QemuImg(params, self.data_dir,
                                         params["target_image"])
            image.create(params)

        return target_image

    def get_device(self):
        params = super(DriveMirror, self).parser_test_args()
        image_file = storage.get_image_filename(params, self.data_dir)
        return self.vm.get_block({"file": image_file})

    @error.context_aware
    def start(self):
        """
        start block device mirroring job;
        """
        params = self.parser_test_args()
        target_image = self.target_image
        device = self.device
        default_speed = params["default_speed"]
        target_format = params["image_format"]
        create_mode = params["create_mode"]
        full_copy = params["full_copy"]

        error.context("Start to mirror block device", logging.info)
        self.vm.block_mirror(device, target_image, default_speed,
                             full_copy, target_format, create_mode)
        if not self.get_status():
            raise error.TestFail("No active mirroring job found")
        if params.get("image_type") != "iscsi":
            self.trash_files.append(target_image)

    @error.context_aware
    def reopen(self):
        """
        reopen target image, then check if image file of the device is
        target images;
        """
        params = self.parser_test_args()
        target_format = params["image_format"]
        timeout = params["reopen_timeout"]

        def is_opened():
            device = self.vm.get_block({"file": self.target_image})
            ret = (device == self.device)
            if self.vm.monitor.protocol == "qmp":
                ret &= bool(self.vm.monitor.get_event("BLOCK_JOB_COMPLETED"))
            return ret

        error.context("reopen new target image", logging.info)
        if self.vm.monitor.protocol == "qmp":
            self.vm.monitor.clear_event("BLOCK_JOB_COMPLETED")
        self.vm.block_reopen(self.device, self.target_image, target_format)
        opened = utils_misc.wait_for(is_opened, first=3.0, timeout=timeout)
        if not opened:
            msg = "Target image not used,wait timeout in %ss" % timeout
            raise error.TestFail(msg)

    def is_steady(self):
        """
        check block device mirroring job is steady status or not;
        """
        params = self.parser_test_args()
        info = self.get_status()
        ret = bool(info and info["len"] == info["offset"])
        if self.vm.monitor.protocol == "qmp":
            if params.get("check_event", "no") == "yes":
                ret &= bool(self.vm.monitor.get_event("BLOCK_JOB_READY"))
        return ret

    def wait_for_steady(self):
        """
        check block device mirroring status, utils timeout; if still not go
        into steady status, raise TestFail exception;
        """
        params = self.parser_test_args()
        timeout = params.get("wait_timeout")
        if self.vm.monitor.protocol == "qmp":
            self.vm.monitor.clear_event("BLOCK_JOB_READY")
        steady = utils_misc.wait_for(self.is_steady, first=3.0,
                                     step=3.0, timeout=timeout)
        if not steady:
            raise error.TestFail("Wait mirroring job ready "
                                 "timeout in %ss" % timeout)

    def action_before_steady(self):
        """
        run steps before job in steady status;
        """
        return self.do_steps("before_steady")

    def action_when_steady(self):
        """
        run steps when job in steady status;
        """
        self.wait_for_steady()
        return self.do_steps("when_steady")

    def action_after_reopen(self):
        """
        run steps after reopened new target image;
        """
        return self.do_steps("after_reopen")

    def clean(self):
        super(DriveMirror, self).clean()
        params = self.parser_test_args()
        if params.get("image_type") == "iscsi":
            params["host_setup_flag"] = int(params["host_setup_flag"])
            qemu_img = utils_misc.get_qemu_img_binary(self.params)
            # Reformat it to avoid impact other test
            cmd = "%s create -f %s %s %s" % (qemu_img,
                                             params["image_format"],
                                             self.target_image,
                                             params["image_size"])
            utils.system(cmd)
            image = qemu_storage.Iscsidev(params, self.data_dir,
                                          params["target_image"])
            image.cleanup()
        elif params.get("image_type") == "nfs":
            image = nfs.Nfs(params)
            image.cleanup()


def run(test, params, env):
    pass
