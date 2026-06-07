function results = simulate_environment_5G(config, ap_configs)
% SIMULATE_ENVIRONMENT_5G
% 5 GHz variant of simulate_environment.m
% - Uses standard 25 UNII 5 GHz channels
% - Produces Sensing Metrics over 25 virtual 20MHz bins
% - Supports 20/40/80/160 MHz channel widths (AP.channel_width_mhz)
% - Final_Output_Matrix size: 107 x num_AP
%
% Usage:
%   results = simulate_environment_5G(config, ap_configs)

%% -------------------- Handle inputs & defaults --------------------
if nargin < 1 || isempty(config)
    config = default_config_5G();
end
if nargin < 2 || isempty(ap_configs)
    ap_configs = default_ap_configs_5G(config);
end
rng(config.random_seed);
num_AP = numel(ap_configs);
if num_AP == 0
    error('No APs provided in ap_configs.');
end

%% -------------------- Build geometry & clients --------------------
env = build_geometry_and_clients_5G(config, ap_configs);
for a = 1:num_AP
    % Copy config into the environment structure for easy access
    env.APs(a).pos = ap_configs(a).pos;
    env.APs(a).tx_power_dbm = ap_configs(a).tx_power_dbm;
    env.APs(a).channel = ap_configs(a).channel;
    env.APs(a).channel_width_mhz = ap_configs(a).channel_width_mhz;
    env.APs(a).obss_pd_dbm = ap_configs(a).obss_pd_dbm;
    env.APs(a).network_id = ap_configs(a).network_id;
end

%% -------------------- 5GHz CHANNEL LIST & SPECTRAL MASK --------------------
% Standard 5 GHz channels (20 MHz channel numbers)
channels_5g = [36,40,44,48,52,56,60,64,100,104,108,112,116,120,124,128,132,136,140,144,149,153,157,161,165];
num_ch = numel(channels_5g);

% Map channel number -> center frequency in MHz (standard formula)
center_freq_mhz = 5000 + 5*channels_5g;

% Build Spectral Mask (25 x 25)
Spectral_Mask = zeros(num_ch, num_ch);
for tx_i = 1:num_ch
    for rx_i = 1:num_ch
        df_mhz = abs(center_freq_mhz(tx_i) - center_freq_mhz(rx_i));
        if df_mhz == 0
            w = 1.0;
        else
            % Compute approximate attenuation per 20 MHz separation
            steps20 = round(df_mhz / 20);
            if steps20 <= 3
                w_db = -20 * steps20; % -20 dB per 20 MHz step up to -60 dB
            else
                w_db = -70; % far away floor
            end
            w = dbm2mw(w_db);
        end
        Spectral_Mask(tx_i, rx_i) = w;
    end
end

%% -------------------- RSSI matrices --------------------
[AP2AP_rssi_dbm, AP2Client_rssi_dbm] = precompute_rssi_5G(env, config, ap_configs, center_freq_mhz);

%% -------------------- Client Association --------------------
% Clients associate to the AP with the strongest long-term average RSSI
assoc = associate_clients_5G(env, AP2Client_rssi_dbm);

%% -------------------- SENSING SETUP --------------------
sim_time_ms = round(config.sim_duration_s * 1000);
dt_ms = config.dt_ms;
num_steps = ceil(sim_time_ms / dt_ms);
num_clients = size(env.client_positions,1);

% Noise floor (per BW)
% Use thermal noise -174 dBm/Hz as reference
BW_Hz_ref = 20e6; % we treat sensing bins as 20 MHz
thermal_noise_dBm_ref = -174;
% noise_floor for sensing bins (20 MHz)
thermal_noise_dBm_bin = thermal_noise_dBm_ref + 10*log10(BW_Hz_ref);
noise_floor_dbm = thermal_noise_dBm_bin + config.noise_figure_db;
noise_floor_mw = dbm2mw(noise_floor_dbm);
cca_thresh_mw = dbm2mw(config.cca_threshold_dbm);

% Time-series storage
AP_airtime = zeros(num_AP, num_steps);
AP_instant_interf_mw = zeros(num_AP, num_steps); % preserved
AP_retry_flag = zeros(num_AP, num_steps);
AP_interf_from_aps_mw = zeros(num_AP, num_steps);
Client_throughput_mbps_ts = zeros(num_clients, num_steps);

% Sensing storage (num_AP x num_ch x num_steps)
Sensed_Power_Map = zeros(num_AP, num_ch, num_steps, 'single');
NonWiFi_Flag_Map = zeros(num_AP, num_ch, num_steps, 'logical');

for step = 1:num_steps

    % Instantaneous non-wifi sampling (stochastic based on duty cycle)
    bt_mw_grid = sample_bluetooth_at_grid_5G(env, config);
    zb_mw_grid = sample_zigbee_at_grid_5G(env, config);

    % 1. Determine which APs transmit (based on CCA/OBSS-PD)
    tx_status = zeros(1, num_AP); % 1 if transmitted, 0 if idle/retry

    for a = 1:num_AP
        ap = env.APs(a);
        others = setdiff(1:num_AP, a);

        % --- A. Instantaneous AP-to-AP interference (small-scale)
        rssi_mean_db = AP2AP_rssi_dbm(a, others);
        rssi_rand_db = rssi_mean_db + config.short_term_shadowing_sigma * randn(size(rssi_mean_db));

        % channel overlap weights based on frequency occupancy & channel widths
        weights = zeros(size(others));
        for k = 1:numel(others)
            weights(k) = channel_overlap_weights_5G(ap, env.APs(others(k)), channels_5g, center_freq_mhz);
        end

        interference_from_aps_mw = sum(dbm2mw(rssi_rand_db) .* weights);
        AP_interf_from_aps_mw(a, step) = interference_from_aps_mw;

        % --- B. Total Background Noise at AP ---
        nonwifi_mw = approximate_nonwifi_at_ap_5G(ap.pos, env.client_positions, bt_mw_grid, zb_mw_grid, config);
        bg_noise_mw = noise_floor_mw * (1 + config.noise_variation_frac * randn);

        % Store instantaneous interference
        AP_instant_interf_mw(a, step) = interference_from_aps_mw + nonwifi_mw + bg_noise_mw;
        total_interf_dbm = mw2dbm(AP_instant_interf_mw(a, step));

        % --- C. CCA/OBSS-PD Decision (LOOSENED) ---
        is_idle = (total_interf_dbm < ap.obss_pd_dbm) || (total_interf_dbm < config.cca_threshold_dbm);

        if is_idle
            tx_prob = offered_tx_probability_dcf_5G(ap.channel, env.APs);
            if rand < tx_prob
                AP_airtime(a,step) = 1;
                AP_retry_flag(a,step) = 0;
                tx_status(a) = 1;
            else
                AP_airtime(a,step) = 0;
                AP_retry_flag(a,step) = 1;
            end
        else
            AP_airtime(a,step) = 0;
            AP_retry_flag(a,step) = 1;
        end
    end

    % --- NEW: VIRTUAL SENSING RADIO (The Scan) ---
    active_tx_indices = find(tx_status == 1);
    for a = 1:num_AP
        base_noise = noise_floor_mw * (1 + 0.05*randn);
        nw_mw_base = approximate_nonwifi_at_ap_5G(env.APs(a).pos, env.client_positions, bt_mw_grid, zb_mw_grid, config);

        for ch_i = 1:num_ch
            wifi_pwr_sum = 0;

            for k = active_tx_indices
                if k == a, continue; end

                % Use precomputed AP2AP RSSI as proxy for sensing power
                % Map tx AP channel number to index in channels_5g
                tx_ch_num = env.APs(k).channel;
                [~, tx_ch_idx] = min(abs(channels_5g - tx_ch_num));
                if isempty(tx_ch_idx)
                    % If AP channel is not in standard list (rare), estimate via nearest
                    [~, tx_ch_idx] = min(abs(center_freq_mhz - (5000 + 5*tx_ch_num)));
                end

                % Received power at sensing AP from transmitting AP
                rssi_val = AP2AP_rssi_dbm(a, k); 
                p_rx_mw = dbm2mw(rssi_val);

                % Apply Spectral Mask between tx channel index and sensing bin ch_i
                mask_val = Spectral_Mask(tx_ch_idx, ch_i);

                % If tx AP uses wider-than-20MHz (80/160), scale power across occupied bins
                bw_tx = env.APs(k).channel_width_mhz;
                nbins_tx = round(bw_tx / 20);
                % Distribute TX power across nbins_tx bins centered on tx_ch_idx
                wifi_pwr_sum = wifi_pwr_sum + (p_rx_mw * mask_val) / max(1, nbins_tx);
            end

            % Non-WiFi mapping: Zigbee on low UNII bands is unlikely; but treat BT bleed uniformly
            nw_pwr_ch = nw_mw_base * (0.2 + 0.8 * (ch_i <= 8)); % slightly higher in lower UNII groups

            total_pwr = wifi_pwr_sum + nw_pwr_ch + base_noise;
            Sensed_Power_Map(a, ch_i, step) = total_pwr;

            if (nw_pwr_ch > cca_thresh_mw) && (wifi_pwr_sum < cca_thresh_mw)
                NonWiFi_Flag_Map(a, ch_i, step) = true;
            end
        end
    end

    % 2. Calculate Client Throughput for APs that Transmitted (tx_status == 1)
    for a = find(tx_status == 1)
        ap = env.APs(a);
        associated_clients = find(assoc == a);
        num_clients_on_ap = numel(associated_clients);

        if num_clients_on_ap > 0
            airtime_share = 1 / num_clients_on_ap;

            interfering_tx_aps_idx = setdiff(find(tx_status == 1), a);

            for c_idx = associated_clients'
                client_pos = env.client_positions(c_idx,:);

                % Signal RSSI (Mean Pathloss + Fading)
                pl_calc = pathloss_calc_5G(ap.pos, client_pos, config);
                signal_dbm_mean = ap.tx_power_dbm - pl_calc;
                walls_count = estimate_walls_between_5G(ap.pos, client_pos, config);
                fading_db = small_scale_fading_db_enhanced_5G(walls_count);
                signal_mw = dbm2mw(signal_dbm_mean + fading_db);

                % Non-AP interference
                non_ap_interf_mw = AP_instant_interf_mw(a, step) - AP_interf_from_aps_mw(a, step);

                % Interference from other transmitting APs
                interf_mw = non_ap_interf_mw;
                for k = interfering_tx_aps_idx
                    other_ap = env.APs(k);
                    pl_client = pathloss_calc_5G(other_ap.pos, client_pos, config);
                    rssi_interf_dbm = other_ap.tx_power_dbm - pl_client;
                    weight = channel_overlap_weights_5G(ap, other_ap, channels_5g, center_freq_mhz);
                    interf_mw = interf_mw + dbm2mw(rssi_interf_dbm) * weight;
                end

                % SINR & Throughput
                sinr_lin = signal_mw / max(interf_mw, 1e-12);
                sinr_db = 10*log10(sinr_lin);
                [rate_mbps, per] = map_sinr_to_rate_per_ber_5G(sinr_db, ap.channel_width_mhz, config);

                Client_throughput_mbps_ts(c_idx, step) = rate_mbps * (1 - per) * airtime_share;
            end
        end
    end
end

%% -------------------- Aggregate results --------------------
AP_throughput_mbps_ts = zeros(num_AP, num_steps);
for a = 1:num_AP
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
results.channels_list = channels_5g;
results.perChannel = repmat(struct(), numel(results.channels_list), 1);

% Legacy Aggregation (per AP)
for a = 1:num_AP
    thr_samples = AP_throughput_mbps_ts(a, :);
    associated_clients = find(assoc == a);

    results.perAP(a).network_id = env.APs(a).network_id;
    results.perAP(a).channel = env.APs(a).channel;
    results.perAP(a).median_throughput_mbps = median(thr_samples);
    results.perAP(a).mean_throughput_mbps = mean(thr_samples);
    results.perAP(a).p95_throughput_mbps = prctile(thr_samples, 95);
    win = 10; % or whatever window size you want
    retry_smooth = movmean(AP_retry_flag(a,:), win);
    results.perAP(a).p95_retry = 100 * prctile(retry_smooth, 95);
    results.perAP(a).avg_channel_util_percent = mean(AP_airtime(a,:))*100;

    results.perAP(a).mean_total_interf_dbm = mw2dbm(mean(AP_instant_interf_mw(a,:)));

    results.perAP(a).avg_client_count = length(associated_clients);
    results.perAP(a).avg_retry_percent = mean(AP_retry_flag(a,:)) * 100;
end

% Per-Channel Aggregation
for i = 1:numel(results.channels_list)
    ch = results.channels_list(i);
    results.perChannel(i).channel_id = ch;

    ch_aps_idx = find([env.APs(:).channel] == ch);

    ch_util_samples = mean(AP_airtime(ch_aps_idx, :), 1);
    results.perChannel(i).avg_channel_util_percent = mean(ch_util_samples)*100;

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
results.time.AP_retry_flag = AP_retry_flag;

% --- NEW: Aggregating Sensing Metrics (25 bins) ---
results.Sensing_Data = repmat(struct(), num_AP, 1);

for a = 1:num_AP
    p95_power_dbm = zeros(num_ch,1);
    duty_cycle_p50 = zeros(num_ch,1);
    prob_non_wifi = zeros(num_ch,1);
    noise_floor_p95_dbm = zeros(num_ch,1);

    for ch_i = 1:num_ch
        pwr_series = reshape(Sensed_Power_Map(a, ch_i, :), [], 1);
        nw_flags = reshape(NonWiFi_Flag_Map(a, ch_i, :), [], 1);

        % 1. Interference Power (P95)
        p95_mw = prctile(pwr_series, 95);
        p95_power_dbm(ch_i) = mw2dbm(p95_mw);

        % 2. Duty Cycle (P50)
        is_busy = pwr_series > cca_thresh_mw;
        duty_cycle_p50(ch_i) = mean(is_busy);

        % 3. Prob Non-WiFi
        total_busy_steps = sum(is_busy);
        if total_busy_steps > 0
            prob_non_wifi(ch_i) = sum(nw_flags) / num_steps;
        else
            prob_non_wifi(ch_i) = 0;
        end

        % 4. Noise Floor (P95 of Idle)
        idle_samples = pwr_series(~is_busy);
        if isempty(idle_samples)
            noise_floor_p95_dbm(ch_i) = mw2dbm(min(pwr_series));
        else
            noise_floor_p95_dbm(ch_i) = mw2dbm(prctile(idle_samples, 95));
        end
    end

    results.Sensing_Data(a).Metrics_Table = table(channels_5g(:), p95_power_dbm, duty_cycle_p50, prob_non_wifi, noise_floor_p95_dbm, ...
        'VariableNames', {'Channel', 'Interf_P95_dBm', 'DutyCycle_P50', 'Prob_NonWiFi', 'NoiseFloor_P95_dBm'});
end

% --- Store raw Sensed_Power_Map for Python retrieval (Crucial for RL state)
results.Sensing_Data_Raw = Sensed_Power_Map; 

%% ============================================================
% FINAL 107×num_AP OUTPUT MATRIX:
% ============================================================
rows_total = 107;
Final_Output_Matrix = zeros(rows_total, num_AP);

for a = 1:num_AP

    APch = env.APs(a).channel;
    APw  = env.APs(a).channel_width_mhz;
    APpd = env.APs(a).obss_pd_dbm;
    APtx = env.APs(a).tx_power_dbm;

    SENS = results.Sensing_Data(a).Metrics_Table;

    Col = zeros(rows_total,1);

    %% 1) AP basic parameters
    Col(1) = APch;
    Col(2) = APw;
    Col(3) = APpd;
    Col(4) = APtx;

    %% 2) Interference P95 for all channels (25)
    Col(5:29) = SENS.Interf_P95_dBm;

    %% 3) Duty cycle P50 for all channels (25)
    Col(30:54) = SENS.DutyCycle_P50;

    %% 4) Prob Non-WiFi (25)
    Col(55:79) = SENS.Prob_NonWiFi;

    %% 5) Noise Floor P95 (25)
    Col(80:104) = SENS.NoiseFloor_P95_dBm;

    %% 6) AP summary metrics (3)
    Col(105) = results.perAP(a).p95_throughput_mbps;
    Col(106) = results.perAP(a).p95_retry;
    Col(107) = results.perAP(a).avg_client_count;

    Final_Output_Matrix(:, a) = Col;
end

results.Final_Output_Matrix = Final_Output_Matrix;

%% ============================================
% CHANNEL OVERLAP MATRIX (num_AP × num_AP)
% compute spectral-overlap weight between AP pairs
Channel_Overlap_Matrix = zeros(num_AP, num_AP);
for a = 1:num_AP
    for b = 1:num_AP
        Channel_Overlap_Matrix(a,b) = channel_overlap_weights_5G(env.APs(a), env.APs(b), channels_5g, center_freq_mhz);
    end
end
results.Channel_Overlap_Matrix = Channel_Overlap_Matrix;

disp("Generated Final_Output_Matrix (107 × num_AP)");

results.AP_Throughput = sum(Client_throughput_mbps_ts, 2);

fprintf('Simulation finished: %d steps (dt %d ms) => %.2f s simulated\n', ...
        num_steps, dt_ms, num_steps*dt_ms/1000);

end

%% -------------------- Defaults & helper functions for 5G --------------------
function cfg = default_config_5G()
    cfg.random_seed = 123;
    cfg.sim_duration_s = 10;
    cfg.dt_ms = 10;
    cfg.channel_width_mhz = 80; % default 80 MHz for 5G tests
    cfg.noise_figure_db = 7;% receiver NF
    % noise & shadowing
    cfg.noise_floor_dbm = -95;
    cfg.noise_variation_frac = 0.03;
    cfg.short_term_shadowing_sigma = 6;
    cfg.shadowing_sigma = 4;
    % detectors (LOOSENED)
    cfg.cca_threshold_dbm = -45;
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
    % 5 GHz channels are provided elsewhere, but keep placeholder
    cfg.channels = []; 
    % MCS Lookup (reuse legacy thresholds but you can override)
    cfg.MCS_SINR_Required = [0,1.5,3.5,5,8,10,12,13,15,17,18,20];
    cfg.MCS_Rates_20MHz = 3*[6.5,13,19.5,26,39,52,58.5,65,78,86.7,97.5,108.3];
    cfg.MCS_Rates_40MHz = 3*[13.5,27,40.5,54,81,108,121.5,135,162,180,202.5,225];
    cfg.MCS_Rates_80MHz = 3*[29.3,58.5,87.8,117,175.5,234,263.25,292.5,351,390,438.8,487.5];
    cfg.MCS_Rates_160MHz = 3*[58.5,117,175.5,234,351,468,526.5,585,702,780,877.5,975];

    % Path Loss Model Parameters (tuned for 5 GHz: higher PL0)
    cfg.pathloss.n_exp = 4.0;
    cfg.pathloss.wall_loss_db = 15;
    cfg.pathloss.PL_d0_dB = 36; % reference at d0=1m, adjusted for 5GHz
    cfg.pathloss.d0 = 1;
end

function ap_configs = default_ap_configs_5G(cfg)
    num_rooms = cfg.num_rooms;
    ap_per_room = cfg.ap_per_room;
    total = num_rooms * ap_per_room;
    ap_configs = repmat(struct(), total, 1);
    idx = 1;
    channels = [36,40,44,48,149,153,157,161,165]; % Example spread (users will override)
    for r = 1:num_rooms
        base_x = (r-1) * (cfg.room_size(1) + 5);
        ap_configs(idx).pos = [ base_x + 2, cfg.room_size(2)/2 ];
        ap_configs(idx).tx_power_dbm = 23;
        ap_configs(idx).channel_width_mhz = 80;
        ap_configs(idx).channel = channels(mod(idx-1, numel(channels))+1);
        ap_configs(idx).obss_pd_dbm = -45;
        ap_configs(idx).network_id = 1;
        idx = idx + 1;
        ap_configs(idx).pos = [ base_x + 5, cfg.room_size(2)/2 ];
        ap_configs(idx).tx_power_dbm = 23;
        ap_configs(idx).channel_width_mhz = 80;
        ap_configs(idx).channel = channels(mod(idx, numel(channels))+1);
        ap_configs(idx).obss_pd_dbm = -45;
        ap_configs(idx).network_id = 2;
        idx = idx + 1;
        ap_configs(idx).pos = [ base_x + 8, cfg.room_size(2)/2 ];
        ap_configs(idx).tx_power_dbm = 23;
        ap_configs(idx).channel_width_mhz = 80;
        ap_configs(idx).channel = channels(mod(idx+1, numel(channels))+1);
        ap_configs(idx).obss_pd_dbm = -45;
        ap_configs(idx).network_id = 3;
        idx = idx + 1;
    end
end

function env = build_geometry_and_clients_5G(cfg, ap_configs)
    env = struct();

    all_client_pos = [];
    local_w = cfg.client_grid_spacing;
    range = -6 : local_w : 6; 
    [lx, ly] = meshgrid(range, range);
    local_grid = [lx(:), ly(:)];

    for i = 1:numel(ap_configs)
        ap_pos = ap_configs(i).pos;
        these_clients = local_grid + ap_pos;
        all_client_pos = [all_client_pos; these_clients];
    end

    env.client_positions = unique(all_client_pos, 'rows');

    % Interferers (scatter near APs)
    env.Interferers.BT = repmat(struct(), cfg.bt.count, 1);
    for i = 1:cfg.bt.count
        target_ap = ap_configs(randi(numel(ap_configs))).pos;
        env.Interferers.BT(i).pos = target_ap + (rand(1,2)-0.5)*10;
        env.Interferers.BT(i).tx_power_dbm = cfg.bt.tx_power_dbm;
    end

    env.Interferers.ZB = repmat(struct(), cfg.zb.count, 1);
    for i = 1:cfg.zb.count
        target_ap = ap_configs(randi(numel(ap_configs))).pos;
        env.Interferers.ZB(i).pos = target_ap + (rand(1,2)-0.5)*10;
        env.Interferers.ZB(i).tx_power_dbm = cfg.zb.tx_power_dbm;
    end
end

function [AP2AP_rssi_dbm, AP2Client_rssi_dbm] = precompute_rssi_5G(env, cfg, ap_configs, center_freq_mhz)
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
            pl = pathloss_calc_5G(tx_pos, rx_pos, cfg);
            AP2AP_rssi_dbm(i,j) = tx_power - pl;
        end
        for c = 1:num_clients
            client_pos = env.client_positions(c,:);
            plc = pathloss_calc_5G(tx_pos, client_pos, cfg);
            AP2Client_rssi_dbm(c,j) = tx_power - plc;
        end
    end
end

function pl_db = pathloss_calc_5G(tx_pos, rx_pos, cfg)
    d0 = cfg.pathloss.d0;
    PL0 = cfg.pathloss.PL_d0_dB;
    n = cfg.pathloss.n_exp;
    d = max(norm(tx_pos - rx_pos), d0);
    walls = estimate_walls_between_5G(tx_pos, rx_pos, cfg);
    wall_loss_db = cfg.pathloss.wall_loss_db * walls;
    shadow = cfg.shadowing_sigma * randn;
    pl_db = PL0 + 10*n*log10(d/d0) + wall_loss_db + shadow;
end

function walls = estimate_walls_between_5G(a, b, cfg)
    room_w = cfg.room_size(1) + 1;
    ra = max(1, floor(a(1) / room_w) + 1);
    rb = max(1, floor(b(1) / room_w) + 1);
    walls = double(ra ~= rb);
end

function w = channel_overlap_weights_5G(thisAP, otherAP, channels_5g, center_freq_mhz)
    % Compute spectrum overlap fraction between two APs using their center freqs and bandwidths
    % Determine center freq of each AP (MHz)
    c1 = 5000 + 5*thisAP.channel;
    c2 = 5000 + 5*otherAP.channel;
    bw1 = thisAP.channel_width_mhz;
    bw2 = otherAP.channel_width_mhz;
    half1 = bw1/2; half2 = bw2/2;
    left1 = c1 - half1; right1 = c1 + half1;
    left2 = c2 - half2; right2 = c2 + half2;
    overlap = max(0, min(right1, right2) - max(left1, left2));
    if overlap > 0
        % normalized overlap fraction between 0 and 1
        frac = overlap / min(bw1, bw2);
        % We want weight in linear multiplier (0..1)
        w = min(1, frac) * (1); 
    else
        % No overlap -> very small coupling
        w = 10^(-70/10);
    end
end

function nonwifi_mw = approximate_nonwifi_at_ap_5G(ap_pos, grid_pts, bt_mw, zb_mw, cfg)
    dists = sqrt(sum((grid_pts - ap_pos).^2, 2));
    dists = max(dists, 0.5);
    weights = 1./(dists.^2);
    weights = weights / sum(weights);
    nonwifi_mw = sum(weights .* (bt_mw(:) + zb_mw(:)));
end

function bt_mw = sample_bluetooth_at_grid_5G(env, cfg)
    grid_count = size(env.client_positions,1);
    bt_mw = zeros(grid_count,1);
    for b = 1:cfg.bt.count
        if rand < cfg.bt.duty_cycle
            tx_idx = randi(grid_count);
            tx_pos = env.client_positions(tx_idx,:);
            for g = 1:grid_count
                pl = pathloss_calc_5G(tx_pos, env.client_positions(g,:), cfg);
                pr_dbm = cfg.bt.tx_power_dbm - pl;
                bt_mw(g) = bt_mw(g) + dbm2mw(pr_dbm) * (0.8 + 0.4*rand);
            end
        end
    end
end

function zb_mw = sample_zigbee_at_grid_5G(env, cfg)
    grid_count = size(env.client_positions,1);
    zb_mw = zeros(grid_count,1);
    for z = 1:cfg.zb.count
        if rand < cfg.zb.duty_cycle
            tx_idx = randi(grid_count);
            tx_pos = env.client_positions(tx_idx,:);
            for g = 1:grid_count
                pl = pathloss_calc_5G(tx_pos, env.client_positions(g,:), cfg);
                pr_dbm = cfg.zb.tx_power_dbm - pl;
                zb_mw(g) = zb_mw(g) + dbm2mw(pr_dbm) * (0.9 + 0.2*rand);
            end
        end
    end
end

function prob = offered_tx_probability_dcf_5G(channel_id, all_APs)
    num_competing_aps = sum([all_APs(:).channel] == channel_id);
    base_prob = 2.5;
    prob = base_prob / (1 + 0.1 * (num_competing_aps - 1));
    prob = min(prob, 0.98);
end

function assoc = associate_clients_5G(env, AP2Client_rssi_dbm)
    num_clients = size(env.client_positions,1);
    assoc = zeros(num_clients,1);
    for c = 1:num_clients
        [~, best] = max(AP2Client_rssi_dbm(c,:));
        assoc(c) = best;
    end
end

function fading_db = small_scale_fading_db_enhanced_5G(walls)
    if walls == 0
        K_dB = 6 + 4*rand; % slightly lower K for 5GHz LOS variability
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

function [rate_mbps, per] = map_sinr_to_rate_per_ber_5G(SINR_dB, bw_mhz, cfg)
    sinr_req = cfg.MCS_SINR_Required;
    if SINR_dB < sinr_req(1)
        rate_mbps = 0; per = 1.0; return;
    end
    idx = find(SINR_dB >= sinr_req, 1, 'last');
    if isempty(idx)
        idx = 1;
    end

    switch bw_mhz
        case 20
            rate_mbps = cfg.MCS_Rates_20MHz(idx);
        case 40
            rate_mbps = cfg.MCS_Rates_40MHz(idx);
        case 80
            rate_mbps = cfg.MCS_Rates_80MHz(idx);
        case 160
            rate_mbps = cfg.MCS_Rates_160MHz(idx);
        otherwise
            rate_mbps = cfg.MCS_Rates_20MHz(idx); % safe fallback
    end


    SINR_lin = 10^(SINR_dB/10);
    k = 0.5;
    Nbits = 2000 + randi([-200,200]);
    BER = 0.5 * exp(-k * SINR_lin);
    per = 1 - (1 - BER)^Nbits;
    per = min(max(per, 0.001), 0.999);
end

function m = dbm2mw(dbm), m = 10.^(dbm/10); end
function dbm = mw2dbm(mw), dbm = 10*log10(max(mw,1e-30)); end