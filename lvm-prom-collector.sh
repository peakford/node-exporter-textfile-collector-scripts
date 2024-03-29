#!/usr/bin/env bash
#
# Expose various types of information about lvm2
#
# Usage: lvm-prom-collector <options>
#
# Options:
#
# -g for used and free space of logical volume groups
# -p for used and free space of physical volumes.
# -s for the percentage usage of the snapshots
# -t for the percentage usage of the thin pools
#
# * * * * *   root lvm-prom-collector -g | sponge /var/lib/prometheus/node-exporter/lvm.prom
#
# This will expose every minute information about the logical volume groups
#
# Author: Badreddin Aboubakr <badreddin.aboubakr@ionos.com>

set -eu

# Ensure predictable numeric / date formats, etc.
export LC_ALL=C

display_usage() {
  echo "This script must be run with super-user privileges."
  echo "Usage: lvm-prom-collector options"
  echo "Options:"
  echo "Expose various types of information about lvm2"
  echo "Use -g for used and free space of logical volume groups."
  echo "Use -p for used and free space of physical volumes."
  echo "Use -s for the percentage usage of snapshots."
  echo "Use -c for the percentage usage of caches. (default)"
  echo "Use -t for the percentage usage of thin pools."
  echo "Use -a to enable everything."
}

if [ "$(id -u)" != "0" ]; then
  1>&2 echo "This script must be run with super-user privileges."
  exit 1
fi

# if [ $# -eq 0 ]; then
#   display_usage
#   exit 1
# fi

thin_pools=false
snapshots=false
caches=true
physical=false
groups=false

while getopts "ahtpscg" opt; do
  case $opt in
    a)
      thin_pools=true
      snapshots=true
      physical=true
      groups=true
      ;;
    p)
      physical=true
      ;;
    s)
      snapshots=true
      ;;
    c)
      caches=true
      ;;
    g)
      groups=true
      ;;
    t)
      thin_pools=true
      ;;
    h)
      display_usage
      exit 0
      ;;
    \?)
      display_usage
      exit 1
      ;;
  esac
done

if [ "$physical" = true ]; then
  echo "# HELP node_physical_volume_size Physical volume size in bytes"
  echo "# TYPE node_physical_volume_size gauge"

  echo "# HELP node_physical_volume_free Physical volume free space in bytes"
  echo "# TYPE node_physical_volume_free gauge"

  pvs_output=$(pvs --noheadings --units b --nosuffix --nameprefixes --unquoted --options pv_name,pv_fmt,pv_free,pv_size,pv_uuid 2>/dev/null)
  echo "$pvs_output" | while IFS= read -r line; do
    # Skip if the line is empty
    [ -z "$line" ] && continue
    # shellcheck disable=SC2086
    declare $line
    echo "node_physical_volume_size{name=\"$LVM2_PV_NAME\", uuid=\"$LVM2_PV_UUID\", format=\"$LVM2_PV_FMT\"} $LVM2_PV_SIZE"
    echo "node_physical_volume_free{name=\"$LVM2_PV_NAME\", uuid=\"$LVM2_PV_UUID\", format=\"$LVM2_PV_FMT\"} $LVM2_PV_FREE"
  done
fi

if [ "$snapshots" = true ]; then
  echo "# HELP node_lvm_snapshots_allocated percentage of allocated data to a snapshot"
  echo "# TYPE node_lvm_snapshots_allocated gauge"

  lvs_output=$(lvs --noheadings --select 'lv_attr=~[^s.*]' --units b --nosuffix --unquoted --nameprefixes --options lv_uuid,vg_name,data_percent 2>/dev/null)
  echo "$lvs_output" | while IFS= read -r line; do
    # Skip if the line is empty
    [ -z "$line" ] && continue
    # shellcheck disable=SC2086
    declare $line
    echo "node_lvm_snapshots_allocated{uuid=\"$LVM2_LV_UUID\", vgroup=\"$LVM2_VG_NAME\"} $LVM2_DATA_PERCENT"
  done
fi

if [ "$caches" = true ]; then
  echo "# HELP node_lvm_caches_allocated percentage of allocated data to a cache"
  echo "# TYPE node_lvm_caches_allocated gauge"

  lvs_output=$(lvs --noheadings --select 'lv_attr=~[^C.*]' --units b --nosuffix --unquoted --nameprefixes --options lv_uuid,vg_name,data_percent 2>/dev/null)
  echo "$lvs_output" | while IFS= read -r line; do
    # Skip if the line is empty
    [ -z "$line" ] && continue
    # shellcheck disable=SC2086
    declare $line
    echo "node_lvm_caches_allocated{uuid=\"$LVM2_LV_UUID\", vgroup=\"$LVM2_VG_NAME\"} $LVM2_DATA_PERCENT"
  done
fi

if [ "$thin_pools" = true ]; then
  lvs_output=$(lvs --noheadings --select 'lv_attr=~[^t.*]' --units b --nosuffix --unquoted --nameprefixes --options lv_uuid,vg_name,data_percent,metadata_percent 2>/dev/null)

  echo "# HELP node_lvm_thin_pools_allocated percentage of allocated thin pool data"
  echo "# TYPE node_lvm_thin_pools_allocated gauge"
  echo "$lvs_output" | while IFS= read -r line; do
    # Skip if the line is empty
    [ -z "$line" ] && continue
    # shellcheck disable=SC2086
    declare $line
    echo "node_lvm_thin_pools_allocated{uuid=\"$LVM2_LV_UUID\", vgroup=\"$LVM2_VG_NAME\"} $LVM2_DATA_PERCENT"
  done

  echo "# HELP node_lvm_thin_pools_metadata percentage of allocated thin pool metadata"
  echo "# TYPE node_lvm_thin_pools_metadata gauge"
  echo "$lvs_output" | while IFS= read -r line; do
    # Skip if the line is empty
    [ -z "$line" ] && continue
    # shellcheck disable=SC2086
    declare $line
    echo "node_lvm_thin_pools_metadata{uuid=\"$LVM2_LV_UUID\", vgroup=\"$LVM2_VG_NAME\"} $LVM2_METADATA_PERCENT"
  done
fi

if [ "$groups" = true ]; then
  echo "# HELP node_volume_group_size Volume group size in bytes"
  echo "# TYPE node_volume_group_size gauge"

  echo "# HELP node_volume_group_free volume group free space in bytes"
  echo "# TYPE node_volume_group_free gauge"

  vgs_output=$(vgs --noheadings --units b --nosuffix --unquoted --nameprefixes --options vg_name,vg_free,vg_size 2>/dev/null)
  echo "$vgs_output" | while IFS= read -r line; do
    # Skip if the line is empty
    [ -z "$line" ] && continue
    # shellcheck disable=SC2086
    declare $line
    echo "node_volume_group_size{name=\"$LVM2_VG_NAME\"} $LVM2_VG_SIZE"
    echo "node_volume_group_free{name=\"$LVM2_VG_NAME\"} $LVM2_VG_FREE"
  done
fi
