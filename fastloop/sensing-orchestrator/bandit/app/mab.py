import numpy as np
from collections import deque
from typing import Optional, Tuple, Dict


class StateBandit:
    """
    Contextual Multi-Armed Bandit with Neural-Linear Model for RF spectrum monitoring.
    
    Uses Thompson Sampling with a shallow neural network for feature extraction
    and Bayesian Linear Regression for reward prediction.
    
    Workflow:
    1. Steps 0-83: Force pull all channels sequentially to fill state (6 pulls per channel)
    2. Steps 84-211: Standard Thompson Sampling with simple reward (vs EWA)
    3. Step 212: First NN training (2 epochs)
    4. Steps 212+: Neural-Linear Thompson Sampling, NN trains every 128 steps (1 epoch)
    """
    
    def __init__(
        self,
        num_channels: int = 14,
        context_dim: int = 11,
        feature_dim: int = 20,  # Changed from 10 to 20
        window_size: int = 6,
        nn_train_interval: int = 128,
        learning_rate: float = 0.001,
        reg_lambda: float = 1.0,
        nu_sq: float = 1.0,
        grad_clip_norm: float = 5.0
    ):
        """
        Initialize the State Bandit.
        
        Args:
            num_channels: Number of channels (arms) to monitor
            context_dim: Dimension of context vector (fixed at 11)
            feature_dim: Dimension of neural network output features (changed to 20)
            window_size: Size of sliding window for statistics (fixed at 6)
            nn_train_interval: Train NN every N timesteps (default 128)
            learning_rate: Learning rate for NN gradient descent
            reg_lambda: Regularization parameter for BLR prior
            nu_sq: Observation noise variance
            grad_clip_norm: Maximum gradient norm for clipping (default 5.0)
        """
        self.num_channels = num_channels
        self.context_dim = context_dim
        self.feature_dim = feature_dim  # Now 20
        self.window_size = window_size
        self.nn_train_interval = nn_train_interval
        self.learning_rate = learning_rate
        self.reg_lambda = reg_lambda
        self.nu_sq = nu_sq
        self.grad_clip_norm = grad_clip_norm
        
        # EWA smoothing factor
        self.alpha_ewa = 0.2
        
        # State tracking
        self.timestep = 0
        self.awaiting_feedback = False
        self.last_chosen_channel = None
        
        # Phase tracking
        self.warmup_steps = num_channels * window_size  # 84 for 14 channels
        self.first_training_step = self.warmup_steps + nn_train_interval  # 212
        
        # Interference type mapping (used for reward calculation only)
        self.interference_map = {
            'empty': 0,
            'wifi': 1,
            'bluetooth': 2,
            'zigbee': 3,
            'microwave': 4
        }
        
        # Initialize channel state
        self._init_channel_state()
        
        # Initialize neural network
        self._init_neural_network()
        
        # Initialize Bayesian Linear Regressor
        self._init_blr()
        
        # Training buffer for NN (stores most recent 128 experiences)
        # Each entry: (context, reward)
        self.training_buffer = deque(maxlen=128)
        
        # Track NN training status
        self.nn_training_count = 0
        
    def _init_channel_state(self):
        """Initialize state tracking for all channels."""
        # Sliding window history: stores (I, D) tuples separately for each channel
        self.history = [
            deque([(0.0, 0.0)] * self.window_size, maxlen=self.window_size)
            for _ in range(self.num_channels)
        ]
        
        # Last observed classification value per channel (for reward calculation only)
        self.last_cv = np.zeros(self.num_channels, dtype=int)
        
        # Time since last dwell on each channel
        self.t_since_dwell = np.zeros(self.num_channels)
        
        # Last pulled (I, D) values per channel
        self.last_pull_value = np.zeros((self.num_channels, 2))
        
        # Exponential weighted average (I, D) per channel
        self.ewa_avg = np.zeros((self.num_channels, 2))
        
    def _init_neural_network(self):
        """Initialize neural network for feature extraction: 11 -> 48 -> 32 -> 20."""
        # Three-layer network: context_dim -> hidden1 -> hidden2 -> feature_dim
        hidden1_dim = 48
        hidden2_dim = 32
        
        # Xavier/He initialization
        self.W1 = np.random.randn(self.context_dim, hidden1_dim) * np.sqrt(2.0 / self.context_dim)
        self.B1 = np.zeros(hidden1_dim)
        self.W2 = np.random.randn(hidden1_dim, hidden2_dim) * np.sqrt(2.0 / hidden1_dim)
        self.B2 = np.zeros(hidden2_dim)
        self.W3 = np.random.randn(hidden2_dim, self.feature_dim) * np.sqrt(2.0 / hidden2_dim)
        self.B3 = np.zeros(self.feature_dim)
        
        # Momentum for optimization
        self.momentum = 0.9
        self.W1_velocity = np.zeros_like(self.W1)
        self.B1_velocity = np.zeros_like(self.B1)
        self.W2_velocity = np.zeros_like(self.W2)
        self.B2_velocity = np.zeros_like(self.B2)
        self.W3_velocity = np.zeros_like(self.W3)
        self.B3_velocity = np.zeros_like(self.B3)
        
    def _init_blr(self):
        """Initialize Bayesian Linear Regression parameters."""
        # Posterior mean of weights (now 20-dimensional)
        self.M = np.zeros(self.feature_dim)
        
        # Posterior covariance matrix (maintain only this, not the inverse)
        self.Q = (1.0 / self.reg_lambda) * np.identity(self.feature_dim)
        
    def _relu(self, x: np.ndarray) -> np.ndarray:
        """ReLU activation function."""
        return np.maximum(0, x)
    
    def _relu_derivative(self, x: np.ndarray) -> np.ndarray:
        """Derivative of ReLU."""
        return (x > 0).astype(float)
    
    def _nn_forward(self, phi_t: np.ndarray, return_cache: bool = False):
        """
        Forward pass through neural network: 11 -> 48 -> 32 -> 20.
        
        Args:
            phi_t: Context vector (size 11)
            return_cache: If True, return intermediate values for backprop
            
        Returns:
            Feature vector z_t (size 20) and optionally cache
        """
        # Layer 1: 11 -> 48
        z1 = phi_t @ self.W1 + self.B1
        h1 = self._relu(z1)
        
        # Layer 2: 48 -> 32
        z2 = h1 @ self.W2 + self.B2
        h2 = self._relu(z2)
        
        # Layer 3: 32 -> 20
        z_t = h2 @ self.W3 + self.B3
        
        if return_cache:
            return z_t, {'phi_t': phi_t, 'z1': z1, 'h1': h1, 'z2': z2, 'h2': h2}
        return z_t
    
    def _nn_backward(self, cache: Dict, grad_output: np.ndarray):
        """
        Backward pass through neural network.
        
        Args:
            cache: Intermediate values from forward pass
            grad_output: Gradient from loss function
            
        Returns:
            Gradients for W1, B1, W2, B2, W3, B3
        """
        phi_t = cache['phi_t']
        z1 = cache['z1']
        h1 = cache['h1']
        z2 = cache['z2']
        h2 = cache['h2']
        
        # Gradient w.r.t W3 and B3
        grad_W3 = np.outer(h2, grad_output)
        grad_B3 = grad_output
        
        # Gradient w.r.t h2
        grad_h2 = grad_output @ self.W3.T
        
        # Gradient through ReLU (layer 2)
        grad_z2 = grad_h2 * self._relu_derivative(z2)
        
        # Gradient w.r.t W2 and B2
        grad_W2 = np.outer(h1, grad_z2)
        grad_B2 = grad_z2
        
        # Gradient w.r.t h1
        grad_h1 = grad_z2 @ self.W2.T
        
        # Gradient through ReLU (layer 1)
        grad_z1 = grad_h1 * self._relu_derivative(z1)
        
        # Gradient w.r.t W1 and B1
        grad_W1 = np.outer(phi_t, grad_z1)
        grad_B1 = grad_z1
        
        return grad_W1, grad_B1, grad_W2, grad_B2, grad_W3, grad_B3
    
    def _clip_gradients(self, grad_W1, grad_B1, grad_W2, grad_B2, grad_W3, grad_B3):
        """
        Clip gradients by global norm to prevent exploding gradients.
        
        Args:
            grad_W1, grad_B1, grad_W2, grad_B2, grad_W3, grad_B3: Gradient arrays
            
        Returns:
            Clipped gradients
        """
        # Calculate global norm
        global_norm = np.sqrt(
            np.sum(grad_W1**2) + 
            np.sum(grad_B1**2) + 
            np.sum(grad_W2**2) + 
            np.sum(grad_B2**2) +
            np.sum(grad_W3**2) + 
            np.sum(grad_B3**2)
        )
        
        # Clip if norm exceeds threshold
        if global_norm > self.grad_clip_norm:
            scale = self.grad_clip_norm / global_norm
            grad_W1 = grad_W1 * scale
            grad_B1 = grad_B1 * scale
            grad_W2 = grad_W2 * scale
            grad_B2 = grad_B2 * scale
            grad_W3 = grad_W3 * scale
            grad_B3 = grad_B3 * scale
        
        return grad_W1, grad_B1, grad_W2, grad_B2, grad_W3, grad_B3
    
    def _build_context(self, channel_idx: int) -> np.ndarray:
        """
        Build context vector for a specific channel.
        
        Context vector (11 features):
        1-2. Mean of I and D over last 6 pulls
        3-4. Mean of I and D over last 3 pulls
        5-6. Last pulled I and D values
        7-8. EWA of I and D
        9-10. Std dev of I and D over last 6 pulls
        11. Time since last dwell
        
        Args:
            channel_idx: Channel index
            
        Returns:
            Context vector of shape (11,)
        """
        hist_data = np.array(self.history[channel_idx])  # Shape: (6, 2)
        
        hist_I = hist_data[:, 0]
        hist_D = hist_data[:, 1]
        
        # Statistics over last 6 observations
        mu_6_I = np.mean(hist_I)
        mu_6_D = np.mean(hist_D)
        sigma_6_I = np.std(hist_I)
        sigma_6_D = np.std(hist_D)
        
        # Statistics over last 3 observations
        mu_3_I = np.mean(hist_I[-3:])
        mu_3_D = np.mean(hist_D[-3:])
        
        # Last pull values
        last_I = self.last_pull_value[channel_idx, 0]
        last_D = self.last_pull_value[channel_idx, 1]
        
        # EWA values
        ewa_I = self.ewa_avg[channel_idx, 0]
        ewa_D = self.ewa_avg[channel_idx, 1]
        
        # Build context vector
        context = np.array([
            mu_6_I, mu_6_D,
            mu_3_I, mu_3_D,
            last_I, last_D,
            ewa_I, ewa_D,
            sigma_6_I, sigma_6_D,
            self.t_since_dwell[channel_idx]
        ])
        
        return context
    
    def _calculate_reward_simple(
        self,
        channel_idx: int,
        current_I: float,
        current_D: float,
        current_cv: int
    ) -> float:
        """
        Calculate reward for simple TS phase (steps 84-211).
        
        Uses EWA as baseline instead of previous observation.
        
        Args:
            channel_idx: Channel index
            current_I: Current interference power
            current_D: Current duty cycle
            current_cv: Current classification value
            
        Returns:
            Reward value
        """
        previous_cv = self.last_cv[channel_idx]
        ewa_I = self.ewa_avg[channel_idx, 0]
        ewa_D = self.ewa_avg[channel_idx, 1]
        
        # Novelty: New interference detected
        novelty_reward = 1.0 if previous_cv != current_cv else 0.0
        
        # Volatility: Change from EWA baseline
        diff_I = abs(current_I - ewa_I)
        diff_D = abs(current_D - ewa_D)
        volatility_reward = (diff_I + diff_D) / 2.0
        
        # Combined reward
        W_novelty = 0.6
        W_volatility = 0.4
        
        reward = W_novelty * novelty_reward + W_volatility * volatility_reward
        return reward
    
    def _calculate_reward_standard(
        self,
        channel_idx: int,
        current_I: float,
        current_D: float,
        current_cv: int
    ) -> float:
        """
        Calculate reward for neural-linear phase (steps 212+).
        
        Uses previous observation as baseline.
        
        Args:
            channel_idx: Channel index
            current_I: Current interference power
            current_D: Current duty cycle
            current_cv: Current classification value
            
        Returns:
            Reward value
        """
        previous_cv = self.last_cv[channel_idx]
        previous_I = self.last_pull_value[channel_idx, 0]
        previous_D = self.last_pull_value[channel_idx, 1]
        
        # Novelty: New interference detected
        novelty_reward = 1.0 if previous_cv != current_cv else 0.0
        
        # Volatility: Change in measurements
        diff_I = abs(current_I - previous_I)
        diff_D = abs(current_D - previous_D)
        volatility_reward = (diff_I + diff_D) / 2.0
        
        # Combined reward
        W_novelty = 0.6
        W_volatility = 0.4
        
        reward = W_novelty * novelty_reward + W_volatility * volatility_reward
        return reward
    
    def _update_blr_stable(self, z_t: np.ndarray, reward: float):
        """
        Online Bayesian Linear Regression update using Sherman-Morrison formula.
        
        This avoids explicit matrix inversion for numerical stability.
        Maintains only the covariance matrix Q, not its inverse.
        
        Args:
            z_t: Feature vector from NN (20-dimensional)
            reward: Observed reward
        """
        # Store old covariance for mean update (FIXED: use old Q for mean update)
        Q_old = self.Q.copy()
        
        # Sherman-Morrison formula for rank-1 update of covariance
        # Q_new = Q_old - (Q_old * z * z^T * Q_old) / (nu_sq + z^T * Q_old * z)
        
        Q_z = Q_old @ z_t
        denominator = self.nu_sq + z_t @ Q_z
        
        # Check for numerical stability
        if denominator < 1e-10:
            print(f"Warning: Small denominator {denominator} in BLR update, skipping")
            return
        
        # Update covariance matrix
        self.Q = Q_old - np.outer(Q_z, Q_z) / denominator
        
        # Update posterior mean using OLD covariance (FIXED)
        # M_new = M_old + (Q_old * z_t * (reward - z_t^T * M_old)) / (nu_sq + z_t^T * Q_old * z_t)
        prediction_error = reward - z_t @ self.M
        self.M = self.M + (Q_old @ z_t) * prediction_error / denominator
    
    def _train_neural_network(self):
        """
        Train neural network on accumulated experiences.
        
        Training schedule:
        - First training (step 212): 2 epochs, 16 samples per minibatch, 8 minibatches
        - Subsequent training: 1 epoch, 16 samples per minibatch, 8 minibatches
        
        Loss: Mean squared error between predicted reward and actual reward
        """
        if len(self.training_buffer) < 128:
            return
        
        # Determine epochs based on training count
        is_first_training = (self.nn_training_count == 0)
        num_epochs = 2 if is_first_training else 1
        
        print(f"\n[Training NN at timestep {self.timestep}]")
        print(f"  Training #{self.nn_training_count + 1}")
        print(f"  Epochs: {num_epochs}")
        print(f"  Buffer size: {len(self.training_buffer)}")
        
        # Training configuration
        minibatch_size = 16
        num_minibatches = 8
        
        # Convert buffer to list for indexing
        buffer_list = list(self.training_buffer)
        
        for epoch in range(num_epochs):
            epoch_loss = 0
            num_clipped = 0
            
            # Create minibatches
            indices = np.arange(len(buffer_list))
            np.random.shuffle(indices)
            
            for mb in range(num_minibatches):
                # Get minibatch indices
                start_idx = mb * minibatch_size
                end_idx = start_idx + minibatch_size
                mb_indices = indices[start_idx:end_idx]
                
                # Accumulate gradients over minibatch
                grad_W1_accum = np.zeros_like(self.W1)
                grad_B1_accum = np.zeros_like(self.B1)
                grad_W2_accum = np.zeros_like(self.W2)
                grad_B2_accum = np.zeros_like(self.B2)
                grad_W3_accum = np.zeros_like(self.W3)
                grad_B3_accum = np.zeros_like(self.B3)
                
                mb_loss = 0
                
                for idx in mb_indices:
                    context, actual_reward = buffer_list[idx]
                    
                    # Forward pass
                    z_t, cache = self._nn_forward(context, return_cache=True)
                    
                    # Predict reward using current BLR weights
                    predicted_reward = z_t @ self.M
                    
                    # Loss: MSE
                    loss = (predicted_reward - actual_reward) ** 2
                    mb_loss += loss
                    
                    # Gradient of loss w.r.t z_t
                    grad_z_t = 2 * (predicted_reward - actual_reward) * self.M
                    
                    # Backpropagation
                    grad_W1, grad_B1, grad_W2, grad_B2, grad_W3, grad_B3 = self._nn_backward(cache, grad_z_t)
                    
                    # Accumulate gradients
                    grad_W1_accum += grad_W1
                    grad_B1_accum += grad_B1
                    grad_W2_accum += grad_W2
                    grad_B2_accum += grad_B2
                    grad_W3_accum += grad_W3
                    grad_B3_accum += grad_B3
                
                # Average gradients over minibatch
                grad_W1_accum /= minibatch_size
                grad_B1_accum /= minibatch_size
                grad_W2_accum /= minibatch_size
                grad_B2_accum /= minibatch_size
                grad_W3_accum /= minibatch_size
                grad_B3_accum /= minibatch_size
                
                # Clip gradients
                grad_W1_accum, grad_B1_accum, grad_W2_accum, grad_B2_accum, grad_W3_accum, grad_B3_accum = \
                    self._clip_gradients(grad_W1_accum, grad_B1_accum, grad_W2_accum, grad_B2_accum, grad_W3_accum, grad_B3_accum)
                
                # Check if clipping occurred
                global_norm = np.sqrt(
                    np.sum(grad_W1_accum**2) + np.sum(grad_B1_accum**2) + 
                    np.sum(grad_W2_accum**2) + np.sum(grad_B2_accum**2) +
                    np.sum(grad_W3_accum**2) + np.sum(grad_B3_accum**2)
                )
                if global_norm >= self.grad_clip_norm - 1e-6:
                    num_clipped += 1
                
                # Apply momentum
                self.W1_velocity = self.momentum * self.W1_velocity + grad_W1_accum
                self.B1_velocity = self.momentum * self.B1_velocity + grad_B1_accum
                self.W2_velocity = self.momentum * self.W2_velocity + grad_W2_accum
                self.B2_velocity = self.momentum * self.B2_velocity + grad_B2_accum
                self.W3_velocity = self.momentum * self.W3_velocity + grad_W3_accum
                self.B3_velocity = self.momentum * self.B3_velocity + grad_B3_accum
                
                # Update weights
                self.W1 -= self.learning_rate * self.W1_velocity
                self.B1 -= self.learning_rate * self.B1_velocity
                self.W2 -= self.learning_rate * self.W2_velocity
                self.B2 -= self.learning_rate * self.B2_velocity
                self.W3 -= self.learning_rate * self.W3_velocity
                self.B3 -= self.learning_rate * self.B3_velocity
                
                epoch_loss += mb_loss
            
            avg_loss = epoch_loss / (num_minibatches * minibatch_size)
            print(f"  Epoch {epoch + 1}/{num_epochs}, Avg Loss: {avg_loss:.6f}, Clipped: {num_clipped}/{num_minibatches}")
        
        self.nn_training_count += 1
        print(f"NN training complete.\n")
    
    def select_channel(self) -> int:
        """
        Select a channel based on current phase.
        
        Phase 1 (steps 0-83): Force sequential pulls to fill state
        Phase 2 (steps 84-211): Simple Thompson Sampling (no NN)
        Phase 3 (steps 212+): Neural-Linear Thompson Sampling
        
        Returns:
            Selected channel number
        """
        if self.awaiting_feedback:
            raise RuntimeError(
                "Cannot select channel: awaiting feedback from previous selection. "
                f"Call update() for channel {self.last_chosen_channel}"
            )
        
        # Phase 1: Force sequential pulls (0-83)
        if self.timestep < self.warmup_steps:
            chosen_channel = self.timestep % self.num_channels
            self.awaiting_feedback = True
            self.last_chosen_channel = chosen_channel
            return chosen_channel
        
        # Phase 2: Simple Thompson Sampling (84-211)
        elif self.timestep < self.first_training_step:
            # Use simple reward-based Thompson Sampling without NN
            sampled_rewards = np.zeros(self.num_channels)
            
            for k in range(self.num_channels):
                # Simple heuristic: sample based on EWA statistics
                ewa_I = self.ewa_avg[k, 0]
                ewa_D = self.ewa_avg[k, 1]
                t_since = self.t_since_dwell[k]
                
                # Exploration bonus based on time since last visit
                exploration_bonus = np.sqrt(2 * np.log(self.timestep + 1) / (t_since + 1))
                
                # Sample reward estimate
                mean_reward = (ewa_I + ewa_D) / 2.0 + exploration_bonus
                sampled_rewards[k] = np.random.normal(mean_reward, 0.1)
            
            chosen_channel = int(np.argmax(sampled_rewards))
            self.awaiting_feedback = True
            self.last_chosen_channel = chosen_channel
            return chosen_channel
        
        # Phase 3: Neural-Linear Thompson Sampling (212+)
        else:
            # Build contexts for all channels
            contexts = np.array([self._build_context(c) for c in range(self.num_channels)])
            
            # Extract features using NN
            features = np.array([self._nn_forward(ctx) for ctx in contexts])
            
            # Thompson Sampling
            sampled_rewards = np.zeros(self.num_channels)
            
            for k in range(self.num_channels):
                z_t = features[k]
                
                # Posterior predictive distribution
                mu_k = z_t @ self.M
                sigma_sq_k = z_t @ self.Q @ z_t + self.nu_sq
                
                # Sample reward
                sampled_rewards[k] = np.random.normal(mu_k, np.sqrt(max(sigma_sq_k, 1e-6)))
            
            chosen_channel = int(np.argmax(sampled_rewards))
            self.awaiting_feedback = True
            self.last_chosen_channel = chosen_channel
            return chosen_channel
    
    def update(
        self,
        channel_number: int,
        interference_detected: str,
        interference_power: float,
        duty_cycle: float
    ) -> None:
        """
        Update the bandit with observed feedback.
        
        Args:
            channel_number: Channel that was monitored
            interference_detected: Type of interference
            interference_power: Normalized interference power [0, 1]
            duty_cycle: Normalized duty cycle [0, 1]
        """
        # Validate state
        if not self.awaiting_feedback:
            raise RuntimeError("No channel selection pending. Call select_channel() first.")
        
        if channel_number != self.last_chosen_channel:
            raise ValueError(
                f"Channel mismatch: expected {self.last_chosen_channel}, got {channel_number}"
            )
        
        # Validate interference type
        interference_type = interference_detected.lower()
        if interference_type not in self.interference_map:
            raise ValueError(
                f"Unknown interference type: '{interference_detected}'. "
                f"Valid types: {list(self.interference_map.keys())}"
            )
        
        cv = self.interference_map[interference_type]
        
        # Clip values
        I = np.clip(interference_power, 0.0, 1.0)
        D = np.clip(duty_cycle, 0.0, 1.0)
        
        # Calculate reward based on current phase
        if self.timestep < self.first_training_step:
            # Phase 1 & 2: Use simple reward (vs EWA)
            reward = self._calculate_reward_simple(channel_number, I, D, cv)
        else:
            # Phase 3: Use standard reward (vs previous)
            reward = self._calculate_reward_standard(channel_number, I, D, cv)
        
        # Get current context BEFORE updating state
        context = self._build_context(channel_number)
        
        # === UPDATE CHANNEL STATE ===
        
        # Update time since dwell for ALL channels
        self.t_since_dwell += 1
        self.t_since_dwell[channel_number] = 0
        
        # Update history
        self.history[channel_number].append((I, D))
        
        # Update EWA
        self.ewa_avg[channel_number, 0] = (1 - self.alpha_ewa) * self.ewa_avg[channel_number, 0] + self.alpha_ewa * I
        self.ewa_avg[channel_number, 1] = (1 - self.alpha_ewa) * self.ewa_avg[channel_number, 1] + self.alpha_ewa * D
        
        # Update last pull values
        self.last_pull_value[channel_number, 0] = I
        self.last_pull_value[channel_number, 1] = D
        self.last_cv[channel_number] = cv
        
        # === UPDATE MODELS ===
        
        # Add experience to buffer (always, to accumulate 128 samples)
        self.training_buffer.append((context, reward))
        
        # Neural-Linear updates (only after warmup)
        if self.timestep >= self.warmup_steps:
            # Extract features
            z_t = self._nn_forward(context)
            
            # Online BLR update
            self._update_blr_stable(z_t, reward)
        
        # NN training schedule
        self.timestep += 1
        
        # First training at step 212
        if self.timestep == self.first_training_step:
            self._train_neural_network()
        # Subsequent training every 128 steps after first training
        elif self.timestep > self.first_training_step:
            steps_since_first = self.timestep - self.first_training_step
            if steps_since_first % self.nn_train_interval == 0:
                self._train_neural_network()
        
        # Reset state
        self.awaiting_feedback = False
        self.last_chosen_channel = None
    
    def get_statistics(self) -> Dict:
        """Get current bandit statistics."""
        if self.timestep < self.warmup_steps:
            phase = f"Warmup ({self.timestep}/{self.warmup_steps})"
        elif self.timestep < self.first_training_step:
            phase = f"Simple TS ({self.timestep}/{self.first_training_step})"
        else:
            phase = f"Neural-Linear TS"
        
        return {
            'timestep': self.timestep,
            'phase': phase,
            'nn_training_count': self.nn_training_count,
            'buffer_size': len(self.training_buffer),
            'awaiting_feedback': self.awaiting_feedback,
            'blr_mean_norm': np.linalg.norm(self.M) if self.timestep >= self.warmup_steps else 0.0,
            'blr_cov_trace': np.trace(self.Q) if self.timestep >= self.warmup_steps else 0.0,
        }


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Initialize the bandit
    bandit = StateBandit(
        num_channels=14,
        nn_train_interval=128,
        learning_rate=0.001,
        grad_clip_norm=5.0
    )
    
    # Simulate spectrum monitoring
    print("=== RF Spectrum Monitoring Simulation ===")
    print(f"Channels: {bandit.num_channels}")
    print(f"Warmup phase: 0-{bandit.warmup_steps-1} (force pull all channels)")
    print(f"Simple TS phase: {bandit.warmup_steps}-{bandit.first_training_step-1}")
    print(f"Neural-Linear TS: {bandit.first_training_step}+\n")
    
    interference_types = ['empty', 'wifi', 'bluetooth', 'zigbee', 'microwave']
    channel_pulls = np.zeros(14)
    
    for t in range(400):
        # Select channel
        channel = bandit.select_channel()
        channel_pulls[channel] += 1
        
        # Simulate observation
        if channel == 5:
            interference = np.random.choice(['zigbee', 'bluetooth'])
            power = np.random.uniform(0.3, 0.9)
            duty = np.random.uniform(0.2, 0.8)
        elif channel == 10 and np.random.random() < 0.1:
            interference = 'microwave'
            power = 0.9
            duty = 0.1
        elif channel == 3:
            interference = 'bluetooth'
            power = np.random.uniform(0.4, 0.7)
            duty = np.random.uniform(0.3, 0.6)
        else:
            interference = np.random.choice(['wifi', 'empty'], p=[0.7, 0.3])
            power = np.random.uniform(0.2, 0.6)
            duty = np.random.uniform(0.2, 0.5)
        
        # Update bandit
        bandit.update(channel, interference, power, duty)
        
        # Log progress
        if (t + 1) % 50 == 0 or (t + 1) in [84, 212]:
            stats = bandit.get_statistics()
            print(f"\nStep {t + 1}:")
            print(f"  Phase: {stats['phase']}")
            print(f"  NN Trainings: {stats['nn_training_count']}")
            print(f"  Buffer Size: {stats['buffer_size']}")
            if stats['blr_mean_norm'] > 0:
                print(f"  BLR Mean Norm: {stats['blr_mean_norm']:.4f}")
    
    print("\n" + "="*60)
    print("FINAL RESULTS")
    print("="*60)
    print(f"Total Steps: {bandit.timestep}")
    print(f"\nChannel Pull Distribution:")
    for i, count in enumerate(channel_pulls):
        print(f"  Channel {i:2d}: {int(count):3d} pulls ({count/bandit.timestep:6.1%})")