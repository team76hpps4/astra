function results = simulate_environment(config, ap_configs)
% SIMULATE_ENVIRONMENT_SENSING_MERGED
% Combines:
% 1. ROBUST LEGACY PHYSICS (Walls, Rician Fading, Retry Logic, RSSI Coupling)
% 2. NEW VIRTUAL SENSING (Spectrum Analyzer, Duty Cycle, Non-WiFi, Noise Floor)
%% -------------------- Handle inputs & defaults --------------------
if nargin < 1 || isempty(config)
    config = default_config_enhanced();
end
if nargin < 2 || isempty(ap_configs)
    ap_configs = default_ap_configs_enhanced(config);
end
rng(config.random_seed);
num_AP = numel(ap_configs);
if num_AP == 0
    error('No APs provided in ap_configs.');
end
%% -------------------- Build geometry & clients --------------------
env = build_geometry_and_clients(config,ap_configs);
for a = 1:num_AP
    % Copy config into the environment structure for easy access
    env.APs(a).pos = ap_configs(a).pos;
    env.APs(a).tx_power_dbm = ap_configs(a).tx_power_dbm;
    env.APs(a).channel = ap_configs(a).channel;
    env.APs(a).channel_width_mhz = ap_configs(a).channel_width_mhz;
    env.APs(a).obss_pd_dbm = ap_configs(a).obss_pd_dbm;
    env.APs(a).network_id = ap_configs(a).network_id;
end
%% -------------------- RSSI matrices --------------------
[AP2AP_rssi_dbm, AP2Client_rssi_dbm] = precompute_rssi(env, config, ap_configs);
%% -------------------- Client Association --------------------
% Clients associate to the AP with the strongest long-term average RSSI
assoc = associate_clients(env, AP2Client_rssi_dbm, ap_configs);
%% -------------------- SENSING SETUP (NEW) --------------------
% Precompute Spectral Mask for the Virtual Spectrum Analyzer
Spectral_Mask = zeros(13, 13);
for tx_ch = 1:13
    for rx_ch = 1:13
        delta = abs(tx_ch - rx_ch);
        if delta == 0
            w = 1.0; 
        elseif delta < 4
            w = dbm2mw(-20 * delta); % -20dB per channel step
        else
            w = dbm2mw(-60); % Noise floor for distant channels
        end
        Spectral_Mask(tx_ch, rx_ch) = w;
    end
end
%% -------------------- Time loop setup --------------------
sim_time_ms = round(config.sim_duration_s * 1000);
dt_ms = config.dt_ms;
num_steps = ceil(sim_time_ms / dt_ms);
num_clients = size(env.client_positions,1);
% Fixed noise floor in mW
BW_Hz = config.channel_width_mhz * 1e6;
thermal_noise_dBm_ref = -174; % kT at 1 Hz
thermal_noise_dBm = thermal_noise_dBm_ref + 10*log10(BW_Hz);
noise_floor_dbm = thermal_noise_dBm + 7; % 7 dB noise figure
noise_floor_mw = dbm2mw(noise_floor_dbm);
cca_thresh_mw = dbm2mw(config.cca_threshold_dbm);
% Time-series storage
AP_airtime = zeros(num_AP, num_steps);
AP_instant_interf_mw = zeros(num_AP, num_steps); % Preserved for legacy stats
AP_retry_flag = zeros(num_AP, num_steps);
AP_interf_from_aps_mw = zeros(num_AP, num_steps);
Client_throughput_mbps_ts = zeros(num_clients, num_steps);
% -- SENSING DATA STORAGE (NEW) --
Sensed_Power_Map = zeros(num_AP, 13, num_steps, 'single'); 
NonWiFi_Flag_Map = zeros(num_AP, 13, num_steps, 'logical');
for step = 1:num_steps
    
    % Instantaneous non-wifi sampling (stochastic based on duty cycle)
    % NOTE: DT_MS scaling is explicitly removed here as requested.
    bt_mw_grid = sample_bluetooth_at_grid(env, config);
    zb_mw_grid = sample_zigbee_at_grid(env, config);
    % 1. Determine which APs transmit (based on CCA/OBSS-PD)
    tx_status = zeros(1, num_AP); % 1 if transmitted, 0 if idle/retry
    
    for a = 1:num_AP
        ap = env.APs(a);
        others = setdiff(1:num_AP, a);
        
        % --- A. Calculate Instantaneous Wi-Fi Interference (LEGACY LOGIC) ---
        % Includes short-term fading and channel overlap
        rssi_mean_db = AP2AP_rssi_dbm(a, others);
        rssi_rand_db = rssi_mean_db + config.short_term_shadowing_sigma * randn(size(rssi_mean_db));
        
        % Calculate weights only for APs in 'others' list
        weights = zeros(size(others));
        for k = 1:numel(others)
            weights(k) = channel_overlap_weights(ap, env.APs(others(k)), config);
        end
        
        interference_from_aps_mw = sum(dbm2mw(rssi_rand_db) .* weights);
        AP_interf_from_aps_mw(a, step) = interference_from_aps_mw;
        
        % --- B. Calculate Total Background Noise at AP ---
        nonwifi_mw = approximate_nonwifi_at_ap(ap.pos, env.client_positions, bt_mw_grid, zb_mw_grid, config);
        bg_noise_mw = noise_floor_mw * (1 + config.noise_variation_frac * randn);
        
        % Store instantaneous interference (LEGACY PRESERVATION)
        AP_instant_interf_mw(a, step) = interference_from_aps_mw + nonwifi_mw + bg_noise_mw;
        total_interf_dbm = mw2dbm(AP_instant_interf_mw(a, step));
        
        % --- C. CCA/OBSS-PD Decision (LOOSENED) ---
        is_idle = (total_interf_dbm < ap.obss_pd_dbm) || (total_interf_dbm < config.cca_threshold_dbm);
        
        if is_idle
            % Offered Tx Probability (DCF/ALOHA heuristic, competitive)
            tx_prob = offered_tx_probability_dcf(ap.channel, env.APs);
            if rand < tx_prob
                AP_airtime(a,step) = 1;
                AP_retry_flag(a,step) = 0;
                tx_status(a) = 1;
            else
                AP_airtime(a,step) = 0;
                AP_retry_flag(a,step) = 1; % Retry due to offered load (backoff)
            end
        else
            AP_airtime(a,step) = 0;
            AP_retry_flag(a,step) = 1; % Retry due to busy channel (CCA/OBSS-PD)
        end
    end
    
    % --- NEW: VIRTUAL SENSING RADIO (The Scan) ---
    % Runs parallel to MAC, doesn't affect tx_status but records spectrum
    active_tx_indices = find(tx_status == 1);
    for a = 1:num_AP
        % Base noise
        base_noise = noise_floor_mw * (1 + 0.05*randn);
        % Non-WiFi at Sensor
        nw_mw_base = approximate_nonwifi_at_ap(env.APs(a).pos, env.client_positions, bt_mw_grid, zb_mw_grid, config);
        
        for ch = 1:13
            wifi_pwr_sum = 0;
            % Calculate WiFi Power on Channel 'ch' from Active Neighbors
            for k = active_tx_indices
                if k == a, continue; end 
                
                % Use precomputed RSSI (approximate for sensing speed)
                rssi_val = AP2AP_rssi_dbm(a, k); 
                p_rx_mw = dbm2mw(rssi_val);
                
                % Apply Spectral Mask
                tx_ch = env.APs(k).channel;
                mask_val = Spectral_Mask(tx_ch, ch);
                wifi_pwr_sum = wifi_pwr_sum + (p_rx_mw * mask_val);
            end
            
            % Non-WiFi Mapping
            nw_pwr_ch = 0;
            if ismember(ch, [1 6 11])
                 nw_pwr_ch = nw_mw_base; % Zigbee presence
            else
                 nw_pwr_ch = nw_mw_base * 0.1; % Just BT bleed
            end
            
            total_pwr = wifi_pwr_sum + nw_pwr_ch + base_noise;
            Sensed_Power_Map(a, ch, step) = total_pwr;
            
            if (nw_pwr_ch > cca_thresh_mw) && (wifi_pwr_sum < cca_thresh_mw)
                NonWiFi_Flag_Map(a, ch, step) = true;
            end
        end
    end
    
    % 2. Calculate Client Throughput for APs that Transmitted (tx_status == 1)
    for a = find(tx_status == 1)
        ap = env.APs(a);
        associated_clients = find(assoc == a);
        num_clients_on_ap = numel(associated_clients);
        
        if num_clients_on_ap > 0
            % Airtime is shared among associated clients
            airtime_share = 1 / num_clients_on_ap;
            
            % --- D. Calculate Inter-AP Interference for Clients (LEGACY LOGIC) ---
            interfering_tx_aps_idx = setdiff(find(tx_status == 1), a);
            
            for c_idx = associated_clients'
                client_pos = env.client_positions(c_idx,:);
                
                % Signal RSSI (Mean Pathloss + Fading)
                pl_calc = pathloss_calc(ap.pos, client_pos, config);
                signal_dbm_mean = ap.tx_power_dbm - pl_calc;
                walls_count = estimate_walls_between(ap.pos, client_pos, config);
                fading_db = small_scale_fading_db_enhanced(walls_count);
                signal_mw = dbm2mw(signal_dbm_mean + fading_db);
                
                % Non-AP interference
                non_ap_interf_mw = AP_instant_interf_mw(a, step) - AP_interf_from_aps_mw(a, step);
                
                % Interference from other transmitting APs
                interf_mw = non_ap_interf_mw;
                for k = interfering_tx_aps_idx
                    other_ap = env.APs(k);
                    % Pathloss
                    pl_client = pathloss_calc(other_ap.pos, client_pos, config);
                    rssi_interf_dbm = other_ap.tx_power_dbm - pl_client;
                    % Check channel overlap
                    weight = channel_overlap_weights(ap, other_ap, config);
                    interf_mw = interf_mw + dbm2mw(rssi_interf_dbm) * weight;
                end
                
                % --- E. Calculate SINR & Throughput ---
                sinr_lin = signal_mw / max(interf_mw, 1e-12);
                sinr_db = 10*log10(sinr_lin);
                [rate_mbps, per] = map_sinr_to_rate_per_ber(sinr_db, ap.channel_width_mhz, config);
                
                % Throughput contribution
                Client_throughput_mbps_ts(c_idx, step) = rate_mbps * (1 - per) * airtime_share;
            end
        end
    end
end
%% -------------------- Aggregate results --------------------
AP_throughput_mbps_ts = zeros(num_AP, num_steps);
for a = 1:num_AP
    % Sum client throughputs for AP throughput
    associated_clients = find(assoc == a);
    if ~isempty(associated_clients)
        AP_throughput_mbps_ts(a, :) = sum(Client_throughput_mbps_ts(associated_clients, :), 1);
    end
end
results = struct();
results.config = config;
results.env = env;
results.AP2AP_rssi_dbm = AP2AP_rssi_dbm;
results.AP2Client_rssi_dbm = AP2Client_rssi_dbm;
results.perAP = repmat(struct(), num_AP, 1);
results.channels_list = unique([env.APs(:).channel]);
results.perChannel = repmat(struct(), numel(results.channels_list), 1);
% Legacy Aggregation
for a = 1:num_AP
    thr_samples = AP_throughput_mbps_ts(a, :);
    associated_clients = find(assoc == a);
    
    results.perAP(a).network_id = env.APs(a).network_id; % Added for filtering
    results.perAP(a).channel = env.APs(a).channel;
    results.perAP(a).median_throughput_mbps = median(thr_samples);
    results.perAP(a).mean_throughput_mbps = mean(thr_samples);
    results.perAP(a).p95_throughput_mbps = prctile(thr_samples, 95);
    results.perAP(a).p95_retry = prctile(AP_retry_flag(a,:), 95);
    results.perAP(a).avg_channel_util_percent = mean(AP_airtime(a,:))*100;
    
    % Using preserved AP_instant_interf_mw for consistency with old logic
    results.perAP(a).mean_total_interf_dbm = mw2dbm(mean(AP_instant_interf_mw(a,:)));
    
    results.perAP(a).avg_client_count = length(associated_clients);
    results.perAP(a).avg_retry_percent = mean(AP_retry_flag(a,:)) * 100;
end
% Per-Channel Aggregation
for i = 1:numel(results.channels_list)
    ch = results.channels_list(i);
    results.perChannel(i).channel_id = ch;
    
    ch_aps_idx = find([env.APs(:).channel] == ch);
    
    % Aggregate Utilization
    ch_util_samples = mean(AP_airtime(ch_aps_idx, :), 1);
    results.perChannel(i).avg_channel_util_percent = mean(ch_util_samples)*100;
    
    % Aggregate Throughput
    if isempty(ch_aps_idx)
        ch_thr_samples = 0;
    else
        ch_thr_samples = sum(AP_throughput_mbps_ts(ch_aps_idx, :), 1);
    end
    
    results.perChannel(i).total_median_throughput_mbps = median(ch_thr_samples);
    results.perChannel(i).total_mean_throughput_mbps = mean(ch_thr_samples);
    results.perChannel(i).total_p95_throughput_mbps = prctile(ch_thr_samples, 95);
end
% Time Series Storage
results.time = struct();
results.time.AP_airtime = AP_airtime;
results.time.AP_throughput_mbps_ts = AP_throughput_mbps_ts;
results.time.Client_throughput_mbps_ts = Client_throughput_mbps_ts;
results.time.AP_retry_flag = AP_retry_flag; % Added for completeness
% --- NEW: Aggregating Sensing Metrics (The 4 Parameters) ---
results.Sensing_Data = repmat(struct(), num_AP, 1);
for a = 1:num_AP
    p95_power_dbm = zeros(13,1);
    duty_cycle_p50 = zeros(13,1);
    prob_non_wifi = zeros(13,1);
    noise_floor_p95_dbm = zeros(13,1);
    
    for ch = 1:13
        pwr_series = reshape(Sensed_Power_Map(a, ch, :), [], 1);
        nw_flags = reshape(NonWiFi_Flag_Map(a, ch, :), [], 1);
        
        % 1. Interference Power (P95)
        p95_mw = prctile(pwr_series, 95);
        p95_power_dbm(ch) = mw2dbm(p95_mw);
        
        % 2. Duty Cycle (P50)
        is_busy = pwr_series > cca_thresh_mw;
        duty_cycle_p50(ch) = mean(is_busy); 
        
        % 3. Prob Non-WiFi
        total_busy_steps = sum(is_busy);
        if total_busy_steps > 0
            prob_non_wifi(ch) = sum(nw_flags) / num_steps;
        else
            prob_non_wifi(ch) = 0;
        end
        
        % 4. Noise Floor (P95 of Idle)
        idle_samples = pwr_series(~is_busy);
        if isempty(idle_samples)
            noise_floor_p95_dbm(ch) = mw2dbm(min(pwr_series)); 
        else
            noise_floor_p95_dbm(ch) = mw2dbm(prctile(idle_samples, 95));
        end
    end
    
    results.Sensing_Data(a).Metrics_Table = table((1:13)', p95_power_dbm, duty_cycle_p50, prob_non_wifi, noise_floor_p95_dbm, ...
        'VariableNames', {'Channel', 'Interf_P95_dBm', 'DutyCycle_P50', 'Prob_NonWiFi', 'NoiseFloor_P95_dBm'});
end
results.AP_Throughput = sum(Client_throughput_mbps_ts, 2); 
%% =====================================================
%  FINAL 59×num_AP OUTPUT MATRIX
%  Structure per AP column:
%  [4 AP-config rows
%   13 Interference rows
%   13 DutyCycle rows
%   13 ProbNonWiFi rows
%   13 NoiseFloor rows
%   Throughput
%   RetryRate
%   ClientCount]
% ======================================================
rows_total = 59;   % 4 + 13 + 13 + 13 +13 + 3
Final_Output_Matrix = zeros(rows_total, num_AP);
for a = 1:num_AP
    APch = env.APs(a).channel;
    APw  = env.APs(a).channel_width_mhz;
    APpd = env.APs(a).obss_pd_dbm;
    APtx = env.APs(a).tx_power_dbm;
    SENS = results.Sensing_Data(a).Metrics_Table;
    Col = zeros(rows_total,1);
    %% ---- 1) AP basic parameters ----
    Col(1) = APch;
    Col(2) = APw;
    Col(3) = APpd;
    Col(4) = APtx;
    %% ---- 2) Interference P95 for all channels ----
    Col(5:17) = SENS.Interf_P95_dBm;
    %% ---- 3) Duty cycle P50 for all channels ----
    Col(18:30) = SENS.DutyCycle_P50;
    %% ---- 4) Prob Non-WiFi ----
    Col(31:43) = SENS.Prob_NonWiFi;
    %% ---- 5) Noise Floor P95 ----
    Col(44:56) = SENS.NoiseFloor_P95_dBm;
    %% ---- 6) AP summary metrics ----
    Col(57) = results.perAP(a).p95_throughput_mbps;
    Col(58) = results.perAP(a).p95_retry;
    Col(59) = results.perAP(a).avg_client_count;
    Final_Output_Matrix(:, a) = Col;
end
results.Final_Output_Matrix = Final_Output_Matrix;
%% ============================================
%   CHANNEL OVERLAP MATRIX (num_AP × num_AP)
%% =============================================
Channel_Overlap_Matrix = zeros(num_AP, num_AP);
for a = 1:num_AP
    for b = 1:num_AP
        Channel_Overlap_Matrix(a,b) = channel_overlap_weights(env.APs(a), env.APs(b), config);
    end
end
results.Channel_Overlap_Matrix = Channel_Overlap_Matrix;
disp("Generated Final_Output_Matrix (59 × num_AP)");
fprintf('Simulation finished: %d steps (dt %d ms) => %.2f s simulated\n', ...
        num_steps, dt_ms, num_steps*dt_ms/1000);
end
%% -------------------- Default config & helper functions (LEGACY PRESERVED) --------------------
function cfg = default_config_enhanced()
    cfg.random_seed = 123;
    cfg.sim_duration_s = 10;
    cfg.dt_ms = 10;
    cfg.channel_width_mhz = 80;
    % noise & shadowing
    cfg.noise_floor_dbm = -95;
    cfg.noise_variation_frac = 0.03;
    cfg.short_term_shadowing_sigma = 6;
    cfg.shadowing_sigma = 4;
    % detectors (LOOSENED)
    cfg.cca_threshold_dbm = -35;
    % geometry
    cfg.room_size = [10, 10];
    cfg.num_rooms = 4;
    cfg.ap_per_room = 3;
    cfg.client_grid_spacing = 2;
    % non-wifi interferers
    cfg.bt.count = 6;
    cfg.bt.tx_power_dbm = 0;
    cfg.bt.duty_cycle = 0.002;
    cfg.zb.count = 1;
    cfg.zb.tx_power_dbm = -5;
    cfg.zb.duty_cycle = 0.001;
    cfg.channels = 1:13;
    % MCS Lookup Tables (LEGACY NAMES PRESERVED)
    cfg.MCS_SINR_Required = [0,1.5,3.5,5,8,10,12,13,15,17,18,20];
    cfg.MCS_Rates_20MHz = [6.5,13,19.5,26,39,52,58.5,65,78,86.7,97.5,108.3];
    % Path Loss Model Parameters
    cfg.pathloss.n_exp = 3.8;
    cfg.pathloss.wall_loss_db = 13;
    cfg.pathloss.PL_d0_dB = 30;
    cfg.pathloss.d0 = 1;
end
function ap_configs = default_ap_configs_enhanced(cfg)
    num_rooms = cfg.num_rooms;
    ap_per_room = cfg.ap_per_room;
    total = num_rooms * ap_per_room;
    ap_configs = repmat(struct(), total, 1);
    idx = 1;
    channels = [1, 6, 11]; 
    for r = 1:num_rooms
        base_x = (r-1) * (cfg.room_size(1) + 1);
        ap_configs(idx).pos = [ base_x + 2, cfg.room_size(2)/2 ];
        ap_configs(idx).tx_power_dbm = 18;
        ap_configs(idx).channel_width_mhz = 20;
        ap_configs(idx).channel = channels(1);
        ap_configs(idx).obss_pd_dbm = -35;  
        ap_configs(idx).network_id = 1;
        idx = idx + 1;
        ap_configs(idx).pos = [ base_x + 5, cfg.room_size(2)/2 ];
        ap_configs(idx).tx_power_dbm = 18;
        ap_configs(idx).channel_width_mhz = 20;
        ap_configs(idx).channel = channels(2);
        ap_configs(idx).obss_pd_dbm = -35;
        ap_configs(idx).network_id = 2;
        idx = idx + 1;
        ap_configs(idx).pos = [ base_x + 8, cfg.room_size(2)/2 ];
        ap_configs(idx).tx_power_dbm = 18;
        ap_configs(idx).channel_width_mhz = 20;
        ap_configs(idx).channel = channels(3);
        ap_configs(idx).obss_pd_dbm = -35;
        ap_configs(idx).network_id = 3;
        idx = idx + 1;
    end
end
function env = build_geometry_and_clients(cfg, ap_configs)
    env = struct();
    
    % --- 1. GENERATE CLIENTS (CLUSTERED AROUND APs) ---
    % Instead of a global grid, we place a grid of clients INSIDE each AP's room.
    
    all_client_pos = [];
    
    % We assume APs belonging to the same 'Network ID' or 'Room' share space.
    % A simple robust way is to generate a small grid around EACH AP.
    
    % Define a local grid relative to an AP (e.g., +/- 5m)
    local_w = cfg.client_grid_spacing;
    range = -5 : local_w : 5; 
    [lx, ly] = meshgrid(range, range);
    local_grid = [lx(:), ly(:)];
    
    for i = 1:numel(ap_configs)
        % Center the grid on this AP
        ap_pos = ap_configs(i).pos;
        
        % Shift local grid to AP position
        these_clients = local_grid + ap_pos;
        
        % Add to master list
        all_client_pos = [all_client_pos; these_clients];
    end
    
    % Remove duplicate clients (if APs are close) and limit total count if needed
    env.client_positions = unique(all_client_pos, 'rows');
    
    % --- 2. GENERATE INTERFERERS (SCATTERED AROUND APs) ---
    % Instead of global random (which might be far away), scatter them near the action
    
    % Bluetooth
    env.Interferers.BT = repmat(struct(), cfg.bt.count, 1);
    for i = 1:cfg.bt.count
        % Pick a random AP to haunt
        target_ap = ap_configs(randi(numel(ap_configs))).pos;
        % Scatter within 5m
        env.Interferers.BT(i).pos = target_ap + (rand(1,2)-0.5)*10; 
        env.Interferers.BT(i).tx_power_dbm = cfg.bt.tx_power_dbm;
    end
    
    % Zigbee
    env.Interferers.ZB = repmat(struct(), cfg.zb.count, 1);
    for i = 1:cfg.zb.count
        target_ap = ap_configs(randi(numel(ap_configs))).pos;
        env.Interferers.ZB(i).pos = target_ap + (rand(1,2)-0.5)*10;
        env.Interferers.ZB(i).tx_power_dbm = cfg.zb.tx_power_dbm;
    end
end
function [AP2AP_rssi_dbm, AP2Client_rssi_dbm] = precompute_rssi(env, cfg, ap_configs)
    num_AP = numel(env.APs);
    num_clients = size(env.client_positions,1);
    AP2AP_rssi_dbm = -200 * ones(num_AP, num_AP);
    AP2Client_rssi_dbm = -200 * ones(num_clients, num_AP);
    for j = 1:num_AP
        tx_pos = ap_configs(j).pos;
        tx_power = ap_configs(j).tx_power_dbm;
        for i = 1:num_AP
            if i == j, continue; end
            rx_pos = ap_configs(i).pos;
            pl = pathloss_calc(tx_pos, rx_pos, cfg);
            AP2AP_rssi_dbm(i,j) = tx_power - pl;
        end
        for c = 1:num_clients
            client_pos = env.client_positions(c,:);
            plc = pathloss_calc(tx_pos, client_pos, cfg);
            AP2Client_rssi_dbm(c,j) = tx_power - plc;
        end
    end
end
function pl_db = pathloss_calc(tx_pos, rx_pos, cfg)
    % Log-distance path loss model with wall loss and shadowing (LEGACY PRESERVED)
    d0 = cfg.pathloss.d0;
    PL0 = cfg.pathloss.PL_d0_dB;
    n = cfg.pathloss.n_exp;
    d = max(norm(tx_pos - rx_pos), d0);
    walls = estimate_walls_between(tx_pos, rx_pos, cfg);
    % Use configurable wall loss
    wall_loss_db = cfg.pathloss.wall_loss_db * walls;
    shadow = cfg.shadowing_sigma * randn;
    pl_db = PL0 + 10*n*log10(d/d0) + wall_loss_db + shadow;
end
function walls = estimate_walls_between(a, b, cfg)
    % Simple wall detection based on room boundaries
    room_w = cfg.room_size(1) + 1;
    ra = max(1, floor(a(1) / room_w) + 1);
    rb = max(1, floor(b(1) / room_w) + 1);
    walls = double(ra ~= rb);
end
function w = channel_overlap_weights(thisAP, otherAP, ~)
    % Simple 2.4 GHz non-overlapping channel model (deeper floor for realism)
    ch1 = thisAP.channel;
    ch2 = otherAP.channel;
    delta_ch = abs(ch1 - ch2);
    if ch1 == ch2
        w = 1.0; % Co-channel interference (full overlap)
    elseif delta_ch <= 4
        % Adjacent or partial overlap (e.g., 1->2, 6->8)
        w_db = -10 * (delta_ch - 1);
        w = dbm2mw(w_db);
    else
        % Non-overlapping (e.g., 1 and 6, 6 and 11)
        w = 10^(-45/10); % -45 dB floor
    end
end
function nonwifi_mw = approximate_nonwifi_at_ap(ap_pos, grid_pts, bt_mw, zb_mw, cfg)
    dists = sqrt(sum((grid_pts - ap_pos).^2, 2));
    dists = max(dists, 0.5);
    weights = 1./(dists.^2);
    weights = weights / sum(weights);
    nonwifi_mw = sum(weights .* (bt_mw(:) + zb_mw(:)));
end
function bt_mw = sample_bluetooth_at_grid(env, cfg)
    % NOTE: Scaling by DT_MS removed as requested. Probability is fixed per step.
    grid_count = size(env.client_positions,1);
    bt_mw = zeros(grid_count,1);
    for b = 1:cfg.bt.count
        if rand < cfg.bt.duty_cycle
            tx_idx = randi(grid_count);
            tx_pos = env.client_positions(tx_idx,:);
            for g = 1:grid_count
                pl = pathloss_calc(tx_pos, env.client_positions(g,:), cfg);
                pr_dbm = cfg.bt.tx_power_dbm - pl;
                bt_mw(g) = bt_mw(g) + dbm2mw(pr_dbm) * (0.8 + 0.4*rand);
            end
        end
    end
end
function zb_mw = sample_zigbee_at_grid(env, cfg)
    % NOTE: Scaling by DT_MS removed as requested. Probability is fixed per step.
    grid_count = size(env.client_positions,1);
    zb_mw = zeros(grid_count,1);
    for z = 1:cfg.zb.count
        if rand < cfg.zb.duty_cycle
            tx_idx = randi(grid_count);
            tx_pos = env.client_positions(tx_idx,:);
            for g = 1:grid_count
                pl = pathloss_calc(tx_pos, env.client_positions(g,:), cfg);
                pr_dbm = cfg.zb.tx_power_dbm - pl;
                zb_mw(g) = zb_mw(g) + dbm2mw(pr_dbm) * (0.9 + 0.2*rand);
            end
        end
    end
end
function prob = offered_tx_probability_dcf(channel_id, all_APs)
    num_competing_aps = sum([all_APs(:).channel] == channel_id);
    base_prob = 2.5;  
    prob = base_prob / (1 + 0.1 * (num_competing_aps - 1));
    prob = min(prob, 0.98);
end
function assoc = associate_clients(env, AP2Client_rssi_dbm, ~)
    num_clients = size(env.client_positions,1);
    assoc = zeros(num_clients,1);
    for c = 1:num_clients
        [~, best] = max(AP2Client_rssi_dbm(c,:));
        assoc(c) = best;
    end
end
function fading_db = small_scale_fading_db_enhanced(walls)
    % Rician (no walls) / Rayleigh (walls) composite fading model (LEGACY PRESERVED)
    if walls == 0
        K_dB = 8 + 4*rand;
        K = 10^(K_dB/10);
        sigma = 2.0 + 0.5*rand;  
    else
        K = 0;
        sigma = 3.0 + rand;  
    end
    if K > 0
        los = sqrt(K/(K+1));
        nlos = sqrt(1/(K+1)) * (randn + 1j*randn)/sqrt(2);
        h = los + nlos;
    else
        h = (randn + 1j*randn)/sqrt(2);
    end
    fading_power_db = 20 * log10(abs(h));
    fading_db = fading_power_db + sigma * randn;
end
function [rate_mbps, per] = map_sinr_to_rate_per_ber(SINR_dB, bw_mhz, cfg)
    % Maps SINR to MCS Rate and PER using a BER-based model (LEGACY PRESERVED)
    sinr_req = cfg.MCS_SINR_Required;
    rates20 = cfg.MCS_Rates_20MHz;
    if SINR_dB < sinr_req(1)
        rate_mbps = 0; per = 1.0; return;
    end
    idx = find(SINR_dB >= sinr_req, 1, 'last');
    if isempty(idx)
        idx = 1;
    end
    rate20 = rates20(idx);
    scale = bw_mhz / 20;
    rate_mbps = rate20 * scale;
    
    SINR_lin = 10^(SINR_dB/10);
    k = 0.5;  
    Nbits = 2000 + randi([-200,200]);
    BER = 0.5 * exp(-k * SINR_lin);
    per = 1 - (1 - BER)^Nbits;
    per = min(max(per, 0.001), 0.999);
end
function m = dbm2mw(dbm), m = 10.^(dbm/10); end
function dbm = mw2dbm(mw), dbm = 10*log10(max(mw,1e-30)); end