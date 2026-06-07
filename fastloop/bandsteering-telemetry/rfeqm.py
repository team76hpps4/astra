import math

INTERFERENCE_TYPE_WEIGHTS = {
    'microwave': 1.0,
    'bluetooth': 0.8,
    'zigbee': 0.5,
    'jammer': 1.0,
}

def dbm_from_watts(watts):
    return 10 * math.log10(watts * 1000) if watts > 0 else -999

def compute_interference_severity(type_name, probability, duty_cycle, power_w, noise_w):
    type_weight = INTERFERENCE_TYPE_WEIGHTS.get(type_name, 0.5)
    
    interf_dbm = dbm_from_watts(power_w)
    noise_dbm = dbm_from_watts(noise_w)
    power_score = min(max((interf_dbm - noise_dbm + 100)/100, 0), 1) 
    
    severity = type_weight * probability * duty_cycle * power_score
    return severity

def compute_rfeqm(interferences, noise_power):
    # interferences: list of dicts, each {'type':str, 'prob':float, 'duty':float, 'power':float}
    total_severity = 0
    for interferer in interferences:
        sev = compute_interference_severity(
            interferer['type'],
            interferer['prob'],
            interferer['duty'],
            interferer['power'],
            noise_power)
        total_severity += sev * 100 
    
    total_severity = min(total_severity, 100)
    rfeqm = int(round(100 - total_severity))
    return rfeqm
