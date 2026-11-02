#
# SPDX-FileCopyrightText: 2026 Zhafron Adani Kautsar
# SPDX-License-Identifier: Apache-2.0
#

PRODUCT_USE_DYNAMIC_PARTITIONS := true
ifneq ($(wildcard vendor/shrp),)
PRODUCT_SHIPPING_API_LEVEL := 32
else
PRODUCT_SHIPPING_API_LEVEL := 33
endif

PRODUCT_PACKAGES += \
    mblu21_stock_vendor_ramdisk \
    fastbootd

PRODUCT_PROPERTY_OVERRIDES += \
    ro.virtual_ab.enabled=true \
    ro.virtual_ab.compression.enabled=true \
    ro.virtual_ab.userspace.snapshots.enabled=true
