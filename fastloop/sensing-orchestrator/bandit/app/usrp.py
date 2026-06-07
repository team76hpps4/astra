import numpy as np
import uhd
import sys


class USRP:
    SAMPLING_RATE = 22e6
    NO_SAMPLES = 4096 
    SWEEPS = 1
    BIN = 70
    AVG_SIZE = 58

    CENTER_FREQUENCIES = [
        2.412e9,
        2.417e9,
        2.422e9,
        2.427e9,
        2.432e9,
        2.437e9,
        2.442e9,
        2.447e9,
        2.452e9,
        2.457e9,
        2.462e9,
        2.467e9,
        2.472e9,
    ]

    def __init__(self):
        self.usrp = uhd.usrp.MultiUSRP()
        self.usrp.set_rx_rate(self.SAMPLING_RATE)

    def reading(self, channel, cb, snr=40):
        return self.generate_spectrum(self.usrp, self.CENTER_FREQUENCIES[channel-1], snr, cb)

    def get_data(self, usrp, center: float, rx_gain: int = 0):
        usrp.set_rx_freq(uhd.types.TuneRequest(center))  # Center frequency
        usrp.set_rx_gain(rx_gain)

        stream_args = uhd.usrp.StreamArgs("fc32", "sc16")  # Complex float32, 16-bit over wire
        rx_stream = usrp.get_rx_stream(stream_args)

        # Set up stream command
        stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.num_done)
        stream_cmd.num_samps = self.NO_SAMPLES
        stream_cmd.stream_now = True

        samples = np.zeros(self.NO_SAMPLES, dtype=np.complex64)

        rx_stream.issue_stream_cmd(stream_cmd)
        num_rx = rx_stream.recv(samples, metadata=uhd.types.RXMetadata())

        if num_rx != self.NO_SAMPLES:
            sys.exit("Fked")

        return samples


    def one_cycle(self, usrp, center: int, snr: int, cb):
        big_data = np.zeros(shape=(self.SWEEPS, self.NO_SAMPLES), dtype=np.complex64)

        for i in (range(0, self.SWEEPS)):
            sample = self.get_data(usrp, center, snr)
            big_data[i] = sample
            cb(sample)
            center += int(self.SAMPLING_RATE)

        amp_fft = np.absolute(np.fft.fft(big_data))
        arr = []

        for i in range(self.SWEEPS):
            data =[]
            for j in range(self.BIN):
                d = np.average(amp_fft[i][j * self.AVG_SIZE: (j+1) * self.AVG_SIZE])
                data.append(d)
            arr.append(data)

        arr = np.array(arr, dtype=np.float32)
        return arr.reshape((-1,))


    def generate_spectrum(self, usrp, center: int, snr: int, cb):
        image = np.zeros(shape=(4 * self.BIN, self.SWEEPS * self.BIN))
        for i in range(4 * self.BIN):
            line = self.one_cycle(usrp, center, snr, cb)
            image[i] = line
            # time.sleep(0.0053)

        return image



def get_usrp():
    usrp = USRP()
    yield usrp