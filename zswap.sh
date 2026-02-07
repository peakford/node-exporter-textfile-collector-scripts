#!/bin/bash
# zswap_exporter.sh - Export zswap metrics for Prometheus node_exporter textfile collector
#
# Usage:
#   Place in /usr/local/bin/zswap_exporter.sh
#   Run via cron or systemd timer every 15-60 seconds:
#     * * * * * /usr/local/bin/zswap_exporter.sh
#
#   Configure node_exporter with:
#     --collector.textfile.directory=/var/lib/node_exporter/textfile_collector
#

set -euo pipefail

OUTPUT_DIR="/var/lib/node_exporter/textfile_collector"
OUTPUT_FILE="${OUTPUT_DIR}/zswap.prom"
TMP_FILE="${OUTPUT_FILE}.$$"

mkdir -p "${OUTPUT_DIR}"

# Check if zswap is available
ZSWAP_DEBUG="/sys/kernel/debug/zswap"
ZSWAP_PARAMS="/sys/module/zswap/parameters"

if [[ ! -d "${ZSWAP_PARAMS}" ]]; then
    echo "# zswap module not available" > "${TMP_FILE}"
    mv "${TMP_FILE}" "${OUTPUT_FILE}"
    exit 0
fi

cat > "${TMP_FILE}" << 'HEADER'
# HELP node_zswap_enabled Whether zswap is enabled (1=yes, 0=no).
# TYPE node_zswap_enabled gauge
# HELP node_zswap_compressor The active zswap compressor algorithm.
# TYPE node_zswap_compressor gauge
# HELP node_zswap_zpool The active zswap zpool allocator.
# TYPE node_zswap_zpool gauge
# HELP node_zswap_max_pool_percent Maximum percentage of RAM usable by zswap pool.
# TYPE node_zswap_max_pool_percent gauge
# HELP node_zswap_pool_total_size_bytes Current compressed pool size in bytes.
# TYPE node_zswap_pool_total_size_bytes gauge
# HELP node_zswap_stored_pages Number of pages currently stored in zswap.
# TYPE node_zswap_stored_pages gauge
# HELP node_zswap_pool_limit_hit_total Number of times the pool limit was reached.
# TYPE node_zswap_pool_limit_hit_total counter
# HELP node_zswap_reject_reclaim_fail_total Pages rejected due to reclaim failure.
# TYPE node_zswap_reject_reclaim_fail_total counter
# HELP node_zswap_reject_alloc_fail_total Pages rejected due to allocation failure.
# TYPE node_zswap_reject_alloc_fail_total counter
# HELP node_zswap_reject_kmemcache_fail_total Pages rejected due to kmemcache failure.
# TYPE node_zswap_reject_kmemcache_fail_total counter
# HELP node_zswap_reject_compress_fail_total Pages rejected because compression failed.
# TYPE node_zswap_reject_compress_fail_total counter
# HELP node_zswap_reject_compress_poor_total Pages rejected due to poor compression ratio.
# TYPE node_zswap_reject_compress_poor_total counter
# HELP node_zswap_written_back_pages_total Pages written back from zswap to swap disk.
# TYPE node_zswap_written_back_pages_total counter
# HELP node_zswap_duplicate_entry_total Duplicate entries encountered.
# TYPE node_zswap_duplicate_entry_total counter
# HELP node_zswap_same_filled_pages Number of same-filled pages stored (zero pages etc).
# TYPE node_zswap_same_filled_pages gauge
# HELP node_zswap_stored_bytes_uncompressed Estimated original (uncompressed) size of stored pages in bytes.
# TYPE node_zswap_stored_bytes_uncompressed gauge
# HELP node_zswap_compression_ratio Ratio of uncompressed to compressed size (higher is better).
# TYPE node_zswap_compression_ratio gauge
HEADER

# --- Parameters ---
enabled=$(cat "${ZSWAP_PARAMS}/enabled" 2>/dev/null || echo "N")
[[ "${enabled}" == "Y" ]] && enabled_val=1 || enabled_val=0
echo "node_zswap_enabled ${enabled_val}" >> "${TMP_FILE}"

compressor=$(cat "${ZSWAP_PARAMS}/compressor" 2>/dev/null || echo "unknown")
echo "node_zswap_compressor{algorithm=\"${compressor}\"} 1" >> "${TMP_FILE}"

zpool=$(cat "${ZSWAP_PARAMS}/zpool" 2>/dev/null || echo "unknown")
echo "node_zswap_zpool{allocator=\"${zpool}\"} 1" >> "${TMP_FILE}"

max_pool_pct=$(cat "${ZSWAP_PARAMS}/max_pool_percent" 2>/dev/null || echo "0")
echo "node_zswap_max_pool_percent ${max_pool_pct}" >> "${TMP_FILE}"

# --- Debug stats (requires root / debugfs access) ---
if [[ -d "${ZSWAP_DEBUG}" ]]; then
    read_debug() {
        local file="${ZSWAP_DEBUG}/$1"
        if [[ -r "${file}" ]]; then
            cat "${file}"
        else
            echo "0"
        fi
    }

    pool_total_size=$(read_debug "pool_total_size")
    stored_pages=$(read_debug "stored_pages")
    pool_limit_hit=$(read_debug "pool_limit_hit")
    reject_reclaim_fail=$(read_debug "reject_reclaim_fail")
    reject_alloc_fail=$(read_debug "reject_alloc_fail")
    reject_kmemcache_fail=$(read_debug "reject_kmemcache_fail")
    reject_compress_fail=$(read_debug "reject_compress_fail")
    reject_compress_poor=$(read_debug "reject_compress_poor" )
    written_back_pages=$(read_debug "written_back_pages")
    duplicate_entry=$(read_debug "duplicate_entry")
    same_filled_pages=$(read_debug "same_filled_pages")

    echo "node_zswap_pool_total_size_bytes ${pool_total_size}" >> "${TMP_FILE}"
    echo "node_zswap_stored_pages ${stored_pages}" >> "${TMP_FILE}"
    echo "node_zswap_pool_limit_hit_total ${pool_limit_hit}" >> "${TMP_FILE}"
    echo "node_zswap_reject_reclaim_fail_total ${reject_reclaim_fail}" >> "${TMP_FILE}"
    echo "node_zswap_reject_alloc_fail_total ${reject_alloc_fail}" >> "${TMP_FILE}"
    echo "node_zswap_reject_kmemcache_fail_total ${reject_kmemcache_fail}" >> "${TMP_FILE}"
    echo "node_zswap_reject_compress_fail_total ${reject_compress_fail}" >> "${TMP_FILE}"
    echo "node_zswap_reject_compress_poor_total ${reject_compress_poor}" >> "${TMP_FILE}"
    echo "node_zswap_written_back_pages_total ${written_back_pages}" >> "${TMP_FILE}"
    echo "node_zswap_duplicate_entry_total ${duplicate_entry}" >> "${TMP_FILE}"
    echo "node_zswap_same_filled_pages ${same_filled_pages}" >> "${TMP_FILE}"

    # Derived metrics: uncompressed size and compression ratio
    page_size=$(getconf PAGESIZE)
    uncompressed_bytes=$(( stored_pages * page_size ))
    echo "node_zswap_stored_bytes_uncompressed ${uncompressed_bytes}" >> "${TMP_FILE}"

    if [[ "${pool_total_size}" -gt 0 ]]; then
        # Use awk for floating point division
        ratio=$(awk "BEGIN {printf \"%.2f\", ${uncompressed_bytes} / ${pool_total_size}}")
    else
        ratio="0"
    fi
    echo "node_zswap_compression_ratio ${ratio}" >> "${TMP_FILE}"
fi

# Atomic replace
mv "${TMP_FILE}" "${OUTPUT_FILE}"
