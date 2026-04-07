import axios from "axios";

// Access API URL from environment variable or default to localhost:8000
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const api = axios.create({
    baseURL: API_URL,
});

export interface YouTubeInfo {
    title: string;
    channel: string;
    thumbnail: string;
    duration: number;
    transcript?: string;
}

export const getVideoInfo = async (url: string): Promise<YouTubeInfo> => {
    const { data } = await api.get<YouTubeInfo>(`/yt/info`, {
        params: { url },
    });
    return data;
};
