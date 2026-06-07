import React, { useContext, createContext, useState, useEffect } from "react";
import axios from "axios";

interface ChannelData {
  interference_power: number;
  noise_power: number;
  wifi_power: number;
  inference: {
    bluetooth: number;
    empty: number;
    wifi: number;
    zigbee: number;
    microwave: number;
  };
  cusum_flag: number;
  channel: number;
}

type ContextType = {
  data: ChannelData[],
}

const context = createContext<ContextType>({} as any);

type Props = {
  children: React.ReactNode;
}

export function RfDataProvider({ children }: Props) {
  const [channelData, setChannelData] = useState<ChannelData[]>([]);

  useEffect(() => {
    axios.get(import.meta.env.VITE_SERVER + "/api/sensing").then(data => setChannelData(data.data));
  }, [])

  const values = {
    data: channelData
  }

  return (
    <context.Provider value={values}>
      {children}
    </context.Provider>
  )
}

export function useRfData() {
  return useContext(context);
}