# orchestrator/cidr_pool.py

import threading


class CIDRPool:
    def __init__(self, start=1, end=254):
        # Pool of available CIDR blocks: 10.1.0.0/16 through 10.254.0.0/16
        self.available = list(range(start, end + 1))
        self.in_use = {}  # FIX: keyed by session_id (not user_id) so one user can run multiple labs
        self.lock = threading.Lock()

    def acquire(self, session_id: str) -> str:
        with self.lock:
            if not self.available:
                raise Exception("No CIDR blocks available — max concurrent labs reached")
            octet = self.available.pop(0)
            self.in_use[session_id] = octet  # FIX: track by session_id
            return f"10.{octet}.0.0/16"

    def release(self, session_id: str):
        with self.lock:
            if session_id in self.in_use:
                octet = self.in_use.pop(session_id)
                self.available.append(octet)
                self.available.sort()

    def active_count(self) -> int:
        with self.lock:
            return len(self.in_use)
            
