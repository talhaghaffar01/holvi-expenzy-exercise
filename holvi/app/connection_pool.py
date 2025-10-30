from psycopg_pool import ConnectionPool
import os

# Global pool for connection a.k.a GCP
_pool = None

def get_connection_pool():
    """
    Get or create the GCP
    allow connections to be reused across webhooks
    """
    global _pool
    
    if _pool is None:
        conninfo = (
            f"host={os.environ.get('DB_HOSTNAME', '127.0.0.1')} "
            f"port={os.environ.get('DB_PORT', '5432')} "
            f"dbname={os.environ.get('DB_DATABASE', 'shared')} "
            f"user={os.environ.get('DB_USERNAME', 'shared')} "
            f"password={os.environ.get('DB_PASSWORD', 'shared')}"
        )
        
        # create pool
        _pool = ConnectionPool(
            conninfo=conninfo,
            min_size=2,
            max_size=20,
            timeout=30
        )
        print("[ConnectionPool] Created connection pool (min=2, max=20)")
    
    return _pool

def close_connection_pool():
    """Close the connection pool on shutdown."""
    global _pool
    if _pool:
        _pool.close()
        _pool = None
        print("[ConnectionPool] Closed connection pool")