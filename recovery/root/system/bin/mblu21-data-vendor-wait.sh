#!/system/bin/sh

for _ in $(seq 1 180); do
    if [ -d /data/vendor/sprd_ss ] && [ -d /data/vendor/sprd_tee_ss ]; then
        setprop mblu21.data_vendor.ready 1
        exit 0
    fi
    sleep 1
done
exit 1
