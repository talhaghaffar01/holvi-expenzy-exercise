import os
import requests
import time
from database import DBConnection


class PayoutService:
    """
    Service for fetching and processing payouts from Expenzy.
    Implements ATOMIC CLAIM pattern to prevent duplicate processing.
    """
    
    def __init__(self):
        self.expenzy_base_url = os.environ.get("EXPENZY_API_BASE_URL", "http://expenzy-server:5001")
        self.db = self._create_db_connection()
    
    def _create_db_connection(self):
        return DBConnection(
            hostname=os.environ.get("DB_HOSTNAME", "127.0.0.1"),
            username=os.environ.get("DB_USERNAME", "shared"),
            password=os.environ.get("DB_PASSWORD", "shared"),
            database=os.environ.get("DB_DATABASE", "shared"),
        )
    
    def process_webhook(self):
        """
        entry point for webhook processing.
        Fetches payouts -> claims them atomically -> and processes claimed ones.
        """
        print("[PayoutService] Starting webhook processing")
        self._ensure_connection()
        
        # 0. clean up any stuck payouts from last failures
        self.cleanup_stuck_payouts(timeout_minutes=5)

        # 1. Fetch all notifying payouts
        payouts = self._fetch_payouts_from_expenzy()
        print(f"[PayoutService] Fetched {len(payouts)} payouts from Expenzy")
        
        if not payouts:
            print("[PayoutService] No payouts to process")
            return
        
        # 2. claim each payout
        claimed_payouts = []
        for payout in payouts:
            if self._try_claim_payout(payout):
                claimed_payouts.append(payout)
        
        print(f"[PayoutService] Successfully claimed {len(claimed_payouts)} out of {len(payouts)} payouts")
        
        # 3. process only claimed payouts
        success_count = 0
        for payout in claimed_payouts:
            if self._process_payout(payout):
                success_count += 1
        
        print(f"[PayoutService] Successfully processed {success_count}/{len(claimed_payouts)} claimed payouts")
        print("[PayoutService] Webhook processing complete")
    
    def _fetch_payouts_from_expenzy(self):
        """
        Fetch payouts in notifying state from expanzy
        """
        try:
            url = f"{self.expenzy_base_url}/api/transaction/"
            params = {"state": "notifying"}
            
            response = requests.post(url, params=params, timeout=10)
            response.raise_for_status()
            
            payouts = response.json()
            return payouts
            
        except requests.RequestException as e:
            print(f"[PayoutService] Error fetching payouts from Expenzy: {e}")
            return []
    
    def _try_claim_payout(self, payout):
        """
        atomically claim payout with processing status being inserted.
        True: if new insert
        False: if exist already
        """
        #validation for required fields
        required_fields = ['id', 'create_time', 'amount', 'recipient_account_identifier']
        for field in required_fields:
            if field not in payout:
                print(f"[PayoutService] Invalid payout data, missing field: {field}")
                return False
            
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
            result = self.db.fetch_one(query, (
                payout['id'],
                payout['create_time'],
                payout['amount'],
                payout['recipient_account_identifier']
            ))
            
            # If result != None, payout inserted successful
            if result:
                print(f"[PayoutService] Claimed payout {payout['id']}")
                return True
            else:
                print(f"[PayoutService] Payout {payout['id']} already exists, skipping")
                return False
                
        except Exception as e:
            print(f"[PayoutService] Error claiming payout {payout.get('id', 'unknown')}: {e}")
            return False
    
    def _process_payout(self, payout):
        """
        process claimed payout. Update state in expenzy as completed.
        Returns True if successful, else False
        """
        payout_id = payout['id']
        
        # Try to update Expenzy state with retry
        success = self._update_expenzy_state(payout_id)
        
        if success:
            # Mark as completed in DB
            self._mark_completed(payout_id)
            print(f"[PayoutService] Successfully processed payout {payout_id}")
            return True
        else:
            print(f"[PayoutService] Failed to update Expenzy state for payout {payout_id}")
            return False
            # Note: Payout stays in 'processing' state
            # Will be reset to 'pending' by cleanup_stuck_payouts on next webhook
    
    def _update_expenzy_state(self, payout_id, max_retries=3):
        """
        Retry logic: update state to processing in expzy
        Returns: True / False
        """
        backoff_seconds = [1, 2, 4]
        
        for attempt in range(max_retries):
            try:
                url = f"{self.expenzy_base_url}/api/transaction/{payout_id}/"
                data = {"state": "processing"}
                
                response = requests.post(url, data=data, timeout=10)
                # Returns. Success = non empty list, Fail = empty list 
                if response.status_code == 200:
                    result = response.json()
                    if result:
                        print(f"[PayoutService] Updated Expenzy state for {payout_id}")
                        return True
                
                print(f"[PayoutService] State update failed for {payout_id}, attempt {attempt + 1}/{max_retries}")
                
            except requests.RequestException as e:
                print(f"[PayoutService] Network error updating {payout_id}: {e}")
            
            if attempt < max_retries - 1:
                time.sleep(backoff_seconds[attempt])
        
        return False
    
    def _mark_completed(self, payout_id):
        """
        mark payput as Completed
        """
        query = """
            UPDATE holvi_received_payout
            SET processing_status = 'completed',
                processing_completed_at = NOW()
            WHERE expenzy_uuid = %s
        """
        
        try:
            self.db.execute(query, (payout_id,))
            print(f"[PayoutService] Marked {payout_id} as completed")
        except Exception as e:
            print(f"[PayoutService] Error marking {payout_id} as completed: {e}")
    
    def cleanup_stuck_payouts(self, timeout_minutes=5):
        """
        reset payouts stuck in processing for longer time.
        example: webhook crashed mid of processing
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
            results = self.db.fetch_results(query_formatted)
            
            if results:
                reset_count = len(results)
                print(f"[PayoutService] Reset {reset_count} stuck payouts back to 'pending'")
                for (uuid,) in results:
                    print(f"[PayoutService] Reset stuck payout: {uuid}")
            
        except Exception as e:
            print(f"[PayoutService] Error cleaning up stuck payouts: {e}")
    
    def _ensure_connection(self):
        """
        mkae sure DB connection is alive, if not reconnect
        """
        try:
            # test
            self.db.fetch_one("SELECT 1")
        except Exception as e:
            print(f"[PayoutService] Database connection lost, reconnecting: {e}")
            try:
                self.db.close()
            except:
                pass
            self.db = self._create_db_connection()
    
    def close(self):
        self.db.close()