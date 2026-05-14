"""Migration 013: Clean up orphaned analysis_cache entries.

This migration removes entries from analysis_cache and analysis_skips tables
where the corresponding cache file no longer exists on disk.

This can happen if:
1. Cache files were manually deleted
2. Data was moved between machines
3. Cache directory was partially restored from backup
"""

import logging
from pathlib import Path

log = logging.getLogger("ohtv")


def upgrade(conn) -> None:
    """Remove analysis_cache entries without corresponding cache files."""
    from ohtv.config import get_analysis_cache_dir
    
    cache_dir = get_analysis_cache_dir()
    
    # Get all conversation IDs from analysis_cache
    cursor = conn.execute(
        "SELECT DISTINCT conversation_id FROM analysis_cache"
    )
    cache_conv_ids = [row[0] for row in cursor.fetchall()]
    
    # Get all conversation IDs from analysis_skips
    cursor = conn.execute(
        "SELECT DISTINCT conversation_id FROM analysis_skips"
    )
    skip_conv_ids = [row[0] for row in cursor.fetchall()]
    
    # Find orphaned entries (no cache file on disk)
    orphaned_cache = []
    for conv_id in cache_conv_ids:
        cache_file = cache_dir / conv_id / "objective_analysis.json"
        if not cache_file.exists():
            orphaned_cache.append(conv_id)
    
    orphaned_skips = []
    for conv_id in skip_conv_ids:
        cache_file = cache_dir / conv_id / "objective_analysis.json"
        if not cache_file.exists():
            orphaned_skips.append(conv_id)
    
    # Warn if orphan rate is suspiciously high (may indicate misconfiguration)
    if cache_conv_ids:
        orphan_rate = len(orphaned_cache) / len(cache_conv_ids)
        if orphan_rate > 0.5:
            log.warning(
                "High orphan rate: %d/%d (%.1f%%) - verify cache_dir is accessible: %s",
                len(orphaned_cache), len(cache_conv_ids), orphan_rate * 100, cache_dir
            )
    
    # Delete orphaned entries
    if orphaned_cache:
        placeholders = ",".join("?" * len(orphaned_cache))
        conn.execute(
            f"DELETE FROM analysis_cache WHERE conversation_id IN ({placeholders})",
            orphaned_cache,
        )
        log.info("Deleted %d orphaned analysis_cache entries", len(orphaned_cache))
    
    if orphaned_skips:
        placeholders = ",".join("?" * len(orphaned_skips))
        conn.execute(
            f"DELETE FROM analysis_skips WHERE conversation_id IN ({placeholders})",
            orphaned_skips,
        )
        log.info("Deleted %d orphaned analysis_skips entries", len(orphaned_skips))
    
    total_orphaned = len(orphaned_cache) + len(orphaned_skips)
    if total_orphaned > 0:
        log.info("Migration 013: Cleaned up %d orphaned cache entries", total_orphaned)
    else:
        log.info("Migration 013: No orphaned cache entries found")
