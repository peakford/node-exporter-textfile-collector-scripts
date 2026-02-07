#!/bin/bash
# zswap.sh - Export zswap metrics for Prometheus node_exporter textfile collector
#
# Usage:
#   cd /var/lib/prometheus/node-exporter && ./zswap.sh > zswap.prom.$$; mv zswap.prom.$$ zswap.prom

set -euo pipefail

ZSWAP_DEBUG="/sys/kernel/debug/zswap"
ZSWAP_PARAMS="/sys/module/zswap/parameters"

if [[ ! -d "${ZSWAP_PARAMS}" ]]; then
    exit 0
fi

# --- Parameters ---
enabled=$(cat "${ZSWAP_PARAMS}/enabled" 2>/dev/null || echo "N")
[[ "${enabled}" == "Y" ]] && enabled_val=1 || enabled_val=0

compressor=$(cat "${ZSWAP_PARAMS}/compressor" 2>/dev/null || echo "unknown")
zpool=$(cat "${ZSWAP_PARAMS}/zpool" 2>/dev/null || echo "unknown")
max_pool_pct=$(cat "${ZSWAP_PARAMS}/max_pool_percent" 2>/dev/null || echo "0")

cat << EOF
# HELP node_zswap_enabled Whether zswap is enabled (1=yes, 0=no).
# TYPE node_zswap_enabled gauge
node_zswap_enabled ${enabled_val}
# HELP node_zswap_compressor The active zswap compressor algorithm.
# TYPE node_zswap_compressor gauge
node_zswap_compressor{algorithm="${compressor}"} 1
# HELP node_zswap_zpool The active zswap zpool allocator.
# TYPE node_zswap_zpool gauge
node_zswap_zpool{allocator="${zpool}"} 1
# HELP node_zswap_max_pool_percent Maximum percentage of RAM usable by zswap pool.
# TYPE node_zswap_max_pool_percent gauge
node_zswap_max_pool_percent ${max_pool_pct}
EOF

# --- Debug stats (requires root / debugfs access) ---
if [[ -d "${ZSWAP_DEBUG}" ]]; then
    read_debug() {
        cat "${ZSWAP_DEBUG}/$1" 2>/dev/null || echo "0"
    }

    pool_total_size=$(read_debug "pool_total_size")
    stored_pages=$(read_debug "stored_pages")
    pool_limit_hit=$(read_debug "pool_limit_hit")
    reject_reclaim_fail=$(read_debug "reject_reclaim_fail")
    reject_alloc_fail=$(read_debug "reject_alloc_fail")
    reject_kmemcache_fail=$(read_debug "reject_kmemcache_fail")
    reject_compress_fail=$(read_debug "reject_compress_fail")
    reject_compress_poor=$(read_debug "reject_compress_poor")
    written_back_pages=$(read_debug "written_back_pages")
    duplicate_entry=$(read_debug "duplicate_entry")
    same_filled_pages=$(read_debug "same_filled_pages")

    cat << EOF
# HELP node_zswap_pool_total_size_bytes Current compressed pool size in bytes.
# TYPE node_zswap_pool_total_size_bytes gauge
node_zswap_pool_total_size_bytes ${pool_total_size}
# HELP node_zswap_stored_pages Number of pages currently stored in zswap.
# TYPE node_zswap_stored_pages gauge
node_zswap_stored_pages ${stored_pages}
# HELP node_zswap_same_filled_pages Number of same-filled pages stored (zero pages etc).
# TYPE node_zswap_same_filled_pages gauge
node_zswap_same_filled_pages ${same_filled_pages}
# HELP node_zswap_pool_limit_hit_total Number of times the pool limit was reached.
# TYPE node_zswap_pool_limit_hit_total counter
node_zswap_pool_limit_hit_total ${pool_limit_hit}
# HELP node_zswap_reject_reclaim_fail_total Pages rejected due to reclaim failure.
# TYPE node_zswap_reject_reclaim_fail_total counter
node_zswap_reject_reclaim_fail_total ${reject_reclaim_fail}
# HELP node_zswap_reject_alloc_fail_total Pages rejected due to allocation failure.
# TYPE node_zswap_reject_alloc_fail_total counter
node_zswap_reject_alloc_fail_total ${reject_alloc_fail}
# HELP node_zswap_reject_kmemcache_fail_total Pages rejected due to kmemcache failure.
# TYPE node_zswap_reject_kmemcache_fail_total counter
node_zswap_reject_kmemcache_fail_total ${reject_kmemcache_fail}
# HELP node_zswap_reject_compress_fail_total Pages rejected because compression failed.
# TYPE node_zswap_reject_compress_fail_total counter
node_zswap_reject_compress_fail_total ${reject_compress_fail}
# HELP node_zswap_reject_compress_poor_total Pages rejected due to poor compression ratio.
# TYPE node_zswap_reject_compress_poor_total counter
node_zswap_reject_compress_poor_total ${reject_compress_poor}
# HELP node_zswap_written_back_pages_total Pages written back from zswap to swap disk.
# TYPE node_zswap_written_back_pages_total counter
node_zswap_written_back_pages_total ${written_back_pages}
# HELP node_zswap_duplicate_entry_total Duplicate entries encountered.
# TYPE node_zswap_duplicate_entry_total counter
node_zswap_duplicate_entry_total ${duplicate_entry}
EOF
fi
