#
# SPDX-FileCopyrightText: 2026 Zhafron Adani Kautsar
# SPDX-License-Identifier: Apache-2.0
#

PRODUCT_USE_DYNAMIC_PARTITIONS := true
PRODUCT_SHIPPING_API_LEVEL := 33

PRODUCT_PACKAGES += \
    mblu21_stock_vendor_ramdisk

PRODUCT_PACKAGES += \
    android.hardware.boot@1.2-impl \
    android.hardware.boot@1.2-impl.recovery \
    android.hardware.boot@1.2-service

PRODUCT_PACKAGES += \
    fastbootd

PRODUCT_PROPERTY_OVERRIDES += \
    ro.virtual_ab.enabled=true \
    ro.virtual_ab.compression.enabled=true \
    ro.virtual_ab.userspace.snapshots.enabled=true
