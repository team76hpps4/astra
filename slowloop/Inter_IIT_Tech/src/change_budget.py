import numpy as np

class ChangeBudgetManager:
    def __init__(self, num_aps, refill_rate=1.0/48.0, max_tokens=1.5):
        """
        refill_rate: Tokens added per step (default 1 change per 48 steps/4 hours)
        """
        self.num_aps = num_aps
        self.refill_rate = refill_rate
        self.max_tokens = max_tokens
        # Start full so we can act immediately if needed
        self.ap_tokens = np.full(num_aps, 1.0) 

    def step_clock(self):
        """Refills tokens at the end of a simulation step."""
        self.ap_tokens += self.refill_rate
        # We allow debt (negative tokens), but cap the positive savings
        self.ap_tokens = np.clip(self.ap_tokens, -5.0, self.max_tokens) 

    def _calculate_cost(self, confidence_alpha):
        """
        Calculates the 'Entry Barrier' (Hurdle) based on RL confidence.
        High Confidence (0.9) -> Low Hurdle (0.1).
        Low Confidence (0.1) -> High Hurdle (0.9).
        """
        # Ensure cost hurdle is at least 0.1
        return max(0.1, 1.0 - confidence_alpha)

    def check_and_spend(self, changed_aps, confidence_alpha):
        """
        Checks budget for a list of APs.
        Logic:
          1. Calculate HURDLE (Cost) based on confidence.
          2. If Credit >= Hurdle: APPROVE.
          3. DEDUCTION: Always subtract 1.0 (Flat Fee).
        """
        hurdle_cost = self._calculate_cost(confidence_alpha)
        allowed_aps = []
        rejected_aps = []

        for ap_idx in changed_aps:
            # Check if we have enough credit to clear the hurdle
            # We also check a hard debt floor (e.g. -2.0) to prevent infinite debt
            if self.ap_tokens[ap_idx] >= hurdle_cost and self.ap_tokens[ap_idx] > -2.0:
                
                # --- THE CHANGE: Always subtract 1.0 ---
                self.ap_tokens[ap_idx] -= 1.0
                
                allowed_aps.append(ap_idx)
            else:
                rejected_aps.append(ap_idx)
        
        return allowed_aps, rejected_aps