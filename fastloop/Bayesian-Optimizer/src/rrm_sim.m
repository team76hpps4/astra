function results = rrm_sim(obss_threshold, ap_tx_power, channel_width, sim_minutes)

% 1 minute = 100 runs, and results are averaged.


% Cast inputs to double for safety
OBSS_PD_Threshold_dBm  = double(obss_threshold);
ap_main_tx_power_dBm   = double(ap_tx_power);
WIFI_CHANNEL_WIDTHS_MHz = double(channel_width);
sim_minutes_double     = double(sim_minutes);

num_runs = 100 * sim_minutes_double;
if num_runs < 1
    num_runs = 1; % Ensure at least one run
end


P50_all = zeros(num_runs,1);
P95_all = zeros(num_runs,1);
P95Retry_all = zeros(num_runs,1);
Flagged_Count_all = zeros(num_runs,1); % Stores the raw count of flagged clients

%% FIXED NETWORK PARAMETERS
bluetooth_tx_power_dBm = 2;
NUM_PACKETS_PER_CLIENT = 50;
noise_figure_dB        = 7;
thermal_noise_dBm_ref  = -174; % kT at 1 Hz

% SINR -> Rate/PER Mapping
MCS_SINR_Required = [0,1.5,3.5,5,8,10,12,13,15,17,18,20];
MCS_Rates_20MHz = [6.5,13,19.5,26,39,52,58.5,65,78,86.7,97.5,108.3];

% Path Loss Model
d0 = 1; PL_d0_dB = 40; n_exp = 3.8;
pathloss = @(d) (PL_d0_dB + 10*n_exp*log10(max(d,d0)/d0));

% Noise Floor calculation (fixed based on channel width)
BW_Hz = WIFI_CHANNEL_WIDTHS_MHz * 1e6;
thermal_noise_dBm = thermal_noise_dBm_ref + 10*log10(BW_Hz);
NoiseFloor_dBm = thermal_noise_dBm + noise_figure_dB;
NoiseFloor_mW = 10^(NoiseFloor_dBm/10);

% Topology
AP_main.loc = [0 0];
AP_obss.loc = [25 25]; AP_obss.tx_dBm = 12; AP_obss.duty_cycle = 0.3;
BT1.loc = [4 12];  BT1.tx_dBm = bluetooth_tx_power_dBm;
BT2.loc = [4 -12]; BT2.tx_dBm = bluetooth_tx_power_dBm;
[xg, yg] = meshgrid(2:5:22, -8:4:8);
STA_locations = [xg(:), yg(:)];
STA_locations = STA_locations(1:25,:);
NUM_CLIENTS = size(STA_locations,1);

%starting the simulations
for run = 1:num_runs
    % Set seed for run-specific randomness
    rng('shuffle');
    
    % METRICS STORAGE (Per Run)
    All_Throughput_samples = [];
    All_PER_samples = [];
    
    Client_Throughput = zeros(NUM_CLIENTS, 1);
    Client_Retry = zeros(NUM_CLIENTS, 1);
    
    for pkt = 1:NUM_PACKETS_PER_CLIENT
        AP2_active = rand < AP_obss.duty_cycle;
        BT1_active = rand < 0.9;
        BT2_active = rand < 0.9;
        
        for c = 1:NUM_CLIENTS
            % Add small spatial randomness to client location
            rx_loc = STA_locations(c,:) + 0.3*randn(1,2);
            
            %Signal Power (P_sig) 
            d_ap = norm(rx_loc - AP_main.loc);
            sigma_shadow_dB = 2 + rand*2;
            PL_ap_dB = pathloss(d_ap) + sigma_shadow_dB*randn;
            fading_lin = (1 + 0.1*randn)^2; % Simplified Rayleigh-like fast fading
            P_sig_mW = 10^((ap_main_tx_power_dBm - PL_ap_dB)/10) * fading_lin;-
            
            P_AP2_mW = 0;
            if AP2_active
                d_ap2 = norm(rx_loc - AP_obss.loc);
                PL_ap2_dB = pathloss(d_ap2) + (1+rand)*randn;
                P_AP2_mW = 10^((AP_obss.tx_dBm - PL_ap2_dB)/10) * (1 + 0.2*randn);
            end
            
            % Bluetooth interference
            d_bt1 = norm(rx_loc - BT1.loc); PL_bt1 = pathloss(d_bt1) + (1+rand)*randn;
            P_BT1_rx_mW = 10^((BT1.tx_dBm - PL_bt1)/10) * (1 + 0.1*randn) * BT1_active;
            
            d_bt2 = norm(rx_loc - BT2.loc); PL_bt2 = pathloss(d_bt2) + (1+rand)*randn;
            P_BT2_rx_mW = 10^((BT2.tx_dBm - PL_bt2)/10) * (1 + 0.1*randn) * BT2_active;
            
            % Total interference + Noise (TIN)
            NoiseFloor_mW_actual = NoiseFloor_mW * (1 + 0.05*randn);
            TotalInterf_mW = NoiseFloor_mW_actual + P_AP2_mW + P_BT1_rx_mW + P_BT2_rx_mW;
            Interf_dBm = 10*log10(TotalInterf_mW);
            
            % OBSS-PD Rule & Channel Utilization
            if Interf_dBm < OBSS_PD_Threshold_dBm
                Interf_for_SINR_mW = NoiseFloor_mW_actual;
                Channel_Utilization = 0.1 + 0.05*rand; % Lower utilization
            else
                Interf_for_SINR_mW = TotalInterf_mW;
                Channel_Utilization = 0.4 + 0.1*rand; % Higher utilization
            end
            
            SINR_lin = P_sig_mW / Interf_for_SINR_mW;
            SINR_dB = 10*log10(SINR_lin);
            
            [rate_Mbps, per] = map_sinr_to_rate_per(SINR_dB, WIFI_CHANNEL_WIDTHS_MHz, MCS_SINR_Required, MCS_Rates_20MHz);
            
            % Add small randomness to PER within bounds
            per = min(max(per*(1 + 0.05*randn),0.001),0.999);
            
            eff_thr = rate_Mbps * (1 - per) * (1 - Channel_Utilization);
            All_Throughput_samples(end+1) = eff_thr;
            All_PER_samples(end+1) = per;
            Client_Throughput(c) = Client_Throughput(c) + eff_thr;
            Client_Retry(c) = Client_Retry(c) + per;
        end
    end
    
    %FINAL METRICS (Per Run)
    avg_thr = Client_Throughput / NUM_PACKETS_PER_CLIENT;
    avg_retry_rate = Client_Retry / NUM_PACKETS_PER_CLIENT;
    flags = (avg_thr < 50) & (avg_retry_rate > 0.5);
    num_flagged_count = sum(flags); % RAW COUNT (0 to 25)
    
    fprintf("Run %d/%d (%.1f MHz, TX=%.1f dBm, OBSS=%.1f dBm) → %d flagged clients\n", ...
        run, num_runs, WIFI_CHANNEL_WIDTHS_MHz, ap_main_tx_power_dBm, OBSS_PD_Threshold_dBm, num_flagged_count);
    P50_all(run) = prctile(All_Throughput_samples,50);
    P95_all(run) = prctile(All_Throughput_samples,95);
    P95Retry_all(run) = prctile(All_PER_samples,95);
    Flagged_Count_all(run) = num_flagged_count/25; % Store the raw count
end

results.P50_Throughput = mean(P50_all);
results.P95_Throughput = mean(P95_all);
results.P95_Retry_Rate = mean(P95Retry_all);
% Output the average of the RAW COUNT for Python to normalize
results.num_flagged = mean(Flagged_Count_all); 

fprintf("\n✅ Monte Carlo complete: %d runs (%.1f min)\n", num_runs, sim_minutes_double);
end

%%HELPER FUNCTION
function [rate_Mbps, per] = map_sinr_to_rate_per(SINR_dB, bw_mhz, sinr_req, rates20)
    if SINR_dB < sinr_req(1)
        rate_Mbps = 0; per = 1.0; return;
    end
    
    idx = find(SINR_dB >= sinr_req, 1, 'last');
    if isempty(idx)
        % Should not happen if SINR_dB >= sinr_req(1), but safety check
        idx = 1; 
    end
    
    rate20 = rates20(idx);
    scale = bw_mhz / 20;
    rate_Mbps = rate20 * scale;
    
    % Packet Error Rate Calculation
    SINR_lin = 10^(SINR_dB/10);
    k = 0.7 + 0.3*rand; 
    BER = 0.5 * exp(-k * SINR_lin);
    
   
    Nbits = 12000 + randi([-2000,2000]);
    
    per = 1 - (1 - BER)^Nbits;
    
    % Ensure PER is within realistic bounds (0.1% to 99.9%)
    per = min(max(per, 0.001), 0.999);
end 