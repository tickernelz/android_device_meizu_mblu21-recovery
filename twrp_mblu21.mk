#
# SPDX-FileCopyrightText: 2026 Zhafron Adani Kautsar
# SPDX-License-Identifier: Apache-2.0
#

$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/aosp_base.mk)
$(call inherit-product, vendor/twrp/config/common.mk)
$(call inherit-product, device/meizu/mblu21/device.mk)

PRODUCT_DEVICE := mblu21
PRODUCT_NAME := twrp_mblu21
PRODUCT_BRAND := meizu
PRODUCT_MODEL := Mblu 21
PRODUCT_MANUFACTURER := MEIZU
