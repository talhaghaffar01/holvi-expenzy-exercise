from connection_pool import get_connection_pool

class PooledDBConnection:
    """
    DB connection using pooling
    """
    
    def __init__(self):
        self.pool = get_connection_pool()
        self.connection = None
    
    def __enter__(self):
        """context manager Entry"""
        self.connection = self.pool.getconn()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """context manager Exit"""
        if self.connection:
            self.pool.putconn(self.connection)
            self.connection = None
    
    def fetch_results(self, sql, params=None):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()
    
    def fetch_one(self, sql, params=None):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()
    
    def execute(self, sql, params=None):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
    
    def commit(self):
        if self.connection:
            self.connection.commit()
    
    def rollback(self):
        if self.connection:
            self.connection.rollback()