#
# SPDX-FileCopyrightText: 2026 Zhafron Adani Kautsar
# SPDX-License-Identifier: Apache-2.0
#

LOCAL_PATH := $(call my-dir)

ifeq ($(TARGET_DEVICE),mblu21)

include $(CLEAR_VARS)
LOCAL_MODULE := mblu21_stock_vendor_ramdisk
LOCAL_MODULE_CLASS := ETC
LOCAL_MODULE_STEM := modules.load
LOCAL_SRC_FILES := prebuilt/vendor_ramdisk/lib/modules/modules.load
LOCAL_MODULE_PATH := $(TARGET_VENDOR_RAMDISK_OUT)/lib/modules
LOCAL_POST_INSTALL_CMD := cp -a $(LOCAL_PATH)/prebuilt/vendor_ramdisk/. $(TARGET_VENDOR_RAMDISK_OUT)/
include $(BUILD_PREBUILT)

endif
