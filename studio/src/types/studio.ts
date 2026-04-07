import { type ThumbnailConfig, DEFAULT_THUMB_CONFIG } from "./thumbnail"

export interface CameraConfig {
    portrait: boolean
    face_tracking: boolean
    tracking_sensitivity: number
    camera_smoothing: number
    zoom_threshold: number
    zoom_level: number
}

export const DEFAULT_CAMERA_CONFIG: CameraConfig = {
    portrait: true,
    face_tracking: true,
    tracking_sensitivity: 5,
    camera_smoothing: 0.25,
    zoom_threshold: 20.0,
    zoom_level: 1.15
}

export interface CaptionConfig {
    model: "small" | "medium" | "large"
    language: string
    settings: {
        font_family: string
        font_size: number
        line_color: string
        word_color: string
        outline_color: string
        outline_width: number
        max_words_per_line: number
        margin_v: number
        position: "bottom_center" | "bottom_left" | "bottom_right" | "top_center" | "top_left" | "top_right" | "center"
        bold: boolean
        italic: boolean
        all_caps: boolean
    }
}

export const DEFAULT_CAPTION_CONFIG: CaptionConfig = {
    model: "small",
    language: "id",
    settings: {
        font_family: "Komika Axis",
        font_size: 130,
        line_color: "#FFFFFF",
        word_color: "#0FE631",
        outline_color: "#000000",
        outline_width: 10,
        max_words_per_line: 2,
        margin_v: 300,
        position: "bottom_center",
        bold: true,
        italic: false,
        all_caps: true
    }
}

export interface StudioState {
    camera: CameraConfig
    caption: CaptionConfig
    thumbnail: ThumbnailConfig
    transcript: string
}

export const DEFAULT_STUDIO_STATE: StudioState = {
    camera: DEFAULT_CAMERA_CONFIG,
    caption: DEFAULT_CAPTION_CONFIG,
    thumbnail: DEFAULT_THUMB_CONFIG,
    transcript: ""
}
