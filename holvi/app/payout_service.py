import os
import requests
import time
from database_pooled import PooledDBConnection


class PayoutService:
    """
    Optimized service
    
    Optimizations:
    - Conn pooling
    - Batch pprocessing
    - Limited fetching
    """
    
    # Config
    FETCH_LIMIT = 200
    BATCH_SIZE = 50  
    MAX_RETRIES = 3   
    
    def __init__(self):
        self.expenzy_base_url = os.environ.get(
            "EXPENZY_API_BASE_URL", 
            "http://expenzy-server:5001"
        )
    
    def process_webhook(self):
        """
        entry point for processing of webhooks.
        conn pooling + batch processing
        """
        print("[PayoutService] starting webhook processing")
        
        with PooledDBConnection() as db:
            # 0. clean stucked payouts
            self._cleanup_stuck_payouts(db, timeout_minutes=5)
            
            # 1. fetch limited payouts from expany
            payouts = self._fetch_payouts_from_expenzy(limit=self.FETCH_LIMIT)
            print(f"[PayoutService] Fetched {len(payouts)} payouts from Expenzy")
            
            if not payouts:
                print("[PayoutService] No payouts to process")
                return
            
            # 2. Process in batches
            total_claimed = 0
            total_processed = 0
            
            for i in range(0, len(payouts), self.BATCH_SIZE):
                batch = payouts[i:i + self.BATCH_SIZE]
                
                claimed = self._claim_batch(db, batch)
                total_claimed += len(claimed)
                
                processed = self._process_batch(db, claimed)
                total_processed += processed
                
                print(f"[PayoutService] Batch {i//self.BATCH_SIZE + 1}: "
                      f"Claimed {len(claimed)}/{len(batch)}, "
                      f"Processed {processed}/{len(claimed)}")
            
            print(f"[PayoutService] Claimed {total_claimed}, "
                  f"Processed {total_processed}")
            print("[PayoutService] processing complete")
    
    def _fetch_payouts_from_expenzy(self, limit=None):
        """
        fetch with optional limit
        """
        try:
            url = f"{self.expenzy_base_url}/api/transaction/"
            params = {"state": "notifying"}
            
            response = requests.post(url, params=params, timeout=10)
            response.raise_for_status()
            
            payouts = response.json()
            
            # limit (if specified)
            if limit and len(payouts) > limit:
                print(f"[PayoutService] limiting to {limit} payouts "
                      f"(total available: {len(payouts)})")
                payouts = payouts[:limit]
            
            return payouts
            
        except requests.RequestException as e:
            print(f"[PayoutService] Error fetching: {e}")
            return []
    
    def _claim_batch(self, db, batch):
        """
        claim batch atomically
        Returns: list of claimed payouts
        """
        claimed = []
        
        for payout in batch:
            # Validation
            required_fields = ['id', 'create_time', 'amount', 
                             'recipient_account_identifier']
            if not all(field in payout for field in required_fields):
                print(f"[PayoutService] invalid data, skipping")
                continue
            
            if self._try_claim_payout(db, payout):
                claimed.append(payout)
        
        return claimed
    
    def _try_claim_payout(self, db, payout):
        """
        claim single atomically
        Return: True (if claimed)
        """
        query = """
            INSERT INTO holvi_received_payout (
                expenzy_uuid,
                create_time,
                amount,
                recipient_account_identifier,
                processing_status,
                processing_started_at
            ) VALUES (%s, %s, %s, %s, 'processing', NOW())
            ON CONFLICT (expenzy_uuid) DO NOTHING
            RETURNING id
        """
        
        try:
            result = db.fetch_one(query, (
                payout['id'],
                payout['create_time'],
                payout['amount'],
                payout['recipient_account_identifier']
            ))
            
            if result:
                return True
            else:
                return False
                
        except Exception as e:
            print(f"[PayoutService] Error claiming: {e}")
            return False
    
    def _process_batch(self, db, claimed_payouts):
        """
        process batch of claimed payouts
        Return: count of successful
        """
        success_count = 0
        
        for payout in claimed_payouts:
            if self._process_payout(db, payout):
                success_count += 1
        
        return success_count
    
    def _process_payout(self, db, payout):
        """
        process single claimed payout
        Return: True (if successful)
        """
        payout_id = payout['id']
        
        # update expenzy state with retry
        success = self._update_expenzy_state(payout_id)
        
        if success:
            self._mark_completed(db, payout_id)
            return True
        else:
            print(f"[PayoutService] Fail to process {payout_id}")
            return False
    
    def _update_expenzy_state(self, payout_id):
        """
        update state in expenzy with retry
        Return: True if successful
        """
        backoff_seconds = [1, 2, 4]
        
        for attempt in range(self.MAX_RETRIES):
            try:
                url = f"{self.expenzy_base_url}/api/transaction/{payout_id}/"
                data = {"state": "processing"}
                
                response = requests.post(url, data=data, timeout=10)
                
                if response.status_code == 200:
                    result = response.json()
                    if result:
                        return True
                
            except requests.RequestException as e:
                print(f"[PayoutService] Network error: {e}")

            if attempt < self.MAX_RETRIES - 1:
                time.sleep(backoff_seconds[attempt])
        
        return False
    
    def _mark_completed(self, db, payout_id):
        """mark payout as completed in db"""
        query = """
            UPDATE holvi_received_payout
            SET processing_status = 'completed',
                processing_completed_at = NOW()
            WHERE expenzy_uuid = %s
        """
        
        try:
            db.execute(query, (payout_id,))
            db.commit()
        except Exception as e:
            print(f"[PayoutService] Error marking completed: {e}")
            db.rollback()
    
    def _cleanup_stuck_payouts(self, db, timeout_minutes=5):
        """
        Reset payouts stuck in processing.
        """
        query = """
            UPDATE holvi_received_payout
            SET processing_status = 'pending',
                processing_started_at = NULL
            WHERE processing_status = 'processing'
              AND processing_started_at < NOW() - INTERVAL '%s minutes'
            RETURNING expenzy_uuid
        """
        
        try:
            query_formatted = query % timeout_minutes
            results = db.fetch_results(query_formatted)
            
            if results:
                db.commit()
                print(f"[PayoutService] Reset {len(results)} stuck payouts")
            
        except Exception as e:
            print(f"[PayoutService] Error in cleanup: {e}")
            db.rollback()