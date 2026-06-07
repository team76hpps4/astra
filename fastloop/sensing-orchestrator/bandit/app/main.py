import usrp
import requests
from cusum import CUSUMDetector
from mab import StateBandit
from matplotlib import pyplot as plt


def get_interference(inference):
    sorted_inference = (sorted(inference.items(), key=lambda item: item[1], reverse=True))
    if sorted_inference[0][0] == "wifi":
        return sorted_inference[1][0]
    return sorted_inference[0][0]


def main():
    sdr = usrp.USRP()
    cusum = CUSUMDetector()

    channel = 1
    channels_data = []

    bandit = StateBandit(13)

    while True:
        channel = bandit.select_channel() + 1
        data = sdr.reading(channel, cusum.predict, 40)

        resp = requests.get("http://ml:8080/api/inference", json={"iq_data": data.tolist() })
        power_resp = requests.get("http://ml:8080/api/powers", json={"image": data.tolist() })
        inference = resp.json()
        powers = power_resp.json()

        flag = cusum.clear_flags()[-1]

        log_data = {
            "inference": inference["inference"],
            "interference_power": powers["interference_power"],
            "noise_power": powers["noise_power"],
            "cusum_flag": flag,
            "channel": channel,
            "wifi_power": powers["wifi_power"],
            "duty_cycle": powers["duty_cycle"]
        }
        print(log_data)
        plt.imshow(data)
        plt.show()

        total_power = log_data["interference_power"] + log_data["noise_power"] + log_data["wifi_power"]
        normailzed_wifi_power = log_data["wifi_power"] / total_power

        interference = get_interference(log_data["inference"])
        print(f"Interference found in the channel is {interference}, probability of wifi is {log_data["inference"]["wifi"]}")

        bandit.update(channel-1, interference, normailzed_wifi_power, log_data["duty_cycle"])
        
        channels_data.append(log_data)


if __name__ == "__main__":
    main()